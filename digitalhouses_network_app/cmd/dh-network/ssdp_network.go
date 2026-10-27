package main

import (
 "context"
 "errors"
 "fmt"
 "log"
 "net"
 "net/netip"
 "net/url"
 "sort"
 "strconv"
 "strings"
 "syscall"
 "time"
)

// SSDP is metadata only. Responses use a private ephemeral UDP port and
// are never fetched via LOCATION (untrusted remote URL / SSRF prevention).
type SSDPRecord struct {
 IPv4 string `json:"ipv4"`
 ST string `json:"st"`
 USN string `json:"usn"`
 Server string `json:"server"`
 Location string `json:"location"`
}

func singleSSDPHeader(value string,max int) string {
 value=strings.TrimSpace(value)
 if len(value)>max || strings.ContainsAny(value,"\x00\r\n") {return ""}
 return value
}
func parseSSDPResponse(packet []byte,source netip.Addr) (SSDPRecord,bool) {
 if len(packet)<30 || len(packet)>8192 || !source.Is4() {return SSDPRecord{},false}
 lines:=strings.Split(string(packet),"\r\n")
 if len(lines)<4 || len(lines)>70 {return SSDPRecord{},false}
 status:=strings.TrimSpace(lines[0])
 if status!="HTTP/1.1 200 OK" && status!="HTTP/1.0 200 OK" {return SSDPRecord{},false}
 headers:=map[string]string{}
 for _,line:=range lines[1:] {
  if line=="" {break}
  idx:=strings.IndexByte(line,':')
  if idx<1 {return SSDPRecord{},false}
  name:=strings.ToLower(strings.TrimSpace(line[:idx]))
  if name=="st"||name=="usn"||name=="server"||name=="location" {
   if _,exists:=headers[name];exists {return SSDPRecord{},false}
   headers[name]=strings.TrimSpace(line[idx+1:])
  }
 }
 st:=singleSSDPHeader(headers["st"],180)
 usn:=singleSSDPHeader(headers["usn"],220)
 server:=singleSSDPHeader(headers["server"],160)
 raw:=singleSSDPHeader(headers["location"],500)
 if st==""||usn==""||raw=="" {return SSDPRecord{},false}
 u,err:=url.Parse(raw)
 if err!=nil || (u.Scheme!="http" && u.Scheme!="https") || u.User!=nil ||
  u.Host=="" {return SSDPRecord{},false}
 // A LOCATION pointing at a different host cannot safely identify sender.
 host,err:=netip.ParseAddr(u.Hostname())
 if err!=nil || !host.Is4() || host!=source {return SSDPRecord{},false}
 port:=u.Port()
 if port!="" {n,err:=strconv.Atoi(port);if err!=nil||n<1||n>65535{return SSDPRecord{},false}}
 // Do not retain path/query/fragment: these may contain device secrets.
 authority:=u.Scheme+"://"+u.Host
 return SSDPRecord{IPv4:source.String(),ST:st,USN:usn,Server:server,Location:authority},true
}
func ssdpScan(ctx context.Context,plan lanTarget) ([]SSDPRecord,int,error) {
 dest:=&net.UDPAddr{IP:net.ParseIP("239.255.255.250"),Port:1900}
 socket,err:=net.ListenUDP("udp4",&net.UDPAddr{IP:net.IP(plan.address.AsSlice()),Port:0})
 if err!=nil {return nil,0,fmt.Errorf("SSDP UDP socket: %w",err)}
 defer socket.Close()
 raw,err:=socket.SyscallConn()
 if err!=nil{return nil,0,err}
 var optsErr error
 if err=raw.Control(func(fd uintptr){
  ip:=plan.address.As4()
  optsErr=syscall.SetsockoptInet4Addr(int(fd),syscall.IPPROTO_IP,syscall.IP_MULTICAST_IF,ip)
  if optsErr==nil {optsErr=syscall.SetsockoptInt(int(fd),syscall.IPPROTO_IP,syscall.IP_MULTICAST_TTL,2)}
 });err!=nil {return nil,0,err}
 if optsErr!=nil{return nil,0,optsErr}
 request:=[]byte("M-SEARCH * HTTP/1.1\r\nHOST: 239.255.255.250:1900\r\nMAN: \"ssdp:discover\"\r\nMX: 1\r\nST: ssdp:all\r\n\r\n")
 for i:=0;i<2;i++ {
  if _,err=socket.WriteToUDP(request,dest);err!=nil{return nil,0,fmt.Errorf("SSDP multicast: %w",err)}
  if i==0 {select {case <-ctx.Done():return nil,0,ctx.Err();case <-time.After(120*time.Millisecond):}}
 }
 unique:=map[string]SSDPRecord{}
 received:=0
 until:=time.Now().Add(2300*time.Millisecond)
 buf:=make([]byte,8193)
 for time.Now().Before(until) {
  if ctx.Err()!=nil{return nil,received,ctx.Err()}
  deadline:=time.Now().Add(150*time.Millisecond)
  if deadline.After(until) {deadline=until}
  if err=socket.SetReadDeadline(deadline);err!=nil{return nil,received,err}
  n,from,readErr:=socket.ReadFromUDP(buf)
  if e,ok:=readErr.(net.Error);ok&&e.Timeout(){continue}
  if readErr!=nil{return nil,received,readErr}
  ip,ok:=netip.AddrFromSlice(from.IP)
  if !ok || !ip.Is4() || !plan.network.Contains(ip) || ip==plan.address {continue}
  received++
  if r,ok:=parseSSDPResponse(buf[:n],ip);ok {
   unique[r.IPv4+"|"+r.USN+"|"+r.ST]=r
  }
 }
 records:=make([]SSDPRecord,0,len(unique))
 for _,item:=range unique {records=append(records,item)}
 sort.Slice(records,func(i,j int)bool{
  a,b:=records[i],records[j]
  return a.IPv4+"|"+a.USN+"|"+a.ST < b.IPv4+"|"+b.USN+"|"+b.ST
 })
 if len(records)>128 {records=records[:128]}
 return records,received,nil
}
func (s *Service) pollSSDP() {
 at:=time.Now().UTC().Format(time.RFC3339)
 plan,err:=localLANPlan()
 if err!=nil {s.recordSSDPError(at,err);return}
 ctx,cancel:=context.WithTimeout(context.Background(),9*time.Second)
 defer cancel()
 records,packets,err:=ssdpScan(ctx,plan)
 if err!=nil {s.recordSSDPError(at,err);return}
 at=time.Now().UTC().Format(time.RFC3339)
 matched,unmatched,services,err:=s.db.importSSDPRecords(records,at,packets,plan.iface.Name)
 if err!=nil {s.recordSSDPError(at,err);return}
 log.Printf("SSDP discovery: %d responses, %d unique records, %d ARP-linked hosts, %d unmatched, %d services",
   packets,len(records),matched,unmatched,services)
}
func (s *Service) recordSSDPError(at string,err error) {
 if errors.Is(err,context.Canceled) {return}
 log.Printf("SSDP discovery unavailable: %v",err)
 if e:=s.db.recordSSDPFailure(at,err);e!=nil {log.Printf("SSDP status write error: %v",e)}
}
func (s *Service) runSSDPPolling(interval time.Duration) {
 // ARP has priority for association; leave time for initial LAN scan.
 select {case <-time.After(18*time.Second):}
 s.pollSSDP()
 ticker:=time.NewTicker(interval)
 defer ticker.Stop()
 for range ticker.C {s.pollSSDP()}
}
