package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "errors"
 "fmt"
 "log"
 "sync"
 "time"
)

// No SQLite schema or Supervisor settings are deleted by an inventory reset.
// All persisted discovery/inventory rows are removed inside one transaction.
// Child records precede their parent device rows because foreign keys are ON.
var inventoryTables=[]string{
 "observations",
 "mdns_services","mdns_hosts","mdns_unmatched",
 "ssdp_services","ssdp_unmatched",
 "wsd_names","wsd_endpoints","wsd_unmatched",
 "ipv4_evidence","ipv4_disagreement_state","lan_positive",
 "identities","events","sources","device_births","devices",
}

// Useful for asserting a complete reset without exposing arbitrary SQL in the API.
func (db *DB) inventoryRecordCount(table string) (int,error) {
 allowed:=table=="schema_version"
 for _,name:=range inventoryTables {if name==table{allowed=true;break}}
 if !allowed {return 0,errors.New("unrecognized inventory table")}
 db.mu.Lock()
 defer db.mu.Unlock()
 count:=0
 _,err:=db.prepared("SELECT COUNT(*) FROM "+table,nil,func(stmt *C.sqlite3_stmt){count=int(C.sqlite3_column_int64(stmt,0))})
 return count,err
}

// resetInventoryRows returns the previous device count. Failed deletes roll
// back *everything*; it never drops schema_version or recreates SQLite files.
func (db *DB) resetInventoryRows() (count int,err error) {
 db.mu.Lock()
 defer db.mu.Unlock()
 if err=db.exec("BEGIN IMMEDIATE");err!=nil{return 0,err}
 committed:=false
 defer func(){if !committed {_=db.exec("ROLLBACK")}}()
 _,err=db.prepared("SELECT COUNT(*) FROM devices",nil,func(s *C.sqlite3_stmt){count=int(C.sqlite3_column_int64(s,0))})
 if err!=nil{return 0,err}
 for _,table:=range inventoryTables {
  // inventoryTables is a static, audited list, never client-controlled SQL.
  if err=db.run("DELETE FROM "+table);err!=nil{return 0,fmt.Errorf("reset table %s: %w",table,err)}
 }
 // Reset is a deliberate new initial inventory. Suppress first-census alerts.
 now:=time.Now().UTC().Format(time.RFC3339Nano)
 if err=db.run("INSERT INTO network_event_policy(key,value) VALUES('baseline_active','1') ON CONFLICT(key) DO UPDATE SET value='1'");err!=nil{return 0,err}
 if err=db.run("INSERT INTO network_event_policy(key,value) VALUES('baseline_started_at',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",now);err!=nil{return 0,err}
 if err=db.run("DELETE FROM network_event_policy WHERE key='baseline_until'");err!=nil{return 0,err}
 if err=db.exec("COMMIT");err!=nil{return 0,err}
 committed=true
 return count,nil
}

// Scanners can spend many seconds collecting network data. A generation is
// captured BEFORE a scan; its result is discarded if Reset completed in the
// meantime. Short persistence sections use the RW gate to serialize with Reset.
func (s *Service) currentScanGeneration() uint64 {
 s.resetGate.RLock()
 defer s.resetGate.RUnlock()
 return s.resetGeneration
}
func (s *Service) withCurrentGeneration(gen uint64,action func()) bool {
 s.resetGate.RLock()
 defer s.resetGate.RUnlock()
 if gen!=s.resetGeneration{return false}
 action()
 return true
}

// Called only by the confirmed Ingress API. The DB transaction and generation
// advance are atomic from every scanner's perspective.
func (s *Service) resetInventory() (int,error) {
 s.resetGate.Lock()
 defer s.resetGate.Unlock()
 previous,err:=s.db.resetInventoryRows()
 if err!=nil{return 0,err}
 s.resetGeneration++
 log.Printf("Network inventory reset confirmed: %d devices removed; discovery generation %d",previous,s.resetGeneration)
 return previous,nil
}

// Re-run an ordered first discovery: router + local interface/ARP first,
// metadata sources only after the fresh ARP identity mapping is available.
// Existing periodic pollers keep running with their normal intervals.
func (s *Service) startFreshDiscovery() {
 go func(){
  s.pollRouterSource()
  s.pollLAN()
  var wg sync.WaitGroup
  wg.Add(3)
  go func(){defer wg.Done();s.pollMDNS()}()
  go func(){defer wg.Done();s.pollSSDP()}()
  go func(){defer wg.Done();s.pollWSD()}()
  wg.Wait()
  log.Print("Post-reset discovery pass completed")
 }()
}

var errResetConfirmation=errors.New("reset requires exact RESET confirmation")

// The UI intentionally performs no reset until this exact word is supplied.
func confirmReset(value string) error {
 if value!="RESET" {return errResetConfirmation}
 return nil
}
