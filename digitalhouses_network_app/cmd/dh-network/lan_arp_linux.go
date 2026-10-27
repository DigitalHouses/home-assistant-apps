//go:build linux

package main

import (
    "context"
    "encoding/binary"
    "errors"
    "fmt"
    "net"
    "net/netip"
    "os"
    "strings"
    "syscall"
    "time"
)

const etherTypeARP = 0x0806

type lanTarget struct {
    iface net.Interface
    address netip.Addr
    network netip.Prefix
    targets []netip.Addr
}

type LANHost struct {
    MAC string
    IPv4 string
}

// Primary-interface selection is intentional: an App with host networking
// must never broadcast into docker/hassio bridges or VPNs by default.
func defaultRouteInterface(routeTable string) (string,error) {
    for _, line := range strings.Split(routeTable,"\n") {
        fields:=strings.Fields(line)
        if len(fields)<8 || fields[0]=="Iface" {continue}
        if fields[1]=="00000000" && fields[2]!="00000000" {
            return fields[0],nil
        }
    }
    return "",errors.New("no default IPv4 LAN route")
}

func chooseLAN(interfaces []net.Interface, defaultInterface string, maxHosts int) (lanTarget,error) {
    if maxHosts<1 || maxHosts>256 {return lanTarget{},errors.New("maxHosts outside 1..256")}
    for _,iface:=range interfaces {
        if iface.Name!=defaultInterface {continue}
        if iface.Flags&net.FlagUp==0 || iface.Flags&net.FlagLoopback!=0 || len(iface.HardwareAddr)!=6 {
            return lanTarget{},fmt.Errorf("default interface %s is not an active Ethernet interface",defaultInterface)
        }
        addresses,err:=iface.Addrs()
        if err!=nil{return lanTarget{},err}
        for _,address:=range addresses {
            ipnet,ok:=address.(*net.IPNet)
            if !ok || ipnet.IP.To4()==nil {continue}
            ip,ok:=netip.AddrFromSlice(ipnet.IP.To4())
            if !ok || !ip.IsPrivate() {continue}
            ones,bits:=ipnet.Mask.Size()
            if bits!=32 || ones<24 || ones>30 {
                return lanTarget{},fmt.Errorf("LAN prefix length /%d is outside supported /24../30; refusing incomplete scan",ones)
            }
            prefix:=netip.PrefixFrom(ip,ones).Masked()
            addressesCount:=uint64(1)<<uint(32-ones)
            if addressesCount-2>uint64(maxHosts) {
                return lanTarget{},fmt.Errorf("LAN %s has more than %d hosts; refusing incomplete scan",prefix,maxHosts)
            }
            all:=make([]netip.Addr,0,int(addressesCount)-2)
            network:=prefix.Addr()
            for n:=uint64(1);n<addressesCount-1;n++ {
                b:=network.As4()
                next:=binary.BigEndian.Uint32(b[:])+uint32(n)
                var bytes [4]byte
                binary.BigEndian.PutUint32(bytes[:],next)
                target:=netip.AddrFrom4(bytes)
                if target!=ip {all=append(all,target)}
            }
            return lanTarget{iface:iface,address:ip,network:prefix,targets:all},nil
        }
        return lanTarget{},fmt.Errorf("no private IPv4 address on %s",defaultInterface)
    }
    return lanTarget{},fmt.Errorf("default route interface %q not found",defaultInterface)
}

func buildARPRequest(mac net.HardwareAddr, sender,target netip.Addr) ([]byte,error) {
    if len(mac)!=6 || !sender.Is4() || !target.Is4() {return nil,errors.New("ARP requires 6-byte MAC and IPv4")}
    packet:=make([]byte,42)
    for i:=0;i<6;i++ {packet[i]=0xff}
    copy(packet[6:12],mac)
    binary.BigEndian.PutUint16(packet[12:14],etherTypeARP)
    binary.BigEndian.PutUint16(packet[14:16],1) // Ethernet
    binary.BigEndian.PutUint16(packet[16:18],0x0800) // IPv4
    packet[18],packet[19]=6,4
    binary.BigEndian.PutUint16(packet[20:22],1) // ARP request
    copy(packet[22:28],mac)
    a:=sender.As4()
    copy(packet[28:32],a[:])
    b:=target.As4()
    copy(packet[38:42],b[:])
    return packet,nil
}

