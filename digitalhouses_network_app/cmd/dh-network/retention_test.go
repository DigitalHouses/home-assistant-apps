package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
    "path/filepath"
    "testing"
    "time"
)

func TestRetentionSettingsUpgradeWithoutReset(t *testing.T) {
    path:=filepath.Join(t.TempDir(),"prior.sqlite3")
    db,err:=openDB(path);if err!=nil{t.Fatal(err)}
    if err=db.run("DROP TABLE discovery_settings");err!=nil{t.Fatal(err)}
    if err=db.run(`CREATE TABLE discovery_settings(
        id INTEGER PRIMARY KEY CHECK(id=1),
        poll_interval_seconds INTEGER NOT NULL,scan_interval_seconds INTEGER NOT NULL,
        mdns_interval_seconds INTEGER NOT NULL,ssdp_interval_seconds INTEGER NOT NULL,
        wsd_interval_seconds INTEGER NOT NULL,
        confirm_successes INTEGER NOT NULL,confirm_failures INTEGER NOT NULL)`);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO discovery_settings VALUES(1,60,180,300,300,300,2,3)");err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO devices(id,mac,presence,first_seen,last_seen,note) VALUES('persistent','02:AA:BB:CC:DD:11','not_observed','2026-09-01T00:00:00Z','2026-09-01T00:00:00Z','customer note')");err!=nil{t.Fatal(err)}
    db.Close()
    db,err=openDB(path);if err!=nil{t.Fatal(err)}
    defer db.Close()
    if err=db.initializeSettings(DiscoverySettings{60,180,300,300,300,2,3,30,30});err!=nil{t.Fatal(err)}
    settings,err:=db.readSettings();if err!=nil{t.Fatal(err)}
    if settings.HistoryDays!=30||settings.AbsentDeviceDays!=30{t.Fatalf("migration settings: %+v",settings)}
    devices,err:=db.devices();if err!=nil||len(devices)!=1||devices[0].ID!="persistent"||devices[0].Note!="customer note" {
        t.Fatalf("migration lost inventory: %+v %v",devices,err)
    }
}

func TestRetentionPrunesOldHistoryAndUnprotectedAbsentDevices(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"retention.sqlite3"))
    if err!=nil{t.Fatal(err)}
    defer db.Close()
    if err=db.initializeSettings(DiscoverySettings{60,180,300,300,300,2,3,30,30});err!=nil{t.Fatal(err)}
    now:=time.Date(2026,11,30,12,0,0,0,time.UTC)
    old:=now.AddDate(0,0,-45).Format(time.RFC3339)
    fresh:=now.Format(time.RFC3339)
    for _,d:=range []struct{id,mac,ip,note string}{
        {"purge","02:AA:BB:CC:DD:11","192.168.11.91",""},
        {"note","02:AA:BB:CC:DD:12","192.168.11.92","important"},
        {"watch_mac","02:AA:BB:CC:DD:13","192.168.11.93",""},
        {"watch_ip","02:AA:BB:CC:DD:14","",""},
        {"ha_guard","02:AA:BB:CC:DD:15","192.168.11.95",""},
    } {
        if err=db.run("INSERT INTO devices(id,display_name,mac,ipv4,presence,first_seen,last_seen,note) VALUES(?,?,?,?,'not_observed',?,?,?)",
            d.id,d.id,d.mac,d.ip,old,old,d.note);err!=nil{t.Fatal(err)}
        if err=db.run("INSERT INTO identities(device_id,kind,value,first_seen,last_seen) VALUES(?,'mac',?,?,?)",
            d.id,d.mac,old,old);err!=nil{t.Fatal(err)}
    }
    if err=db.run("INSERT INTO identities(device_id,kind,value,first_seen,last_seen) VALUES('watch_ip','ipv4','192.168.11.94',?,?)",old,old);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO identities(device_id,kind,value,first_seen,last_seen) VALUES('ha_guard','ha_entity','device_tracker.test',?,?)",old,old);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO presence_subscriptions(kind,target,enabled,updated_at) VALUES('mac','02:AA:BB:CC:DD:13',1,?)",fresh);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO presence_subscriptions(kind,target,enabled,updated_at) VALUES('ip','192.168.11.94',1,?)",fresh);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO observations(device_id,source,observed_at) VALUES('purge','arp',?)",old);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO events(event_type,occurred_at) VALUES('old',?)",old);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO events(event_type,occurred_at) VALUES('recent',?)",fresh);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO event_delivery_log(event_id,event_type,occurred_at,status,payload_json) VALUES('old-acked','device_discovered',?,'broker_acked','{}')",old);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO event_delivery_log(event_id,event_type,occurred_at,status,payload_json) VALUES('pending','device_discovered',?,'queued','{}')",old);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO sources(id,kind,status,last_success) VALUES('LAN ARP','lan_arp','ok',?)",fresh);err!=nil{t.Fatal(err)}
    history,removed,err:=db.maintainRetention(now)
    if err!=nil{t.Fatal(err)}
    if history<2||removed!=1{t.Fatalf("history=%d removed=%d",history,removed)}
    present:=map[string]bool{}
    devices,err:=db.devices();if err!=nil{t.Fatal(err)}
    for _,device:=range devices {present[device.ID]=true}
    if present["purge"]||!present["note"]||!present["watch_mac"]||!present["watch_ip"]||!present["ha_guard"] {
        t.Fatalf("unsafe device purge: %+v",present)
    }
    for _,table:=range []string{"identities","device_births","observations"} {
        n:=0
        _,err=db.prepared("SELECT COUNT(*) FROM "+table+" WHERE device_id='purge'",nil,
            func(s *C.sqlite3_stmt){n=int(C.sqlite3_column_int(s,0))})
        if err!=nil||n!=0{t.Fatalf("orphan %s rows=%d err=%v",table,n,err)}
    }
    n:=0
    _,err=db.prepared("SELECT COUNT(*) FROM event_delivery_log WHERE event_id IN ('pending','old-acked')",nil,
        func(s *C.sqlite3_stmt){n=int(C.sqlite3_column_int(s,0))})
    if err!=nil||n!=1{t.Fatalf("retention of pending MQTT failed %d %v",n,err)}
    // With HA healthy, the old HA-linked device becomes eligible too.
    if err=db.run("INSERT INTO sources(id,kind,status,last_success) VALUES('HA','ha_device_tracker','ok',?)",fresh);err!=nil{t.Fatal(err)}
    _,removed,err=db.maintainRetention(now)
    if err!=nil||removed!=1{t.Fatalf("HA-scoped deletion: %d %v",removed,err)}
}

