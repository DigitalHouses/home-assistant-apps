package main

import (
 "encoding/binary"
 "errors"
 "fmt"
 "net/netip"
 "strings"
)

const (
 dnsTypeA uint16=1
 dnsTypePTR uint16=12
 dnsTypeTXT uint16=16
 dnsTypeAAAA uint16=28
 dnsTypeSRV uint16=33
)
type dnsRecord struct {
 Name string
 Type uint16
 TTL uint32
 Target string
 IP string
 Port uint16
}

// Encoded DNS names may contain compression pointers to previous labels.
// Never allow pointer loops, out-of-bounds offsets or oversized names.
func readDNSName(data []byte, start int) (string,int,error) {
 if start<0 || start>=len(data) {return "",start,errors.New("DNS name offset out of range")}
 labels:=make([]string,0,10)
 offset,end:=start,-1
 visited:=map[int]bool{}
 for hops:=0;hops<32;hops++ {
  if offset>=len(data) || visited[offset] {return "",start,errors.New("DNS name pointer invalid")}
  visited[offset]=true
  length:=int(data[offset])
  if length==0 {
   offset++
   if end<0 {end=offset}
   name:=strings.Join(labels,".")
   if len(name)>253 {return "",start,errors.New("DNS name too long")}
   return name+".",end,nil
  }
  if (length&0xC0)==0xC0 {
   if offset+1>=len(data) {return "",start,errors.New("truncated DNS pointer")}
   ptr:=(length&0x3F)<<8|int(data[offset+1])
   if end<0 {end=offset+2}
   offset=ptr
   continue
  }
  if (length&0xC0)!=0 || length>63 || offset+1+length>len(data) {
   return "",start,errors.New("invalid DNS label")
  }
  label:=string(data[offset+1:offset+1+length])
  for _,c:=range label {
   if c<32 || c>126 {return "",start,errors.New("nonprintable DNS label")}
  }
  labels=append(labels,label)
  offset+=1+length
 }
 return "",start,errors.New("DNS name too many pointer jumps")
}

func dnsEncodeName(value string) ([]byte,error) {
 value=strings.TrimSuffix(strings.TrimSpace(value),".")
 if value=="" || len(value)>253 {return nil,errors.New("invalid query name")}
 labels:=strings.Split(value,".")
 result:=make([]byte,0,len(value)+2)
 for _,label:=range labels {
  if label==""||len(label)>63 {return nil,errors.New("invalid query label")}
  result=append(result,byte(len(label)))
  result=append(result,[]byte(label)...)
 }
 return append(result,0),nil
}

func mdnsQuestion(name string,kind uint16) ([]byte,error) {
 encoded,err:=dnsEncodeName(name)
 if err!=nil {return nil,err}
 result:=make([]byte,12,12+len(encoded)+4)
 // Transaction ID zero for DNS-SD. Using a non-5353 source UDP port asks
 // responders to reply unicast to this legacy query's source port.
 binary.BigEndian.PutUint16(result[4:6],1)
 result=append(result,encoded...)
 var suffix [4]byte
 binary.BigEndian.PutUint16(suffix[0:2],kind)
 binary.BigEndian.PutUint16(suffix[2:4],1)
 return append(result,suffix[:]...),nil
}

