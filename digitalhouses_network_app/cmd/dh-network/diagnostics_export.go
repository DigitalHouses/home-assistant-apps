package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
    "encoding/json"
    "fmt"
    "net/http"
    "time"
)

// The Ingress UI can be sandboxed by Home Assistant. Avoid blob: URLs and
// deliver real attachment bytes from the authenticated Ingress API.
// No archive or temporary file is stored on the server.
func (s *Service) downloadDiagnostics(w http.ResponseWriter,r *http.Request) {
    report,err:=s.diagnosticReport()
    if err!=nil {http.Error(w,"diagnostic unavailable",http.StatusInternalServerError);return}
    payload,err:=json.MarshalIndent(report,"","  ")
    if err!=nil {http.Error(w,"diagnostic encoding failed",http.StatusInternalServerError);return}
    name:="dh-network-diagnostic-"+time.Now().UTC().Format("20060102-150405")+".json"
    w.Header().Set("Content-Type","application/json; charset=utf-8")
    w.Header().Set("Content-Disposition",fmt.Sprintf("attachment; filename=%q",name))
    w.Header().Set("Cache-Control","no-store, no-cache, must-revalidate")
    w.Header().Set("X-Content-Type-Options","nosniff")
    w.WriteHeader(http.StatusOK)
    _,_ =w.Write(append(payload,'\n'))
}

// Debug data is a bounded snapshot of the actual persisted machine state.
// Statuses are kept separate: MQTT broker ACK is never reported as HA handled.
func (s *Service) diagnosticDebug() map[string]any {
    detail:=map[string]any{
        "mode":"extended_debug_v1",
        "notes":"Contains IP/MAC, names, user notes and recent event payloads; review before sharing. No access tokens or MQTT passwords.",
        "captured_at":time.Now().UTC().Format(time.RFC3339Nano),
    }
    if settings,err:=s.db.readSettings();err==nil {
        detail["global_settings"]=settings
    } else {detail["global_settings_status"]="unavailable"}
    if watches,err:=s.db.presenceSubscriptions();err==nil {
        detail["presence_subscriptions"]=watches
        stateCounts:=map[string]int{}
        for _,watch:=range watches {stateCounts[watch.State]++}
        detail["presence_state_counts"]=stateCounts
    } else {detail["presence_status"]="unavailable"}
    if legacy,err:=s.db.monitoredStates();err==nil {
        detail["legacy_monitor_states"]=legacy
    } else {detail["legacy_monitor_status"]="unavailable"}
    if events,err:=s.db.deliveryEvents();err==nil {
        if len(events)>150 {events=events[:150]}
        detail["last_delivery_events"]=events
        detail["last_delivery_events_limit"]=150
    } else {detail["delivery_journal_status"]="unavailable"}
    queues:=map[string]int{}
    err:=s.db.query(`SELECT
        (SELECT count(*) FROM presence_outbox),
        (SELECT count(*) FROM monitor_outbox),
        (SELECT count(*) FROM device_births WHERE publish_state='pending'),
        (SELECT count(*) FROM event_delivery_log WHERE status='queued'),
        (SELECT count(*) FROM event_delivery_log WHERE status='retrying'),
        (SELECT count(*) FROM event_delivery_log WHERE status='broker_acked'),
        (SELECT count(*) FROM presence_subscriptions WHERE enabled=1),
        (SELECT count(*) FROM presence_states)`,
        func(stmt *C.sqlite3_stmt) {
            labels:=[]string{"presence_outbox","legacy_monitor_outbox","new_device_pending",
                "delivery_queued","delivery_retrying","delivery_broker_acked",
                "active_presence_subscriptions","presence_state_records"}
            for i,label:=range labels {queues[label]=int(C.sqlite3_column_int64(stmt,C.int(i)))}
        })
    if err!=nil {
        detail["queue_status"]="unavailable"
    } else {
        detail["queue_counters"]=queues
    }
    return detail
}
