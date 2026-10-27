package main

import (
    "context"
    "net/http"
    "net/http/httptest"
    "path/filepath"
    "strings"
    "testing"
    "time"
)

func TestOnlyRouterTrackersAndValidNetworkIdentifiers(t *testing.T) {
    states:=[]haState{
        {EntityID:"device_tracker.asus_phone",State:"home",Attributes:map[string]any{
            "source_type":"router","friendly_name":"ASUS Phone","mac":"aa:bb:cc:dd:ee:ff",
            "ip":"192.168.11.14","ipv6":"fe80::abcd","hostname":"asus-phone"}},
        {EntityID:"device_tracker.gps_phone",State:"home",Attributes:map[string]any{"source_type":"gps","ip":"192.168.11.15"}},
        {EntityID:"device_tracker.no_type",State:"home",Attributes:map[string]any{"mac":"aa:bb:cc:dd:ee:11"}},
        {EntityID:"sensor.bad",State:"home",Attributes:map[string]any{"source_type":"router"}},
        {EntityID:"device_tracker.invalid",State:"home",Attributes:map[string]any{
            "source_type":"router","mac":"00:00:00:00:00:00","ip":"not-an-IP"}},
    }
    got:=normalizeRouterTrackers(states)
    if len(got)!=2 { t.Fatalf("expected two router trackers, got %+v",got) }
    if got[0].MAC!="AA:BB:CC:DD:EE:FF" || got[0].IPv4!="192.168.11.14" || got[0].IPv6!="fe80::abcd" {
        t.Fatalf("bad normalization %+v",got[0])
    }
    if got[1].MAC!="" || got[1].IPv4!="" { t.Fatalf("invalid identifiers accepted %+v",got[1]) }
}

func TestHomeAssistantHTTPSourceContract(t *testing.T) {
    var authorization string
    server:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){
        authorization=r.Header.Get("Authorization")
        w.Header().Set("Content-Type","application/json")
        _,_=w.Write([]byte(`[{"entity_id":"device_tracker.router","state":"home","attributes":{"source_type":"router","mac":"10:20:30:40:50:60","ip":"10.0.0.5"}}]`))
    }))
    defer server.Close()
    got,err:=fetchRouterTrackers(context.Background(),server.Client(),"fake-token",server.URL)
    if err!=nil || len(got)!=1 || authorization!="Bearer fake-token" {t.Fatalf("HA request %v %+v %q",err,got,authorization)}
    _,err=fetchRouterTrackers(context.Background(),server.Client(),"",server.URL)
    if err==nil {t.Fatal("missing token accepted")}
    bad:=httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter,r *http.Request){http.Error(w,"oops",http.StatusForbidden)}))
    defer bad.Close()
    _,err=fetchRouterTrackers(context.Background(),bad.Client(),"token",bad.URL)
    if err==nil || !strings.Contains(err.Error(),"403") {t.Fatalf("expected API permission error, got %v",err)}
}

func TestImportPersistsNotesAndIdentityThroughRestart(t *testing.T) {
    path:=filepath.Join(t.TempDir(),"device.sqlite3")
    db,err:=openDB(path)
    if err!=nil {t.Fatal(err)}
    now:="2026-10-27T20:00:00Z"
    record:=RouterTracker{EntityID:"device_tracker.router_client",Name:"Office workstation",State:"home",MAC:"AA:BB:CC:DD:EE:FF",IPv4:"192.168.1.50"}
    if err=db.importRouterTrackers([]RouterTracker{record},now);err!=nil {t.Fatal(err)}
    records,err:=db.devices()
    if err!=nil || len(records)!=1 {t.Fatalf("import %+v %v",records,err)}
    id:=records[0].ID
    if id=="" || records[0].Presence!="online" || records[0].LastSeen!=now {t.Fatalf("unexpected first record %+v",records[0])}
    saved,err:=db.setNote(id,"UPS + Proxmox")
    if err!=nil || !saved {t.Fatalf("note update: %v %v",saved,err)}
    record.IPv4="192.168.1.99"
    record.State="not_home"
    if err=db.importRouterTrackers([]RouterTracker{record},"2026-10-27T20:01:00Z");err!=nil {t.Fatal(err)}
    db.Close()

    db,err=openDB(path)
    if err!=nil {t.Fatal(err)}
    defer db.Close()
    records,err=db.devices()
    if err!=nil || len(records)!=1 {t.Fatalf("reopened %+v %v",records,err)}
    got:=records[0]
    if got.ID!=id || got.IPv4!="" || got.Presence!="not_observed" ||
        got.LastSeen!=now || got.Note!="UPS + Proxmox" || got.FirstSeen!=now {
        t.Fatalf("history/note not preserved %+v",got)
    }
    original,err:=db.lookupIdentity("ipv4","192.168.1.50")
    if err!=nil || original!=id {t.Fatalf("IP history lost %q %v",original,err)}
    later,err:=db.lookupIdentity("ipv4","192.168.1.99")
    if err!=nil || later!=id {t.Fatalf("new router-reported IP history lost %q %v",later,err)}
    sources,err:=db.sources()
    if err!=nil || len(sources)!=1 || sources[0].Status!="ok" {t.Fatalf("source health %+v %v",sources,err)}
    if err=db.recordSourceFailure(time.Now().UTC().Format(time.RFC3339),"HA Core offline");err!=nil {t.Fatal(err)}
    records,_=db.devices()
    sources,_=db.sources()
    if records[0].Presence!="not_observed" || sources[0].Status!="error" ||
        sources[0].LastSuccess!="2026-10-27T20:01:00Z" {t.Fatalf("source failure fabricated presence %+v %+v",records,sources)}
}

