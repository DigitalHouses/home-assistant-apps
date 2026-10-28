package main

import (
 "context"
 "encoding/xml"
 "errors"
 "fmt"
 "io"
 "log"
 "net"
 "net/netip"
 "net/url"
 "sort"
 "strings"
 "syscall"
 "time"
)

const (
 wsdDiscoveryNS="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 wsdAction=wsdDiscoveryNS+"/ProbeMatches"
 soapNS="http://www.w3.org/2003/05/soap-envelope"
)
type WSDAnnouncement struct {
 IPv4 string `json:"ipv4"`
 Endpoint string `json:"endpoint"`
 Types string `json:"types"`
 Scopes string `json:"scopes"`
 Origin string `json:"origin"`
}
type wsdEnvelope struct {
 XMLName xml.Name
 Header struct{
  Action string `xml:"Action"`
  RelatesTo string `xml:"RelatesTo"`
 } `xml:"Header"`
 Body struct{
  Matches struct{
   Items []struct{
    EndpointReference struct{
     Address string `xml:"Address"`
    } `xml:"EndpointReference"`
    Types string `xml:"Types"`
    Scopes string `xml:"Scopes"`
    XAddrs string `xml:"XAddrs"`
   } `xml:"ProbeMatch"`
  } `xml:"ProbeMatches"`
 } `xml:"Body"`
}
func wsdProbe(messageID string) []byte {
 // WS-Discovery 2005/04 Probe for DPWS devices (Microsoft WSDAPI).
 return []byte(`<?xml version="1.0" encoding="UTF-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:wsd="http://schemas.xmlsoap.org/ws/2005/04/discovery"
 xmlns:wsdp="http://schemas.xmlsoap.org/ws/2006/02/devprof">
<s:Header>
<wsa:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</wsa:Action>
<wsa:MessageID>`+messageID+`</wsa:MessageID>
<wsa:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</wsa:To>
</s:Header><s:Body><wsd:Probe><wsd:Types>wsdp:Device</wsd:Types></wsd:Probe></s:Body></s:Envelope>`)
}
func boundedWSDString(s string,limit int) string {
 s=strings.TrimSpace(s)
 if len(s)>limit || strings.ContainsAny(s,"\x00\r\n") {return ""}
 return s
}
func safeWSDOrigin(raw string,from netip.Addr) string {
 for _,addr:=range strings.Fields(raw) {
  u,err:=url.Parse(addr)
  if err!=nil || u.User!=nil || (u.Scheme!="http"&&u.Scheme!="https") || u.Host=="" {continue}
  host,err:=netip.ParseAddr(u.Hostname())
  if err!=nil || host!=from {continue}
  port:=u.Port()
  if len(port)>5 {continue}
  return u.Scheme+"://"+u.Host
 }
 return ""
}
func parseWSDProbeMatches(packet []byte,from netip.Addr,messageID string) []WSDAnnouncement {
 if !from.Is4() || len(packet)<100 || len(packet)>16384 {return nil}
 dec:=xml.NewDecoder(strings.NewReader(string(packet)))
 dec.Strict=true
 var env wsdEnvelope
 if err:=dec.Decode(&env);err!=nil {return nil}
 if env.XMLName.Space!=soapNS || env.XMLName.Local!="Envelope" {return nil}
 if strings.TrimSpace(env.Header.Action)!=wsdAction || strings.TrimSpace(env.Header.RelatesTo)!=messageID {return nil}
 unique:=map[string]WSDAnnouncement{}
 for _,match:=range env.Body.Matches.Items {
  endpoint:=boundedWSDString(match.EndpointReference.Address,130)
  if !strings.HasPrefix(strings.ToLower(endpoint),"urn:uuid:") {continue}
  uuid:=strings.TrimPrefix(strings.ToLower(endpoint),"urn:uuid:")
  if len(uuid)!=36 {continue}
  valid:=true
  for i,c:=range uuid {
   if i==8||i==13||i==18||i==23 {if c!='-' {valid=false};continue}
   if !(c>='0'&&c<='9'||c>='a'&&c<='f') {valid=false}
  }
  if !valid {continue}
  types:=boundedWSDString(match.Types,300)
  scopes:=boundedWSDString(match.Scopes,500)
  origin:=safeWSDOrigin(match.XAddrs,from)
  // No guessed hostname, no HTTP/XML retrieval, no assigning UUID to a MAC.
  unique[endpoint]=WSDAnnouncement{IPv4:from.String(),Endpoint:endpoint,Types:types,Scopes:scopes,Origin:origin}
 }
 result:=make([]WSDAnnouncement,0,len(unique))
 for _,x:=range unique {result=append(result,x)}
 sort.Slice(result,func(i,j int)bool{return result[i].Endpoint<result[j].Endpoint})
 return result
}
func scanWSD(ctx context.Context,plan lanTarget) ([]WSDAnnouncement,int,error) {
 socket,err:=net.ListenUDP("udp4",&net.UDPAddr{IP:net.IP(plan.address.AsSlice()),Port:0})
 if err!=nil {return nil,0,fmt.Errorf("WS-Discovery UDP socket: %w",err)}
 defer socket.Close()
 raw,err:=socket.SyscallConn()
 if err!=nil{return nil,0,err}
 var optErr error
 if err=raw.Control(func(fd uintptr){
  optErr=syscall.SetsockoptInet4Addr(int(fd),syscall.IPPROTO_IP,syscall.IP_MULTICAST_IF,plan.address.As4())
  if optErr==nil {optErr=syscall.SetsockoptInt(int(fd),syscall.IPPROTO_IP,syscall.IP_MULTICAST_TTL,2)}
 });err!=nil{return nil,0,err}
 if optErr!=nil{return nil,0,optErr}
 msgUUID,err:=freshDeviceID()
 if err!=nil{return nil,0,err}
 messageID:="urn:uuid:"+msgUUID
 target:=&net.UDPAddr{IP:net.ParseIP("239.255.255.250"),Port:3702}
 if _,err=socket.WriteToUDP(wsdProbe(messageID),target);err!=nil{return nil,0,err}
 received:=0
 unique:=map[string]WSDAnnouncement{}
 deadline:=time.Now().Add(4700*time.Millisecond)
 buf:=make([]byte,16385)
 for time.Now().Before(deadline) {
  if ctx.Err()!=nil{return nil,received,ctx.Err()}
  next:=time.Now().Add(160*time.Millisecond)
  if next.After(deadline){next=deadline}
  if err=socket.SetReadDeadline(next);err!=nil{return nil,received,err}
  n,from,readErr:=socket.ReadFromUDP(buf)
  if err,ok:=readErr.(net.Error);ok&&err.Timeout(){continue}
  if readErr!=nil {if errors.Is(readErr,io.EOF){break};return nil,received,readErr}
  addr,ok:=netip.AddrFromSlice(from.IP)
  if !ok||!addr.Is4()||!plan.network.Contains(addr)||addr==plan.address {continue}
  received++
  for _,item:=range parseWSDProbeMatches(buf[:n],addr,messageID) {
   unique[item.IPv4+"|"+item.Endpoint]=item
  }
 }
 result:=make([]WSDAnnouncement,0,len(unique))
 for _,v:=range unique {result=append(result,v)}
 sort.Slice(result,func(i,j int)bool{return result[i].IPv4+"|"+result[i].Endpoint<result[j].IPv4+"|"+result[j].Endpoint})
 if len(result)>128 {result=result[:128]}
 return result,received,nil
}
func (s *Service) pollWSD() {
 generation:=s.currentScanGeneration()
 plan,err:=localLANPlan()
 if err!=nil {s.withCurrentGeneration(generation,func(){s.reportWSDError(err)});return}
 ctx,cancel:=context.WithTimeout(context.Background(),8*time.Second)
 defer cancel()
 items,packets,err:=scanWSD(ctx,plan)
 if err!=nil {s.reportWSDError(err);return}
 s.withCurrentGeneration(generation,func(){
 at:=time.Now().UTC().Format(time.RFC3339)
 linked,unmatched,err:=s.db.importWSD(items,at,packets,plan.iface.Name)
 if err!=nil{s.reportWSDError(err);return}
 verified,attempted:=0,0
 for _,item:=range items {
  if attempted>=8 {break}
  if !strings.Contains(" "+item.Types+" "," pub:Computer ") {continue}
  if _,targetErr:=safeWSDMetadataTarget(item);targetErr!=nil {continue}
  confirmed,checkErr:=s.db.wsdConfirmedEndpoint(item,at)
  if checkErr!=nil {log.Printf("WSD endpoint validation: %v",checkErr);continue}
  if !confirmed {continue}
  attempted++
  metaCtx,metaCancel:=context.WithTimeout(ctx,2*time.Second)
  name,metaErr:=fetchWSDComputerName(metaCtx,item)
  metaCancel()
  if metaErr!=nil {log.Printf("WSD metadata Get %s: %v",item.IPv4,metaErr);continue}
  if err:=s.db.persistWSDComputerName(item,name,time.Now().UTC().Format(time.RFC3339));err!=nil {
   log.Printf("WSD verified name persistence error: %v",err);continue
  }
  verified++
  log.Printf("WSD verified computer name: %s -> %s",item.IPv4,name)
 }
 log.Printf("WS-Discovery: %d responses, %d endpoints, %d ARP/local-interface-linked, %d unmatched, %d/%d verified computer names",
  packets,len(items),linked,unmatched,verified,attempted)
 })
}
func (s *Service) reportWSDError(err error) {
 log.Printf("WS-Discovery unavailable: %v",err)
 if issue:=s.db.recordWSDFailure(time.Now().UTC().Format(time.RFC3339),err);issue!=nil {log.Printf("WS-Discovery source-status error: %v",issue)}
}
func (s *Service) runWSDPolling(interval time.Duration) {
 // First local interface/ARP scan must have completed before joining WSD to IDs.
 time.Sleep(60*time.Second)
 for {s.pollWSD();time.Sleep(s.intervalFor("wsd",interval))}
}
