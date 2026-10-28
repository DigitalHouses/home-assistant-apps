package main

import (
 "context"
 "errors"
 "fmt"
 "log"
 "net"
 "net/netip"
 "sort"
 "strings"
 "syscall"
 "time"
)

type MDNSService struct {
 Instance string `json:"instance"`
 Type string `json:"type"`
 Port uint16 `json:"port"`
 Target string `json:"target"`
}
type MDNSHost struct {
 IPv4 string `json:"ipv4"`
 Hostname string `json:"hostname"`
 IPv6 []string `json:"ipv6"`
 Services []MDNSService `json:"services"`
}

func mdnsHostsFromRecords(records []dnsRecord) []MDNSHost {
 hostIPs:=map[string][]string{}
 v6:=map[string][]string{}
 for _,r:=range records {
  name:=canonicalDNS(r.Name)
  if !strings.HasSuffix(name,".local") || r.IP=="" {continue}
  switch r.Type {
  case dnsTypeA:
   if normalizedIP(r.IP,false)!="" {hostIPs[name]=append(hostIPs[name],r.IP)}
  case dnsTypeAAAA:
   if normalizedIP(r.IP,true)!="" {v6[name]=append(v6[name],r.IP)}
  }
 }
 hostServices:=map[string][]MDNSService{}
 for _,r:=range records {
  if r.Type!=dnsTypeSRV || r.Port==0 {continue}
  target:=canonicalDNS(r.Target)
  instance:=strings.TrimSuffix(r.Name,".")
  pos:=strings.Index(instance,"._")
  if pos<1 || !strings.HasSuffix(target,".local") || len(instance)>220 {continue}
  kind:=instance[pos+1:]
  if !strings.Contains(kind,"._tcp.") && !strings.Contains(kind,"._udp.") {continue}
  hostServices[target]=append(hostServices[target],MDNSService{
    Instance:instance[:pos],Type:kind,Port:r.Port,Target:r.Target,
  })
 }
 unique:=map[string]*MDNSHost{}
 for hostname, ips:=range hostIPs {
  for _,ip:=range ips {
   host:=unique[ip]
   if host==nil {
    host=&MDNSHost{IPv4:ip,IPv6:[]string{},Services:[]MDNSService{}}
    unique[ip]=host
   }
   if host.Hostname=="" || hostname<canonicalDNS(host.Hostname) {host.Hostname=hostname+"."}
   for _,ip6:=range v6[hostname] {host.IPv6=append(host.IPv6,ip6)}
   host.Services=append(host.Services,hostServices[hostname]...)
  }
 }
 hosts:=make([]MDNSHost,0,len(unique))
 for _,host:=range unique {
  if friendlyMDNSHost(host.Hostname)=="" {continue}
  serviceSeen:=map[string]bool{}
  services:=make([]MDNSService,0)
  for _,s:=range host.Services {
   key:=strings.ToLower(s.Instance+"|"+s.Type)
   if serviceSeen[key] {continue}
   serviceSeen[key]=true
   services=append(services,s)
  }
  sort.Slice(services,func(i,j int)bool{
   if services[i].Type!=services[j].Type {return services[i].Type<services[j].Type}
   return services[i].Instance<services[j].Instance
  })
  host.Services=services
  host.IPv6=dedupeStrings(host.IPv6)
  hosts=append(hosts,*host)
 }
 sort.Slice(hosts,func(i,j int)bool{return hosts[i].IPv4<hosts[j].IPv4})
 return hosts
}

func dedupeStrings(in []string) []string {
 seen:=map[string]bool{}
 out:=make([]string,0,len(in))
 for _,s:=range in {if !seen[s] {seen[s]=true;out=append(out,s)}}
 sort.Strings(out)
 return out
}