func TestMACReconciliationAndUnknownAreSafe(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"test.sqlite3"))
    if err!=nil {t.Fatal(err)}
    defer db.Close()
    first:=RouterTracker{EntityID:"device_tracker.asus",State:"home",MAC:"02:11:22:33:44:55",IPv4:"192.168.1.15"}
    second:=RouterTracker{EntityID:"device_tracker.unifi",State:"unavailable",MAC:first.MAC}
    if err=db.importRouterTrackers([]RouterTracker{first},"2026-10-27T20:00:00Z");err!=nil {t.Fatal(err)}
    if err=db.importRouterTrackers([]RouterTracker{second},"2026-10-27T20:01:00Z");err!=nil {t.Fatal(err)}
    records,err:=db.devices()
    if err!=nil || len(records)!=1 {t.Fatalf("MAC identity created duplicate %+v %v",records,err)}
    if records[0].Presence!="unknown" || records[0].LastSeen!="2026-10-27T20:00:00Z" {
        t.Fatalf("unavailable treated as offline/online %+v",records[0])
    }
    if err=db.importRouterTrackers(nil,"2026-10-27T20:02:00Z");err!=nil {t.Fatal(err)}
    sources,_:=db.sources()
    if len(sources)!=1 || sources[0].Status!="empty" {t.Fatalf("expected empty source %+v",sources)}
}

func TestIdentityConflictDoesNotMergeHosts(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"test.sqlite3"))
    if err!=nil {t.Fatal(err)}
    defer db.Close()
    a:=RouterTracker{EntityID:"device_tracker.a",MAC:"02:11:22:33:44:01",State:"home"}
    b:=RouterTracker{EntityID:"device_tracker.b",MAC:"02:11:22:33:44:02",State:"home"}
    if err=db.importRouterTrackers([]RouterTracker{a,b},"2026-10-27T20:00:00Z");err!=nil {t.Fatal(err)}
    // Entity b points to one host but now reports the MAC assigned to a.
    b.MAC=a.MAC
    if err=db.importRouterTrackers([]RouterTracker{b},"2026-10-27T20:01:00Z");err!=nil {t.Fatal(err)}
    devices,_:=db.devices(); sources,_:=db.sources()
    if len(devices)!=2 || sources[0].Status!="degraded" {t.Fatalf("identity conflict not contained %+v %+v",devices,sources)}
}

func TestSameSnapshotHomeWinsOverUnavailable(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"test.sqlite3"))
    if err!=nil {t.Fatal(err)}
    defer db.Close()
    a:=RouterTracker{EntityID:"device_tracker.one",MAC:"02:01:02:03:04:05",State:"home"}
    b:=RouterTracker{EntityID:"device_tracker.two",MAC:a.MAC,State:"unavailable"}
    for _,batch:=range [][]RouterTracker{{a,b},{b,a}} {
        if err=db.importRouterTrackers(batch,"2026-10-27T20:00:00Z");err!=nil{t.Fatal(err)}
        devices,_:=db.devices()
        if len(devices)!=1 || devices[0].Presence!="online" {
            t.Fatalf("same-cycle positive presence lost %+v",devices)
        }
    }
}
