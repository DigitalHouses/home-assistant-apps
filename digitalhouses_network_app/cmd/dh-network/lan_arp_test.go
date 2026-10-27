//go:build linux

package main

import (
    "encoding/binary"
    "net"
    "net/netip"
    "path/filepath"
    "testing"
)

func TestARPRequestAndReplyValidation(t *testing.T) {
    mac,_:=net.ParseMAC("02:11:22:33:44:55")
    own:=netip.MustParseAddr("192.168.11.33")
    remote:=netip.MustParseAddr("192.168.11.42")
    packet,err:=buildARPRequest(mac,own,remote)
    if err!=nil || len(packet)!=42 {t.Fatalf("build failed: %v",err)}
    if binary.BigEndian.Uint16(packet[20:22])!=1 {t.Fatal("not ARP request")}
    // Construct a reply with matching Ethernet and advertised sender.
    copy(packet[6:12],mac)
    copy(packet[22:28],mac)
    binary.BigEndian.PutUint16(packet[20:22],2)
    ip:=remote.As4()
    copy(packet[28:32],ip[:])
    network:=netip.MustParsePrefix("192.168.11.0/24")
    host,ok:=parseARPReply(packet,network)
    if !ok || host.MAC!="02:11:22:33:44:55" || host.IPv4!="192.168.11.42" {t.Fatalf("wrong ARP host %+v %v",host,ok)}
    packet[6]=3 // mismatch in Ethernet source, should be rejected
    if _,ok:=parseARPReply(packet,network);ok {t.Fatal("mismatched Ethernet and ARP MAC accepted")}
    packet[6]=2
    if _,ok:=parseARPReply(packet,netip.MustParsePrefix("10.0.0.0/24"));ok {t.Fatal("out of subnet ARP accepted")}
}

func TestRouteSafety(t *testing.T) {
    table:="Iface Destination Gateway Flags RefCnt Use Metric Mask MTU Window IRTT\n"+
      "eth0 00000000 010BA8C0 0003 0 0 100 00000000 0 0 0\n"+
      "hassio 0000000A 00000000 0001 0 0 0 00FFFFFF 0 0 0\n"
    iface,err:=defaultRouteInterface(table)
    if err!=nil || iface!="eth0" {t.Fatalf("unexpected route %s %v",iface,err)}
    if _,err:=defaultRouteInterface("Iface Destination Gateway\n");err==nil {t.Fatal("no default route accepted")}
    _,err=chooseLAN(nil,"missing",256)
    if err==nil {t.Fatal("missing interface silently accepted")}
    _,err=chooseLAN(nil,"eth0",1000)
    if err==nil {t.Fatal("oversized limit accepted")}
}

func TestLANMergesWithRouterNoteAndIPHistory(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"network.sqlite3"))
    if err!=nil {t.Fatal(err)}
    defer db.Close()
    start:="2026-10-27T15:30:00Z"
    address:="02:AA:BB:CC:DD:11"
    router:=RouterTracker{EntityID:"device_tracker.test_router",MAC:address,State:"not_home",Name:"Router-provided name",IPv4:"192.168.11.70"}
    if err:=db.importRouterTrackers([]RouterTracker{router},start);err!=nil {t.Fatal(err)}
    devices,_:=db.devices()
    id:=devices[0].ID
    if _,err:=db.setNote(id,"test - HA");err!=nil {t.Fatal(err)}
    at:="2026-10-27T15:31:00Z"
    if err:=db.importARPHosts([]LANHost{{MAC:address,IPv4:"192.168.11.71"}},at,"eth0","192.168.11.0/24");err!=nil {t.Fatal(err)}
    devices,_=db.devices()
    if len(devices)!=1 || devices[0].ID!=id || devices[0].Note!="test - HA" ||
       devices[0].DisplayName!="Router-provided name" || devices[0].IPv4!="192.168.11.71" ||
       devices[0].Presence!="online" {
        t.Fatalf("reconciliation lost identity or Note: %+v",devices)
    }
    oldIP,err:=db.lookupIdentity("ipv4","192.168.11.70")
    if err!=nil || oldIP!=id {t.Fatalf("lost historical IP: %v %v",oldIP,err)}
    // A negative HA router report after the ARP observation must not erase
    // more recent positive link-layer evidence.
    if err:=db.importRouterTrackers([]RouterTracker{router},"2026-10-27T15:32:00Z");err!=nil {t.Fatal(err)}
    devices,_=db.devices()
    if devices[0].Presence!="online" {t.Fatalf("router not_home hid ARP online: %+v",devices)}
}

func TestProxyARPAmbiguousMACSkipped(t *testing.T) {
    db,err:=openDB(filepath.Join(t.TempDir(),"test.sqlite3"))
    if err!=nil {t.Fatal(err)}
    defer db.Close()
    sameMAC:="02:33:44:55:66:77"
    observations:=[]LANHost{{MAC:sameMAC,IPv4:"192.168.11.20"},{MAC:sameMAC,IPv4:"192.168.11.21"}}
    if err:=db.importARPHosts(observations,"2026-10-27T15:31:00Z","eth0","192.168.11.0/24");err!=nil {t.Fatal(err)}
    devices,_:=db.devices()
    sources,_:=db.sources()
    if len(devices)!=0 || len(sources)!=1 || sources[0].Status!="degraded" {t.Fatalf("proxy ARP not rejected %+v %+v",devices,sources)}
}

func TestIngressPeerProtected(t *testing.T) {
    for _,entry:=range []struct{source string; allowed bool}{
        {"172.30.32.2:49152",true},
        {"192.168.11.33:49152",false},
        {"127.0.0.1:49152",false},
        {"192.168.11.12:49152",false},
        {"invalid",false},
    } {
        if ingressPeerAllowed(entry.source)!=entry.allowed {t.Errorf("ingress decision for %s",entry.source)}
    }
}