func decodeDNSRecords(packet []byte) ([]dnsRecord,error) {
 if len(packet)<12 || len(packet)>9000 {return nil,errors.New("invalid DNS response size")}
 if packet[2]&0x80==0 {return nil,errors.New("not a DNS response")}
 qn:=int(binary.BigEndian.Uint16(packet[4:6]))
 rn:=int(binary.BigEndian.Uint16(packet[6:8]))+
  int(binary.BigEndian.Uint16(packet[8:10]))+int(binary.BigEndian.Uint16(packet[10:12]))
 if qn>50 || rn>250 {return nil,errors.New("too many DNS records")}
 offset:=12
 for i:=0;i<qn;i++ {
  _,next,err:=readDNSName(packet,offset)
  if err!=nil{return nil,err}
  offset=next+4
  if offset>len(packet){return nil,errors.New("truncated DNS question")}
 }
 records:=make([]dnsRecord,0,rn)
 for i:=0;i<rn;i++ {
  name,next,err:=readDNSName(packet,offset)
  if err!=nil{return nil,err}
  if next+10>len(packet){return nil,errors.New("truncated DNS answer")}
  kind:=binary.BigEndian.Uint16(packet[next:next+2])
  class:=binary.BigEndian.Uint16(packet[next+2:next+4])&0x7FFF
  ttl:=binary.BigEndian.Uint32(packet[next+4:next+8])
  sz:=int(binary.BigEndian.Uint16(packet[next+8:next+10]))
  valueStart:=next+10
  offset=valueStart+sz
  if offset>len(packet){return nil,errors.New("truncated DNS resource data")}
  if class!=1 || ttl==0 {continue}
  rec:=dnsRecord{Name:name,Type:kind,TTL:ttl}
  switch kind {
  case dnsTypeA:
   if sz!=4 {continue}
   var a [4]byte
   copy(a[:],packet[valueStart:offset])
   rec.IP=netip.AddrFrom4(a).String()
  case dnsTypeAAAA:
   if sz!=16 {continue}
   var a [16]byte
   copy(a[:],packet[valueStart:offset])
   ip:=netip.AddrFrom16(a)
   if !ip.IsUnspecified() && !ip.IsMulticast() {rec.IP=ip.String()}
  case dnsTypePTR:
   target,_,err:=readDNSName(packet,valueStart)
   if err!=nil {continue}
   rec.Target=target
  case dnsTypeSRV:
   if sz<7 {continue}
   rec.Port=binary.BigEndian.Uint16(packet[valueStart+4:valueStart+6])
   target,_,err:=readDNSName(packet,valueStart+6)
   if err!=nil {continue}
   rec.Target=target
  default:
   continue // TXT is deliberately neither persisted nor exported.
  }
  records=append(records,rec)
 }
 return records,nil
}

func canonicalDNS(name string) string {return strings.ToLower(strings.TrimSuffix(name,"."))}

// Strip trailing .local from a discovered host but never use a service
// instance name as a host label.
func friendlyMDNSHost(host string) string {
 lower:=canonicalDNS(host)
 if !strings.HasSuffix(lower,".local"){return ""}
 base:=strings.TrimSuffix(strings.TrimSuffix(host,"."),".local")
 if base==""||len(base)>120{return ""}
 return base
}

func limitMDNSTypes(records []dnsRecord) []string {
 known:=[]string{
  "_workstation._tcp.local.","_http._tcp.local.","_https._tcp.local.",
  "_ssh._tcp.local.","_smb._tcp.local.","_airplay._tcp.local.",
  "_raop._tcp.local.","_googlecast._tcp.local.","_hap._tcp.local.",
  "_ipp._tcp.local.","_printer._tcp.local.","_mqtt._tcp.local.",
  "_digitalhouses._tcp.local.","_home-assistant._tcp.local.",
 }
 found:=map[string]bool{}
 result:=make([]string,0,32)
 add:=func(name string){
  key:=canonicalDNS(name)
  if len(result)>=32 || found[key] || !strings.HasSuffix(key,".local") {return}
  if !strings.HasPrefix(key,"_") || !strings.Contains(key,"._tcp.") && !strings.Contains(key,"._udp.") {return}
  if len(name)>170{return}
  found[key]=true;result=append(result,name)
 }
 for _,record:=range records {
  if record.Type==dnsTypePTR && canonicalDNS(record.Name)=="_services._dns-sd._udp.local" {add(record.Target)}
 }
 for _,name:=range known {add(name)}
 return result
}

func dnsRecordKey(record dnsRecord) string {
 return fmt.Sprintf("%s|%d|%s|%s|%d",canonicalDNS(record.Name),record.Type,canonicalDNS(record.Target),record.IP,record.Port)
}
