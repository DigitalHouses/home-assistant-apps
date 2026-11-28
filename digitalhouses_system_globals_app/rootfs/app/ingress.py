"""Small same-origin Ingress API; only Supervisor ingress proxy may connect."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import json
import os
from dh_journal.http import get as journal_get
import threading
from core import ContractError, GLOBAL, PRODUCT
from discovery import CTRL, OPS

HTML=Path(__file__).with_name("index.html")
ALLOWED={"internal/import",GLOBAL+"/set",PRODUCT+"/config/set",PRODUCT+"/profiles/set"}|{CTRL+o for o in OPS}


def serve(service,*,host,port,allowed):
    class Handler(BaseHTTPRequestHandler):
        def authorized(self):
            if self.client_address[0] not in allowed:
                self.send_error(403)
                return False
            return True

        def output(self,status,body,content_type="application/json",filename=None):
            if content_type=="application/json":
                body=json.dumps(body,ensure_ascii=False,allow_nan=False).encode()
            self.send_response(status)
            self.send_header("Content-Type",content_type+"; charset=utf-8")
            self.send_header("Cache-Control","no-store")
            self.send_header("X-Content-Type-Options","nosniff")
            self.send_header("Content-Security-Policy","default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; object-src 'none'; base-uri 'none'")
            if filename:
                self.send_header("Content-Disposition",'attachment; filename="'+filename+'"')
            self.send_header("Content-Length",str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            if not self.authorized():
                return
            if self.path in ("/","/index.html"):
                self.output(200,HTML.read_bytes(),"text/html")
            elif self.path=="/api/state":
                self.output(200,service.view())
            elif getattr(service,"journal",None) is not None:
                try:
                    result=journal_get(service.journal,self.path,os.environ.get("TZ") or service.view()["state"]["config"]["timezone"])
                    if result is None:
                        self.send_error(404)
                    else:
                        body,mime,filename=result
                        self.output(200,body,mime,filename)
                except (ValueError,OverflowError):
                    self.output(400,{"error":"Invalid journal request"})
            else:
                self.send_error(404)

        def do_POST(self):
            if not self.authorized():
                return
            if self.path=="/api/log/clear" and getattr(service,"journal",None) is not None:
                try:
                    if self.headers.get_content_type()!="application/json" or not 0<int(self.headers.get("Content-Length","0"))<=128:
                        raise ValueError()
                    self.connection.settimeout(5)
                    data=json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                    if not isinstance(data,dict) or set(data)!={"confirm"} or data["confirm"] is not True:
                        raise ValueError()
                    if service.journal.clear():
                        self.output(200,{"ok":True})
                    else:
                        self.output(409,{"error":"journal_clear_unavailable"})
                except (ValueError,OSError):
                    self.output(400,{"error":"Invalid clear request"})
                return
            if self.path!="/api/command":
                self.send_error(404)
                return
            if self.headers.get_content_type()!="application/json":
                self.send_error(415)
                return
            try:
                size=int(self.headers.get("Content-Length","0"))
                if not 0<size<=65536:
                    raise ContractError("Invalid request size")
                self.connection.settimeout(5)
                data=json.loads(self.rfile.read(size))
                if not isinstance(data,dict) or set(data)!={"topic","payload"} or not isinstance(data["topic"],str) or data["topic"] not in ALLOWED:
                    raise ContractError("Invalid command")
                result=service.submit(data["topic"],data["payload"])
                self.output(200,result)
            except (ValueError,TypeError,OSError) as exc:
                self.output(400,{"error":str(exc) if isinstance(exc,ContractError) else "Invalid request"})

        def log_message(self,*args):
            pass
    server=ThreadingHTTPServer((host,port),Handler)
    threading.Thread(target=server.serve_forever,daemon=True,name="ingress").start()
    return server
