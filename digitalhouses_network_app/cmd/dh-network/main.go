package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
#include <stdlib.h>
static int dh_bind_text(sqlite3_stmt *stmt, int pos, const char *text) {
    return sqlite3_bind_text(stmt, pos, text, -1, SQLITE_TRANSIENT);
}
*/
import "C"

import (
    "embed"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "log"
    "net/http"
    "os"
    "path/filepath"
    "strconv"
    "strings"
    "sync"
    "time"
    "unsafe"
)

//go:embed ui/index.html
var ui embed.FS

type Device struct {
    ID string `json:"id"`
    DisplayName string `json:"display_name"`
    Hostname string `json:"hostname"`
    MAC string `json:"mac"`
    IPv4 string `json:"ipv4"`
    IPv6 string `json:"ipv6"`
    Presence string `json:"presence"`
    FirstSeen string `json:"first_seen"`
    LastSeen string `json:"last_seen"`
    Note string `json:"note"`
}

type Event struct {
    ID int64 `json:"id"`
    EventType string `json:"event_type"`
    DeviceID string `json:"device_id"`
    OccurredAt string `json:"occurred_at"`
    DataJSON string `json:"data_json"`
}

type DB struct {
    mu sync.Mutex
    connection *C.sqlite3
    lanFreshness time.Duration
}

func cstring(value string) (*C.char, func()) {
    p := C.CString(value)
    return p, func() { C.free(unsafe.Pointer(p)) }
}

func openDB(path string) (*DB, error) {
    p, free := cstring(path)
    defer free()
    var handle *C.sqlite3
    rc := C.sqlite3_open_v2(p, &handle, C.SQLITE_OPEN_READWRITE|C.SQLITE_OPEN_CREATE|C.SQLITE_OPEN_FULLMUTEX, nil)
    if rc != C.SQLITE_OK {
        if handle != nil {
            msg := C.GoString(C.sqlite3_errmsg(handle))
            C.sqlite3_close(handle)
            return nil, fmt.Errorf("sqlite open: %s", msg)
        }
        return nil, errors.New("sqlite open failed")
    }
    db := &DB{connection: handle}
    C.sqlite3_busy_timeout(handle, 3000)
    schema := strings.Join([]string{
        "PRAGMA journal_mode=WAL;",
        "PRAGMA foreign_keys=ON;",
        "CREATE TABLE IF NOT EXISTS schema_version (version INTEGER NOT NULL);",
        "INSERT INTO schema_version(version) SELECT 1 WHERE NOT EXISTS (SELECT 1 FROM schema_version);",
        "CREATE TABLE IF NOT EXISTS devices (id TEXT PRIMARY KEY, display_name TEXT NOT NULL DEFAULT '', hostname TEXT NOT NULL DEFAULT '', mac TEXT NOT NULL DEFAULT '', ipv4 TEXT NOT NULL DEFAULT '', ipv6 TEXT NOT NULL DEFAULT '', presence TEXT NOT NULL DEFAULT 'unknown', first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, note TEXT NOT NULL DEFAULT '');",
        "CREATE TABLE IF NOT EXISTS identities (device_id TEXT NOT NULL REFERENCES devices(id), kind TEXT NOT NULL, value TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL, PRIMARY KEY(device_id,kind,value));",
        "CREATE TABLE IF NOT EXISTS observations (id INTEGER PRIMARY KEY, device_id TEXT NOT NULL REFERENCES devices(id), source TEXT NOT NULL, observed_at TEXT NOT NULL, details_json TEXT NOT NULL DEFAULT '{}');",
        "CREATE TABLE IF NOT EXISTS sources (id TEXT PRIMARY KEY, kind TEXT NOT NULL, status TEXT NOT NULL, last_success TEXT, details_json TEXT NOT NULL DEFAULT '{}');",
        "CREATE TABLE IF NOT EXISTS events (id INTEGER PRIMARY KEY, event_type TEXT NOT NULL, device_id TEXT NOT NULL DEFAULT '', occurred_at TEXT NOT NULL, data_json TEXT NOT NULL DEFAULT '{}');",
        "CREATE INDEX IF NOT EXISTS event_order ON events(occurred_at);",
        "CREATE TABLE IF NOT EXISTS lan_positive (device_id TEXT PRIMARY KEY REFERENCES devices(id),last_seen TEXT NOT NULL);",
        "UPDATE schema_version SET version=2;",
    }, "\n")
    if err := db.exec(schema); err != nil {
        db.Close()
        return nil, err
    }
    return db, nil
}

func (db *DB) exec(script string) error {
    sql, free := cstring(script)
    defer free()
    var msg *C.char
    if C.sqlite3_exec(db.connection, sql, nil, nil, &msg) != C.SQLITE_OK {
        if msg == nil { return errors.New("sqlite schema failed") }
        detail := C.GoString(msg)
        C.sqlite3_free(unsafe.Pointer(msg))
        return errors.New(detail)
    }
    return nil
}

