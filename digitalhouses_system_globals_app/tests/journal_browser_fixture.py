"""Isolated real Ingress fixture for the optional Chromium acceptance test."""
import tempfile
from pathlib import Path
import sys

from dh_journal import Journal, LIMIT
from journal_events import LOCALES, PRODUCT_NAME, VALUE_LOCALES, ICONS
from ingress import serve

def main():
    with tempfile.TemporaryDirectory() as tmp:
        journal=Journal(Path(tmp)/"journal.sqlite3",product="digitalhouses_system_globals_app",
                        product_name=PRODUCT_NAME,locales=LOCALES,value_locales=VALUE_LOCALES,icons=ICONS)
        journal.start("0.1.8")
        for i in range(1,LIMIT):
            journal.record("warning" if i%10==0 else "info","gate_not_ready",
                           gate=f"TEST-{i:04d}",reason="awaiting_probe",
                           **{f"detail_{n}":"💡"*500 for n in range(5)})
        class Service:
            def __init__(self,journal):
                self.journal=journal
            def view(self):
                return {"state":{"config":{"timezone":"Asia/Almaty"}}}
        server=serve(Service(journal),host="127.0.0.1",port=0,allowed={"127.0.0.1"})
        print(server.server_address[1],flush=True)
        try:
            for line in sys.stdin:
                cmd=line.strip()
                if cmd=="append":
                    journal.success("gate_ready",gate="NEW-ROW")
                elif cmd=="fail":
                    with journal.db:
                        journal.db.execute("CREATE TRIGGER fail_insert BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT,'failure'); END")
                    journal.warning("gate_not_ready",gate="RAM-ROW",reason="awaiting_probe")
                elif cmd=="exit":
                    break
                print("ok",flush=True)
        finally:
            server.shutdown()
            server.server_close()
            journal.close()

if __name__=="__main__":
    main()
