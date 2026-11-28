import json
from contextlib import closing
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from dh_journal import Journal, LIMIT, MAX_RECORD_BYTES
from dh_journal.http import get

NOW = datetime(2026,11,28,12,15,32,123000,tzinfo=timezone.utc)
LOCALES = {"ru":{"example":"Значение {value}"},"en":{"example":"Value {value}"}}

class JournalTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path=Path(self.tmp.name)/"journal.sqlite3"
        self.j=self.open()
        self.addCleanup(self.j.close)

    def open(self, **kw):
        return Journal(self.path,product="digitalhouses_test_app",locales=LOCALES,clock=lambda:NOW,**kw)

    def test_restart_retention_and_cursor(self):
        self.j.start("0.1.0")
        for n in range(LIMIT+5):
            self.j.info("example",value=n)
        s=self.j.snapshot()
        self.assertEqual(s["count"],LIMIT)
        self.assertEqual(s["rows"][0]["params"]["value"],5)
        self.assertEqual(s["rows"][-1]["params"]["value"],LIMIT+4)
        self.j.close()
        j=self.open()
        self.addCleanup(j.close)
        j.start("0.1.1")
        d=j.snapshot(s["newest"],s["generation"])
        self.assertEqual(d["count"],LIMIT)
        self.assertEqual(len(d["rows"]),LIMIT)
        self.assertEqual(d["rows"][-1]["code"],"app_started")
        j.success("example",value=123)
        delta=j.snapshot(d["newest"],d["generation"])
        self.assertEqual(len(delta["rows"]),1)
        self.assertGreater(delta["oldest"],d["oldest"])
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT count(*) FROM events").fetchone()[0],LIMIT)

    def test_locale_export_and_safe_fields(self):
        self.j.start("1.2.3")
        self.j.info("example",value="a\nb",password="secret-value",nested={"token":"another-secret"})
        data,content_type,filename=get(self.j,"/api/log?lang=ru","Asia/Almaty")
        self.assertEqual(content_type,"application/json")
        self.assertIsNone(filename)
        self.assertEqual(data["rows"][1]["message"],"Значение a b")
        self.assertEqual(data["rows"][1]["local_time"],"2026-11-28 17:15:32.123")
        self.assertNotIn("secret-value",json.dumps(data))
        self.assertNotIn("another-secret",json.dumps(data))
        raw,mime,name=get(self.j,"/api/log/export?lang=en","Asia/Almaty")
        self.assertEqual(name,"digitalhouses_test_app_2026-11-28_17-15-32.log")
        self.assertEqual(mime,"text/plain")
        text=raw.decode()
        self.assertIn("APPLICATION START",text)
        self.assertIn("Value a b",text)
        self.assertEqual(len(text.splitlines()),2)
        self.assertIn("[REDACTED]",text)
        self.assertNotIn("secret-value",text)
        self.assertEqual(self.j.snapshot()["rows"][1]["code"],"example")

    def test_clear_generation_and_debug(self):
        self.j.debug("example",value=0)
        self.assertEqual(self.j.snapshot()["count"],0)
        self.j.info("example",value=1)
        old=self.j.snapshot()
        self.j.clear()
        new=self.j.snapshot(old["newest"],old["generation"])
        self.assertNotEqual(old["generation"],new["generation"])
        self.assertEqual(new["count"],1)
        self.assertEqual(new["rows"][0]["code"],"journal_cleared")
        self.j.close()
        j=self.open(debug=True)
        self.addCleanup(j.close)
        j.debug("example",value=2)
        self.assertEqual(j.snapshot()["rows"][-1]["level"],"debug")

    def test_ram_fallback_and_bounds(self):
        j=Journal(Path(self.tmp.name)/"missing"/"db",product="test")
        self.addCleanup(j.close)
        for n in range(LIMIT+2):
            j.info("example",value=n)
        s=j.snapshot()
        self.assertEqual(s["storage"],"ram")
        self.assertEqual(s["count"],LIMIT)
        self.assertEqual(s["rows"][0]["params"]["value"],2)
        get(j,"/api/log?lang=en","UTC")
        self.assertNotIn("message",j.snapshot()["rows"][0])
        self.assertFalse(j.clear())
        self.assertEqual(j.snapshot()["count"],LIMIT)

    def test_runtime_database_failure(self):
        self.j.info("example",value=1)
        self.j.db.close()
        self.j.info("example",value=2)
        self.assertEqual(self.j.snapshot()["storage"],"ram")
        self.assertEqual(self.j.snapshot()["rows"][-1]["params"]["value"],2)

    def test_api_assets_and_bad_cursor(self):
        self.assertIn(b'id="rows"',get(self.j,"/log","UTC")[0])
        self.assertEqual(get(self.j,"/journal.js","UTC")[1],"text/javascript")
        self.assertIsNone(get(self.j,"/api/state","UTC"))
        for url in ("/api/log?lang=bad","/api/log?after=-1","/api/log?after=abc"):
            with self.assertRaises(ValueError):
                get(self.j,url,"UTC")

    def test_malformed_events_isolated_and_bounded(self):
        class Bad:
            def __str__(self):
                raise RuntimeError("never stringify unknown values")
        self.assertFalse(self.j.record("bad","example"))
        self.assertFalse(self.j.info(None))
        self.assertFalse(self.j.info())
        self.assertEqual(self.j.snapshot()["rejected"],3)
        cycle=[]
        cycle.append(cycle)
        self.assertTrue(self.j.info("example",value=Bad(),cycle=cycle,huge=2**100000,
                                   unicode="\ud800",level="data"))
        self.assertEqual(self.j.snapshot()["rows"][-1]["params"]["value"],"[UNSUPPORTED]")
        self.assertTrue(self.j.info("example",value="keep",**{f"field{i}":"💡"*500 for i in range(30)}))
        row=self.j.snapshot()["rows"][-1]
        self.assertTrue(row["params"]["_truncated"])
        self.assertEqual(row["params"]["value"],"keep")
        self.assertLessEqual(len(json.dumps(row,ensure_ascii=False,separators=(",",":")).encode()),MAX_RECORD_BYTES)
        self.j.clock=lambda: (_ for _ in ()).throw(RuntimeError("clock broken"))
        self.assertFalse(self.j.info("example",value=5))
        self.assertEqual(self.j.snapshot()["rejected"],4)
        self.j.clock=lambda:NOW
        self.assertTrue(self.j.info("example",value=6))

    def test_clear_failure_never_acknowledged_and_restart(self):
        self.j.info("example",value="old")
        with closing(sqlite3.connect(self.path)) as blocker, blocker:
            blocker.execute("BEGIN IMMEDIATE")
            self.assertFalse(self.j.clear())
            self.assertEqual(self.j.snapshot()["storage"],"ram")
            self.assertFalse(self.j.snapshot()["can_clear"])
            self.assertFalse(self.j.clear())
            self.assertEqual(self.j.snapshot()["rows"][0]["params"]["value"],"old")
        self.j.close()
        j=self.open()
        self.addCleanup(j.close)
        self.assertEqual(j.snapshot()["rows"][0]["params"]["value"],"old")
        self.assertTrue(j.clear())
        j.close()
        reopened=self.open()
        self.addCleanup(reopened.close)
        self.assertEqual([r["code"] for r in reopened.snapshot()["rows"]],["journal_cleared"])

    def test_atomic_clear_marker_rollback(self):
        self.j.info("example",value="old")
        with self.j.db:
            self.j.db.execute("CREATE TRIGGER fail_clear BEFORE INSERT ON events WHEN NEW.code='journal_cleared' BEGIN SELECT RAISE(ABORT,'failure'); END")
        self.assertFalse(self.j.clear())
        self.assertEqual(self.j.snapshot()["rows"][0]["params"]["value"],"old")
        with closing(sqlite3.connect(self.path)) as db, db:
            self.assertEqual(db.execute("SELECT code FROM events").fetchall(),[("example",)])
