package main

import (
 "encoding/binary"
 "net/netip"
 "path/filepath"
 "testing"
 "time"
)

func TestDNSNameCompressionAndMalformedPackets(t *testing.T) {
 name,err:=dnsEncodeName("_http._tcp.local.")
 if err!=nil {t.Fatal(err)}
 packet:=make([]byte,12)
 packet[2]=0x80 // DNS response
 binary.BigEndian.PutUint16(packet[6:8],1)
 packet=append(packet,name...)
 packet=append(packet,0,12,0,1,0,0,0,120,0,2,0xC0,0x0C)
 records,err:=decodeDNSRecords(packet)
 if err!=nil||len(records)!=1||records[0].Name!="_http._tcp.local."||
   records[0].Target!="_http._tcp.local." {t.Fatalf("PTR compression failed: %+v %v",records,err)}
 _,_,err=readDNSName([]byte{0xC0,0},0)
 if err==nil {t.Fatal("DNS pointer loop accepted")}
 _,err=decodeDNSRecords([]byte{1,2,3})
 if err==nil {t.Fatal("truncated DNS packet accepted")}
 q,err:=mdnsQuestion("_digitalhouses._tcp.local.",dnsTypePTR)
 if err!=nil || len(q)<20 {t.Fatalf("mDNS query failed: %v",err)}
 if binary.BigEndian.Uint16(q[4:6])!=1 {t.Fatal("DNS question count missing")}
}

func TestMDNSServiceRecordsResolveToOneHost(t *testing.T) {
 records:=[]dnsRecord{
  {Name:"_http._tcp.local.",Type:dnsTypePTR,Target:"My Site._http._tcp.local.",TTL:120},
  {Name:"My Site._http._tcp.local.",Type:dnsTypeSRV,Target:"haos.local.",Port:8099,TTL:120},
  {Name:"Other Service._ssh._tcp.local.",Type:dnsTypeSRV,Target:"haos.local.",Port:22,TTL:120},
  {Name:"haos.local.",Type:dnsTypeA,IP:"192.168.11.33",TTL:120},
  {Name:"haos.local.",Type:dnsTypeA,IP:"192.168.11.33",TTL:120},
  {Name:"haos.local.",Type:dnsTypeAAAA,IP:"fe80::1",TTL:120},
 }
 hosts:=mdnsHostsFromRecords(records)
 if len(hosts)!=1 || hosts[0].IPv4!="192.168.11.33" ||
   len(hosts[0].Services)!=2 || len(hosts[0].IPv6)!=1 {
  t.Fatalf("service improperly created duplicate host: %+v",hosts)
 }
 types:=limitMDNSTypes([]dnsRecord{{Name:"_services._dns-sd._udp.local.",Type:dnsTypePTR,Target:"_digitalhouses._tcp.local."}})
 found:=false
 for _,v:=range types {if canonicalDNS(v)=="_digitalhouses._tcp.local"{found=true}}
 if !found {t.Fatal("DigitalHouses service type not browsed")}
}

