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
    haFreshness time.Duration
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
        "CREATE TABLE IF NOT EXISTS ipv4_disagreement_state (ipv4 TEXT PRIMARY KEY,classification TEXT NOT NULL,fingerprint TEXT NOT NULL,details_json TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL);",
        "CREATE TABLE IF NOT EXISTS ssdp_services (device_id TEXT NOT NULL REFERENCES devices(id),ipv4 TEXT NOT NULL,st TEXT NOT NULL,usn TEXT NOT NULL,server TEXT NOT NULL,location TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,PRIMARY KEY(device_id,st,usn));",
        "CREATE TABLE IF NOT EXISTS ssdp_unmatched (ipv4 TEXT NOT NULL,st TEXT NOT NULL,usn TEXT NOT NULL,last_seen TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(ipv4,st,usn));",
        "CREATE TABLE IF NOT EXISTS wsd_endpoints (device_id TEXT NOT NULL REFERENCES devices(id),ipv4 TEXT NOT NULL,endpoint TEXT NOT NULL,types TEXT NOT NULL,scopes TEXT NOT NULL,origin TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,PRIMARY KEY(device_id,endpoint));",
        "CREATE TABLE IF NOT EXISTS wsd_unmatched (ipv4 TEXT NOT NULL,endpoint TEXT NOT NULL,last_seen TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(ipv4,endpoint));",
        "CREATE TABLE IF NOT EXISTS wsd_names (device_id TEXT NOT NULL REFERENCES devices(id),endpoint TEXT NOT NULL,computer_name TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,PRIMARY KEY(device_id,endpoint));",
        "CREATE TABLE IF NOT EXISTS lan_positive (device_id TEXT PRIMARY KEY REFERENCES devices(id),last_seen TEXT NOT NULL);",
        "CREATE TABLE IF NOT EXISTS ipv4_evidence (device_id TEXT NOT NULL REFERENCES devices(id),source TEXT NOT NULL,reference TEXT NOT NULL,ipv4 TEXT NOT NULL,state TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,PRIMARY KEY(device_id,source,reference,ipv4));",
        "CREATE INDEX IF NOT EXISTS ipv4_evidence_ip ON ipv4_evidence(ipv4,last_seen);",
        "CREATE TABLE IF NOT EXISTS mdns_hosts (device_id TEXT PRIMARY KEY REFERENCES devices(id),hostname TEXT NOT NULL,ipv4 TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL);",
        "CREATE TABLE IF NOT EXISTS mdns_services (device_id TEXT NOT NULL REFERENCES devices(id),instance TEXT NOT NULL,type TEXT NOT NULL,port INTEGER NOT NULL,target TEXT NOT NULL,first_seen TEXT NOT NULL,last_seen TEXT NOT NULL,PRIMARY KEY(device_id,instance,type,port));",
        "CREATE TABLE IF NOT EXISTS mdns_unmatched (hostname TEXT NOT NULL,ipv4 TEXT NOT NULL,last_seen TEXT NOT NULL,reason TEXT NOT NULL,PRIMARY KEY(hostname,ipv4));",
        // Existing records are an established baseline: never notify them on upgrade.
        "CREATE TABLE IF NOT EXISTS device_births (device_id TEXT PRIMARY KEY REFERENCES devices(id),first_positive_at TEXT NOT NULL,publish_state TEXT NOT NULL CHECK(publish_state IN ('pending','suppressed','published')),detection_source TEXT NOT NULL DEFAULT '');",
        "CREATE TABLE IF NOT EXISTS network_event_policy (key TEXT PRIMARY KEY,value TEXT NOT NULL);",
        "INSERT OR IGNORE INTO device_births(device_id,first_positive_at,publish_state) SELECT id,first_seen,'suppressed' FROM devices WHERE last_seen<>'';",
        "CREATE TRIGGER IF NOT EXISTS dh_birth_on_insert AFTER INSERT ON devices WHEN NEW.last_seen<>'' BEGIN INSERT OR IGNORE INTO device_births(device_id,first_positive_at,publish_state) VALUES(NEW.id,NEW.last_seen,'pending'); END;",
        "CREATE TRIGGER IF NOT EXISTS dh_birth_on_first_positive AFTER UPDATE OF last_seen ON devices WHEN NEW.last_seen<>'' BEGIN INSERT OR IGNORE INTO device_births(device_id,first_positive_at,publish_state) VALUES(NEW.id,NEW.last_seen,'pending'); END;",
        "CREATE TABLE IF NOT EXISTS monitor_states (method TEXT NOT NULL,watch_id TEXT NOT NULL,state TEXT NOT NULL,last_confirmed TEXT NOT NULL,ok_count INTEGER NOT NULL,bad_count INTEGER NOT NULL,last_sample TEXT NOT NULL,last_check TEXT NOT NULL,reason TEXT NOT NULL,target_json TEXT NOT NULL,label TEXT NOT NULL,PRIMARY KEY(method,watch_id));",
        "CREATE TABLE IF NOT EXISTS monitor_outbox (event_id TEXT PRIMARY KEY,method TEXT NOT NULL,watch_id TEXT NOT NULL,occurred_at TEXT NOT NULL,payload_json TEXT NOT NULL,FOREIGN KEY(method,watch_id) REFERENCES monitor_states(method,watch_id));",
        "CREATE TABLE IF NOT EXISTS monitor_tombstones (method TEXT NOT NULL,watch_id TEXT NOT NULL,PRIMARY KEY(method,watch_id));",
        "CREATE TABLE IF NOT EXISTS discovery_settings (id INTEGER PRIMARY KEY CHECK(id=1),poll_interval_seconds INTEGER NOT NULL,scan_interval_seconds INTEGER NOT NULL,mdns_interval_seconds INTEGER NOT NULL,ssdp_interval_seconds INTEGER NOT NULL,wsd_interval_seconds INTEGER NOT NULL,confirm_successes INTEGER NOT NULL,confirm_failures INTEGER NOT NULL);",
        "CREATE TABLE IF NOT EXISTS presence_subscriptions (kind TEXT NOT NULL CHECK(kind IN ('ip','mac')),target TEXT NOT NULL,enabled INTEGER NOT NULL DEFAULT 1,notifications INTEGER NOT NULL DEFAULT 0,updated_at TEXT NOT NULL,label TEXT NOT NULL DEFAULT '',PRIMARY KEY(kind,target));",
        "CREATE TABLE IF NOT EXISTS presence_states (kind TEXT NOT NULL,target TEXT NOT NULL,state TEXT NOT NULL DEFAULT 'unknown',last_confirmed TEXT NOT NULL DEFAULT '',last_sample_at TEXT NOT NULL DEFAULT '',last_check TEXT NOT NULL DEFAULT '',last_positive TEXT NOT NULL DEFAULT '',last_changed TEXT NOT NULL DEFAULT '',successes INTEGER NOT NULL DEFAULT 0,failures INTEGER NOT NULL DEFAULT 0,reason TEXT NOT NULL DEFAULT '',PRIMARY KEY(kind,target));",
        "CREATE TABLE IF NOT EXISTS presence_outbox (event_id TEXT PRIMARY KEY,kind TEXT NOT NULL,target TEXT NOT NULL,occurred_at TEXT NOT NULL,payload_json TEXT NOT NULL);",
        "CREATE TABLE IF NOT EXISTS event_delivery_log (event_id TEXT PRIMARY KEY,event_type TEXT NOT NULL,occurred_at TEXT NOT NULL,published_at TEXT NOT NULL DEFAULT '',status TEXT NOT NULL CHECK(status IN ('queued','broker_acked','retrying')),attempts INTEGER NOT NULL DEFAULT 0,payload_json TEXT NOT NULL);",
        "CREATE INDEX IF NOT EXISTS delivery_order ON event_delivery_log(occurred_at DESC);",
        "UPDATE schema_version SET version=12;",
    }, "\n")
    if err := db.exec(schema); err != nil {
        db.Close()
        return nil, err
    }
    if err:=db.ensureDeviceBirthSourceColumn();err!=nil{db.Close();return nil,err}
    if err:=db.ensurePresenceLabelColumn();err!=nil{db.Close();return nil,err}
    if err:=db.initializeDiscoveryBaseline(path);err!=nil{db.Close();return nil,err}
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
    mdnsIntervalSeconds int
    ssdpIntervalSeconds int
    wsdIntervalSeconds int
    // Reset gate protects the persisted generation against in-flight scans.
    resetGate sync.RWMutex
    resetGeneration uint64
    lanScanMu sync.Mutex
    presenceScanMu sync.Mutex
    presenceScanQueued bool
    presenceScanRevision uint64
    // Test-only seam: production always executes the shared LAN scanner.
    presenceScanNow func()
    // Optional test seam; the production path always invokes first discovery.
    afterReset func()
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
        settings,err:=s.db.readSettings();if err!=nil{http.Error(w,"settings unavailable",500);return}
        reply(w,map[string]any{"product":"digitalhouses_network_app","version":s.version,"started_at":s.started.Format(time.RFC3339),"database":"ready","discovery_running":true,"ha_router_import_enabled":true,"poll_interval_seconds":settings.PollIntervalSeconds,"devices":len(devices),"scan_interval_seconds":settings.ScanIntervalSeconds,"mdns_interval_seconds":settings.MDNSIntervalSeconds,"ssdp_interval_seconds":settings.SSDPIntervalSeconds,"wsd_interval_seconds":settings.WSDIntervalSeconds,"phase":"local_interface_lan_arp_ha_router_mdns_ssdp_wsd"})
    })
    mux.HandleFunc("GET /api/settings",s.settingsAPI)
    mux.HandleFunc("PUT /api/settings",s.settingsAPI)
    mux.HandleFunc("GET /api/presence",s.presenceAPI)
    mux.HandleFunc("PUT /api/presence",s.presenceAPI)
    mux.HandleFunc("GET /api/event-log",func(w http.ResponseWriter,r *http.Request){
        entries,err:=s.db.deliveryEvents()
        if err!=nil{http.Error(w,"event journal unavailable",500);return}
        reply(w,entries)
    })
    mux.HandleFunc("GET /api/monitored-config",readMonitorConfig)
    mux.HandleFunc("PUT /api/monitored-config",writeMonitorConfig)
    mux.HandleFunc("GET /api/monitored-state",func(w http.ResponseWriter,r *http.Request){
        values,err:=s.db.monitoredStates()
        if err!=nil{http.Error(w,"monitor state unavailable",500);return}
        reply(w,values)
    })
    mux.HandleFunc("GET /api/device-births",func(w http.ResponseWriter,r *http.Request){
        births,err:=s.db.deviceBirths()
        if err!=nil{http.Error(w,"database unavailable",500);return}
        reply(w,births)
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
        if !containsSource(sources,"Local Interface") {sources=append(sources,SourceInfo{Name:"Local Interface",Kind:"local_interface",Status:"pending"})}
        if !containsSource(sources,"LAN ARP") {sources=append(sources,SourceInfo{Name:"LAN ARP",Kind:"lan_arp",Status:"pending"})}
        if !containsSource(sources,"mDNS / Bonjour") {sources=append(sources,SourceInfo{Name:"mDNS / Bonjour",Kind:"mdns",Status:"pending"})}
        if !containsSource(sources,"SSDP") {sources=append(sources,SourceInfo{Name:"SSDP",Kind:"ssdp",Status:"pending"})}
        if !containsSource(sources,"WS-Discovery") {sources=append(sources,SourceInfo{Name:"WS-Discovery",Kind:"wsd",Status:"pending"})}
        sources=append(sources,SourceInfo{Name:"IPv6 NDP",Kind:"planned",Status:"planned"})
        reply(w,sources)
    })
    mux.HandleFunc("GET /api/device-sources",func(w http.ResponseWriter,r *http.Request){
        snapshot,err:=s.db.snapshot()
        if err!=nil {http.Error(w,"database unavailable",500);return}
        reply(w,snapshot.DeviceSources)
    })
    mux.HandleFunc("GET /api/wsd-endpoints",func(w http.ResponseWriter,r *http.Request){
        snapshot,err:=s.db.snapshot()
        if err!=nil {http.Error(w,"database unavailable",500);return}
        reply(w,snapshot.WSDEndpoints)
    })
    mux.HandleFunc("GET /api/ssdp-services",func(w http.ResponseWriter,r *http.Request){
        snapshot,err:=s.db.snapshot()
        if err!=nil { http.Error(w,"database unavailable",500);return}
        reply(w,snapshot.SSDPServices)
    })
    mux.HandleFunc("GET /api/mdns-services",func(w http.ResponseWriter,r *http.Request){
        snapshot,err:=s.db.snapshot()
        if err!=nil {http.Error(w,"database unavailable",500);return}
        reply(w,snapshot.MDNSServices)
    })
    mux.HandleFunc("GET /api/diagnostics/download",s.downloadDiagnostics)
    mux.HandleFunc("GET /api/diagnostics",func(w http.ResponseWriter,r *http.Request){
        report,err:=s.diagnosticReport()
        if err!=nil {http.Error(w,"diagnostic unavailable",500);return}
        reply(w,report)
    })
    mux.HandleFunc("POST /api/inventory/reset",func(w http.ResponseWriter,r *http.Request){
        // The Ingress proxy enforces HA admin access. A JSON-only custom-header
        // endpoint is not callable by plain cross-site HTML forms.
        if r.Header.Get("X-DH-UI")!="1" || r.Header.Get("Content-Type")!="application/json" {
            http.Error(w,"reset requires Ingress JSON request",http.StatusUnsupportedMediaType);return
        }
        var input struct{Confirmation string `json:"confirmation"`}
        decoder:=json.NewDecoder(http.MaxBytesReader(w,r.Body,256))
        decoder.DisallowUnknownFields()
        if err:=decoder.Decode(&input);err!=nil {http.Error(w,"invalid reset request",http.StatusBadRequest);return}
        var extra any
        if err:=decoder.Decode(&extra);err!=io.EOF {http.Error(w,"unexpected reset request body",http.StatusBadRequest);return}
        if err:=confirmReset(input.Confirmation);err!=nil {http.Error(w,"confirmation must be RESET",http.StatusBadRequest);return}
        removed,err:=s.resetInventory()
        if err!=nil {log.Printf("Network inventory reset failed: %v",err);http.Error(w,"inventory reset failed",http.StatusInternalServerError);return}
        reply(w,map[string]any{"reset":true,"previous_devices":removed,"discovery_started":true})
        // Schedule after releasing DB/generation locks, independent of browser.
        if s.afterReset!=nil {s.afterReset()} else {s.startFreshDiscovery()}
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
    db.haFreshness=time.Duration(intervalSeconds*3)*time.Second
    mdnsSeconds,err:=strconv.Atoi(os.Getenv("DH_MDNS_INTERVAL"))
    if err!=nil || mdnsSeconds<120 || mdnsSeconds>3600 {log.Fatal("DH_MDNS_INTERVAL must be 120..3600")}
    ssdpSeconds,err:=strconv.Atoi(os.Getenv("DH_SSDP_INTERVAL"))
    if err!=nil || ssdpSeconds<120 || ssdpSeconds>3600 {log.Fatal("DH_SSDP_INTERVAL must be 120..3600")}
    wsdSeconds,err:=strconv.Atoi(os.Getenv("DH_WSD_INTERVAL"))
    if err!=nil || wsdSeconds<120 || wsdSeconds>3600 {log.Fatal("DH_WSD_INTERVAL must be 120..3600")}
    service:=&Service{db:db,version:os.Getenv("APP_VERSION"),started:time.Now().UTC(),intervalSeconds:intervalSeconds,scanIntervalSeconds:scanSeconds,mdnsIntervalSeconds:mdnsSeconds,ssdpIntervalSeconds:ssdpSeconds,wsdIntervalSeconds:wsdSeconds}
    if err:=db.initializeSettings(DiscoverySettings{
        PollIntervalSeconds:intervalSeconds,ScanIntervalSeconds:scanSeconds,
        MDNSIntervalSeconds:mdnsSeconds,SSDPIntervalSeconds:ssdpSeconds,WSDIntervalSeconds:wsdSeconds,
        ConfirmSuccesses:2,ConfirmFailures:3,
    });err!=nil{log.Fatal(err)}
    go service.runRouterPolling(time.Duration(intervalSeconds)*time.Second)
    go service.runLANPolling(time.Duration(scanSeconds)*time.Second)
    go service.runMDNSPolling(time.Duration(mdnsSeconds)*time.Second)
    go service.runSSDPPolling(time.Duration(ssdpSeconds)*time.Second)
    go service.runWSDPolling(time.Duration(wsdSeconds)*time.Second)
    log.Printf("DigitalHouses Network App %s started; ingress=%s",service.version,port)
    server:=&http.Server{Addr:":"+port,Handler:service.routes(),ReadHeaderTimeout:10*time.Second,ReadTimeout:30*time.Second,WriteTimeout:30*time.Second}
    log.Fatal(server.ListenAndServe())
}
