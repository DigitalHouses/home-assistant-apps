package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "net/http"
 "net/http/httptest"
 "path/filepath"
 "strings"
 "testing"
 "time"
)

func resetTestDB(t *testing.T) (*DB,string,string) {
 t.Helper()
 db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
 if err!=nil{t.Fatal(err)}
 at:=time.Now().UTC().Format(time.RFC3339)
 mac:="18:31:BF:2F:ED:37"
 if err:=db.importARPHosts([]LANHost{{MAC:mac,IPv4:"192.168.11.71"}},at,"eth0","192.168.11.0/24");err!=nil{t.Fatal(err)}
 items,err:=db.devices()
 if err!=nil||len(items)!=1{t.Fatalf("device seed: %+v %v",items,err)}
 id:=items[0].ID
 if ok,err:=db.setNote(id,"Never silently delete this note");err!=nil||!ok{t.Fatalf("seed note: %v",err)}
 statements:=[]string{
  "INSERT INTO observations(device_id,source,observed_at,details_json) VALUES('"+id+"','ARP','"+at+"','{}')",
  "INSERT INTO events(event_type,device_id,occurred_at,data_json) VALUES('test',' "+id+"','"+at+"','{}')",
  "INSERT INTO ipv4_disagreement_state(ipv4,classification,fingerprint,details_json,first_seen,last_seen) VALUES('192.168.11.71','source_disagreement','abc','{}','"+at+"','"+at+"')",
  "INSERT INTO mdns_hosts(device_id,hostname,ipv4,first_seen,last_seen) VALUES('"+id+"','view71.local','192.168.11.71','"+at+"','"+at+"')",
  "INSERT INTO mdns_services(device_id,instance,type,port,target,first_seen,last_seen) VALUES('"+id+"','win','_http._tcp.local',80,'view71.local','"+at+"','"+at+"')",
  "INSERT INTO mdns_unmatched(hostname,ipv4,last_seen,reason) VALUES('ghost.local','192.168.11.88','"+at+"','no_arp')",
  "INSERT INTO ssdp_services(device_id,ipv4,st,usn,server,location,first_seen,last_seen) VALUES('"+id+"','192.168.11.71','upnp:rootdevice','uuid:a','test','http://192.168.11.71','"+at+"','"+at+"')",
  "INSERT INTO ssdp_unmatched(ipv4,st,usn,last_seen,reason) VALUES('192.168.11.81','upnp:rootdevice','uuid:ghost','"+at+"','no_arp')",
  "INSERT INTO wsd_endpoints(device_id,ipv4,endpoint,types,scopes,origin,first_seen,last_seen) VALUES('"+id+"','192.168.11.71','urn:uuid:11111111-1111-1111-1111-111111111111','pub:Computer','','http://192.168.11.71:5357','"+at+"','"+at+"')",
  "INSERT INTO wsd_unmatched(ipv4,endpoint,last_seen,reason) VALUES('192.168.11.81','urn:uuid:22222222-2222-2222-2222-222222222222','"+at+"','unmatched')",
  "INSERT INTO wsd_names(device_id,endpoint,computer_name,first_seen,last_seen) VALUES('"+id+"','urn:uuid:11111111-1111-1111-1111-111111111111','VIEW71','"+at+"','"+at+"')",
  "INSERT INTO sources(id,kind,status,last_success,details_json) VALUES('test','source','ok','"+at+"','{}')",
 }
 for _,sql:=range statements {if err:=db.run(sql);err!=nil{db.Close();t.Fatalf("seed %s: %v",sql,err)}}
 return db,id,mac
}
func countResetTable(t *testing.T,db *DB,table string) int{
 t.Helper()
 n:=-1
 if err:=db.query("SELECT COUNT(*) FROM "+table,func(s *C.sqlite3_stmt){n=int(C.sqlite3_column_int64(s,0))});err!=nil{t.Fatal(err)}
 return n
}

