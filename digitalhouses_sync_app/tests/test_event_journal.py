from contextlib import closing
import json
import sqlite3
import tempfile
import threading
import unittest
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import HTTPError

from event_journal import EventJournal
from catalog_web import make_server
from discovery_contract import ProductSources


class JournalTests(unittest.TestCase):
    def test_migration_and_clear(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "journal.db"
            with closing(sqlite3.connect(path)) as db, db:
                db.execute("CREATE TABLE events (id INTEGER PRIMARY KEY, ts INTEGER, product TEXT, event TEXT, level TEXT, detail TEXT)")
                db.executemany("INSERT INTO events VALUES (?,?,?,?,?,?)", [
                    (1, 1700000000, "digitalhouses_sync_app", "app_started", "info", "0.6.5"),
                    (2, 1700000001, "app", "package_updated", "info", "packages/test.yaml"),
                    (3, 1700000002, "app", "package_error", "error", "secret=abc"),
                ])
            j = EventJournal(path)
            rows = j.backend.snapshot()["rows"]
            self.assertEqual(len(rows), 3)
            self.assertEqual(rows[0]["ts"], "2023-11-14T22:13:20.000+00:00")
            self.assertIn("0.6.5", j.backend.message(rows[0], "ru"))
            self.assertIn("packages/test.yaml", j.backend.message(rows[1], "en"))
            self.assertNotIn("secret=abc", str(rows))
            j.backend.start("0.6.6")
            j.backend.close()
            j = EventJournal(path)
            self.assertEqual(len(j.backend.snapshot()["rows"]), 4)
            self.assertTrue(j.backend.clear())
            self.assertEqual([r["code"] for r in j.backend.snapshot()["rows"]], ["journal_cleared"])
            j.backend.close()

    def test_retention_and_debug(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = EventJournal(Path(tmp) / "journal.db")
            self.assertFalse(j.record("sync_started", "automatic", level="debug"))
            for i in range(3005):
                j.record("package_updated", f"packages/{i}.yaml")
            rows = j.backend.snapshot()["rows"]
            self.assertEqual(len(rows), 3000)
            self.assertIn("packages/5.yaml", j.backend.message(rows[0], "en"))
            j.backend.close()

    def test_unavailable(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = EventJournal(Path(tmp) / "missing" / "journal.db")
            self.assertFalse(j.record("sync_started"))
            self.assertEqual(j.backend.snapshot()["storage"], "unavailable")

    def test_ingress(self):
        with tempfile.TemporaryDirectory() as tmp:
            j = EventJournal(Path(tmp) / "journal.db")
            j.backend.start("0.6.6")
            server = make_server(ProductSources(), port=0, auto_status=lambda: {}, journal=j)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = f"http://127.0.0.1:{server.server_port}"
            try:
                self.assertIn(b"LOG", urlopen(base + "/log").read())
                self.assertIn(b"./log", urlopen(base + "/").read())
                self.assertIn(b"function", urlopen(base + "/journal.js").read())
                data = json.load(urlopen(base + "/api/log?lang=en"))
                self.assertEqual(data["count"], 1)
                self.assertIn("APPLICATION START", data["rows"][0]["message"])
                export = urlopen(base + "/api/log/export?lang=en")
                self.assertIn(".log", export.headers["Content-Disposition"])
                self.assertIn(b"APPLICATION START", export.read())
                with self.assertRaises(HTTPError) as err:
                    urlopen(Request(base + "/api/log/clear", data=b'{"confirm":false}', headers={"Content-Type":"application/json"}))
                self.assertEqual(err.exception.code, 400)
                result = json.load(urlopen(Request(base + "/api/log/clear", data=b'{"confirm":true}', headers={"Content-Type":"application/json"})))
                self.assertTrue(result["ok"])
                self.assertEqual(j.backend.snapshot()["rows"][0]["code"], "journal_cleared")
            finally:
                server.shutdown()
                server.server_close()
                thread.join()
                j.backend.close()
