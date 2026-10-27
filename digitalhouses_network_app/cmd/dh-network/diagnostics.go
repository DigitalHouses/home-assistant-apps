package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import (
    "encoding/json"
    "fmt"
    "sort"
    "time"
)

const diagnosticFormat = "digitalhouses.network.diagnostic.v1"

type DeviceOrigin struct {
    DeviceID string `json:"device_id"`
    Source string `json:"source"`
    Reference string `json:"reference,omitempty"`
    LastReportedAt string `json:"last_reported_at"`
}

type IdentityHistory struct {
    DeviceID string `json:"device_id"`
    Kind string `json:"kind"`
    Value string `json:"value"`
    FirstSeen string `json:"first_seen"`
    LastSeen string `json:"last_seen"`
}

type LANObservation struct {
    DeviceID string `json:"device_id"`
    LastSeen string `json:"last_seen"`
}

type DatabaseSnapshot struct {
    Devices []Device `json:"devices"`
    Sources []SourceInfo `json:"sources"`
    Events []Event `json:"events"`
    DeviceSources []DeviceOrigin `json:"device_sources"`
    IdentityHistory []IdentityHistory `json:"identity_history"`
    LANLastPositive []LANObservation `json:"lan_last_positive"`
    IPv4Evidence []IPv4Evidence `json:"ipv4_evidence"`
    MDNSHosts []MDNSRecord `json:"mdns_hosts"`
    MDNSServices []MDNSServiceRecord `json:"mdns_services"`
    MDNSUnmatched []MDNSUnmatched `json:"mdns_unmatched"`
    SSDPServices []SSDPServiceRecord `json:"ssdp_services"`
    SSDPUnmatched []SSDPUnmatched `json:"ssdp_unmatched"`
}

func fillSourcePlaceholders(in []SourceInfo) []SourceInfo {
    out:=append([]SourceInfo{},in...)
    if !containsSource(out,"Home Assistant router trackers") {
        out=append(out,SourceInfo{Name:"Home Assistant router trackers", Kind:"ha_device_tracker", Status:"pending"})
    }
    if !containsSource(out,"LAN ARP") {
        out=append(out,SourceInfo{Name:"LAN ARP", Kind:"lan_arp", Status:"pending"})
    }
    if !containsSource(out,"mDNS / Bonjour") {
        out=append(out,SourceInfo{Name:"mDNS / Bonjour", Kind:"mdns", Status:"pending"})
    }
    if !containsSource(out,"SSDP") {out=append(out,SourceInfo{Name:"SSDP",Kind:"ssdp",Status:"pending"})}
    out=append(out,SourceInfo{Name:"IPv6 NDP", Kind:"planned", Status:"planned"})
    return out
}

// Source membership means an interface was ever observed via this source,
// not that it is currently online. "last_reported_at" is the latest record
// updated by the source, NOT proof of a positive presence observation.
func deriveDeviceSources(identities []IdentityHistory, positives []LANObservation) []DeviceOrigin {
    result:=make([]DeviceOrigin,0)
    for _,item:=range identities {
        if item.Kind!="ha_entity" {continue}
        result=append(result,DeviceOrigin{DeviceID:item.DeviceID,Source:"HA Router",Reference:item.Value,LastReportedAt:item.LastSeen})
    }
    for _,item:=range positives {
        result=append(result,DeviceOrigin{DeviceID:item.DeviceID,Source:"ARP",LastReportedAt:item.LastSeen})
    }
    sort.Slice(result,func(i,j int)bool{
        if result[i].DeviceID!=result[j].DeviceID {return result[i].DeviceID<result[j].DeviceID}
        if result[i].Source!=result[j].Source {return result[i].Source<result[j].Source}
        return result[i].Reference<result[j].Reference
    })
    return result
}

