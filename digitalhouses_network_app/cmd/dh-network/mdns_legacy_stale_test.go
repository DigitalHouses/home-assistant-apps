package main

import (
	"path/filepath"
	"testing"
	"time"
)

// Simulate an older App which already updated its mDNS metadata while
// keeping the stale name, before source-provenance columns existed.
func TestLegacyBonjourAlreadyRefreshedSourceRow(t *testing.T) {
	path := filepath.Join(t.TempDir(), "network.sqlite3")
	db, err := openDB(path)
	if err != nil {
		t.Fatal(err)
	}
	at := time.Now().UTC().Truncate(time.Second).Format(time.RFC3339)
	ip := "192.168.11.230"
	mac := "02:11:22:33:44:99"
	if err = db.importARPHosts([]LANHost{{MAC: mac, IPv4: ip}}, at, "eth0", "192.168.11.0/24"); err != nil {
		t.Fatal(err)
	}
	announce := func(host string) {
		t.Helper()
		if _, _, _, err := db.importMDNSHosts([]MDNSHost{{IPv4: ip, Hostname: host}}, at, 1, "eth0"); err != nil {
			t.Fatal(err)
		}
	}
	announce("pve-2.local.")
	devices, _ := db.devices()
	if len(devices) != 1 {
		t.Fatalf("unexpected devices: %+v", devices)
	}
	id := devices[0].ID
	if ok, err := db.setNote(id, "important note"); err != nil || !ok {
		t.Fatal(err)
	}
	announce("pve-serzhan.local.")
	// Emulate prior version's stale inventory after its source row has advanced.
	if err = db.run("UPDATE devices SET display_name='pve-2',hostname='pve-2.local' WHERE id=?", id); err != nil {
		t.Fatal(err)
	}
	if err = db.exec("ALTER TABLE devices DROP COLUMN display_name_source; ALTER TABLE devices DROP COLUMN hostname_source; UPDATE schema_version SET version=13;"); err != nil {
		t.Fatal(err)
	}
	db.Close()
	db, err = openDB(path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	announce("pve-serzhan.local.")
	got, err := db.devices()
	if err != nil || len(got) != 1 {
		t.Fatalf("unexpected devices %+v %v", got, err)
	}
	if got[0].ID != id || got[0].MAC != mac || got[0].IPv4 != ip ||
		got[0].DisplayName != "pve-serzhan" || got[0].Hostname != "pve-serzhan.local" ||
		got[0].Note != "important note" {
		t.Fatalf("old already-overwritten mdns_hosts left stale label or lost identity: %+v", got)
	}
}

// When HA router identity exists, never guess an unknown legacy label came
// from Bonjour, even if the old mDNS source row has already advanced.
func TestLegacyBonjourDoesNotGuessRouterOwnedLabel(t *testing.T) {
	db, err := openDB(filepath.Join(t.TempDir(), "network.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	at := time.Now().UTC().Truncate(time.Second).Format(time.RFC3339)
	ip := "192.168.11.229"
	mac := "02:11:22:33:44:AA"
	router := RouterTracker{EntityID: "device_tracker.pve", State: "home", Name: "Router-owned", Hostname: "router.host", MAC: mac, IPv4: ip}
	if err = db.importRouterTrackers([]RouterTracker{router}, at); err != nil {
		t.Fatal(err)
	}
	if err = db.importARPHosts([]LANHost{{MAC: mac, IPv4: ip}}, at, "eth0", "192.168.11.0/24"); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := db.importMDNSHosts([]MDNSHost{{IPv4: ip, Hostname: "pve-serzhan.local."}}, at, 1, "eth0"); err != nil {
		t.Fatal(err)
	}
	// Force an old schema's lack of provenance after the mdns record is current.
	if err = db.run("UPDATE devices SET display_name_source='',hostname_source=''"); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := db.importMDNSHosts([]MDNSHost{{IPv4: ip, Hostname: "pve-serzhan.local."}}, at, 1, "eth0"); err != nil {
		t.Fatal(err)
	}
	got, _ := db.devices()
	if len(got) != 1 || got[0].DisplayName != "Router-owned" || got[0].Hostname != "router.host" {
		t.Fatalf("unknown legacy router name overwritten: %+v", got)
	}
}
