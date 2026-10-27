package main

import (
 "path/filepath"
 "strings"
 "testing"
 "time"
)

func sampleWindowsWSDGetResponse(id,endpoint,computer string) []byte {
 return []byte(`<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope"
 xmlns:a="http://schemas.xmlsoap.org/ws/2004/08/addressing"
 xmlns:x="http://schemas.xmlsoap.org/ws/2004/09/mex"
 xmlns:dp="http://schemas.xmlsoap.org/ws/2006/02/devprof"
 xmlns:pub="http://schemas.microsoft.com/windows/pub/2005/07">
 <s:Header>
 <a:Action>http://schemas.xmlsoap.org/ws/2004/09/transfer/GetResponse</a:Action>
 <a:RelatesTo>`+id+`</a:RelatesTo>
 </s:Header>
 <s:Body><x:Metadata>
 <x:MetadataSection Dialect="http://schemas.xmlsoap.org/ws/2006/02/devprof/ThisDevice">
 <dp:ThisDevice><dp:FriendlyName>Microsoft Publication Service Device Host</dp:FriendlyName></dp:ThisDevice>
 </x:MetadataSection>
 <x:MetadataSection Dialect="http://schemas.xmlsoap.org/ws/2006/02/devprof/Relationship">
 <dp:Relationship Type="http://schemas.xmlsoap.org/ws/2006/02/devprof/host">
 <dp:Host><a:EndpointReference><a:Address>`+endpoint+`</a:Address></a:EndpointReference>
 <dp:Types>pub:Computer</dp:Types><pub:Computer>`+computer+`</pub:Computer></dp:Host></dp:Relationship>
 </x:MetadataSection>
 </x:Metadata></s:Body></s:Envelope>`)
}
func TestWSDWindowsComputerNameOnlyFromVerifiedGetResponse(t *testing.T) {
 endpoint:="urn:uuid:e2bf7703-4b57-4ee5-bedd-ef9676b731f9"
 correlation:="urn:uuid:99999999-aaaa-bbbb-cccc-111111111111"
 payload:=sampleWindowsWSDGetResponse(correlation,endpoint,"VIEW71/Workgroup:WORKGROUP")
 got,ok:=parseWSDComputerMetadata(payload,correlation,endpoint)
 if !ok||got!="VIEW71"{t.Fatalf("wrong WSD Windows computer name: %q %v",got,ok)}
 for _,bad:=range [][]byte{
  sampleWindowsWSDGetResponse("urn:uuid:wrong",endpoint,"VIEW71/Workgroup:WORKGROUP"),
  sampleWindowsWSDGetResponse(correlation,"urn:uuid:aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa","VIEW71/Workgroup:WORKGROUP"),
  sampleWindowsWSDGetResponse(correlation,endpoint,"localhost/Workgroup:WORKGROUP"),
  sampleWindowsWSDGetResponse(correlation,endpoint,"?made-up?/Workgroup:WORKGROUP"),
  sampleWindowsWSDGetResponse(correlation,endpoint,"VIEW71"),
  []byte(strings.Repeat("Z",40000)),
 } {
  if value,ok:=parseWSDComputerMetadata(bad,correlation,endpoint);ok {t.Fatalf("invalid WSD metadata used as computer name %q",value)}
 }
 if got,ok:=parseWSDComputerMetadata(sampleWindowsWSDGetResponse(correlation,endpoint,"MEDIA-SERZHAN/Domain:HOME"),correlation,endpoint);!ok||got!="MEDIA-SERZHAN" {
  t.Fatalf("domain Windows computer name refused: %s %v",got,ok)
 }
}
func TestWSDMetadataURLRestrictedToVerifiedWindowsPort(t *testing.T) {
 good:=WSDAnnouncement{IPv4:"192.168.11.71",Endpoint:"urn:uuid:e2bf7703-4b57-4ee5-bedd-ef9676b731f9",Origin:"http://192.168.11.71:5357"}
 target,err:=safeWSDMetadataTarget(good)
 if err!=nil||target!="http://192.168.11.71:5357/e2bf7703-4b57-4ee5-bedd-ef9676b731f9" {t.Fatalf("valid WSD target missing: %s %v",target,err)}
 for _,origin:=range []string{
  "http://192.168.11.1:5357",
  "http://192.168.11.71:22",
  "http://192.168.11.71:80",
  "https://192.168.11.71:5357",
  "http://user:password@192.168.11.71:5357",
  "http://192.168.11.71:5357/private",
  "http://localhost:5357",
  "http://169.254.169.254:5357",
  "http://192.168.11.71:5357?secret=1",
 } {
  item:=good
  item.Origin=origin
  if _,err:=safeWSDMetadataTarget(item);err==nil{t.Fatalf("dangerous metadata URL allowed: %s",origin)}
 }
}
func TestWSDComputerNameNeverOverridesRealNamesOrNotes(t *testing.T) {
 db,err:=openDB(filepath.Join(t.TempDir(),"windows.sqlite3"))
 if err!=nil{t.Fatal(err)}
 defer db.Close()
 db.lanFreshness=420*time.Second
 at:=time.Now().UTC().Truncate(time.Second).Format(time.RFC3339)
 ip:="192.168.11.71"
 mac:="18:31:BF:2F:ED:37"
 item:=WSDAnnouncement{IPv4:ip,Endpoint:"urn:uuid:e2bf7703-4b57-4ee5-bedd-ef9676b731f9",Origin:"http://192.168.11.71:5357",Types:"wsdp:Device pub:Computer"}
 if err=db.importARPHosts([]LANHost{{MAC:mac,IPv4:ip}},at,"enp6s18","192.168.11.0/24");err!=nil{t.Fatal(err)}
 devices,_:=db.devices()
 id:=devices[0].ID
 if _,err=db.setNote(id,"my PC");err!=nil{t.Fatal(err)}
 if err=db.persistWSDComputerName(item,"VIEW71",at);err==nil{t.Fatal("unverified WSD endpoint accepted")}
 if _,_,err=db.importWSD([]WSDAnnouncement{item},at,1,"enp6s18");err!=nil{t.Fatal(err)}
 confirmed,err:=db.wsdConfirmedEndpoint(item,at)
 if err!=nil||!confirmed{t.Fatalf("valid WSD endpoint not confirmed: %v",err)}
 if err=db.persistWSDComputerName(item,"VIEW71",at);err!=nil{t.Fatal(err)}
 devices,_=db.devices()
 if len(devices)!=1||devices[0].ID!=id||devices[0].DisplayName!="VIEW71"||devices[0].Note!="my PC"||devices[0].MAC!=mac{
  t.Fatalf("WSD changed identity, notes or failed real name: %+v",devices)
 }
 snapshot,err:=db.snapshot()
 if err!=nil||len(snapshot.WSDEndpoints)!=1||snapshot.WSDEndpoints[0].ComputerName!="VIEW71"{
  t.Fatalf("WSD source detail missing: %+v %v",snapshot.WSDEndpoints,err)
 }
 if err=db.run("UPDATE devices SET display_name='Admin selected name' WHERE id=?",id);err!=nil{t.Fatal(err)}
 if err=db.persistWSDComputerName(item,"VIEW71",at);err!=nil{t.Fatal(err)}
 devices,_=db.devices()
 if devices[0].DisplayName!="Admin selected name"{t.Fatal("verified source overwrote existing descriptive label")}
 item.IPv4="192.168.11.49"
 if err=db.persistWSDComputerName(item,"FAKEHOST",at);err==nil{t.Fatal("name accepted after source/IP mismatch")}
}
func TestWSDComputerNameValidation(t *testing.T) {
 if !validWSDComputerName("VIEW71")||!validWSDComputerName("MEDIA-SERZHAN"){t.Fatal("actual verified names refused")}
 for _,x:=range []string{"","localhost","unknown","1-2-3","-host","host-","host/Workgroup:HOME","bad.name","44aa55bb66cc",strings.Repeat("a",70)} {
  if validWSDComputerName(x){t.Fatalf("unreliable computer label accepted: %s",x)}
 }
}
