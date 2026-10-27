package main

import (
 "path/filepath"
 "testing"
 "time"
)

func TestIPv4ConflictARPWinsAndNotesRemain(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
 if err!=nil {t.Fatal(err)}
 defer db.Close()
 base:=time.Now().UTC().Truncate(time.Second)
 now:=base.Add(-60*time.Second).Format(time.RFC3339)
 ha:=RouterTracker{EntityID:"device_tracker.ha",MAC:"02:AA:BB:CC:DD:01",State:"home",Name:"HA Device",IPv4:"192.168.11.30"}
 if err=db.importRouterTrackers([]RouterTracker{ha},now);err!=nil {t.Fatal(err)}
 devices,_:=db.devices()
 if len(devices)!=1 {t.Fatalf("router import: %+v",devices)}
 originalID:=devices[0].ID
 if ok,err:=db.setNote(originalID,"test - HA");err!=nil||!ok {t.Fatal(err)}
 if err=db.importARPHosts([]LANHost{{MAC:"02:AA:BB:CC:DD:02",IPv4:"192.168.11.30"}},base.Add(-30*time.Second).Format(time.RFC3339),"enp6s18","192.168.11.0/24");err!=nil{t.Fatal(err)}
 devices,_=db.devices()
 if len(devices)!=2 {t.Fatalf("dropped or merged separate MACs: %+v",devices)}
 var haGot,arpGot Device
 for _,dev:=range devices {
  switch dev.MAC {
  case "02:AA:BB:CC:DD:01":haGot=dev
  case "02:AA:BB:CC:DD:02":arpGot=dev
  }
 }
 if haGot.ID!=originalID||haGot.Note!="test - HA"||haGot.IPv4!="" {t.Fatalf("conflicting HA IP not suppressed: %+v",haGot)}
 if arpGot.ID==""||arpGot.ID==originalID||arpGot.IPv4!="192.168.11.30" {t.Fatalf("ARP not winning: %+v",arpGot)}
 prior,err:=db.lookupIdentity("ipv4","192.168.11.30")
 if err!=nil||prior=="" {t.Fatalf("IP history should be preserved: %s %v",prior,err)}
 s:=Service{db:db,version:"0.1.4",started:time.Now(),intervalSeconds:60,scanIntervalSeconds:180}
 report,err:=s.diagnosticReport()
 if err!=nil {t.Fatal(err)}
 conflicts:=report["ipv4_conflicts"].([]IPv4Conflict)
 if len(conflicts)!=1 || conflicts[0].WinnerDeviceID!=arpGot.ID ||
 conflicts[0].Resolution!="arp_over_router" || len(conflicts[0].Claims)!=2 {
   t.Fatalf("incorrect conflict export: %+v",conflicts)
 }
 sources,_:=db.sources()
 status:=""
 for _,v:=range sources {if v.Kind=="ha_device_tracker" {status=v.Status}}
 if status!="ok" { // ARP scan happened after the HA poll; HA status updates at its next poll.
   t.Fatalf("unexpected HA status before repoll: %s",status)
 }
 if err=db.importRouterTrackers([]RouterTracker{ha},base.Add(-10*time.Second).Format(time.RFC3339));err!=nil {t.Fatal(err)}
 sources,_=db.sources()
 for _,v:=range sources {
  if v.Kind=="ha_device_tracker" && v.Status!="ok" {t.Fatalf("ARP-vs-router disagreement should be informational, not degraded: %+v",v)}
 }
 devices,_=db.devices()
 for _,dev:=range devices {
  if dev.ID==originalID && (dev.Note!="test - HA"||dev.IPv4!="") {t.Fatalf("regression after repeated HA poll: %+v",dev)}
 }
}
func TestRouterPreviousClaimRevokedAndOnlyHistoryRemains(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
 if err!=nil {t.Fatal(err)}
 defer db.Close()
 tracker:=RouterTracker{EntityID:"device_tracker.test",MAC:"02:01:02:03:04:05",State:"home",IPv4:"192.168.11.33"}
 if err=db.importRouterTrackers([]RouterTracker{tracker},"2026-10-27T16:00:00Z");err!=nil {t.Fatal(err)}
 tracker.IPv4="192.168.11.44"
 if err=db.importRouterTrackers([]RouterTracker{tracker},"2026-10-27T16:01:00Z");err!=nil {t.Fatal(err)}
 devices,_:=db.devices()
 if len(devices)!=1||devices[0].IPv4!="192.168.11.44" {t.Fatalf("old IP retained as current: %+v",devices)}
 past,err:=db.lookupIdentity("ipv4","192.168.11.33")
 if err!=nil||past!=devices[0].ID {t.Fatalf("history lost: %q %v",past,err)}
 snapshot,err:=db.snapshot()
 if err!=nil {t.Fatal(err)}
 if len(snapshot.IPv4Evidence)!=2 {t.Fatalf("not recording source history: %+v",snapshot.IPv4Evidence)}
 for _,claim:=range snapshot.IPv4Evidence {
  if claim.IPv4=="192.168.11.33"&&claim.State!="previous" {t.Fatalf("superseded home still active: %+v",claim)}
 }
 tracker.State="not_home"
 if err=db.importRouterTrackers([]RouterTracker{tracker},"2026-10-27T16:02:00Z");err!=nil {t.Fatal(err)}
 devices,_=db.devices()
 if devices[0].IPv4!="" {t.Fatalf("not_home address mislabeled current: %+v",devices[0])}
}
func TestTwoEquallyRecentARPClaimsAreAmbiguous(t *testing.T) {
 now:="2026-10-27T17:19:36Z"
 c:=[]IPv4Evidence{
  {DeviceID:"a",MAC:"02:11:22:33:44:01",IPv4:"192.168.11.30",Source:"arp",State:"observed",LastSeen:now},
  {DeviceID:"b",MAC:"02:11:22:33:44:02",IPv4:"192.168.11.30",Source:"arp",State:"observed",LastSeen:now},
 }
 result:=resolveIPv4Evidence(c,now,420*time.Second,180*time.Second)
 if len(result.Conflicts)!=1||result.Conflicts[0].Resolution!="ambiguous_equal_evidence"||len(result.Addresses)!=0 {
  t.Fatalf("ambiguous ARP should not assign either address: %+v",result)
 }
}
func TestExpiredARPClaimDoesNotSuppressNewRouterClaim(t *testing.T) {
 now:="2026-10-27T17:19:36Z"
 evidence:=[]IPv4Evidence{
 {DeviceID:"a",IPv4:"192.168.11.30",Source:"arp",State:"observed",LastSeen:"2026-10-27T17:00:00Z"},
 {DeviceID:"b",IPv4:"192.168.11.30",Source:"ha_router",State:"home",LastSeen:now},
 }
 got:=resolveIPv4Evidence(evidence,now,420*time.Second,180*time.Second)
 if got.Addresses["b"]!="192.168.11.30"||len(got.Conflicts)!=0 {t.Fatalf("expired evidence should not conflict: %+v",got)}
}
