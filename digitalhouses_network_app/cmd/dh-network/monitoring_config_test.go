package main

import (
 "encoding/json"
 "net/http"
 "net/http/httptest"
 "os"
 "path/filepath"
 "strings"
 "testing"
)

func TestMonitorConfigIngressAtomicValidationAndUTF8(t *testing.T){
 dbPath:=filepath.Join(t.TempDir(),"network.sqlite3")
 t.Setenv("DH_DB",dbPath)
 script:=filepath.Join("..","..","rootfs","app","monitoring.py")
 t.Setenv("DH_MONITOR_VALIDATOR",script)
 db,err:=openDB(dbPath)
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 service:=&Service{db:db}
 path:=monitoredConfigPath()
 request:=func(method,uri,raw,addr string,header bool) *httptest.ResponseRecorder{
  req:=httptest.NewRequest(method,uri,strings.NewReader(raw))
  req.RemoteAddr=addr
  req.Header.Set("Content-Type","application/json")
  if header{req.Header.Set("X-DH-UI","1")}
  recorder:=httptest.NewRecorder()
  service.routes().ServeHTTP(recorder,req)
  return recorder
 }
 initial:=request("GET","/api/monitored-config","","172.30.32.2:4500",false)
 if initial.Code!=200||!strings.Contains(initial.Body.String(),"monitored_devices") {t.Fatalf("missing default empty YAML: %d %s",initial.Code,initial.Body)}
 if _,err:=os.Stat(path);!os.IsNotExist(err){t.Fatalf("default YAML must not create a file: %v",err)}
 valid:="monitored_devices:\n  icmp:\n    media_server:\n      ip: 192.168.11.238\n      label: \"Медиасервер\"\n"
 payload,_:=json.Marshal(map[string]string{"yaml":valid})
 denied:=request("PUT","/api/monitored-config",string(payload),"192.168.11.71:4500",true)
 if denied.Code!=403{t.Fatalf("non-Ingress update accepted: %d",denied.Code)}
 denied=request("PUT","/api/monitored-config",string(payload),"172.30.32.2:4500",false)
 if denied.Code!=415{t.Fatalf("missing guarded header accepted: %d",denied.Code)}
 good:=request("PUT","/api/monitored-config",string(payload),"172.30.32.2:4500",true)
 if good.Code!=200{t.Fatalf("valid YAML rejected: %d %s",good.Code,good.Body)}
 original,err:=os.ReadFile(path)
 if err!=nil||string(original)!=valid{t.Fatalf("atomic YAML differs: %v %q",err,original)}
 invalid:="monitored_devices:\n  tcp:\n    plex:\n      ip: 192.168.11.238\n"
 payload,_=json.Marshal(map[string]string{"yaml":invalid})
 bad:=request("PUT","/api/monitored-config",string(payload),"172.30.32.2:4500",true)
 if bad.Code!=400{t.Fatalf("invalid YAML accepted: %d %s",bad.Code,bad.Body)}
 persisted,err:=os.ReadFile(path)
 if err!=nil||string(persisted)!=valid{t.Fatalf("invalid edit destroyed previous YAML: %v",err)}
 current:=request("GET","/api/monitored-config","","172.30.32.2:4500",false)
 if current.Code!=200||!strings.Contains(current.Body.String(),"Медиасервер"){t.Fatalf("GET did not return Unicode content: %d %s",current.Code,current.Body)}
}

func TestEmptyMonitorStateList(t *testing.T){
 db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 rows,err:=db.monitoredStates()
 if err!=nil||rows==nil||len(rows)!=0{t.Fatalf("unexpected monitoring rows: %#v %v",rows,err)}
}