func (db *DB) Close() { db.mu.Lock(); defer db.mu.Unlock(); C.sqlite3_close(db.connection) }

func (db *DB) query(statement string, read func(*C.sqlite3_stmt)) error {
    db.mu.Lock()
    defer db.mu.Unlock()
    sql, free := cstring(statement)
    defer free()
    var stmt *C.sqlite3_stmt
    if C.sqlite3_prepare_v2(db.connection, sql, -1, &stmt, nil) != C.SQLITE_OK {
        return errors.New(C.GoString(C.sqlite3_errmsg(db.connection)))
    }
    defer C.sqlite3_finalize(stmt)
    for {
        switch C.sqlite3_step(stmt) {
        case C.SQLITE_ROW:
            read(stmt)
        case C.SQLITE_DONE:
            return nil
        default:
            return errors.New(C.GoString(C.sqlite3_errmsg(db.connection)))
        }
    }
}

func field(stmt *C.sqlite3_stmt, n int) string {
    p := C.sqlite3_column_text(stmt, C.int(n))
    if p == nil { return "" }
    return C.GoString((*C.char)(unsafe.Pointer(p)))
}

func (db *DB) devices() ([]Device, error) {
    result := make([]Device, 0)
    err := db.query("SELECT id,display_name,hostname,mac,ipv4,ipv6,presence,first_seen,last_seen,note FROM devices ORDER BY display_name,id;", func(stmt *C.sqlite3_stmt) {
        result = append(result, Device{field(stmt,0),field(stmt,1),field(stmt,2),field(stmt,3),field(stmt,4),field(stmt,5),field(stmt,6),field(stmt,7),field(stmt,8),field(stmt,9)})
    })
    return result, err
}

func (db *DB) events() ([]Event, error) {
    result := make([]Event, 0)
    err := db.query("SELECT id,event_type,device_id,occurred_at,data_json FROM events ORDER BY id DESC LIMIT 200;", func(stmt *C.sqlite3_stmt) {
        result = append(result, Event{int64(C.sqlite3_column_int64(stmt,0)),field(stmt,1),field(stmt,2),field(stmt,3),field(stmt,4)})
    })
    return result, err
}

func (db *DB) setNote(id, note string) (bool,error) {
    db.mu.Lock()
    defer db.mu.Unlock()
    sql, free := cstring("UPDATE devices SET note = ? WHERE id = ?")
    defer free()
    var stmt *C.sqlite3_stmt
    if C.sqlite3_prepare_v2(db.connection,sql,-1,&stmt,nil) != C.SQLITE_OK { return false,errors.New("prepare failed") }
    defer C.sqlite3_finalize(stmt)
    n, freeN := cstring(note); defer freeN()
    d, freeD := cstring(id); defer freeD()
    if C.dh_bind_text(stmt,1,n) != C.SQLITE_OK || C.dh_bind_text(stmt,2,d) != C.SQLITE_OK { return false,errors.New("bind failed") }
    if C.sqlite3_step(stmt) != C.SQLITE_DONE { return false,errors.New(C.GoString(C.sqlite3_errmsg(db.connection))) }
    return C.sqlite3_changes(db.connection) > 0,nil
}

type Service struct {
    db *DB
    version string
    started time.Time
    intervalSeconds int
    scanIntervalSeconds int
}

func reply(w http.ResponseWriter, data any) {
    w.Header().Set("Content-Type","application/json; charset=utf-8")
    _ = json.NewEncoder(w).Encode(data)
}

