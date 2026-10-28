package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
 "encoding/json"
 "errors"
 "fmt"
 "io"
 "net/http"
 "strings"
 "time"
)

type DiscoverySettings struct {
 PollIntervalSeconds int `json:"poll_interval_seconds"`
 ScanIntervalSeconds int `json:"scan_interval_seconds"`
 MDNSIntervalSeconds int `json:"mdns_interval_seconds"`
 SSDPIntervalSeconds int `json:"ssdp_interval_seconds"`
 WSDIntervalSeconds int `json:"wsd_interval_seconds"`
 ConfirmSuccesses int `json:"confirm_successes"`
 ConfirmFailures int `json:"confirm_failures"`
}

func(defaults DiscoverySettings)validate()error{
 boundaries:=[]struct{name string;value,min,max int}{
  {"poll_interval_seconds",defaults.PollIntervalSeconds,15,3600},
  {"scan_interval_seconds",defaults.ScanIntervalSeconds,60,3600},
  {"mdns_interval_seconds",defaults.MDNSIntervalSeconds,120,3600},
  {"ssdp_interval_seconds",defaults.SSDPIntervalSeconds,120,3600},
  {"wsd_interval_seconds",defaults.WSDIntervalSeconds,120,3600},
  {"confirm_successes",defaults.ConfirmSuccesses,1,5},
  {"confirm_failures",defaults.ConfirmFailures,1,8},
 }
 for _,f:=range boundaries{if f.value<f.min||f.value>f.max{return fmt.Errorf("%s must be %d..%d",f.name,f.min,f.max)}}
 return nil
}

func(db *DB)initializeSettings(defaults DiscoverySettings)error{
 if err:=defaults.validate();err!=nil{return err}
 db.mu.Lock()
 defer db.mu.Unlock()
 if err:=db.run(`INSERT OR IGNORE INTO discovery_settings
 (id,poll_interval_seconds,scan_interval_seconds,mdns_interval_seconds,ssdp_interval_seconds,wsd_interval_seconds,confirm_successes,confirm_failures)
 VALUES(1,?,?,?,?,?,?,?)`,
 fmt.Sprint(defaults.PollIntervalSeconds),fmt.Sprint(defaults.ScanIntervalSeconds),
 fmt.Sprint(defaults.MDNSIntervalSeconds),fmt.Sprint(defaults.SSDPIntervalSeconds),
 fmt.Sprint(defaults.WSDIntervalSeconds),fmt.Sprint(defaults.ConfirmSuccesses),fmt.Sprint(defaults.ConfirmFailures));err!=nil{return err}
 values,err:=db.readSettingsLocked()
 if err==nil {db.lanFreshness=time.Duration(values.ScanIntervalSeconds*2+30)*time.Second;db.haFreshness=time.Duration(values.PollIntervalSeconds*3)*time.Second}
 return err
}
func(db *DB)readSettingsLocked()(DiscoverySettings,error){
 var values DiscoverySettings
 count,err:=db.prepared(`SELECT poll_interval_seconds,scan_interval_seconds,mdns_interval_seconds,
 ssdp_interval_seconds,wsd_interval_seconds,confirm_successes,confirm_failures FROM discovery_settings WHERE id=1`,
 nil,func(stmt *C.sqlite3_stmt){
  values=DiscoverySettings{
   int(C.sqlite3_column_int(stmt,0)),int(C.sqlite3_column_int(stmt,1)),
   int(C.sqlite3_column_int(stmt,2)),int(C.sqlite3_column_int(stmt,3)),
   int(C.sqlite3_column_int(stmt,4)),int(C.sqlite3_column_int(stmt,5)),
   int(C.sqlite3_column_int(stmt,6)),
  }
 })
 if err!=nil{return values,err}
 if count!=1{return values,errors.New("discovery settings missing")}
 return values,values.validate()
}
func(db *DB)readSettings()(DiscoverySettings,error){
 db.mu.Lock();defer db.mu.Unlock()
 return db.readSettingsLocked()
}
func(db *DB)writeSettings(v DiscoverySettings)error{
 if err:=v.validate();err!=nil{return err}
 db.mu.Lock();defer db.mu.Unlock()
 err:=db.run(`UPDATE discovery_settings SET poll_interval_seconds=?,scan_interval_seconds=?,
 mdns_interval_seconds=?,ssdp_interval_seconds=?,wsd_interval_seconds=?,
 confirm_successes=?,confirm_failures=? WHERE id=1`,
 fmt.Sprint(v.PollIntervalSeconds),fmt.Sprint(v.ScanIntervalSeconds),
 fmt.Sprint(v.MDNSIntervalSeconds),fmt.Sprint(v.SSDPIntervalSeconds),
 fmt.Sprint(v.WSDIntervalSeconds),fmt.Sprint(v.ConfirmSuccesses),fmt.Sprint(v.ConfirmFailures))
 if err==nil {
  db.lanFreshness=time.Duration(v.ScanIntervalSeconds*2+30)*time.Second
  db.haFreshness=time.Duration(v.PollIntervalSeconds*3)*time.Second
 }
 return err
}
func(s *Service)intervalFor(source string,original time.Duration)time.Duration{
 values,err:=s.db.readSettings()
 if err!=nil{return original}
 var n int
 switch source{
 case "ha":n=values.PollIntervalSeconds
 case "arp":n=values.ScanIntervalSeconds
 case "mdns":n=values.MDNSIntervalSeconds
 case "ssdp":n=values.SSDPIntervalSeconds
 case "wsd":n=values.WSDIntervalSeconds
 default:return original
 }
 return time.Duration(n)*time.Second
}
func(s *Service)settingsAPI(w http.ResponseWriter,r *http.Request){
 if r.Method==http.MethodGet {
  values,err:=s.db.readSettings()
  if err!=nil{http.Error(w,"settings unavailable",500);return}
  reply(w,values);return
 }
 if r.Method!=http.MethodPut{http.Error(w,"method not allowed",405);return}
 if r.Header.Get("X-DH-UI")!="1"||!strings.HasPrefix(r.Header.Get("Content-Type"),"application/json"){
  http.Error(w,"Ingress JSON required",415);return
 }
 var input DiscoverySettings
 dec:=json.NewDecoder(http.MaxBytesReader(w,r.Body,4096))
 dec.DisallowUnknownFields()
 if err:=dec.Decode(&input);err!=nil{http.Error(w,"invalid JSON",400);return}
 var extra any
 if err:=dec.Decode(&extra);err!=io.EOF{http.Error(w,"unexpected JSON",400);return}
 if err:=input.validate();err!=nil{http.Error(w,err.Error(),400);return}
 if err:=s.db.writeSettings(input);err!=nil{http.Error(w,"settings unavailable",500);return}
 reply(w,map[string]any{"saved":true,"settings":input})
}
