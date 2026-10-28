package main

import (
 "path/filepath"
 "testing"
 "net/http"
 "net/http/httptest"
 "strings"
 "sync/atomic"
 "time"
)

func TestPresenceSubscriptionAndGlobalSettingsPersistence(t *testing.T){
 path:=filepath.Join(t.TempDir(),"network.sqlite3")
 db,err:=openDB(path);if err!=nil{t.Fatal(err)}
 if err=db.initializeSettings(DiscoverySettings{60,180,300,300,300,2,3});err!=nil{t.Fatal(err)}
 if _,err=presenceTarget("ip","192.168.2.30");err!=nil{t.Fatal(err)}
 if _,err=presenceTarget("mac","E8:FF:1E:D7:3A:48");err!=nil{t.Fatal(err)}
 for _,target:=range []string{"127.0.0.1","2001:db8::1","999.168.2.1"}{
  if _,err=presenceTarget("ip",target);err==nil{t.Fatalf("invalid IP accepted %s",target)}
 }
 if _,err=presenceTarget("mac","FF:FF:FF:FF:FF:FF");err==nil{t.Fatal("broadcast MAC accepted")}
 if _,err=db.updatePresence("ip","192.168.2.30",true,true);err!=nil{t.Fatal(err)}
 states,err:=db.presenceSubscriptions();if err!=nil{t.Fatal(err)}
 if len(states)!=1||states[0].State!="working"||states[0].Reason!="scan_requested"{
  t.Fatalf("initial Presence should show Working, got %#v",states)
 }
 if _,err=db.updatePresence("mac","E8:FF:1E:D7:3A:48",true,false);err!=nil{t.Fatal(err)}
 subs,err:=db.presenceSubscriptions();if err!=nil{t.Fatal(err)}
 if len(subs)!=2||!subs[0].Notifications{t.Fatalf("unexpected subscriptions %#v",subs)}
 settings:=DiscoverySettings{30,120,600,480,360,3,4}
 if err=db.writeSettings(settings);err!=nil{t.Fatal(err)}
 if err=db.writeSettings(DiscoverySettings{});err==nil{t.Fatal("zero intervals accepted")}
 db.Close()
 db,err=openDB(path);if err!=nil{t.Fatal(err)}
 defer db.Close()
 if err=db.initializeSettings(DiscoverySettings{60,180,300,300,300,2,3});err!=nil{t.Fatal(err)}
 got,err:=db.readSettings();if err!=nil{t.Fatal(err)}
 if got!=settings{t.Fatalf("settings lost on restart got %#v expected %#v",got,settings)}
 subs,err=db.presenceSubscriptions();if err!=nil{t.Fatal(err)}
 if len(subs)!=2{t.Fatalf("subscriptions lost: %#v",subs)}
 if _,err=db.updatePresence("ip","192.168.2.30",false,false);err!=nil{t.Fatal(err)}
 subs,err=db.presenceSubscriptions();if err!=nil{t.Fatal(err)}
 if len(subs)!=1||subs[0].Kind!="mac"{t.Fatalf("disabled subscription remained active: %#v",subs)}
}

func TestResetClearsDeliveryHistoryAndRuntimeStatesButNotSettings(t *testing.T){
 db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"));if err!=nil{t.Fatal(err)}
 defer db.Close()
 if err=db.initializeSettings(DiscoverySettings{60,180,300,300,300,2,3});err!=nil{t.Fatal(err)}
 if _,err=db.updatePresence("ip","192.168.2.30",true,false);err!=nil{t.Fatal(err)}
 if err=db.run("INSERT INTO event_delivery_log(event_id,event_type,occurred_at,status,payload_json) VALUES('id','tracked_device_reachable','2026-10-29T00:00:00Z','queued','{}')");err!=nil{t.Fatal(err)}
 if _,err=db.resetInventoryRows();err!=nil{t.Fatal(err)}
 logs,err:=db.deliveryEvents();if err!=nil{t.Fatal(err)}
 if len(logs)!=0{t.Fatal("Reset retained old delivery log")}
 subs,err:=db.presenceSubscriptions();if err!=nil{t.Fatal(err)}
 if len(subs)!=1{t.Fatalf("Reset unexpectedly deleted user subscription: %#v",subs)}
}

func TestPresenceAPIStartsOneImmediateGlobalScanAndNotForNotificationChanges(t *testing.T){
 db,err:=openDB(filepath.Join(t.TempDir(),"presence.sqlite3"));if err!=nil{t.Fatal(err)}
 defer db.Close()
 if err=db.initializeSettings(DiscoverySettings{60,180,300,300,300,2,3});err!=nil{t.Fatal(err)}
 var started atomic.Int32
 signal:=make(chan struct{},1)
 unblock:=make(chan struct{})
 service:=&Service{db:db,started:time.Now()}
 service.presenceScanNow=func(){started.Add(1);signal<-struct{}{};<-unblock}
 handler:=service.routes()
 request:=func(body string) *httptest.ResponseRecorder{
  req:=httptest.NewRequest(http.MethodPut,"/api/presence",strings.NewReader(body))
  req.RemoteAddr="172.30.32.2:12345"
  req.Header.Set("Content-Type","application/json")
  req.Header.Set("X-DH-UI","1")
  out:=httptest.NewRecorder()
  handler.ServeHTTP(out,req)
  return out
 }
 first:=request(`{"kind":"ip","target":"192.168.2.30","enabled":true,"notifications":false}`)
 if first.Code!=200||!strings.Contains(first.Body.String(),`"scan_requested":true`){
  t.Fatalf("first enable did not schedule scan: %d %s",first.Code,first.Body.String())
 }
 select {case <-signal:case <-time.After(2*time.Second):t.Fatal("out-of-cycle scan not started")}
 second:=request(`{"kind":"ip","target":"192.168.2.30","enabled":true,"notifications":true}`)
 if second.Code!=200||!strings.Contains(second.Body.String(),`"scan_requested":false`){
  t.Fatalf("changing notifications triggered duplicate scan: %d %s",second.Code,second.Body.String())
 }
 third:=request(`{"kind":"mac","target":"E8:FF:1E:D7:3A:48","enabled":true,"notifications":false}`)
 if third.Code!=200||!strings.Contains(third.Body.String(),`"scan_requested":true`){
  t.Fatalf("MAC enable failed: %d %s",third.Code,third.Body.String())
 }
 if started.Load()!=1{t.Fatal("concurrent activations launched duplicate scans")}
 close(unblock)
 time.Sleep(15*time.Millisecond)
 if started.Load()!=1{t.Fatal("coalesced scan unexpectedly repeated")}
}
