package main

import (
    "encoding/json"
    "net/http"
    "net/http/httptest"
    "os"
    "path/filepath"
    "strings"
    "testing"
    "time"
)

func TestDownloadDiagnosticsIsRealAttachmentAndCarriesBoundedDebug(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
    if err!=nil {t.Fatal(err)}
    defer db.Close()
    if err:=db.initializeSettings(DiscoverySettings{60,180,300,300,300,2,3,30,30});err!=nil{t.Fatal(err)}
    if _,err:=db.updatePresence("ip","192.168.2.30",true,false);err!=nil{t.Fatal(err)}
    if err:=db.run("INSERT INTO event_delivery_log(event_id,event_type,occurred_at,status,payload_json) VALUES('testid','tracked_device_unreachable','2026-10-29T00:00:00Z','queued','{}')");err!=nil{t.Fatal(err)}
    if err:=os.Setenv("MQTT_PASSWORD","test-export-secret-never-include");err!=nil{t.Fatal(err)}
    defer os.Unsetenv("MQTT_PASSWORD")

    service:=Service{db:db,version:"0.1.23",started:time.Now()}
    direct:=httptest.NewRequest(http.MethodGet,"/api/diagnostics/download",nil)
    direct.RemoteAddr="192.168.11.11:45000"
    blocked:=httptest.NewRecorder()
    service.routes().ServeHTTP(blocked,direct)
    if blocked.Code!=http.StatusForbidden {t.Fatalf("diagnostic download exposed outside Ingress: %d",blocked.Code)}

    request:=httptest.NewRequest(http.MethodGet,"/api/diagnostics/download",nil)
    request.RemoteAddr="172.30.32.2:39000"
    rec:=httptest.NewRecorder()
    service.routes().ServeHTTP(rec,request)
    if rec.Code!=200 {t.Fatalf("download failed: %d %s",rec.Code,rec.Body.String())}
    if !strings.Contains(rec.Header().Get("Content-Disposition"),"attachment; filename=") ||
       !strings.Contains(rec.Header().Get("Content-Disposition"),".json") {
       t.Fatalf("not a real attachment: %q",rec.Header().Get("Content-Disposition"))
    }
    if !strings.HasPrefix(rec.Header().Get("Content-Type"),"application/json") {
       t.Fatalf("wrong content type: %q",rec.Header().Get("Content-Type"))
    }
    if !strings.Contains(rec.Header().Get("Cache-Control"),"no-store") {t.Fatal("sensitive report may be cached")}
    if strings.Contains(rec.Body.String(),"test-export-secret-never-include"){t.Fatal("export leaked MQTT password")}
    var payload map[string]any
    if err:=json.Unmarshal(rec.Body.Bytes(),&payload);err!=nil{t.Fatalf("invalid JSON: %v",err)}
    if payload["format"]!=diagnosticFormat{t.Fatalf("diagnostic format changed: %v",payload["format"])}
    debug,ok:=payload["debug"].(map[string]any)
    if !ok||debug["mode"]!="extended_debug_v1"{t.Fatalf("no debug payload: %#v",debug)}
    if _,ok:=debug["global_settings"].(map[string]any);!ok{t.Fatal("missing global configuration snapshot")}
    subs,ok:=debug["presence_subscriptions"].([]any)
    if !ok||len(subs)!=1{t.Fatalf("missing watch state: %v",subs)}
    if subs[0].(map[string]any)["state"]!="working"{t.Fatalf("watch not in Working state: %v",subs)}
    history,ok:=debug["last_delivery_events"].([]any)
    if !ok||len(history)!=1{t.Fatalf("missing queued event: %v",history)}
    if history[0].(map[string]any)["event_type"]!="tracked_device_unreachable"{t.Fatalf("wrong event type: %v",history)}
    counts,ok:=debug["queue_counters"].(map[string]any)
    if !ok||counts["delivery_queued"]!=float64(1){t.Fatalf("missing queue counts: %v",counts)}
    if payload["inventory"]==nil||payload["source_diagnostics"]==nil{t.Fatal("base inventory lost")}
}
