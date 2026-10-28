package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "context"
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "net/http"
 "os"
 "os/exec"
 "path/filepath"
 "strings"
 "time"
 "unicode/utf8"
)

type MonitorView struct {
 Method string `json:"method"`
 WatchID string `json:"watch_id"`
 State string `json:"state"`
 Reason string `json:"reason"`
 LastCheck string `json:"last_check"`
 Label string `json:"label"`
 TargetJSON string `json:"target_json"`
}

func (db *DB) monitoredStates() ([]MonitorView,error) {
 result:=[]MonitorView{}
 err:=db.query("SELECT method,watch_id,state,reason,last_check,label,target_json FROM monitor_states ORDER BY method,watch_id",func(s *C.sqlite3_stmt){
  result=append(result,MonitorView{Method:field(s,0),WatchID:field(s,1),State:field(s,2),Reason:field(s,3),LastCheck:field(s,4),Label:field(s,5),TargetJSON:field(s,6)})
 })
 return result,err
}

func monitoredConfigPath() string {
 dir:=filepath.Dir(os.Getenv("DH_DB"))
 if dir=="." {dir="/data"}
 return filepath.Join(dir,"monitored_devices.yaml")
}

func readMonitorConfig(w http.ResponseWriter,r *http.Request) {
 content,err:=os.ReadFile(monitoredConfigPath())
 if errors.Is(err,os.ErrNotExist) {
  reply(w,map[string]any{"yaml":"monitored_devices: {}\n","configured":false})
  return
 }
 if err!=nil{http.Error(w,"monitor YAML unavailable",http.StatusInternalServerError);return}
 reply(w,map[string]any{"yaml":string(content),"configured":true})
}

func validateMonitorFile(ctx context.Context,path string) error {
 script:=os.Getenv("DH_MONITOR_VALIDATOR")
 if script=="" {script="/app/monitoring.py"}
 cmd:=exec.CommandContext(ctx,"python3",script,"--validate",path)
 output,err:=cmd.CombinedOutput()
 if err!=nil {
  if ctx.Err()!=nil{return fmt.Errorf("monitor config validation timed out")}
  problem:=strings.TrimSpace(string(output))
  if len(problem)>750 {problem=problem[:750]}
  if problem=="" {problem="invalid monitored_devices configuration"}
  return errors.New(problem)
 }
 return nil
}

func writeMonitorConfig(w http.ResponseWriter,r *http.Request) {
 if r.Header.Get("X-DH-UI")!="1" ||
     !strings.HasPrefix(r.Header.Get("Content-Type"),"application/json") {
  http.Error(w,"Ingress JSON request required",http.StatusUnsupportedMediaType)
  return
 }
 var input struct { YAML string `json:"yaml"` }
 decoder:=json.NewDecoder(http.MaxBytesReader(w,r.Body,1<<17))
 decoder.DisallowUnknownFields()
 if err:=decoder.Decode(&input);err!=nil {http.Error(w,"invalid JSON request",400);return}
 var extra any
 if err:=decoder.Decode(&extra);err!=io.EOF {http.Error(w,"unexpected JSON request content",400);return}
 if len(input.YAML)==0||len(input.YAML)>65536||!utf8.ValidString(input.YAML) {
  http.Error(w,"YAML must be valid UTF-8, 1..65536 bytes",400);return
 }
 path:=monitoredConfigPath()
 temporary,err:=os.CreateTemp(filepath.Dir(path),".monitored-*.tmp")
 if err!=nil{http.Error(w,"monitor YAML storage unavailable",500);return}
 defer os.Remove(temporary.Name())
 defer temporary.Close()
 if err:=temporary.Chmod(0600);err!=nil {http.Error(w,"temporary YAML permission failure",500);return}
 if _,err:=temporary.WriteString(input.YAML);err!=nil {http.Error(w,"YAML write failed",500);return}
 if err:=temporary.Sync();err!=nil{http.Error(w,"YAML sync failed",500);return}
 if err:=temporary.Close();err!=nil{http.Error(w,"YAML close failed",500);return}
 ctx,cancel:=context.WithTimeout(r.Context(),5*time.Second)
 defer cancel()
 if err:=validateMonitorFile(ctx,temporary.Name());err!=nil {
  http.Error(w,err.Error(),400)
  return
 }
 if err:=os.Rename(temporary.Name(),path);err!=nil {
  http.Error(w,"atomic YAML replace failed",500);return
 }
 reply(w,map[string]any{"saved":true,"reloaded_automatically":true})
}
