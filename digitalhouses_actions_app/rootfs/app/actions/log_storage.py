"""Bounded SQLite backing store for the live journal. Never replay commands."""
import json
import sqlite3


class LogStorage:
    def __init__(self,path):
        self.db=sqlite3.connect(str(path),timeout=0.15,check_same_thread=False)
        try:
            self.db.execute("PRAGMA journal_mode=WAL")
            self.db.execute("PRAGMA synchronous=FULL")
            with self.db:
                self.db.execute("""CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY, created REAL NOT NULL, payload TEXT NOT NULL
                )""")
                self.db.execute("CREATE INDEX IF NOT EXISTS journal_created ON journal(created)")
        except BaseException:
            self.db.close()
            raise

    def load(self,cutoff,limit):
        with self.db:
            self.db.execute("DELETE FROM journal WHERE created < ?",(cutoff,))
            self.db.execute("DELETE FROM journal WHERE id NOT IN (SELECT id FROM journal ORDER BY id DESC LIMIT ?)",(limit,))
            return [(created,json.loads(payload)) for created,payload in
                    self.db.execute("SELECT created,payload FROM journal ORDER BY id")]

    def put(self,row,created):
        payload=json.dumps({k:v for k,v in row.items() if k!="_created"},ensure_ascii=False,
                           separators=(",",":"),allow_nan=False)
        with self.db:
            self.db.execute("INSERT INTO journal(id,created,payload) VALUES(?,?,?) "
                            "ON CONFLICT(id) DO UPDATE SET payload=excluded.payload",
                            (row["id"],created,payload))

    def remove(self,ids):
        with self.db:
            self.db.executemany("DELETE FROM journal WHERE id=?",((i,) for i in ids))

    def close(self):
        self.db.close()
