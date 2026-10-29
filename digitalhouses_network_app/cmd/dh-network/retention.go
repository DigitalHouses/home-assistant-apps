package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
    "fmt"
    "log"
    "time"
)

// Upgrades existing 0.1.25 databases in place. Neither subscriptions nor
// inventory are reset by adding the two retention settings.
func (db *DB) ensureRetentionColumns() error {
    present:=map[string]bool{}
    _,err:=db.prepared("PRAGMA table_info(discovery_settings)",nil,func(s *C.sqlite3_stmt){
        present[field(s,1)]=true
    })
    if err!=nil{return err}
    for _,name:=range []string{"history_days","absent_device_days"} {
        if present[name]{continue}
        if err:=db.run("ALTER TABLE discovery_settings ADD COLUMN "+name+" INTEGER NOT NULL DEFAULT 30");err!=nil{return err}
    }
    return nil
}

func (db *DB) retentionSourceHealthy(kind string, now time.Time, maxAge time.Duration) (bool,error) {
    var status,stamp string
    _,err:=db.prepared("SELECT status,COALESCE(last_success,'') FROM sources WHERE kind=?",
        []string{kind},func(s *C.sqlite3_stmt){status=field(s,0);stamp=field(s,1)})
    if err!=nil{return false,err}
    if status!="ok"&&status!="empty"&&status!="degraded"{return false,nil}
    at,err:=time.Parse(time.RFC3339,stamp)
    if err!=nil{return false,nil}
    age:=now.Sub(at)
    return age>=0&&age<=maxAge,nil
}

// History may be discarded; identifiers, subscriptions, current Presence state,
// device_births (one-time alert deduplication) and pending MQTT events must survive.
func (db *DB) maintainRetention(now time.Time) (historyRows,devicesRemoved int,err error) {
    db.mu.Lock()
    defer db.mu.Unlock()
    settings,err:=db.readSettingsLocked()
    if err!=nil{return 0,0,err}
    historyCutoff:=now.AddDate(0,0,-settings.HistoryDays).UTC().Format(time.RFC3339)
    deviceCutoff:=now.AddDate(0,0,-settings.AbsentDeviceDays).UTC().Format(time.RFC3339)

    if err=db.exec("BEGIN IMMEDIATE");err!=nil{return 0,0,err}
    committed:=false
    defer func(){if !committed {_=db.exec("ROLLBACK")}}()
    // Never purge inventory while its source cannot confirm absence.
    // HA-linked devices additionally require a healthy HA source; LAN-only
    // devices remain eligible if the independent ARP source is healthy.
    arpOK,sourceErr:=db.retentionSourceHealthy("lan_arp",now,
        time.Duration(settings.ScanIntervalSeconds*3+90)*time.Second)
    if sourceErr!=nil{return 0,0,sourceErr}
    haOK,sourceErr:=db.retentionSourceHealthy("ha_device_tracker",now,
        time.Duration(settings.PollIntervalSeconds*3+90)*time.Second)
    if sourceErr!=nil{return 0,0,sourceErr}
    if arpOK {
        eligible:=make([]string,0)
        // Avoid deleting a monitored device even when an IP changed; check
        // retained address identity history as well as the current address.
        _,err=db.prepared(`SELECT d.id FROM devices d
          WHERE d.presence='not_observed'
            AND COALESCE(NULLIF(d.last_seen,''),d.first_seen) < ?
            AND TRIM(d.note)=''
            AND (?='1' OR NOT EXISTS (
              SELECT 1 FROM identities hi WHERE hi.device_id=d.id AND hi.kind='ha_entity'
            ))
            AND NOT EXISTS (
              SELECT 1 FROM presence_subscriptions p WHERE p.enabled=1 AND
                ((p.kind='mac' AND UPPER(p.target)=UPPER(d.mac)) OR
                 (p.kind='ip' AND
                   (p.target=d.ipv4 OR EXISTS (
                     SELECT 1 FROM identities i WHERE i.device_id=d.id
                     AND i.kind='ipv4' AND i.value=p.target
                   ))))
            )
          ORDER BY COALESCE(NULLIF(d.last_seen,''),d.first_seen),d.id LIMIT 1000`,
          []string{deviceCutoff,map[bool]string{true:"1",false:"0"}[haOK]},
          func(s *C.sqlite3_stmt){eligible=append(eligible,field(s,0))})
        if err!=nil{return 0,0,err}
        // Child rows first: foreign keys are enforced; deletion is all-or-nothing.
        for _,id:=range eligible {
            for _,table:=range []string{"observations","mdns_services","mdns_hosts",
                "ssdp_services","wsd_names","wsd_endpoints","ipv4_evidence",
                "lan_positive","identities","device_births"} {
                if err=db.run("DELETE FROM "+table+" WHERE device_id=?",id);err!=nil{
                    return 0,0,fmt.Errorf("retention child %s: %w",table,err)
                }
            }
            if err=db.run("DELETE FROM devices WHERE id=?",id);err!=nil{return 0,0,err}
            devicesRemoved+=int(C.sqlite3_changes(db.connection))
        }
    }
    // All identifiers below are hardcoded SQL; neither setting supplies a table name.
    for _,job:=range []struct{table,condition string}{
        {"observations","observed_at < ?"},
        {"events","occurred_at < ?"},
        {"event_delivery_log","occurred_at < ? AND status='broker_acked'"},
        {"identities",`last_seen < ? AND kind IN ('ipv4','ipv6') AND NOT (
            kind='ipv4' AND EXISTS (
              SELECT 1 FROM presence_subscriptions p
              WHERE p.enabled=1 AND p.kind='ip' AND p.target=identities.value
            ))`},
        {"ipv4_evidence","last_seen < ?"},
        {"ipv4_disagreement_state","last_seen < ?"},
        {"mdns_hosts","last_seen < ?"},
        {"mdns_services","last_seen < ?"},
        {"mdns_unmatched","last_seen < ?"},
        {"ssdp_services","last_seen < ?"},
        {"ssdp_unmatched","last_seen < ?"},
        {"wsd_names","last_seen < ?"},
        {"wsd_endpoints","last_seen < ?"},
        {"wsd_unmatched","last_seen < ?"},
    } {
        if err=db.run("DELETE FROM "+job.table+" WHERE "+job.condition,historyCutoff);err!=nil {
            return 0,0,fmt.Errorf("retention history %s: %w",job.table,err)
        }
        historyRows+=int(C.sqlite3_changes(db.connection))
    }

    if err=db.exec("COMMIT");err!=nil{return 0,0,err}
    committed=true
    return historyRows,devicesRemoved,nil
}

func (s *Service) runRetention() {
    // First discoveries must settle before any automatic purge.
    time.Sleep(5*time.Minute)
    for {
        history,devices,err:=s.db.maintainRetention(time.Now().UTC())
        if err!=nil {
            log.Printf("Network retention failed: %v",err)
        }else if history>0||devices>0 {
            log.Printf("Network retention: %d history rows, %d absent devices removed",history,devices)
        }
        time.Sleep(24*time.Hour)
    }
}