func parseARPReply(packet []byte, network netip.Prefix) (LANHost,bool) {
    if len(packet)<42 || binary.BigEndian.Uint16(packet[12:14])!=etherTypeARP ||
        binary.BigEndian.Uint16(packet[14:16])!=1 ||
        binary.BigEndian.Uint16(packet[16:18])!=0x0800 ||
        packet[18]!=6 || packet[19]!=4 ||
        binary.BigEndian.Uint16(packet[20:22])!=2 {return LANHost{},false}
    mac:=net.HardwareAddr(packet[22:28])
    if (mac[0]&1)!=0 || normalizedMAC(mac.String())=="" {return LANHost{},false}
    // Reject inconsistent L2 source and advertised ARP sender MAC.
    for i:=0;i<6;i++ {if packet[6+i]!=packet[22+i] {return LANHost{},false}}
    var bytes [4]byte
    copy(bytes[:],packet[28:32])
    ip:=netip.AddrFrom4(bytes)
    if !ip.IsValid() || !network.Contains(ip) || ip==network.Addr() {return LANHost{},false}
    return LANHost{MAC:normalizedMAC(mac.String()),IPv4:ip.String()},true
}

func htons(value uint16) int {
    var b [2]byte
    binary.BigEndian.PutUint16(b[:],value)
    return int(binary.NativeEndian.Uint16(b[:]))
}

func scanARP(ctx context.Context, target lanTarget, rate int) ([]LANHost,error) {
    if rate<1 || rate>30 {return nil,fmt.Errorf("ARP probe rate %d invalid",rate)}
    proto:=htons(etherTypeARP)
    fd,err:=syscall.Socket(syscall.AF_PACKET,syscall.SOCK_RAW|syscall.SOCK_CLOEXEC,proto)
    if err!=nil {return nil,fmt.Errorf("AF_PACKET ARP socket: %w",err)}
    defer syscall.Close(fd)
    bind:=&syscall.SockaddrLinklayer{Ifindex:target.iface.Index,Protocol:uint16(proto),Halen:6}
    if err:=syscall.Bind(fd,bind);err!=nil {return nil,fmt.Errorf("ARP bind: %w",err)}
    if err:=syscall.SetNonblock(fd,true);err!=nil{return nil,err}
    requestTo:=&syscall.SockaddrLinklayer{Ifindex:target.iface.Index,Protocol:uint16(proto),Halen:6}
    for i:=0;i<6;i++{requestTo.Addr[i]=0xff}
    expected:=make(map[string]struct{},len(target.targets))
    for _,t:=range target.targets {expected[t.String()]=struct{}{}}
    observations:=make(map[string]LANHost)
    receive:=func() error {
        buf:=make([]byte,2048)
        for {
            n,_,err:=syscall.Recvfrom(fd,buf,syscall.MSG_DONTWAIT)
            if err==syscall.EAGAIN || err==syscall.EWOULDBLOCK {return nil}
            if err==syscall.EINTR {continue}
            if err!=nil {return fmt.Errorf("ARP receive: %w",err)}
            if host,ok:=parseARPReply(buf[:n],target.network);ok {
                if _,requested:=expected[host.IPv4];requested {
                    observations[host.MAC]=host
                }
            }
        }
    }
    interval:=time.Second/time.Duration(rate)
    for _,addr:=range target.targets {
        select {case <-ctx.Done():return nil,ctx.Err();default:}
        if err:=receive();err!=nil{return nil,err}
        request,err:=buildARPRequest(target.iface.HardwareAddr,target.address,addr)
        if err!=nil{return nil,err}
        if err:=syscall.Sendto(fd,request,0,requestTo);err!=nil{return nil,fmt.Errorf("ARP send to %s: %w",addr,err)}
        timer:=time.NewTimer(interval)
        select {
        case <-ctx.Done():timer.Stop();return nil,ctx.Err()
        case <-timer.C:
        }
    }
    end:=time.NewTimer(900*time.Millisecond)
    defer end.Stop()
    for {
        if err:=receive();err!=nil{return nil,err}
        select {
        case <-ctx.Done():return nil,ctx.Err()
        case <-end.C:
            results:=make([]LANHost,0,len(observations))
            for _,host:=range observations {results=append(results,host)}
            return results,nil
        default:
            time.Sleep(25*time.Millisecond)
        }
    }
}

func localLANPlan() (lanTarget,error) {
    data,err:=os.ReadFile("/proc/net/route")
    if err!=nil{return lanTarget{},fmt.Errorf("read default route: %w",err)}
    route,err:=defaultRouteInterface(string(data))
    if err!=nil{return lanTarget{},err}
    interfaces,err:=net.Interfaces()
    if err!=nil{return lanTarget{},err}
    return chooseLAN(interfaces,route,256)
}
