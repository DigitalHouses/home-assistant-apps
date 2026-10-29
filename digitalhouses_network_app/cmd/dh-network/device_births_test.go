package main

import (
 "path/filepath"
 "testing"
 "time"
)

func TestDeviceBirthOnlyAfterPositiveAndExactlyOnce(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"devices.sqlite3"))
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 at:=time.Now().UTC().Format(time.RFC3339)
 tkr:=RouterTracker{EntityID:"device_tracker.view71",State:"not_home",Name:"VIEW71",MAC:"18:31:BF:2F:ED:37",IPv4:"192.168.11.71"}
 if err:=db.importRouterTrackers([]RouterTracker{tkr},at);err!=nil{t.Fatal(err)}
 first,err:=db.devices()
 if err!=nil||len(first)!=0{t.Fatalf("negative-only router import: %+v %v",first,err)}
 births,err:=db.deviceBirths()
 if err!=nil||len(births)!=0{t.Fatalf("not_home cannot count as new: %+v %v",births,err)}
 tkr.State="home"
 next:=time.Now().UTC().Add(time.Second).Format(time.RFC3339)
 if err:=db.importRouterTrackers([]RouterTracker{tkr},next);err!=nil{t.Fatal(err)}
 first,err=db.devices()
 if err!=nil||len(first)!=1{t.Fatalf("positive device missing: %+v %v",first,err)}
 births,err=db.deviceBirths()
 if err!=nil||len(births)!=1||births[first[0].ID]!=next{t.Fatalf("first positive timestamp: %+v %v",births,err)}
 if err:=db.importRouterTrackers([]RouterTracker{tkr},time.Now().UTC().Add(time.Minute).Format(time.RFC3339));err!=nil{t.Fatal(err)}
 repeated,err:=db.deviceBirths()
 if err!=nil||repeated[first[0].ID]!=next||len(repeated)!=1{t.Fatalf("repeated positive reset NEW: %+v %v",repeated,err)}
 if n:=countResetTable(t,db,"device_births");n!=1{t.Fatalf("duplicate birth events: %d",n)}
}

func TestExistingRegistryIsSuppressedOnUpgradeAndResetClearsBirths(t *testing.T){
 path:=filepath.Join(t.TempDir(),"existing.sqlite3")
 db,err:=openDB(path)
 if err!=nil{t.Fatal(err)}
 at:=time.Now().UTC().Format(time.RFC3339)
 if err:=db.importARPHosts([]LANHost{{MAC:"18:31:BF:2F:ED:37",IPv4:"192.168.11.71"}},at,"eth0","192.168.11.0/24");err!=nil{t.Fatal(err)}
 if err:=db.exec("DELETE FROM device_births");err!=nil{t.Fatal(err)}
 db.Close()
 db,err=openDB(path)
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 births,err:=db.deviceBirths()
 if err!=nil||len(births)!=1 {t.Fatalf("backfilled existing birth: %+v %v",births,err)}
 state,err:=db.deviceBirthPublishStates()
 if err!=nil||len(state)!=1 {t.Fatalf("backfilled state: %+v %v",state,err)}
 for _,publishState:=range state {if publishState!="suppressed"{t.Fatalf("existing inventory must not flood notifications: %s",publishState)}}

 if _,err:=db.resetInventoryRows();err!=nil{t.Fatal(err)}
 if n:=countResetTable(t,db,"device_births");n!=0{t.Fatalf("reset left %d births",n)}
}

func TestBaselineWaitsForBothSourceSnapshotsAndSurvivesRestart(t *testing.T) {
 path:=filepath.Join(t.TempDir(),"census.sqlite3")
 db,err:=openDB(path)
 if err!=nil{t.Fatal(err)}
 // The first successful ARP pass is NOT enough to close the baseline.
 at:=time.Now().UTC().Add(time.Second).Format(time.RFC3339Nano)
 if err:=db.importARPHosts([]LANHost{{MAC:"18:31:BF:2F:ED:37",IPv4:"192.168.11.71"}},at,"eth0","192.168.11.0/24");err!=nil{t.Fatal(err)}
 if closed,err:=db.finalizeDiscoveryBaseline();err!=nil||closed{t.Fatalf("ARP-only baseline closed: %v %v",closed,err)}
 births,err:=db.deviceBirthPublishStates()
 if err!=nil||len(births)!=1{t.Fatalf("expected one pending birth: %+v %v",births,err)}
 for _,v:=range births {if v!="pending"{t.Fatalf("premature suppression: %s",v)}}
 // HA router import completes the second independent census source.
 now:=time.Now().UTC().Add(2*time.Second).Format(time.RFC3339Nano)
 if err:=db.importRouterTrackers([]RouterTracker{{EntityID:"device_tracker.view71",State:"home",MAC:"18:31:BF:2F:ED:37",Name:"VIEW71"}},now);err!=nil{t.Fatal(err)}
 if closed,err:=db.finalizeDiscoveryBaseline();err!=nil||!closed{t.Fatalf("complete baseline was not closed: %v %v",closed,err)}
 for _,v:=range births {
  if v!="pending"{t.Fatal("test fixture must have pending births")}
 }
 births,err=db.deviceBirthPublishStates()
 if err!=nil{t.Fatal(err)}
 for _,v:=range births {if v!="suppressed"{t.Fatalf("census emitted a new-device event: %s",v)}}
 db.Close()
 db,err=openDB(path)
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 // Subsequent new MACs after baseline completion ARE genuine transitions.
 if err:=db.importARPHosts([]LANHost{{MAC:"18:31:BF:2F:ED:37",IPv4:"192.168.11.71"},{MAC:"02:AA:BB:CC:DD:EE",IPv4:"192.168.11.72"}},time.Now().UTC().Add(3*time.Second).Format(time.RFC3339Nano),"eth0","192.168.11.0/24");err!=nil{t.Fatal(err)}
 states,err:=db.deviceBirthPublishStates()
 if err!=nil||len(states)!=2{t.Fatalf("new identity missing: %+v %v",states,err)}
 pending,suppressed:=0,0
 for _,state:=range states {if state=="pending"{pending++};if state=="suppressed"{suppressed++}}
 if pending!=1||suppressed!=1{t.Fatalf("expected one post-baseline event and one suppressed census: %+v",states)}
}

func TestBirthDetectionSourceCannotBeRewrittenByLaterRouter(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"sources.sqlite3"))
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 at:=time.Now().UTC().Format(time.RFC3339Nano)
 mac:="18:31:BF:2F:ED:37"
 if err:=db.importARPHosts([]LANHost{{MAC:mac,IPv4:"192.168.11.71"}},at,"eth0","192.168.11.0/24");err!=nil{t.Fatal(err)}
 if err:=db.importRouterTrackers([]RouterTracker{{EntityID:"device_tracker.view71",State:"home",MAC:mac,Name:"VIEW71"}},time.Now().UTC().Add(time.Second).Format(time.RFC3339Nano));err!=nil{t.Fatal(err)}
 sources,err:=db.deviceBirthSources()
 if err!=nil{t.Fatal(err)}
 if len(sources)!=1{t.Fatalf("unexpected birth sources: %+v",sources)}
 for _,source:=range sources{if source!="arp"{t.Fatalf("first evidence was overwritten: %q",source)}}
}
