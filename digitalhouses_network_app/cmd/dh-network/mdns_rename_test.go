package main

import (
	"path/filepath"
	"testing"
	"time"
)

func TestBonjourRenameKeepsSameDeviceAndHistory(t *testing.T) {
	path := filepath.Join(t.TempDir(), "network.sqlite3")
	db, err := openDB(path)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Truncate(time.Second)
	at := now.Format(time.RFC3339)
	mac := "02:11:22:33:44:66"
	ip := "192.168.11.6"
	if err = db.importARPHosts([]LANHost{{MAC: mac, IPv4: ip}}, at, "eth0", "192.168.11.0/24"); err != nil {
		t.Fatal(err)
	}
	first, err := db.devices()
	if err != nil || len(first) != 1 {
		t.Fatalf("first device: %+v %v", first, err)
	}
	id := first[0].ID
	if ok, err := db.setNote(id, "original note"); err != nil || !ok {
		t.Fatal(err)
	}
	oldHost := []MDNSHost{{IPv4: ip, Hostname: "pve-2.local."}}
	if matched, _, _, err := db.importMDNSHosts(oldHost, at, 2, "eth0"); err != nil || matched != 1 {
		t.Fatalf("first Bonjour: %v", err)
	}
	// A restart must retain source provenance and not reset the database.
	db.Close()
	db, err = openDB(path)
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	newHost := []MDNSHost{{IPv4: ip, Hostname: "pve-serzhan-home.local."}}
	if matched, _, _, err := db.importMDNSHosts(newHost, at, 2, "eth0"); err != nil || matched != 1 {
		t.Fatalf("renamed Bonjour: %v", err)
	}
	got, err := db.devices()
	if err != nil || len(got) != 1 {
		t.Fatalf("unexpected inventory: %+v %v", got, err)
	}
	if got[0].ID != id || got[0].MAC != mac || got[0].IPv4 != ip ||
		got[0].DisplayName != "pve-serzhan-home" || got[0].Hostname != "pve-serzhan-home.local" ||
		got[0].Note != "original note" || got[0].Presence != first[0].Presence ||
		got[0].FirstSeen != first[0].FirstSeen || got[0].LastSeen != first[0].LastSeen {
		t.Fatalf("rename lost identity, presence, timestamps or note: %+v", got[0])
	}
	hosts, _, _, err := db.mdnsSourceRecordsLocked()
	if err != nil || len(hosts) != 1 || hosts[0].DeviceID != id || hosts[0].Hostname != "pve-serzhan-home.local" {
		t.Fatalf("source record was lost: %+v %v", hosts, err)
	}
}

func TestBonjourRenamePreservesRouterWSDAndNonMatchingLabels(t *testing.T) {
	db, err := openDB(filepath.Join(t.TempDir(), "network.sqlite3"))
	if err != nil {
		t.Fatal(err)
	}
	defer db.Close()
	now := time.Now().UTC().Truncate(time.Second)
	at := now.Format(time.RFC3339)
	mac := "02:11:22:33:44:77"
	ip := "192.168.11.7"
	router := RouterTracker{EntityID: "device_tracker.pve", State: "home", Name: mac, Hostname: mac, MAC: mac, IPv4: ip}
	if err = db.importRouterTrackers([]RouterTracker{router}, at); err != nil {
		t.Fatal(err)
	}
	if err = db.importARPHosts([]LANHost{{MAC: mac, IPv4: ip}}, at, "eth0", "192.168.11.0/24"); err != nil {
		t.Fatal(err)
	}
	announce := func(name string) {
		t.Helper()
		if _, _, _, err := db.importMDNSHosts([]MDNSHost{{IPv4: ip, Hostname: name}}, at, 1, "eth0"); err != nil {
			t.Fatal(err)
		}
	}
	announce("pve-2.local.")
	devices, _ := db.devices()
	id := devices[0].ID
	if devices[0].DisplayName != "pve-2" {
		t.Fatalf("placeholder router prevented Bonjour: %+v", devices)
	}
	// Another router cycle with MAC fallback must not erase Bonjour.
	if err = db.importRouterTrackers([]RouterTracker{router}, at); err != nil {
		t.Fatal(err)
	}
	devices, _ = db.devices()
	if devices[0].DisplayName != "pve-2" {
		t.Fatalf("MAC fallback replaced name: %+v", devices)
	}
	// A router can claim the SAME name as Bonjour: provenance, not equality,
	// determines priority when the Bonjour hostname later changes.
	router.Name = "pve-2"
	router.Hostname = "router-host.example"
	if err = db.importRouterTrackers([]RouterTracker{router}, at); err != nil {
		t.Fatal(err)
	}
	announce("pve-serzhan-home.local.")
	devices, _ = db.devices()
	if devices[0].ID != id || devices[0].DisplayName != "pve-2" ||
		devices[0].Hostname != "router-host.example" {
		t.Fatalf("Bonjour overwrote authoritative router: %+v", devices)
	}
	// Confirmed WSD names and other meaningful legacy names also remain.
	if err = db.run("UPDATE devices SET display_name='WSD-NAME',display_name_source='wsd' WHERE id=?", id); err != nil {
		t.Fatal(err)
	}
	announce("another.local.")
	devices, _ = db.devices()
	if devices[0].DisplayName != "WSD-NAME" {
		t.Fatalf("Bonjour overwrote WSD: %+v", devices)
	}
	if err = db.run("UPDATE devices SET display_name='Saved label',display_name_source='' WHERE id=?", id); err != nil {
		t.Fatal(err)
	}
	announce("third.local.")
	devices, _ = db.devices()
	if devices[0].DisplayName != "Saved label" {
		t.Fatalf("Bonjour overwrote unknown source: %+v", devices)
	}
}

func TestBonjourRenameUpgradesLegacyNameWithoutProvenance(t *testing.T) {
	path := filepath.Join(t.TempDir(), "network.sqlite3")
	db, err := openDB(path)
	if err != nil {
		t.Fatal(err)
	}
	now := time.Now().UTC().Truncate(time.Second)
	at := now.Format(time.RFC3339)
	ip := "192.168.11.8"
	if err = db.importARPHosts([]LANHost{{MAC: "02:11:22:33:44:88", IPv4: ip}}, at, "eth0", "192.168.11.0/24"); err != nil {
		t.Fatal(err)
	}
	if _, _, _, err := db.importMDNSHosts([]MDNSHost{{IPv4: ip, Hostname: "pve-2.local."}}, at, 1, "eth0"); err != nil {
		t.Fatal(err)
	}
	if err = db.exec("ALTER TABLE devices DROP COLUMN display_name_source; ALTER TABLE devices DROP COLUMN hostname_source; UPDATE schema_version SET version=13;"); err != nil {
		t.Fatal(err)
	}
	db.Close()
	upgraded, err := openDB(path)
	if err != nil {
		t.Fatalf("non-destructive schema upgrade failed: %v", err)
	}
	defer upgraded.Close()
	if _, _, _, err = upgraded.importMDNSHosts([]MDNSHost{{IPv4: ip, Hostname: "pve-serzhan-home.local."}}, at, 1, "eth0"); err != nil {
		t.Fatal(err)
	}
	got, _ := upgraded.devices()
	if len(got) != 1 || got[0].DisplayName != "pve-serzhan-home" || got[0].Hostname != "pve-serzhan-home.local" {
		t.Fatalf("legacy Bonjour name did not migrate: %+v", got)
	}
}