func TestMDNSAugmentsFreshARPWithoutMergingHostsOrChangingNote(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
 if err!=nil {t.Fatal(err)}
 defer db.Close()
 db.lanFreshness=420*time.Second
 now:=time.Now().UTC().Truncate(time.Second)
 start:=now.Add(-35*time.Second).Format(time.RFC3339)
 mac:="02:11:22:33:44:55"
 router:=RouterTracker{EntityID:"device_tracker.demo",State:"home",Name:mac,Hostname:mac,MAC:mac,IPv4:"192.168.11.33"}
 if err:=db.importRouterTrackers([]RouterTracker{router},start);err!=nil {t.Fatal(err)}
 if err:=db.importARPHosts([]LANHost{{MAC:mac,IPv4:"192.168.11.33"}},
     now.Add(-25*time.Second).Format(time.RFC3339),"enp6s18","192.168.11.0/24");err!=nil {t.Fatal(err)}
 initial,_:=db.devices()
 if len(initial)!=1 {t.Fatal("missing original device")}
 id:=initial[0].ID
 if ok,err:=db.setNote(id,"test - HA");err!=nil || !ok {t.Fatal(err)}
 hosts:=[]MDNSHost{{
  IPv4:"192.168.11.33",Hostname:"haos.local.",IPv6:[]string{"fe80::1"},
  Services:[]MDNSService{
   {Instance:"Home Assistant",Type:"_home-assistant._tcp.local.",Port:8123,Target:"haos.local."},
   {Instance:"SSH",Type:"_ssh._tcp.local.",Port:22,Target:"haos.local."},
  },
 },{
  IPv4:"192.168.11.92",Hostname:"unlinked.local.",
  Services:[]MDNSService{{Instance:"not-matched",Type:"_http._tcp.local.",Port:80,Target:"unlinked.local."}},
 }}
 matched,unmatched,services,err:=db.importMDNSHosts(hosts,now.Format(time.RFC3339),7,"enp6s18")
 if err!=nil || matched!=1 || unmatched!=1 || services!=2 {
  t.Fatalf("mDNS source results %d %d %d %v",matched,unmatched,services,err)
 }
 devices,_:=db.devices()
 if len(devices)!=1 || devices[0].ID!=id || devices[0].MAC!=mac || devices[0].Note!="test - HA" ||
  devices[0].Presence!="online" || devices[0].DisplayName!="haos" || devices[0].Hostname!="haos.local" {
  t.Fatalf("mDNS changed host identity/presence or Note %+v",devices)
 }
 snapshot,err:=db.snapshot()
 if err!=nil{t.Fatal(err)}
 if len(snapshot.MDNSHosts)!=1||len(snapshot.MDNSServices)!=2 ||len(snapshot.MDNSUnmatched)!=1 {t.Fatalf("missing mDNS diagnostics: %+v",snapshot)}
 if len(snapshot.DeviceSources)!=3 {t.Fatalf("missing mDNS source badge: %+v",snapshot.DeviceSources)}
 for _,service:=range snapshot.MDNSServices {
  if service.DeviceID!=id {t.Fatalf("service created fake device: %+v",service)}
 }
 if !containsSource(snapshot.Sources,"mDNS / Bonjour") {t.Fatalf("missing new source: %+v",snapshot.Sources)}
 report,err:=(&Service{db:db,version:"0.1.5",started:now,intervalSeconds:60,scanIntervalSeconds:180,mdnsIntervalSeconds:300}).diagnosticReport()
 if err!=nil {t.Fatal(err)}
 if report["counts"].(map[string]int)["mdns_service_records"]!=2 {t.Fatal("mDNS not counted")}
}

func TestMDNSNeverMatchesRouterOnlyOrStaleARPIP(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
 if err!=nil {t.Fatal(err)}
 defer db.Close()
 db.lanFreshness=420*time.Second
 now:=time.Now().UTC().Truncate(time.Second)
 router:=RouterTracker{EntityID:"device_tracker.router",MAC:"02:22:33:44:55:66",Name:"Router Known",IPv4:"192.168.11.77",State:"home"}
 if err:=db.importRouterTrackers([]RouterTracker{router},now.Format(time.RFC3339));err!=nil {t.Fatal(err)}
 hosts:=[]MDNSHost{{IPv4:"192.168.11.77",Hostname:"different.local."}}
 m,u,_,err:=db.importMDNSHosts(hosts,now.Format(time.RFC3339),1,"enp6s18")
 if err!=nil||m!=0||u!=1 {t.Fatalf("mDNS trusted unverified IP: %d %d %v",m,u,err)}
 devices,_:=db.devices()
 if len(devices)!=1||devices[0].DisplayName!="Router Known" {t.Fatalf("mDNS overwrote router: %+v",devices)}
 if err:=db.importARPHosts([]LANHost{{MAC:router.MAC,IPv4:router.IPv4}},
  now.Add(-20*time.Minute).Format(time.RFC3339),"enp6s18","192.168.11.0/24");err!=nil {t.Fatal(err)}
 m,u,_,err=db.importMDNSHosts(hosts,now.Format(time.RFC3339),1,"enp6s18")
 if err!=nil||m!=0||u!=1 {t.Fatalf("stale ARP must not match: %d %d %v",m,u,err)}
}

func TestDNSNameAndIPParsingWithinLimits(t *testing.T) {
 if _,err:=netip.ParseAddr("192.168.11.33");err!=nil {t.Fatal(err)}
 if friendlyMDNSHost("host.local.")!="host" {t.Fatal("hostname suffix not stripped")}
 for _,s:=range []string{"","..local.","_bad..local"} {
  if _,err:=dnsEncodeName(s);err==nil {t.Fatalf("bad query accepted: %s",s)}
 }
}