func (s *Service) routes() http.Handler {
    mux:=http.NewServeMux()
    mux.HandleFunc("GET /",func(w http.ResponseWriter,r *http.Request){
        if r.URL.Path != "/" { http.NotFound(w,r); return }
        page,err:=ui.ReadFile("ui/index.html")
        if err != nil { http.Error(w,"UI asset unavailable",500); return }
        w.Header().Set("Content-Type","text/html; charset=utf-8")
        _,_=w.Write(page)
    })
    mux.HandleFunc("GET /healthz",func(w http.ResponseWriter,r *http.Request){ _,_=io.WriteString(w,"ok\n") })
    mux.HandleFunc("GET /api/status",func(w http.ResponseWriter,r *http.Request){
        devices,err:=s.db.devices()
        if err != nil { http.Error(w,"database unavailable",500); return }
        reply(w,map[string]any{"product":"digitalhouses_network_app","version":s.version,"started_at":s.started.Format(time.RFC3339),"database":"ready","discovery_running":false,"ha_router_import_enabled":true,"poll_interval_seconds":s.intervalSeconds,"devices":len(devices),"scan_interval_seconds":s.scanIntervalSeconds,"phase":"lan_arp_and_ha_router"})
    })
    mux.HandleFunc("GET /api/devices",func(w http.ResponseWriter,r *http.Request){
        devices,err:=s.db.devices()
        if err != nil { http.Error(w,"database unavailable",500); return }
        reply(w,devices)
    })
    mux.HandleFunc("GET /api/events",func(w http.ResponseWriter,r *http.Request){
        events,err:=s.db.events()
        if err != nil { http.Error(w,"database unavailable",500); return }
        reply(w,events)
    })
    mux.HandleFunc("GET /api/sources",func(w http.ResponseWriter,r *http.Request){
        sources,err:=s.db.sources()
        if err!=nil {http.Error(w,"database unavailable",500);return}
        if len(sources)==0 {sources=append(sources,SourceInfo{Name:"Home Assistant router trackers",Kind:"ha_device_tracker",Status:"pending"})}
        if !containsSource(sources,"LAN ARP") {sources=append(sources,SourceInfo{Name:"LAN ARP",Kind:"lan_arp",Status:"pending"})}
        sources=append(sources,SourceInfo{Name:"IPv6 NDP",Kind:"planned",Status:"planned"},
            SourceInfo{Name:"mDNS / Bonjour",Kind:"planned",Status:"planned"},
            SourceInfo{Name:"SSDP",Kind:"planned",Status:"planned"})
        reply(w,sources)
    })
    mux.HandleFunc("GET /api/device-sources",func(w http.ResponseWriter,r *http.Request){
        snapshot,err:=s.db.snapshot()
        if err!=nil {http.Error(w,"database unavailable",500);return}
        reply(w,snapshot.DeviceSources)
    })
    mux.HandleFunc("GET /api/diagnostics",func(w http.ResponseWriter,r *http.Request){
        report,err:=s.diagnosticReport()
        if err!=nil {http.Error(w,"diagnostic unavailable",500);return}
        reply(w,report)
    })
    mux.HandleFunc("PUT /api/devices/{id}/note",func(w http.ResponseWriter,r *http.Request){
        id:=r.PathValue("id")
        if id=="" || len(id)>128 { http.Error(w,"invalid device ID",400);return }
        if r.Header.Get("X-DH-UI")!="1" || !strings.HasPrefix(r.Header.Get("Content-Type"),"application/json") {
            http.Error(w,"invalid request",415);return
        }
        var input struct{ Note string `json:"note"` }
        decoder:=json.NewDecoder(http.MaxBytesReader(w,r.Body,6000))
        decoder.DisallowUnknownFields()
        if err:=decoder.Decode(&input);err!=nil { http.Error(w,"invalid JSON",400);return }
        var extra any
        if err:=decoder.Decode(&extra);err!=io.EOF { http.Error(w,"unexpected JSON",400);return }
        if len(input.Note)>4096 { http.Error(w,"note too long",400);return }
        ok,err:=s.db.setNote(id,input.Note)
        if err!=nil { http.Error(w,"database unavailable",500);return }
        if !ok { http.Error(w,"device not found",404);return }
        reply(w,map[string]bool{"updated":true})
    })
    return http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
        if !ingressPeerAllowed(r.RemoteAddr) {http.Error(w,"Ingress only",http.StatusForbidden);return}
        w.Header().Set("Cache-Control","no-store")
        w.Header().Set("X-Content-Type-Options","nosniff")
        w.Header().Set("Referrer-Policy","no-referrer")
        w.Header().Set("Content-Security-Policy","default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; connect-src 'self'; base-uri 'none'")
        mux.ServeHTTP(w,r)
    })
}

func main() {
    port:=os.Getenv("DH_PORT")
    if port=="" { log.Fatal("DH_PORT missing: only Supervisor Ingress is supported") }
    path:=os.Getenv("DH_DB")
    if path=="" { log.Fatal("DH_DB missing") }
    if err:=os.MkdirAll(filepath.Dir(path),0700); err!=nil { log.Fatal(err) }
    db,err:=openDB(path)
    if err!=nil { log.Fatal(err) }
    defer db.Close()
    intervalSeconds,err:=strconv.Atoi(os.Getenv("DH_INTERVAL"))
    if err!=nil || intervalSeconds<15 || intervalSeconds>3600 {log.Fatal("DH_INTERVAL must be between 15 and 3600")}
    scanSeconds,err:=strconv.Atoi(os.Getenv("DH_SCAN_INTERVAL"))
    if err!=nil || scanSeconds<60 || scanSeconds>3600 {log.Fatal("DH_SCAN_INTERVAL must be 60..3600")}
    db.lanFreshness=time.Duration(scanSeconds*2+30)*time.Second
    service:=&Service{db:db,version:os.Getenv("APP_VERSION"),started:time.Now().UTC(),intervalSeconds:intervalSeconds,scanIntervalSeconds:scanSeconds}
    go service.runRouterPolling(time.Duration(intervalSeconds)*time.Second)
    go service.runLANPolling(time.Duration(scanSeconds)*time.Second)
    log.Printf("DigitalHouses Network App %s started; ingress=%s",service.version,port)
    server:=&http.Server{Addr:":"+port,Handler:service.routes(),ReadHeaderTimeout:10*time.Second,ReadTimeout:30*time.Second,WriteTimeout:30*time.Second}
    log.Fatal(server.ListenAndServe())
}
