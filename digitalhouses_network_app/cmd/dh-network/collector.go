package main

import (
    "context"
    "encoding/json"
    "errors"
    "fmt"
    "io"
    "log"
    "net"
    "net/http"
    "net/netip"
    "os"
    "strings"
    "time"
)

const haStatesURL = "http://supervisor/core/api/states"

// RouterTracker is an observation from an existing Home Assistant router integration.
// An HA tracker is NOT a general LAN scan and not evidence of a host MAC when
// the integration does not actually expose a valid hardware address.
type RouterTracker struct {
    EntityID string
    State string
    Name string
    Hostname string
    MAC string
    IPv4 string
    IPv6 string
}

type haState struct {
    EntityID string                 `json:"entity_id"`
    State string                    `json:"state"`
    Attributes map[string]any       `json:"attributes"`
}

func attrString(attrs map[string]any, keys ...string) string {
    for _, key := range keys {
        if value, ok := attrs[key].(string); ok {
            value = strings.TrimSpace(value)
            if value != "" { return value }
        }
    }
    return ""
}

func normalizedMAC(raw string) string {
    mac, err := net.ParseMAC(strings.TrimSpace(raw))
    if err != nil || len(mac) != 6 || (mac[0]&1) != 0 { return "" }
    allZero := true
    for _, b := range mac { if b != 0 { allZero = false; break } }
    if allZero { return "" }
    return strings.ToUpper(mac.String())
}

func normalizedIP(raw string, v6 bool) string {
    addr, err := netip.ParseAddr(strings.TrimSpace(raw))
    if err != nil || addr.Zone() != "" || addr.IsUnspecified() || addr.IsMulticast() { return "" }
    if v6 && addr.Is6() && !addr.Is4In6() { return addr.String() }
    if !v6 && addr.Is4() { return addr.String() }
    return ""
}

func normalizeRouterTrackers(states []haState) []RouterTracker {
    trackers := make([]RouterTracker, 0)
    for _, state := range states {
        if !strings.HasPrefix(state.EntityID, "device_tracker.") ||
            attrString(state.Attributes, "source_type") != "router" { continue }
        status := strings.TrimSpace(state.State)
        if status != "home" && status != "not_home" &&
            status != "unknown" && status != "unavailable" { continue }
        ip := attrString(state.Attributes,"ip","ip_address","ipv4")
        ip6 := attrString(state.Attributes,"ipv6","ip6")
        tracker := RouterTracker{
            EntityID: state.EntityID, State: status,
            Name: attrString(state.Attributes,"friendly_name"),
            Hostname: attrString(state.Attributes,"hostname","host_name"),
            MAC: normalizedMAC(attrString(state.Attributes,"mac","mac_address","macaddr")),
            IPv4: normalizedIP(ip,false),
            IPv6: normalizedIP(ip6,true),
        }
        if tracker.IPv6 == "" { tracker.IPv6 = normalizedIP(ip,true) }
        if tracker.IPv4 == "" { tracker.IPv4 = normalizedIP(ip6,false) }
        if tracker.Name == "" { tracker.Name = state.EntityID }
        trackers = append(trackers,tracker)
    }
    return trackers
}

func fetchRouterTrackers(ctx context.Context, client *http.Client, token, url string) ([]RouterTracker, error) {
    if strings.TrimSpace(token) == "" { return nil, errors.New("SUPERVISOR_TOKEN is missing") }
    request, err := http.NewRequestWithContext(ctx, http.MethodGet, url, nil)
    if err != nil { return nil, err }
    request.Header.Set("Authorization","Bearer "+token)
    request.Header.Set("Accept","application/json")
    resp, err := client.Do(request)
    if err != nil { return nil,fmt.Errorf("Home Assistant request failed: %w",err) }
    defer resp.Body.Close()
    if resp.StatusCode != http.StatusOK {
        return nil,fmt.Errorf("Home Assistant API returned HTTP %d",resp.StatusCode)
    }
    var states []haState
    decoder := json.NewDecoder(io.LimitReader(resp.Body, 20<<20))
    if err := decoder.Decode(&states); err != nil {
        return nil, fmt.Errorf("invalid Home Assistant states JSON: %w",err)
    }
    if states == nil { return nil,errors.New("Home Assistant states must be a JSON array") }
    var extra any
    if err := decoder.Decode(&extra); err != io.EOF {
        return nil,errors.New("Home Assistant API returned extra or oversized data")
    }
    return normalizeRouterTrackers(states),nil
}

func (s *Service) pollRouterSource() {
    token := os.Getenv("SUPERVISOR_TOKEN")
    ctx,cancel := context.WithTimeout(context.Background(),15*time.Second)
    defer cancel()
    trackers,err := fetchRouterTrackers(ctx,&http.Client{Timeout:15*time.Second},token,haStatesURL)
    now := time.Now().UTC().Format(time.RFC3339)
    if err == nil {
        err = s.db.importRouterTrackers(trackers,now)
    }
    if err != nil {
        if recordErr:=s.db.recordSourceFailure(now,err.Error());recordErr!=nil {
            log.Printf("HA source error and SQLite status failure: %v",recordErr)
        }
        log.Printf("HA router tracker source unavailable: %v",err)
        return
    }
    log.Printf("HA router tracker import complete: %d tracker entities",len(trackers))
}

func (s *Service) runRouterPolling(interval time.Duration) {
    s.pollRouterSource()
    ticker := time.NewTicker(interval)
    defer ticker.Stop()
    for range ticker.C { s.pollRouterSource() }
}
