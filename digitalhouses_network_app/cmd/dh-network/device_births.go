package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import "time"

// A device is NEW for the first 24 hours after its first positive observation.
// Device registration with a router's not_home/unknown status is not evidence
// of presence and must not produce a NEW badge or a discovered event.
func (db *DB) deviceBirths() (map[string]string,error) {
 result:=map[string]string{}
 err:=db.query("SELECT device_id,first_positive_at FROM device_births ORDER BY device_id",func(stmt *C.sqlite3_stmt){
  result[field(stmt,0)]=field(stmt,1)
 })
 return result,err
}

// A narrow diagnostic view keeps outbox state inspectable by tests without
// exporting MQTT delivery flags in the public /api/device-births contract.
func (db *DB) deviceBirthPublishStates() (map[string]string,error) {
 result:=map[string]string{}
 err:=db.query("SELECT device_id,publish_state FROM device_births ORDER BY device_id",func(stmt *C.sqlite3_stmt){
  result[field(stmt,0)]=field(stmt,1)
 })
 return result,err
}

// First database initialization/upgrade establishes a quiet baseline. New
// inserts from the initial census are visible as NEW but not emitted as alerts.
func (db *DB) initializeDiscoveryBaseline(_ string) error {
 until:=time.Now().UTC().Add(120*time.Second).Format(time.RFC3339Nano)
 return db.run("INSERT OR IGNORE INTO network_event_policy(key,value) VALUES('baseline_until',?)",until)
}