func TestRetentionDoesNotRemoveDevicesDuringARPFailure(t *testing.T){
    db,err:=openDB(filepath.Join(t.TempDir(),"down.sqlite3"));if err!=nil{t.Fatal(err)}
    defer db.Close()
    if err=db.initializeSettings(DiscoverySettings{60,180,300,300,300,2,3,30,30});err!=nil{t.Fatal(err)}
    now:=time.Date(2026,11,30,12,0,0,0,time.UTC)
    old:=now.AddDate(0,0,-40).Format(time.RFC3339)
    if err=db.run("INSERT INTO devices(id,mac,presence,first_seen,last_seen) VALUES('old','02:AA:BB:CC:DD:66','not_observed',?,?)",old,old);err!=nil{t.Fatal(err)}
    if err=db.run("INSERT INTO sources(id,kind,status,last_success) VALUES('LAN ARP','lan_arp','error',?)",now.Format(time.RFC3339));err!=nil{t.Fatal(err)}
    _,removed,err:=db.maintainRetention(now)
    if err!=nil||removed!=0{t.Fatalf("removed during source error: %d %v",removed,err)}
}

func TestReconcileIPv4NoUnchangedDeviceWrites(t *testing.T){
    db,err:=openDB(filepath.Join(t.TempDir(),"no-op.sqlite3"));if err!=nil{t.Fatal(err)}
    defer db.Close()
    at:="2026-10-29T18:00:00Z"
    if err=db.importARPHosts([]LANHost{{MAC:"02:AA:BB:CC:DD:77",IPv4:"192.168.11.77"}},at,"enp6s18","192.168.11.0/24");err!=nil{t.Fatal(err)}
    if err=db.exec(`CREATE TABLE ipv4_write_count(n INTEGER NOT NULL);
        INSERT INTO ipv4_write_count VALUES(0);
        CREATE TRIGGER count_ip_updates AFTER UPDATE OF ipv4 ON devices
        BEGIN UPDATE ipv4_write_count SET n=n+1; END;`);err!=nil{t.Fatal(err)}
    db.mu.Lock()
    _,err=db.reconcileIPv4Locked(at)
    db.mu.Unlock()
    if err!=nil{t.Fatal(err)}
    writes:=0
    err=db.query("SELECT n FROM ipv4_write_count",func(s *C.sqlite3_stmt){writes=int(C.sqlite3_column_int(s,0))})
    if err!=nil||writes!=0{t.Fatalf("unchanged mapping rewrote %d rows: %v",writes,err)}
}
