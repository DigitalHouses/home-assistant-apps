package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import "time"

// A device is NEW for the first 24 hours after its first positive observation.
// not_home / unknown trackers are not positive evidence.
func (db *DB) deviceBirths() (map[string]string,error) {
 result:=map[string]string{}
 err:=db.query("SELECT device_id,first_positive_at FROM device_births ORDER BY device_id",func(stmt *C.sqlite3_stmt){
  result[field(stmt,0)]=field(stmt,1)
 })
 return result,err
}

func (db *DB) deviceBirthPublishStates() (map[string]string,error) {
 result:=map[string]string{}
 err:=db.query("SELECT device_id,publish_state FROM device_births ORDER BY device_id",func(stmt *C.sqlite3_stmt){
  result[field(stmt,0)]=field(stmt,1)
 })
 return result,err
}

// Test/diagnostic inspection of persisted original positive-evidence source.
func (db *DB) deviceBirthSources() (map[string]string,error) {
 result:=map[string]string{}
 err:=db.query("SELECT device_id,detection_source FROM device_births ORDER BY device_id",func(stmt *C.sqlite3_stmt){
  result[field(stmt,0)]=field(stmt,1)
 })
 return result,err
}

// The 0.1.16 database lacked this column. Preserve existing UUIDs, notes,
// birth timestamps and outbox states when migrating, including on restart.
func (db *DB) ensureDeviceBirthSourceColumn() error {
 found:=false
 if err:=db.query("PRAGMA table_info(device_births)",func(stmt *C.sqlite3_stmt){
  if field(stmt,1)=="detection_source" {found=true}
 });err!=nil{return err}
 if found{return nil}
 return db.exec("ALTER TABLE device_births ADD COLUMN detection_source TEXT NOT NULL DEFAULT ''")
}

// Caller already owns db.mu and the inventory transaction. Never replace
// the source of the very first positive observation with later evidence.
func (db *DB) markDeviceBirthSource(id,source string) error {
 return db.run("UPDATE device_births SET detection_source=? WHERE device_id=? AND detection_source=''",source,id)
}

// A first inventory is an explicit census, not a timed two-minute quiet
// period. Upgraded established inventories are already a baseline.
func (db *DB) initializeDiscoveryBaseline(_ string) error {
 now:=time.Now().UTC().Format(time.RFC3339Nano)
 if err:=db.run(`INSERT OR IGNORE INTO network_event_policy(key,value)
  SELECT 'baseline_active',
  CASE WHEN NOT EXISTS(SELECT 1 FROM devices)
       OR EXISTS(SELECT 1 FROM network_event_policy WHERE key='baseline_until' AND julianday(value)>=julianday(?))
       THEN '1' ELSE '0' END`,now);err!=nil{return err}
 return db.run("INSERT OR IGNORE INTO network_event_policy(key,value) VALUES('baseline_started_at',?)",now)
}

// Called after successful, independent HA router and LAN ARP source imports.
// Neither a timer nor process restart can end the census prematurely.
// When both sources are ready since the latest Reset/initialization,
// suppress all census births and atomically open the transition outbox.
func (db *DB) finalizeDiscoveryBaseline() (bool,error) {
 db.mu.Lock()
 defer db.mu.Unlock()
 if err:=db.exec("BEGIN IMMEDIATE");err!=nil{return false,err}
 committed:=false
 defer func(){if !committed{_ =db.exec("ROLLBACK")}}()
 active:=""
 start:=""
 _,err:=db.prepared("SELECT key,value FROM network_event_policy WHERE key IN ('baseline_active','baseline_started_at')",nil,func(s *C.sqlite3_stmt){
  switch field(s,0){case "baseline_active":active=field(s,1);case "baseline_started_at":start=field(s,1)}
 })
 if err!=nil{return false,err}
 if active!="1"||start=="" {
  if err:=db.exec("COMMIT");err!=nil{return false,err}
  committed=true
  return false,nil
 }
 ready:=0
 _,err=db.prepared(`SELECT COUNT(*) FROM sources WHERE id IN ('LAN ARP','Home Assistant router trackers')
  AND last_success IS NOT NULL AND julianday(last_success)>=julianday(?)`,[]string{start},func(s *C.sqlite3_stmt){
  ready=int(C.sqlite3_column_int64(s,0))
 })
 if err!=nil{return false,err}
 if ready!=2 {
  if err:=db.exec("COMMIT");err!=nil{return false,err}
  committed=true
  return false,nil
 }
 if err:=db.run("UPDATE device_births SET publish_state='suppressed' WHERE publish_state='pending'");err!=nil{return false,err}
 if err:=db.run("UPDATE network_event_policy SET value='0' WHERE key='baseline_active'");err!=nil{return false,err}
 if err:=db.run("DELETE FROM network_event_policy WHERE key='baseline_until'");err!=nil{return false,err}
 if err:=db.exec("COMMIT");err!=nil{return false,err}
 committed=true
 return true,nil
}
