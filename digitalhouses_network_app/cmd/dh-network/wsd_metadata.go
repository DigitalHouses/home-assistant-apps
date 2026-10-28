package main

import (
 "bytes"
 "context"
 "encoding/xml"
 "errors"
 "fmt"
 "io"
 "net"
 "net/http"
 "net/netip"
 "net/url"
 "strings"
 "time"
)

const (
 wsdAddressingNS="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 wsdGetAction="http://schemas.xmlsoap.org/ws/2004/09/transfer/Get"
 wsdGetResponseAction="http://schemas.xmlsoap.org/ws/2004/09/transfer/GetResponse"
 wsdMetadataNS="http://schemas.xmlsoap.org/ws/2004/09/mex"
 wsdProfileNS="http://schemas.xmlsoap.org/ws/2006/02/devprof"
 wsdPublishingNS="http://schemas.microsoft.com/windows/pub/2005/07"
)

// Windows' generic ThisDevice/FriendlyName describes its publication
// service, not necessarily the computer. Only the explicit pub:Computer
// metadata can supply a trustworthy machine name.
type wsdGetEnvelope struct {
 XMLName xml.Name
 Header struct {
  Action string `xml:"http://schemas.xmlsoap.org/ws/2004/08/addressing Action"`
  RelatesTo string `xml:"http://schemas.xmlsoap.org/ws/2004/08/addressing RelatesTo"`
 } `xml:"http://www.w3.org/2003/05/soap-envelope Header"`
 Body struct {
  Metadata struct {
   Sections []struct {
    Dialect string `xml:"Dialect,attr"`
    Relationship struct {
     Host struct {
      EndpointReference struct {
       Address string `xml:"http://schemas.xmlsoap.org/ws/2004/08/addressing Address"`
      } `xml:"http://schemas.xmlsoap.org/ws/2004/08/addressing EndpointReference"`
      Types string `xml:"http://schemas.xmlsoap.org/ws/2006/02/devprof Types"`
      Computer string `xml:"http://schemas.microsoft.com/windows/pub/2005/07 Computer"`
     } `xml:"http://schemas.xmlsoap.org/ws/2006/02/devprof Host"`
    } `xml:"http://schemas.xmlsoap.org/ws/2006/02/devprof Relationship"`
   } `xml:"http://schemas.xmlsoap.org/ws/2004/09/mex MetadataSection"`
  } `xml:"http://schemas.xmlsoap.org/ws/2004/09/mex Metadata"`
 } `xml:"http://www.w3.org/2003/05/soap-envelope Body"`
}
func wsdGetSOAP(endpoint,requestID string) []byte {
 return []byte(`<?xml version="1.0" encoding="utf-8"?>
<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:wsa="http://schemas.xmlsoap.org/ws/2004/08/addressing">
<s:Header>
<wsa:To>`+endpoint+`</wsa:To>
<wsa:Action>http://schemas.xmlsoap.org/ws/2004/09/transfer/Get</wsa:Action>
<wsa:MessageID>`+requestID+`</wsa:MessageID>
<wsa:ReplyTo><wsa:Address>http://schemas.xmlsoap.org/ws/2004/08/addressing/role/anonymous</wsa:Address></wsa:ReplyTo>
</s:Header><s:Body/></s:Envelope>`)
}
func validWSDComputerName(s string) bool {
 if len(s)<1||len(s)>63{return false}
 if strings.EqualFold(s,"localhost")||strings.EqualFold(s,"unknown")||strings.EqualFold(s,"unavailable"){return false}
 if len(s)==12 {
  hex:=true
  for _,c:=range s {if !(c>='0'&&c<='9'||c>='a'&&c<='f'||c>='A'&&c<='F'){hex=false;break}}
  if hex{return false}
 }
 if s[0]=='-'||s[len(s)-1]=='-'{return false}
 hasLetter:=false
 for _,c:=range s {
  if c>='a'&&c<='z'||c>='A'&&c<='Z' {hasLetter=true;continue}
  if c>='0'&&c<='9'||c=='-' {continue}
  return false
 }
 return hasLetter
}
func parseWSDComputerMetadata(packet []byte,requestID,endpoint string) (string,bool) {
 if len(packet)<180||len(packet)>32768 {return "",false}
 var doc wsdGetEnvelope
 if err:=xml.Unmarshal(packet,&doc);err!=nil{return "",false}
 if doc.XMLName.Space!=soapNS||doc.XMLName.Local!="Envelope" {return "",false}
 if strings.TrimSpace(doc.Header.Action)!=wsdGetResponseAction||strings.TrimSpace(doc.Header.RelatesTo)!=requestID {
  return "",false
 }
 for _,section:=range doc.Body.Metadata.Sections {
  if section.Dialect!=wsdProfileNS+"/Relationship" {continue}
  host:=section.Relationship.Host
  if !strings.EqualFold(strings.TrimSpace(host.EndpointReference.Address),endpoint) {continue}
  if !strings.Contains(" "+strings.TrimSpace(host.Types)+" "," pub:Computer ") {continue}
  raw:=strings.TrimSpace(host.Computer)
  var name string
  if i:=strings.Index(raw,"/Workgroup:");i>0 {name=raw[:i]}
  if i:=strings.Index(raw,"/Domain:");i>0 {name=raw[:i]}
  if validWSDComputerName(name) {return name,true}
 }
 return "",false
}
func safeWSDMetadataTarget(item WSDAnnouncement) (string,error) {
 ip,err:=netip.ParseAddr(item.IPv4)
 if err!=nil||!ip.Is4()||!ip.IsPrivate(){return "",errors.New("WSD target must be a private IPv4")}
 u,err:=url.Parse(item.Origin)
 if err!=nil||u.Scheme!="http"||u.User!=nil||u.Host==""||(u.Port()!="5357"&&u.Port()!="3702") || u.Path!=""||u.RawQuery!=""||u.Fragment!="" {
  return "",errors.New("WSD metadata target is not a sanitized Windows WSD origin")
 }
 resolved,err:=netip.ParseAddr(u.Hostname())
 if err!=nil||resolved!=ip {return "",errors.New("WSD metadata host mismatches reply address")}
 if !strings.HasPrefix(strings.ToLower(item.Endpoint),"urn:uuid:")||len(item.Endpoint)!=45 {return "",errors.New("invalid WSD endpoint UUID")}
 uuid:=strings.ToLower(strings.TrimPrefix(strings.ToLower(item.Endpoint),"urn:uuid:"))
 for i,c:=range uuid {
  if i==8||i==13||i==18||i==23 {if c!='-'{return "",errors.New("invalid UUID separator")};continue}
  if !(c>='0'&&c<='9'||c>='a'&&c<='f'){return "",errors.New("invalid UUID")}
 }
 return item.Origin+"/"+uuid,nil
}
func fetchWSDComputerName(ctx context.Context,item WSDAnnouncement) (string,error) {
 target,err:=safeWSDMetadataTarget(item)
 if err!=nil{return "",err}
 id,err:=freshDeviceID()
 if err!=nil{return "",err}
 requestID:="urn:uuid:"+id
 req,err:=http.NewRequestWithContext(ctx,http.MethodPost,target,bytes.NewReader(wsdGetSOAP(item.Endpoint,requestID)))
 if err!=nil{return "",err}
 // wsdd2 uses literal Content-Type comparison and rejects charset parameters.
 req.Header.Set("Content-Type","application/soap+xml")
 req.Header.Set("User-Agent","DigitalHouses-Network-WSD/0.1.10")
 client:=&http.Client{
  Timeout:1800*time.Millisecond,
  CheckRedirect:func(req *http.Request,via []*http.Request)error{return http.ErrUseLastResponse},
  Transport:&http.Transport{
   Proxy:nil,
   DialContext:(&net.Dialer{Timeout:1000*time.Millisecond}).DialContext,
   DisableKeepAlives:true,
   MaxConnsPerHost:1,
   ResponseHeaderTimeout:1200*time.Millisecond,
  },
 }
 defer client.CloseIdleConnections()
 response,err:=client.Do(req)
 if err!=nil{return "",err}
 defer response.Body.Close()
 if response.StatusCode!=http.StatusOK {return "",fmt.Errorf("WSD Get HTTP %d",response.StatusCode)}
 if ct:=strings.ToLower(response.Header.Get("Content-Type"));!strings.HasPrefix(ct,"application/soap+xml") {
  return "",errors.New("WSD metadata response is not SOAP")
 }
 packet,err:=io.ReadAll(io.LimitReader(response.Body,32769))
 if err!=nil{return "",err}
 if len(packet)>32768{return "",errors.New("WSD metadata response too large")}
 if value,ok:=parseWSDComputerMetadata(packet,requestID,item.Endpoint);ok{return value,nil}
 return "",errors.New("WSD GetResponse did not provide verified pub:Computer")
}
