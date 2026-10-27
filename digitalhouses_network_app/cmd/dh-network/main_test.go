package main

import (
    "net/http"
    "net/http/httptest"
    "path/filepath"
    "strings"
    "testing"
    "time"
)

func TestFreshStoreHasNoInventedDevicesOrEvents(t *testing.T) {
    db, err := openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
    if err != nil { t.Fatal(err) }
    defer db.Close()
    devices, err := db.devices()
    if err != nil || len(devices) != 0 { t.Fatalf("new database devices=%v err=%v",devices,err) }
    events, err := db.events()
    if err != nil || len(events) != 0 { t.Fatalf("new database events=%v err=%v",events,err) }
    service := Service{db:db,version:"0.1.0",started:time.Now()}
    req := httptest.NewRequest(http.MethodGet,"/api/status",nil)
    req.RemoteAddr = "172.30.32.2:40000"
    rec := httptest.NewRecorder()
    service.routes().ServeHTTP(rec,req)
    if rec.Code != 200 || !strings.Contains(rec.Body.String(),`"discovery_running":false`) {
        t.Fatalf("unexpected status %d %s",rec.Code,rec.Body.String())
    }
}

func TestNoteMissingDeviceDoesNotCreateDevice(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
    if err!=nil { t.Fatal(err) }
    defer db.Close()
    service:=Service{db:db,version:"0.1.0",started:time.Now()}
    request:=httptest.NewRequest(http.MethodPut,"/api/devices/unknown/note",strings.NewReader(`{"note":"test"}`))
    request.Header.Set("Content-Type","application/json")
    request.Header.Set("X-DH-UI","1")
    request.RemoteAddr = "172.30.32.2:40000"
    rec:=httptest.NewRecorder()
    service.routes().ServeHTTP(rec,request)
    if rec.Code!=404 { t.Fatalf("expected 404, got %d",rec.Code) }
}