// The diagnostic bundle reads all related tables in a single SQLite
// read transaction. It does not modify the database or persist a new file.
func (db *DB) snapshot() (DatabaseSnapshot,error) {
    db.mu.Lock()
    defer db.mu.Unlock()
    result:=DatabaseSnapshot{
        Devices:make([]Device,0),
        Sources:make([]SourceInfo,0),
        Events:make([]Event,0),
        DeviceSources:make([]DeviceOrigin,0),
        IdentityHistory:make([]IdentityHistory,0),
        LANLastPositive:make([]LANObservation,0),
        IPv4Evidence:make([]IPv4Evidence,0),
        MDNSHosts:make([]MDNSRecord,0),
        MDNSServices:make([]MDNSServiceRecord,0),
        MDNSUnmatched:make([]MDNSUnmatched,0),
        SSDPServices:make([]SSDPServiceRecord,0),
        SSDPUnmatched:make([]SSDPUnmatched,0),
    }
    if err:=db.exec("BEGIN");err!=nil{return result,err}
    committed:=false
    defer func(){if !committed {_=db.exec("ROLLBACK")}}()

    _,err:=db.prepared("SELECT id,display_name,hostname,mac,ipv4,ipv6,presence,first_seen,last_seen,note FROM devices ORDER BY display_name,id",nil,
        func(stmt *C.sqlite3_stmt){
            result.Devices=append(result.Devices,Device{
                ID:field(stmt,0),DisplayName:field(stmt,1),Hostname:field(stmt,2),
                MAC:field(stmt,3),IPv4:field(stmt,4),IPv6:field(stmt,5),
                Presence:field(stmt,6),FirstSeen:field(stmt,7),LastSeen:field(stmt,8),Note:field(stmt,9),
            })
        })
    if err!=nil{return result,fmt.Errorf("diagnostics devices: %w",err)}

    _,err=db.prepared("SELECT id,kind,status,COALESCE(last_success,''),details_json FROM sources ORDER BY id",nil,
        func(stmt *C.sqlite3_stmt){
            result.Sources=append(result.Sources,SourceInfo{
                Name:field(stmt,0),Kind:field(stmt,1),Status:field(stmt,2),
                LastSuccess:field(stmt,3),DetailsJSON:field(stmt,4),
            })
        })
    if err!=nil{return result,fmt.Errorf("diagnostics sources: %w",err)}

    _,err=db.prepared("SELECT id,event_type,device_id,occurred_at,data_json FROM events ORDER BY id DESC LIMIT 200",nil,
        func(stmt *C.sqlite3_stmt){
            result.Events=append(result.Events,Event{
                ID:int64(C.sqlite3_column_int64(stmt,0)),EventType:field(stmt,1),
                DeviceID:field(stmt,2),OccurredAt:field(stmt,3),DataJSON:field(stmt,4),
            })
        })
    if err!=nil{return result,fmt.Errorf("diagnostics events: %w",err)}

    _,err=db.prepared("SELECT device_id,kind,value,first_seen,last_seen FROM identities ORDER BY device_id,kind,value",nil,
        func(stmt *C.sqlite3_stmt){
            result.IdentityHistory=append(result.IdentityHistory,IdentityHistory{
                DeviceID:field(stmt,0),Kind:field(stmt,1),Value:field(stmt,2),
                FirstSeen:field(stmt,3),LastSeen:field(stmt,4),
            })
        })
    if err!=nil{return result,fmt.Errorf("diagnostics identities: %w",err)}

    _,err=db.prepared("SELECT device_id,last_seen FROM lan_positive ORDER BY device_id",nil,
        func(stmt *C.sqlite3_stmt){
            result.LANLastPositive=append(result.LANLastPositive,LANObservation{
                DeviceID:field(stmt,0),LastSeen:field(stmt,1),
            })
        })
    if err!=nil{return result,fmt.Errorf("diagnostics LAN evidence: %w",err)}
    result.IPv4Evidence,err=db.ipv4EvidenceLocked()
    if err!=nil{return result,fmt.Errorf("diagnostics IPv4 evidence: %w",err)}
    result.MDNSHosts,result.MDNSServices,result.MDNSUnmatched,err=db.mdnsSourceRecordsLocked()
    if err!=nil{return result,fmt.Errorf("diagnostics mDNS: %w",err)}
    result.SSDPServices,result.SSDPUnmatched,err=db.ssdpSourceRecordsLocked()
    if err!=nil{return result,fmt.Errorf("diagnostics SSDP: %w",err)}
    if err:=db.exec("COMMIT");err!=nil{return result,err}
    committed=true
    result.DeviceSources=deriveDeviceSources(result.IdentityHistory,result.LANLastPositive)
    for _,item:=range result.MDNSHosts {
        result.DeviceSources=append(result.DeviceSources,DeviceOrigin{
            DeviceID:item.DeviceID,Source:"mDNS",Reference:item.Hostname,LastReportedAt:item.LastSeen,
        })
    }
    lastSSDP:=map[string]string{}
    for _,item:=range result.SSDPServices {
        if lastSSDP[item.DeviceID]<item.LastSeen {lastSSDP[item.DeviceID]=item.LastSeen}
    }
    for id,seen:=range lastSSDP {
        result.DeviceSources=append(result.DeviceSources,DeviceOrigin{
            DeviceID:id,Source:"SSDP",LastReportedAt:seen,
        })
    }
    sort.Slice(result.DeviceSources,func(i,j int)bool{
        a,b:=result.DeviceSources[i],result.DeviceSources[j]
        if a.DeviceID!=b.DeviceID{return a.DeviceID<b.DeviceID}
        if a.Source!=b.Source{return a.Source<b.Source}
        return a.Reference<b.Reference
    })
    result.Sources=fillSourcePlaceholders(result.Sources)
    return result,nil
}

