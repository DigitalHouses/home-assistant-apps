package main

/*
#cgo pkg-config: sqlite3
#include <sqlite3.h>
*/
import "C"

import "strings"

// Existing databases predate explicit name provenance. Unknown old names
// remain unclaimed; only a match to a previously stored Bonjour hostname may
// be upgraded to mDNS when a later verified announcement changes that name.
func (db *DB) ensureDeviceNameSourceColumns() error {
	found := map[string]bool{}
	_, err := db.prepared("PRAGMA table_info(devices)", nil, func(s *C.sqlite3_stmt) {
		found[field(s, 1)] = true
	})
	if err != nil {
		return err
	}
	for _, column := range []string{"display_name_source", "hostname_source"} {
		if found[column] {
			continue
		}
		if err = db.run("ALTER TABLE devices ADD COLUMN " + column + " TEXT NOT NULL DEFAULT ''"); err != nil {
			return err
		}
	}
	return nil
}

// MACs and HA entity IDs are fallbacks, not authoritative router labels.
func meaningfulSourceLabel(label, mac string) bool {
	value := strings.TrimSpace(label)
	return value != "" && !strings.EqualFold(value, strings.TrimSpace(mac)) &&
		!strings.HasPrefix(strings.ToLower(value), "device_tracker.")
}

func sameNonemptyName(a, b string) bool {
	return a != "" && b != "" && strings.EqualFold(strings.TrimSpace(a), strings.TrimSpace(b))
}