func TestResetInventoryTransactionalFullPurgeAndCleanReacquisition(t *testing.T){
 db,oldID,mac:=resetTestDB(t)
 defer db.Close()
 for _,table:=range inventoryTables {if countResetTable(t,db,table)==0{t.Fatalf("reset test did not seed %s",table)}}
 removed,err:=db.resetInventoryRows()
 if err!=nil||removed!=1{t.Fatalf("reset failed: %d %v",removed,err)}
 for _,table:=range inventoryTables {if n:=countResetTable(t,db,table);n!=0{t.Fatalf("table %s retained %d rows",table,n)}}
 version:=0
 if err:=db.query("SELECT version FROM schema_version",func(s *C.sqlite3_stmt){version=int(C.sqlite3_column_int(s,0))});err!=nil||version!=7{
  t.Fatalf("schema_version must remain v7: %d %v",version,err)
 }
 at:=time.Now().UTC().Format(time.RFC3339)
 if err:=db.importARPHosts([]LANHost{{MAC:mac,IPv4:"192.168.11.71"}},at,"eth0","192.168.11.0/24");err!=nil{t.Fatal(err)}
 items,err:=db.devices()
 if err!=nil||len(items)!=1||items[0].ID==oldID||items[0].Note!=""{
  t.Fatalf("fresh scan must create fresh UUID and blank note, got %+v %v",items,err)
 }
}
func TestResetRollbackOnAnyTableFailure(t *testing.T){
 db,_,_:=resetTestDB(t)
 defer db.Close()
 if err:=db.exec("CREATE TRIGGER stop_reset BEFORE DELETE ON devices BEGIN SELECT RAISE(FAIL,'test induced error'); END;");err!=nil{t.Fatal(err)}
 removed,err:=db.resetInventoryRows()
 if err==nil||removed!=0{t.Fatalf("reset must fail atomically: %d %v",removed,err)}
 for _,table:=range inventoryTables {if n:=countResetTable(t,db,table);n==0{t.Fatalf("transaction partially deleted %s",table)}}
 if err:=db.exec("DROP TRIGGER stop_reset");err!=nil{t.Fatal(err)}
}
func TestResetStaleDiscoveryCannotRepublishOldGeneration(t *testing.T){
 db,_,_:=resetTestDB(t)
 defer db.Close()
 service:=Service{db:db}
 old:=service.currentScanGeneration()
 if removed,err:=service.resetInventory();err!=nil||removed!=1{t.Fatalf("reset: %d %v",removed,err)}
 called:=false
 if service.withCurrentGeneration(old,func(){called=true})||called{t.Fatal("pre-reset source would be imported after reset")}
 if !service.withCurrentGeneration(service.currentScanGeneration(),func(){called=true})||!called{t.Fatal("post-reset source cannot update registry")}
}
func TestResetIngressRequiresCustomHeaderAndExplicitConfirmation(t *testing.T){
 db,_,_:=resetTestDB(t)
 defer db.Close()
 started:=0
 service:=Service{db:db,afterReset:func(){started++}}
 call:=func(addr,header,content,body string) *httptest.ResponseRecorder{
  req:=httptest.NewRequest(http.MethodPost,"/api/inventory/reset",strings.NewReader(body))
  req.RemoteAddr=addr
  if header!=""{req.Header.Set("X-DH-UI",header)}
  if content!=""{req.Header.Set("Content-Type",content)}
  rec:=httptest.NewRecorder()
  service.routes().ServeHTTP(rec,req)
  return rec
 }
 cases:=[]struct{label,addr,header,content,body string;status int}{
  {"direct LAN denied","192.168.11.71:5555","1","application/json",`{"confirmation":"RESET"}`,403},
  {"missing UI header","172.30.32.2:5555","","application/json",`{"confirmation":"RESET"}`,415},
  {"non JSON form","172.30.32.2:5555","1","application/x-www-form-urlencoded","confirmation=RESET",415},
  {"wrong phrase","172.30.32.2:5555","1","application/json",`{"confirmation":"reset"}`,400},
  {"missing phrase","172.30.32.2:5555","1","application/json",`{}`,400},
  {"extra fields","172.30.32.2:5555","1","application/json",`{"confirmation":"RESET","force":true}`,400},
 }
 for _,c:=range cases{
  rec:=call(c.addr,c.header,c.content,c.body)
  if rec.Code!=c.status{t.Fatalf("%s: HTTP %d expected %d: %s",c.label,rec.Code,c.status,rec.Body.String())}
  if countResetTable(t,db,"devices")!=1||started!=0{t.Fatalf("%s deleted data on invalid request",c.label)}
 }
 rec:=call("172.30.32.2:5555","1","application/json",`{"confirmation":"RESET"}`)
 if rec.Code!=200||!strings.Contains(rec.Body.String(),`"previous_devices":1`)||started!=1{
  t.Fatalf("confirmed reset request failed: HTTP %d, %q, starts=%d",rec.Code,rec.Body.String(),started)
 }
 for _,table:=range inventoryTables{if n:=countResetTable(t,db,table);n!=0{t.Fatalf("reset API retained %s",table)}}
}
func TestResetConfirmationExactMatch(t *testing.T){
 if confirmReset("RESET")!=nil{t.Fatal("correct confirmation rejected")}
 for _,word:=range []string{"","reset"," RESET","RESET ","СБРОС","RESET
"}{
  if confirmReset(word)==nil{t.Fatalf("invalid reset confirmation accepted %q",word)}
 }
}
