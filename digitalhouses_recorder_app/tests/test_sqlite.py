from __future__ import annotations

import json
import sqlite3
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "rootfs/app"))
from config import DatabaseConfig, load_config
from contracts import validate_static_db_metrics, validate_runtime_state
from db.sqlite import SQLiteAdapter
from discovery import build_discovery_payload
from runtime_settings import migrate_runtime_settings, save_runtime_setting, save_disk_usage_threshold, RuntimeSettingError
from storage import StorageCollector


class SQLiteTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "home-assistant_v2.db"
        self.writer = sqlite3.connect(self.path)
        self.addCleanup(self.writer.close)
        self.writer.execute("PRAGMA journal_mode=WAL")
        self.writer.executescript("""
            CREATE TABLE states_meta(metadata_id INTEGER PRIMARY KEY, entity_id TEXT);
            CREATE TABLE states(state_id INTEGER PRIMARY KEY, metadata_id INTEGER, last_updated_ts REAL);
            CREATE INDEX ix_states_ts ON states(last_updated_ts);
            CREATE INDEX ix_states_meta_ts ON states(metadata_id,last_updated_ts);
            INSERT INTO states_meta VALUES(1,'sensor.a'),(2,'sensor.b');
            INSERT INTO states(metadata_id,last_updated_ts) VALUES(1,10),(1,20),(1,30),(2,40);
        """)
        self.writer.commit()
        self.adapter = SQLiteAdapter(DatabaseConfig("sqlite", "", 0, self.path.name, "", ""), self.path)

    def test_wal_live_metrics_and_no_write(self):
        self.assertEqual(self.adapter.fast_metrics()["db_last_ts"], 40)
        medium = self.adapter.medium_metrics(25, 15, 45)
        self.assertEqual((medium["records_current_hour"], medium["records_today"]), (2, 3))
        self.assertGreater(medium["db_wal_size_bytes"], 0)
        self.assertEqual(self.adapter.slow_metrics(), {"db_start_ts": 10, "records_total": 4})
        self.assertEqual(self.adapter.top_entities(None, None, 2), [("sensor.a", 3, 75.0), ("sensor.b", 1, 25.0)])
        self.assertEqual(self.adapter.top_entities(25, 45, 1), [("sensor.a", 1, 50.0)])
        with self.assertRaises(sqlite3.OperationalError):
            self.adapter._rows("DELETE FROM states")
        self.writer.execute("INSERT INTO states(metadata_id,last_updated_ts) VALUES(2,50)")
        self.writer.commit()
        self.assertEqual(self.adapter.fast_metrics()["db_last_ts"], 50)
        self.assertEqual(self.writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0], 0)

    def test_missing_file_not_created(self):
        path = self.path.with_name("missing.db")
        self.adapter.path = path
        with self.assertRaises(sqlite3.OperationalError):
            self.adapter.fast_metrics()
        self.assertFalse(path.exists())

    def test_timeout_releases_reader(self):
        self.adapter.query_timeout = 0.015
        before = time.monotonic()
        with self.assertRaisesRegex(sqlite3.OperationalError, "interrupted"):
            self.adapter._one("WITH RECURSIVE n(x) AS (VALUES(1) UNION ALL SELECT x+1 FROM n WHERE x<100000000) SELECT sum(x) FROM n")
        self.assertLess(time.monotonic() - before, 1)
        self.assertEqual(self.writer.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()[0], 0)

    def test_readonly_directory_and_sidecars(self):
        files = [self.path, Path(str(self.path)+"-wal"), Path(str(self.path)+"-shm")]
        for file in files:
            file.chmod(0o444)
        self.path.parent.chmod(0o555)
        try:
            self.assertEqual(self.adapter.fast_metrics()["db_last_ts"], 40)
        finally:
            self.path.parent.chmod(0o755)
            for file in files:
                file.chmod(0o600)

    def test_sqlite_configuration_contract_and_disk(self):
        path = self.path.with_name("options.json")
        path.write_text(json.dumps({"database_type":"sqlite", "storage":{"source":"automatic"}}))
        with patch.dict("os.environ", {"TZ":"UTC"}):
            config = load_config(path)
        self.assertEqual(config.database.engine, "sqlite")
        self.assertEqual(config.storage.source, "local")
        metrics = StorageCollector(config.storage, self.adapter).collect()
        self.assertGreater(metrics["db_disk_total"], 0)
        self.assertNotIn("db_user", validate_static_db_metrics(self.adapter.static_metrics(), "sqlite"))
        validate_runtime_state({"version":"0.2.0","started_at":"2026-11-28T00:00:00+00:00","db_type":"sqlite"})
        discovery = build_discovery_payload("0.2.0", True, "sqlite")["components"]
        self.assertNotIn("db_user", discovery)
        self.assertIn("db_wal_size", discovery)
        self.assertIn("db_user", build_discovery_payload("0.2.0")["components"])

    def test_migration_preserves_user_values_and_threshold(self):
        path = self.path.with_name("runtime_settings.json")
        save_disk_usage_threshold(73, path)
        settings = migrate_runtime_settings({"publish_interval_minutes":7,"top_entities_limit":17,"recorder_stale_seconds":600}, path)
        self.assertEqual(settings, {"publish_interval_minutes":7,"top_entities_limit":17,"recorder_stale_seconds":600})
        save_runtime_setting("top_entities_limit", 20, path)
        save_disk_usage_threshold(75, path)
        self.assertEqual(migrate_runtime_settings({"top_entities_limit":17}, path)["top_entities_limit"], 20)
        self.assertEqual(json.loads(path.read_text())["disk_usage_threshold_percent"], 75)
        with self.assertRaises(RuntimeSettingError):
            save_runtime_setting("top_entities_limit", 0, path)
