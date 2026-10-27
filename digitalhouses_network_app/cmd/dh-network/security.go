package main

import (
    "net"
)

// Since the App uses the host network, an unprotected random TCP Ingress port
// would also be reachable directly on the LAN. Only the Supervisor proxy peer
// is authorized. Do not trust X-Forwarded-For from clients.
func ingressPeerAllowed(remote string) bool {
    host,_,err:=net.SplitHostPort(remote)
    if err!=nil {return false}
    return host=="172.30.32.2"
}

func containsSource(sources []SourceInfo, name string) bool {
    for _,s:=range sources {if s.Name==name{return true}}
    return false
}
