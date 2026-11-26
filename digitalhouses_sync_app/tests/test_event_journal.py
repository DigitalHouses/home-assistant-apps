import sqlite3
import time
from event_journal import EventJournal, DEFAULTS
from journal_web import section


def test_persistence_filters_and_clear(tmp_path):
    path = tmp_path / "journal.db"
    j = EventJournal(path)
    assert j.ready and j.settings() == DEFAULTS
    j.record("package_updated", "<script>", product="app")
    j.record("sync_finished")
    j = EventJournal(path)
    assert len(j.rows()) == 2
    assert j.rows("app", "package_updated")[0]["detail"] == "<script>"
    assert "&lt;script&gt;" in section(j, "token", {})
    assert "<script>" not in section(j, "token", {})
    j.configure(1, 100, 10)
    assert EventJournal(path).settings() == (1, 100, 10)
    j.clear()
    assert [r["event"] for r in j.rows()] == ["journal_cleared"]


def test_retention(tmp_path):
    j = EventJournal(tmp_path / "journal.db")
    j.configure(1, 100, 10)
    with sqlite3.connect(j.path) as db:
        db.execute("UPDATE events SET ts=?", (int(time.time()) - 2 * 86400,))
    assert j.rows() == []
    for i in range(105):
        j.record("test", str(i))
    assert len(j.rows()) == 10
    assert len(j.rows(all_rows=True)) == 100
    assert j.rows()[0]["detail"] == "104"


def test_unavailable_is_fail_open(tmp_path):
    j = EventJournal(tmp_path / "missing" / "journal.db")
    assert not j.ready
    j.record("sync_started")
    assert "SQLite" in section(j, "token", {})