func mdnsScan(ctx context.Context, plan lanTarget) ([]MDNSHost,int,error) {
 addr:=&net.UDPAddr{IP:net.ParseIP("224.0.0.251"),Port:5353}
 listener,err:=net.ListenUDP("udp4",&net.UDPAddr{IP:net.IP(plan.address.AsSlice()),Port:0})
 if err!=nil {return nil,0,fmt.Errorf("mDNS UDP socket: %w",err)}
 defer listener.Close()
 raw,err:=listener.SyscallConn()
 if err!=nil{return nil,0,err}
 var sockErr error
 if err:=raw.Control(func(fd uintptr){
    ip:=plan.address.As4()
    if x:=syscall.SetsockoptInet4Addr(int(fd),syscall.IPPROTO_IP,syscall.IP_MULTICAST_IF,ip);x!=nil {sockErr=x}
    if x:=syscall.SetsockoptInt(int(fd),syscall.IPPROTO_IP,syscall.IP_MULTICAST_TTL,255);x!=nil && sockErr==nil {sockErr=x}
 });err!=nil {return nil,0,err}
 if sockErr!=nil {return nil,0,fmt.Errorf("mDNS multicast socket: %w",sockErr)}
 answers:=make(map[string]dnsRecord)
 packets:=0
 send:=func(name string,typ uint16) error {
  packet,err:=mdnsQuestion(name,typ)
  if err!=nil{return err}
  _,err=listener.WriteToUDP(packet,addr)
  return err
 }
 receive:=func(d time.Duration) error {
  end:=time.Now().Add(d)
  buf:=make([]byte,9000)
  for time.Now().Before(end) {
   select {case <-ctx.Done():return ctx.Err(); default:}
   timeout:=time.Now().Add(160*time.Millisecond)
   if timeout.After(end) {timeout=end}
   if err:=listener.SetReadDeadline(timeout);err!=nil {return err}
   size,peer,err:=listener.ReadFromUDP(buf)
   if netErr,ok:=err.(net.Error);ok && netErr.Timeout(){continue}
   if err!=nil{return err}
   peerIP,ok:=netip.AddrFromSlice(peer.IP)
   if !ok || !plan.network.Contains(peerIP.Unmap()) {continue}
   records,err:=decodeDNSRecords(buf[:size])
   if err!=nil {continue}
   packets++
   for _,item:=range records {answers[dnsRecordKey(item)]=item}
  }
  return nil
 }
 if err:=send("_services._dns-sd._udp.local.",dnsTypePTR);err!=nil {
  return nil,0,fmt.Errorf("mDNS type discovery: %w",err)
 }
 if err:=receive(1200*time.Millisecond);err!=nil{return nil,packets,err}
 records:=func() []dnsRecord {
  result:=make([]dnsRecord,0,len(answers))
  for _,record:=range answers {result=append(result,record)}
  return result
 }
 types:=limitMDNSTypes(records())
 for _,typ:=range types {
  if err:=send(typ,dnsTypePTR);err!=nil{return nil,packets,err}
  time.Sleep(18*time.Millisecond)
 }
 if err:=receive(1700*time.Millisecond);err!=nil{return nil,packets,err}
 targets:=map[string]bool{}
 for _,r:=range records() {
  if r.Type==dnsTypeSRV && strings.HasSuffix(canonicalDNS(r.Target),".local") {
   targets[r.Target]=true
  }
 }
 count:=0
 for target:=range targets {
  if count>=64 {break}
  if err:=send(target,dnsTypeA);err!=nil{return nil,packets,err}
  // IPv6 addresses are recorded as metadata, not used as identity/presence
  // evidence until independent NDP support exists.
  _=send(target,dnsTypeAAAA)
  count++
  time.Sleep(12*time.Millisecond)
 }
 if err:=receive(1300*time.Millisecond);err!=nil{return nil,packets,err}
 return mdnsHostsFromRecords(records()),packets,nil
}

func (s *Service) pollMDNS() {
 generation:=s.currentScanGeneration()
 at:=time.Now().UTC().Format(time.RFC3339)
 plan,err:=localLANPlan()
 if err!=nil {s.withCurrentGeneration(generation,func(){s.recordMDNSError(at,err)});return}
 ctx,cancel:=context.WithTimeout(context.Background(),14*time.Second)
 defer cancel()
 hosts,packets,err:=mdnsScan(ctx,plan)
 if err!=nil {s.withCurrentGeneration(generation,func(){s.recordMDNSError(at,err)});return}
 s.withCurrentGeneration(generation,func(){
  at=time.Now().UTC().Format(time.RFC3339)
  matched,unmatched,services,importErr:=s.db.importMDNSHosts(hosts,at,packets,plan.iface.Name)
  if importErr!=nil {s.recordMDNSError(at,importErr);return}
  log.Printf("mDNS discovery: %d hosts with A records, %d linked to fresh ARP, %d unmatched, %d services, %d response packets",
   len(hosts),matched,unmatched,services,packets)
 })
}

func (s *Service) recordMDNSError(at string,err error) {
 if errors.Is(err,context.Canceled) {return}
 log.Printf("mDNS discovery unavailable: %v",err)
 if e:=s.db.recordMDNSFailure(at,err);e!=nil {log.Printf("mDNS failure status write error: %v",e)}
}

func (s *Service) runMDNSPolling(interval time.Duration) {
 // Give the LAN ARP scanner a chance to populate reliable mapping first.
 timer:=time.NewTimer(12*time.Second)
 <-timer.C
 for {s.pollMDNS();time.Sleep(s.intervalFor("mdns",interval))}
}
