package main

import (
 "net/netip"
 "path/filepath"
 "strings"
 "testing"
 "time"
)

func TestSSDPSafeResponseParsing(t *testing.T) {
 source:=netip.MustParseAddr("192.168.11.40")
 packet:=[]byte("HTTP/1.1 200 OK\r\nST: upnp:rootdevice\r\nUSN: uuid:abcd::upnp:rootdevice\r\nSERVER: Device/1.0 UPnP/1.1\r\nLOCATION: http://192.168.11.40:8080/description.xml?token=secret\r\nCACHE-CONTROL: max-age=1800\r\n\r\n")
 got,ok:=parseSSDPResponse(packet,source)
 if !ok || got.IPv4!="192.168.11.40" ||got.ST!="upnp:rootdevice" ||got.Server!="Device/1.0 UPnP/1.1" {
  t.Fatalf("legitimate response rejected: %+v %v",got,ok)
 }
 if got.Location!="http://192.168.11.40:8080" ||strings.Contains(got.Location,"secret") {t.Fatalf("secret-bearing URL persisted: %+v",got)}
 for _,bad:=range [][]byte{
  []byte(strings.Replace(string(packet),"192.168.11.40:8080","192.168.11.1:8080",1)),
  []byte(strings.Replace(string(packet),"http://192.168.11.40","http://admin:pw@192.168.11.40",1)),
  []byte(strings.Replace(string(packet),"HTTP/1.1 200 OK","NOTIFY * HTTP/1.1",1)),
  []byte(strings.Replace(string(packet),"ST: upnp:rootdevice\r\n","",1)),
  append([]byte{},[]byte(strings.Repeat("A",9000))...),
 }{
  if _,ok:=parseSSDPResponse(bad,source);ok {t.Fatalf("unsafe response accepted %q",string(bad)[:min(len(bad),80)])}
 }
}
func TestSSDPMatchedOnlyViaFreshARPAndPreservesIdentity(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"net.sqlite3"))
 if err!=nil {t.Fatal(err)}
 defer db.Close()
 db.lanFreshness=420*time.Second
 now:=time.Now().UTC().Truncate(time.Second)
 at:=now.Format(time.RFC3339)
 router:=RouterTracker{EntityID:"device_tracker.sample",MAC:"02:20:30:40:50:60",State:"home",IPv4:"192.168.11.40",Name:"Verified user label"}
 if err=db.importRouterTrackers([]RouterTracker{router},at);err!=nil {t.Fatal(err)}
 devices,_:=db.devices()
 original:=devices[0].ID
 if _,err=db.setNote(original,"persistent note");err!=nil{t.Fatal(err)}
 observations:=[]SSDPRecord{
  {IPv4:"192.168.11.40",ST:"upnp:rootdevice",USN:"uuid:1",Server:"Device",Location:"http://192.168.11.40:80"},
  {IPv4:"192.168.11.91",ST:"upnp:rootdevice",USN:"uuid:other",Server:"Other",Location:"http://192.168.11.91:80"},
 }
 m,u,s,err:=db.importSSDPRecords(observations,at,2,"enp6s18")
 if err!=nil || m!=0 ||u!=2 ||s!=0 {t.Fatalf("matched router-only record: %d %d %d %v",m,u,s,err)}
 if err=db.importARPHosts([]LANHost{{MAC:router.MAC,IPv4:router.IPv4}},at,"enp6s18","192.168.11.0/24");err!=nil{t.Fatal(err)}
 m,u,s,err=db.importSSDPRecords(observations,at,4,"enp6s18")
 if err!=nil ||m!=1 ||u!=1 ||s!=1 {t.Fatalf("SSDP binding not conservative: %d %d %d %v",m,u,s,err)}
 snapshot,err:=db.snapshot()
 if err!=nil {t.Fatal(err)}
 if len(snapshot.SSDPServices)!=1 ||snapshot.SSDPServices[0].DeviceID!=original||
 len(snapshot.SSDPUnmatched)!=2 {t.Fatalf("SSDP diagnostics wrong: %+v %+v",snapshot.SSDPServices,snapshot.SSDPUnmatched)}
 devices,_=db.devices()
 if len(devices)!=1||devices[0].ID!=original||devices[0].DisplayName!="Verified user label"||devices[0].Note!="persistent note"||devices[0].Presence!="online"{
  t.Fatalf("SSDP must not mutate devices: %+v",devices)
 }
 report,err:=(&Service{db:db,version:"0.1.7",started:now,intervalSeconds:60,scanIntervalSeconds:180,mdnsIntervalSeconds:300,ssdpIntervalSeconds:300}).diagnosticReport()
 if err!=nil{t.Fatal(err)}
 counts:=report["counts"].(map[string]int)
 if counts["ssdp_matched_devices"]!=1 ||counts["ssdp_service_records"]!=1 {t.Fatalf("missing SSDP metrics %+v",counts)}
}
func TestIPv4DisagreementJournalOneTransitionPerChange(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"events.sqlite3"))
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 db.lanFreshness=420*time.Second
 db.haFreshness=180*time.Second
 now:=time.Now().UTC().Truncate(time.Second)
 tracker:=RouterTracker{EntityID:"device_tracker.asus_bridge",MAC:"04:92:26:53:9C:B4",IPv4:"192.168.11.30",State:"home",Name:"ASUS wifi"}
 if err=db.importRouterTrackers([]RouterTracker{tracker},now.Add(-90*time.Second).Format(time.RFC3339));err!=nil{t.Fatal(err)}
 if err=db.importARPHosts([]LANHost{{MAC:"E8:FF:1E:D7:38:17",IPv4:"192.168.11.30"}},now.Add(-60*time.Second).Format(time.RFC3339),"enp6s18","192.168.11.0/24");err!=nil{t.Fatal(err)}
 events,err:=db.events()
 if err!=nil ||len(events)!=1 ||events[0].EventType!="ipv4_disagreement_started"||!strings.Contains(events[0].DataJSON,"source_disagreement"){
  t.Fatalf("missing informative disagreement start: %+v %v",events,err)
 }
 if err=db.importRouterTrackers([]RouterTracker{tracker},now.Add(-30*time.Second).Format(time.RFC3339));err!=nil{t.Fatal(err)}
 events,_=db.events()
 if len(events)!=1 {t.Fatalf("repeated polls spammed journal: %+v",events)}
 tracker.IPv4="192.168.11.33"
 if err=db.importRouterTrackers([]RouterTracker{tracker},now.Format(time.RFC3339));err!=nil{t.Fatal(err)}
 events,_=db.events()
 if len(events)!=2 ||events[0].EventType!="ipv4_disagreement_resolved" {
  t.Fatalf("missing resolution: %+v",events)
 }
 devices,_:=db.devices()
 for _,dev:=range devices {
  if dev.MAC=="E8:FF:1E:D7:38:17"&&dev.IPv4!="192.168.11.30" {t.Fatalf("ARP winner lost: %+v",dev)}
 }
}