func (s *Service) diagnosticReport() (map[string]any,error) {
    snapshot,err:=s.db.snapshot()
    if err!=nil{return nil,err}
    online:=0
    notObserved:=0
    unknown:=0
    for _,device:=range snapshot.Devices {
        switch device.Presence {
        case "online":online++
        case "not_observed":notObserved++
        default:unknown++
        }
    }
    diagnostics:=make([]map[string]any,0,len(snapshot.Sources))
    for _,src:=range snapshot.Sources {
        diagnostics=append(diagnostics,map[string]any{
            "source":src.Name,"kind":src.Kind,"status":src.Status,
            "last_success":src.LastSuccess,"details":normalizedSourceDetails(src),
        })
    }
    arpTTL,haTTL:=s.db.evidenceWindows()
    resolved:=resolveIPv4Evidence(snapshot.IPv4Evidence,time.Now().UTC().Format(time.RFC3339),arpTTL,haTTL)
    lastScan:=0
    for _,source:=range snapshot.Sources {
        if source.Kind!="lan_arp" {continue}
        if n,ok:=normalizedSourceDetails(source)["last_scan_hosts"].(float64);ok {lastScan=int(n)}
    }
    return map[string]any{
        "format":diagnosticFormat,
        "generated_at":time.Now().UTC().Format(time.RFC3339Nano),
        "application":map[string]any{
            "id":"digitalhouses_network_app",
            "version":s.version,
            "started_at":s.started.UTC().Format(time.RFC3339),
            "ha_poll_interval_seconds":s.intervalSeconds,
            "arp_scan_interval_seconds":s.scanIntervalSeconds,
            "mdns_scan_interval_seconds":s.mdnsIntervalSeconds,
            "ssdp_scan_interval_seconds":s.ssdpIntervalSeconds,
        },
        "counts":map[string]int{
            "devices":len(snapshot.Devices),"online":online,"not_observed":notObserved,
            "unknown":unknown,"ha_router_entities":countSources(snapshot.DeviceSources,"HA Router"),
            "arp_hosts":countSources(snapshot.DeviceSources,"ARP"),
            "arp_last_scan_hosts":lastScan,
            "ipv4_conflicts":len(resolved.Conflicts),
            "mdns_matched_devices":countSources(snapshot.DeviceSources,"mDNS"),
            "mdns_service_records":len(snapshot.MDNSServices),
            "mdns_unmatched_hosts":len(snapshot.MDNSUnmatched),
            "ssdp_matched_devices":countSources(snapshot.DeviceSources,"SSDP"),
            "ssdp_service_records":len(snapshot.SSDPServices),
            "ssdp_unmatched_records":len(snapshot.SSDPUnmatched),
        },
        "inventory":snapshot,
        "ipv4_conflicts":resolved.Conflicts,
        "resolved_ipv4":resolved.Addresses,
        "source_diagnostics":diagnostics,
        "interpretation":map[string]string{
            "source_membership":"Historical association, not proof of current network presence.",
            "mdns":"Hostnames and service records complement ONLY uniquely ARP-confirmed hosts. A service is not an extra device; mDNS never changes Presence.",
            "ssdp":"Metadata-only M-SEARCH on the local LAN; USN, ST, SERVER and sanitized LOCATION origin are retained only when fresh unique ARP confirms the address. No XML fetched, no device creation or Presence changes.",
            "ipv4_disagreement":"A router versus ARP IP claim is recorded as a source disagreement in local Events; NOT proof of two hosts simultaneously owning an IP.",
            "online":"Last aggregated device presence from Home Assistant router or positive ARP evidence.",
            "not_observed":"No current positive evidence; NOT a confirmed disconnection.",
            "generated_at":"UTC server clock; the browser adds active view/filter metadata.",
        },
        "sensitive_fields":"This local export contains IP/MAC addresses, hostnames and verbatim user notes. Supervisor credentials are never read for export; do not share if notes contain secrets.",
    },nil
}

func countSources(sources []DeviceOrigin, name string) int {
    seen:=map[string]bool{}
    for _,source:=range sources {
        if source.Source==name {seen[source.DeviceID]=true}
    }
    return len(seen)
}

// Remove double-encoding from source diagnostics for human and machine readers.
func normalizedSourceDetails(src SourceInfo) map[string]any {
    var detail map[string]any
    if json.Unmarshal([]byte(src.DetailsJSON),&detail)!=nil || detail==nil {
        return map[string]any{}
    }
    return detail
}
