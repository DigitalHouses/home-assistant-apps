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
 if err!=nil||len(first)!=1{t.Fatalf("router import: %+v %v",first,err)}
 births,err:=db.deviceBirths()
 if err!=nil||len(births)!=0{t.Fatalf("not_home cannot count as new: %+v %v",births,err)}
 tkr.State="home"
 next:=time.Now().UTC().Add(time.Second).Format(time.RFC3339)
 if err:=db.importRouterTrackers([]RouterTracker{tkr},next);err!=nil{t.Fatal(err)}
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
