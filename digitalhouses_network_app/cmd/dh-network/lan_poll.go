package main

import (
    "context"
    "log"
    "time"
)

// ARP discovery is independent from Home Assistant and does not use Nmap.
// Failed scans preserve the device registry and its last-positive evidence.
func (s *Service) pollLAN() {
    generation:=s.currentScanGeneration()
    at:=time.Now().UTC().Format(time.RFC3339)
    plan,err:=localLANPlan()
    if err!=nil {
        s.withCurrentGeneration(generation,func(){s.reportLANError(at,err)})
        return
    }
    if !s.withCurrentGeneration(generation,func(){s.recordLocalInterface(plan)}) {return}
    ctx,cancel:=context.WithTimeout(context.Background(),50*time.Second)
    defer cancel()
    hosts,err:=scanARP(ctx,plan,18)
    if err!=nil {
        s.withCurrentGeneration(generation,func(){s.reportLANError(at,err)})
        return
    }
    s.withCurrentGeneration(generation,func(){
        now:=time.Now().UTC().Format(time.RFC3339)
        if err:=s.db.importARPHosts(hosts,now,plan.iface.Name,plan.network.String());err!=nil {
            s.reportLANError(now,err)
            return
        }
        log.Printf("LAN ARP scan: %d observed IPv4 hosts on %s %s",len(hosts),plan.iface.Name,plan.network)
        if finished,baselineErr:=s.db.finalizeDiscoveryBaseline();baselineErr!=nil {log.Printf("Network census finalization failed: %v",baselineErr)} else if finished {log.Print("Network initial census complete; new machine events enabled")}
    })
}

func (s *Service) reportLANError(now string,err error) {
    log.Printf("LAN ARP unavailable: %v",err)
    if dbErr:=s.db.recordLANFailure(now,err);dbErr!=nil {
        log.Printf("LAN ARP source status write failed: %v",dbErr)
    }
}

func (s *Service) runLANPolling(interval time.Duration) {
    s.pollLAN()
    ticker:=time.NewTicker(interval)
    defer ticker.Stop()
    for range ticker.C {s.pollLAN()}
}
