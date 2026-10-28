package main

import (
 "net/netip"
 "path/filepath"
 "strings"
 "testing"
 "time"
)

func TestLocalInterfaceWinsRouterAndKeepsNote(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"local-interface.sqlite3"))
 if err!=nil {t.Fatal(err)}
 defer db.Close()
 db.lanFreshness=420*time.Second
 db.haFreshness=180*time.Second
 now:=time.Now().UTC().Truncate(time.Second)
 at:=now.Format(time.RFC3339)
 rogue:=RouterTracker{EntityID:"device_tracker.asus_bridge",MAC:"04:92:26:53:9C:B4",IPv4:"192.168.11.33",State:"home",Name:"04:92:26:53:9C:B4"}
 if err=db.importRouterTrackers([]RouterTracker{rogue},now.Add(-20*time.Second).Format(time.RFC3339));err!=nil {t.Fatal(err)}
 initial,_:=db.devices()
 if len(initial)!=1{t.Fatalf("test fixture wrong: %+v",initial)}
 bridgeID:=initial[0].ID
 if _,err=db.setNote(bridgeID,"test - HA");err!=nil{t.Fatal(err)}
 local:=LocalInterfaceObservation{MAC:"02:7F:2F:27:4E:92",IPv4:"192.168.11.33",Interface:"enp6s18",Prefix:"192.168.11.0/24"}
 if err=db.importLocalInterface(local,at);err!=nil{t.Fatal(err)}
 devices,_:=db.devices()
 if len(devices)!=2 {t.Fatalf("local source did not create genuine host: %+v",devices)}
 var bridge,own Device
 for _,v:=range devices {
  if v.MAC=="04:92:26:53:9C:B4"{bridge=v}
  if v.MAC=="02:7F:2F:27:4E:92"{own=v}
 }
 if bridge.ID!=bridgeID||bridge.Note!="test - HA"||bridge.IPv4!="" {t.Fatalf("bridge state corrupted: %+v",bridge)}
 if own.ID==""||own.IPv4!="192.168.11.33"||own.DisplayName!=""||own.Note!=""||own.Presence!="online"{
  t.Fatalf("local source should have no invented name: %+v",own)
 }
 snapshot,err:=db.snapshot()
 if err!=nil {t.Fatal(err)}
 if countSources(snapshot.DeviceSources,"Local Interface")!=1 {t.Fatalf("local provenance missing: %+v",snapshot.DeviceSources)}
 if len(snapshot.Events)!=1||snapshot.Events[0].EventType!="ipv4_disagreement_started"||
  !strings.Contains(snapshot.Events[0].DataJSON,"source_disagreement"){t.Fatalf("wrong local disagreement: %+v",snapshot.Events)}
 id,err:=db.mdnsARPDevice(local.IPv4,at)
 if err!=nil||id!=own.ID {t.Fatalf("mDNS/WSD cannot map direct local IP: %s %v",id,err)}
 if err=db.importRouterTrackers([]RouterTracker{rogue},now.Add(2*time.Second).Format(time.RFC3339));err!=nil{t.Fatal(err)}
 devices,_=db.devices()
 for _,v:=range devices {
  if v.ID==own.ID&&(v.IPv4!=local.IPv4||v.Presence!="online"){t.Fatalf("router displaced direct local device: %+v",v)}
  if v.ID==bridgeID&&(v.IPv4!=""||v.Note!="test - HA"){t.Fatalf("router incorrectly gained IP: %+v",v)}
 }
 if err=db.importLocalInterface(local,now.Add(3*time.Second).Format(time.RFC3339));err!=nil{t.Fatal(err)}
 devices,_=db.devices()
 if len(devices)!=2 {t.Fatalf("repeated local poll duplicated registry: %+v",devices)}
}
func TestLocalInterfaceInvalidObservationsRefused(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"invalid.sqlite3"))
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 for _,v:=range []LocalInterfaceObservation{
  {MAC:"",IPv4:"192.168.11.33",Interface:"enp6s18",Prefix:"192.168.11.0/24"},
  {MAC:"02:7F:2F:27:4E:92",IPv4:"192.168.12.33",Interface:"enp6s18",Prefix:"192.168.11.0/24"},
  {MAC:"02:7F:2F:27:4E:92",IPv4:"10.0.0.5",Interface:"",Prefix:"10.0.0.0/24"},
 } {
  if err:=db.importLocalInterface(v,time.Now().UTC().Format(time.RFC3339));err==nil{t.Fatalf("invalid local observation accepted %+v",v)}
 }
 devices,_:=db.devices()
 if len(devices)!=0{t.Fatalf("failed validation wrote rows %+v",devices)}
}
func wsdExample(relatesTo,xaddr string) []byte {
 return []byte(`<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery">
 <s:Header><a:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/ProbeMatches</a:Action>
 <a:RelatesTo>`+relatesTo+`</a:RelatesTo></s:Header>
 <s:Body><d:ProbeMatches><d:ProbeMatch>
 <a:EndpointReference><a:Address>urn:uuid:12345678-1234-1234-1234-123456789abc</a:Address></a:EndpointReference>
 <d:Types>wsdp:Device</d:Types>
 <d:Scopes>urn:some:vendor:discovery</d:Scopes>
 <d:XAddrs>`+xaddr+`</d:XAddrs>
 </d:ProbeMatch></d:ProbeMatches></s:Body>
 </s:Envelope>`)
}
func TestWSDProbeMatchesValidationAndNoInventedName(t *testing.T) {
 ip:=netip.MustParseAddr("192.168.11.238")
 msg:="urn:uuid:aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
 if got:=string(wsdProbe(msg));!strings.Contains(got,"<wsa:Action>")||!strings.Contains(got,"<wsa:MessageID>"+msg+"</wsa:MessageID>")||!strings.Contains(got,"<wsd:Types>wsdp:Device</wsd:Types>"){t.Fatalf("Probe must use wsdd2-compatible WSA prefixes and type: %s",got)}
 matched:=parseWSDProbeMatches(wsdExample(msg,"http://192.168.11.238:5357/uuid?token=do-not-store"),ip,msg)
 if len(matched)!=1{t.Fatalf("legitimate ProbeMatch rejected: %+v",matched)}
 if matched[0].Origin!="http://192.168.11.238:5357"||matched[0].Endpoint!="urn:uuid:12345678-1234-1234-1234-123456789abc"||
  strings.Contains(matched[0].Origin,"token") {t.Fatalf("WSD retained raw URL or lost endpoint: %+v",matched)}
 if got:=parseWSDProbeMatches(wsdExample("urn:uuid:wrong","http://192.168.11.238:5357"),ip,msg);len(got)!=0 {t.Fatal("uncorrelated response accepted")}
 if got:=parseWSDProbeMatches(wsdExample(msg,"http://192.168.11.1:5357"),ip,msg);len(got)!=1||got[0].Origin!="" {t.Fatalf("foreign XAddr trusted: %+v",got)}
 if got:=parseWSDProbeMatches(append(wsdExample(msg,"http://192.168.11.238:5357"),[]byte(strings.Repeat("x",18000))...),ip,msg);len(got)!=0 {t.Fatal("oversized SOAP accepted")}
 if got:=parseWSDProbeMatches([]byte("garbage"),ip,msg);len(got)!=0{t.Fatal("non-XML accepted")}
}
func TestWSDRequiresDirectEvidenceAndNeverRenames(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"wsd.sqlite3"))
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 db.lanFreshness=420*time.Second
 now:=time.Now().UTC().Truncate(time.Second).Format(time.RFC3339)
 target:=WSDAnnouncement{IPv4:"192.168.11.238",Endpoint:"urn:uuid:12345678-1234-1234-1234-123456789abc",Types:"wsdp:Device",Scopes:"urn:some:vendor:discovery",Origin:"http://192.168.11.238:5357"}
 if m,u,err:=db.importWSD([]WSDAnnouncement{target},now,1,"enp6s18");err!=nil||m!=0||u!=1 {t.Fatalf("WSD created unauthorised identity: %d %d %v",m,u,err)}
 devices,_:=db.devices()
 if len(devices)!=0{t.Fatalf("WSD created device: %+v",devices)}
 if err=db.importARPHosts([]LANHost{{MAC:"BC:24:11:B7:6E:CF",IPv4:target.IPv4}},now,"enp6s18","192.168.11.0/24");err!=nil {t.Fatal(err)}
 devices,_=db.devices()
 deviceID:=devices[0].ID
 if _,err=db.setNote(deviceID,"user note");err!=nil{t.Fatal(err)}
 if m,u,err:=db.importWSD([]WSDAnnouncement{target},now,2,"enp6s18");err!=nil||m!=1||u!=0 {t.Fatalf("verified ARP match failed: %d %d %v",m,u,err)}
 snapshot,err:=db.snapshot()
 if err!=nil{t.Fatal(err)}
 if len(snapshot.WSDEndpoints)!=1||snapshot.WSDEndpoints[0].DeviceID!=deviceID||countSources(snapshot.DeviceSources,"WSD")!=1{
  t.Fatalf("WSD metadata not attached: %+v",snapshot.WSDEndpoints)
 }
 devices,_=db.devices()
 if len(devices)!=1||devices[0].ID!=deviceID||devices[0].DisplayName!="BC:24:11:B7:6E:CF"||devices[0].Note!="user note" {t.Fatalf("WSD renamed or changed identity: %+v",devices)}
}
