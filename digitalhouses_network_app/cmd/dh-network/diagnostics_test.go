package main

import (
    "encoding/json"
    "net/http"
    "net/http/httptest"
    "path/filepath"
    "strings"
    "testing"
    "time"
)

func TestDiagnosticReportPreservesNotesIdentityAndOrigins(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"registry.sqlite3"))
    if err!=nil {t.Fatal(err)}
    t.Cleanup(db.Close)
    mac:="02:AA:BB:CC:DD:EF"
    now:="2026-10-27T16:00:00Z"
    router:=RouterTracker{EntityID:"device_tracker.demo_router",MAC:mac,IPv4:"192.168.11.33",Name:"Demo",State:"home"}
    if err=db.importRouterTrackers([]RouterTracker{router},now);err!=nil {t.Fatal(err)}
    devices,_:=db.devices()
    if len(devices)!=1 {t.Fatal("expected one device")}
    id:=devices[0].ID
    if ok,err:=db.setNote(id,"test - HA");err!=nil || !ok {t.Fatalf("save note %v %v",ok,err)}
    if err=db.importARPHosts([]LANHost{{MAC:mac,IPv4:"192.168.11.34"}},"2026-10-27T16:01:00Z","enp6s18","192.168.11.0/24");err!=nil {t.Fatal(err)}
    service:=Service{db:db,version:"0.1.3",started:time.Now(),intervalSeconds:60,scanIntervalSeconds:180}
    report,err:=service.diagnosticReport()
    if err!=nil {t.Fatal(err)}
    bytes,err:=json.Marshal(report)
    if err!=nil {t.Fatal(err)}
    raw:=string(bytes)
    for _,expected:=range []string{
        diagnosticFormat,"test - HA","device_tracker.demo_router","192.168.11.33",
        "192.168.11.34","HA Router","ARP","0.1.3","enp6s18",
    } {
        if !strings.Contains(raw,expected) {t.Errorf("missing expected field %q",expected)}
    }
    if strings.Contains(raw,"SUPERVISOR_TOKEN") {t.Fatal("environment credential name must not be exported")}
    counts:=report["counts"].(map[string]int)
    if counts["devices"]!=1 || counts["online"]!=1 ||
        counts["ha_router_entities"]!=1 || counts["arp_hosts"]!=1 {t.Fatalf("bad counts %+v",counts)}
    data:=report["inventory"].(DatabaseSnapshot)
    if len(data.Devices)!=1 || data.Devices[0].Note!="test - HA" || data.Devices[0].ID!=id ||
        len(data.DeviceSources)!=2 || len(data.IdentityHistory)<3 {
        t.Fatalf("broken snapshot %+v",data)
    }
    if len(data.Sources)!=5 {t.Fatalf("planned and active sources missing: %+v",data.Sources)}
}

func TestDiagnosticIngressOnlyAndValidJSON(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"registry.sqlite3"))
    if err!=nil {t.Fatal(err)}
    defer db.Close()
    s:=Service{db:db,version:"0.1.3",started:time.Now(),intervalSeconds:60,scanIntervalSeconds:180}

    direct:=httptest.NewRequest(http.MethodGet,"/api/diagnostics",nil)
    direct.RemoteAddr="192.168.11.100:4332"
    rec:=httptest.NewRecorder()
    s.routes().ServeHTTP(rec,direct)
    if rec.Code!=http.StatusForbidden {t.Fatalf("direct API exposure: %d",rec.Code)}

    viaHA:=httptest.NewRequest(http.MethodGet,"/api/diagnostics",nil)
    viaHA.RemoteAddr="172.30.32.2:41000"
    response:=httptest.NewRecorder()
    s.routes().ServeHTTP(response,viaHA)
    if response.Code!=http.StatusOK {t.Fatalf("diagnostics returned HTTP %d: %s",response.Code,response.Body.String())}
    var report map[string]any
    if err:=json.Unmarshal(response.Body.Bytes(),&report);err!=nil {t.Fatalf("invalid diagnostics JSON: %v",err)}
    if report["format"]!=diagnosticFormat {t.Fatalf("invalid export version: %+v",report)}
    if _,exists:=report["browser_view"];exists {t.Fatal("browser view must be populated by the client, not fabricated")}
    originsReq:=httptest.NewRequest(http.MethodGet,"/api/device-sources",nil)
    originsReq.RemoteAddr="172.30.32.2:41001"
    result:=httptest.NewRecorder()
    s.routes().ServeHTTP(result,originsReq)
    if result.Code!=http.StatusOK || !strings.HasPrefix(result.Body.String(),"[]") {
        t.Fatalf("bad device source endpoint: %d %s",result.Code,result.Body.String())
    }
}

func TestDeviceSourcesAreHistoricalAssociations(t *testing.T) {
    identities:=[]IdentityHistory{
        {DeviceID:"a",Kind:"ha_entity",Value:"device_tracker.phone",LastSeen:"2026-10-27T16:00:00Z"},
        {DeviceID:"a",Kind:"mac",Value:"02:AA:BB:CC:DD:EF",LastSeen:"2026-10-27T16:00:00Z"},
        {DeviceID:"b",Kind:"ipv4",Value:"192.168.11.70",LastSeen:"2026-10-27T16:00:00Z"},
    }
    positives:=[]LANObservation{{DeviceID:"a",LastSeen:"2026-10-27T15:59:00Z"}}
    origins:=deriveDeviceSources(identities,positives)
    if len(origins)!=2 || countSources(origins,"ARP")!=1 || countSources(origins,"HA Router")!=1 {
        t.Fatalf("MAC/IP mistaken for discovery source %+v",origins)
    }
}
