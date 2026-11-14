"""Small admin-only Ingress UI for deliberate DH Sync v0.1.0 changes."""
from __future__ import annotations

import hmac
import html
import json
import secrets
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from sync_engine import SyncEngine, SyncError


STYLE = """body{font:15px system-ui,-apple-system,sans-serif;background:#121619;color:#e5e9eb;
margin:0;line-height:1.5} main{max-width:1050px;margin:30px auto;padding:0 22px}
header{border-bottom:1px solid #30383d;padding:22px} h1{margin:0;font-size:23px}
small,.muted{color:#a8b3ba}.desc{margin:6px 0 20px}
table{border-collapse:collapse;width:100%;margin:16px 0}
th,td{text-align:left;border-bottom:1px solid #30383d;padding:11px 9px;vertical-align:top}
th{color:#99aab4}code{font:12px ui-monospace,monospace;overflow-wrap:anywhere;color:#bddbf1}
.ok{color:#8bd58e}.bad{color:#ffa2a2}.changed{color:#ffdd80}
button{border:0;padding:11px 18px;border-radius:7px;background:#2694c6;color:white;
font:inherit;cursor:pointer;margin-right:12px}button:disabled{background:#454d52;cursor:not-allowed}
button.danger{background:#a34c47}form{margin:18px 0}
section{background:#1c2225;border:1px solid #343d43;border-radius:8px;padding:18px;margin:16px 0}
input[type=checkbox]{margin-right:8px}.note{color:#b9c8d1}
"""


def _h(value) -> str:
    return html.escape(str(value), quote=True)


def make_server(engine: SyncEngine, *, allow_changes: bool, port: int = 8099):
    csrf = secrets.token_urlsafe(32)

    class Handler(BaseHTTPRequestHandler):
        server_version = "DHSync/0.1"

        def _write(self, body: str, code: int = 200) -> None:
            raw = body.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy",
                             "default-src 'none'; style-src 'unsafe-inline'; "
                             "form-action 'self'; base-uri 'none'; frame-ancestors 'self'")
            self.end_headers()
            self.wfile.write(raw)

        def do_GET(self):
            path = urlparse(self.path).path
            if path == "/health":
                self._write("<html><body>ok</body></html>")
                return
            if path not in ("/", ""):
                self._write("<html><body>Not found</body></html>", 404)
                return
            self._page()

        def do_POST(self):
            if urlparse(self.path).path not in ("/", ""):
                self._write("<html><body>Not found</body></html>", 404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size < 1 or size > 4096:
                    raise SyncError("Invalid form length")
                values = parse_qs(self.rfile.read(size).decode("utf-8", "strict"))
                def field(key):
                    return values.get(key, [""])[0]
                if not hmac.compare_digest(field("csrf"), csrf):
                    raise SyncError("Invalid operation confirmation token")
                if not allow_changes:
                    raise SyncError("Changes disabled in App settings (allow_changes: false)")
                if field("confirm") != "yes":
                    raise SyncError("The confirmation checkbox is required")
                action = field("action")
                if action == "apply":
                    result = engine.apply(field("fingerprint"), approved=True)
                elif action == "rollback":
                    result = engine.rollback(approved=True)
                else:
                    raise SyncError("Unknown operation")
                self._page(message="Готово: " + json.dumps(result, ensure_ascii=False))
            except (UnicodeDecodeError, ValueError, SyncError) as exc:
                self._page(message="Операция не выполнена: " + str(exc), error=True)

        def _page(self, message: str = "", error: bool = False):
            try:
                plan = engine.plan()
                result_error = ""
            except (SyncError, OSError, ValueError) as exc:
                plan = None
                result_error = str(exc)
            try:
                recent = engine.last_transaction()
            except (SyncError, OSError) as exc:
                recent = None
                result_error += " Journal error: " + str(exc)
            rows = ""
            if plan:
                for item in plan["items"]:
                    action = item["action"]
                    label = {
                        "unchanged": "Актуально",
                        "replace": "Требуется обновить",
                        "create": "Новый view",
                        "conflict": "Локальные изменения — стоп",
                        "incompatible": "Версия не подтверждена — стоп",
                    }.get(action, action)
                    color = ("ok" if action == "unchanged"
                             else "changed" if action in ("replace", "create") else "bad")
                    rows += (
                        "<tr><td>" + _h(item["title"]) + "<br><small>" + _h(item["path"]) +
                        "</small></td><td><code>" + _h(item["installed_agent"]) +
                        "</code><br><small>ожидается " + _h(item["required_agent"]) +
                        "</small></td><td class='" + color + "'>" + _h(label) +
                        "</td><td><code>" + _h(item["source_commit"][:12]) +
                        "</code></td></tr>"
                    )
            state = "Разрешено вручную" if allow_changes else "Только просмотр"
            count = str(plan["changes"]) if plan else "?"
            plan_warn = (
                "Нельзя применять: требуется исправить конфликт или совместимость."
                if plan and plan["blocked"] else
                "План подготовлен: " + count + " файлов требуют изменений."
                if plan else "Нет проверенного плана: " + result_error
            )
            disabled = "" if (allow_changes and plan and not plan["blocked"] and plan["changes"]) else "disabled"
            apply_form = (
                "<form method='post'><input type='hidden' name='csrf' value='" + _h(csrf) +
                "'><input type='hidden' name='fingerprint' value='" + _h(plan["fingerprint"] if plan else "") +
                "'><label><input type='checkbox' name='confirm' value='yes' required>"
                "Подтверждаю обновление только перечисленных YAML views</label><p>"
                "<button type='submit' name='action' value='apply' " + disabled +
                ">Применить изменения</button></p></form>"
            )
            rollback_form = ""
            if recent:
                rollback_form = (
                    "<p>Последняя транзакция: <code>" + _h(recent["id"]) +
                    "</code>; статус: " + _h(recent["phase"]) + "</p>"
                )
                if recent["phase"] in ("committed", "applying", "recovery_required"):
                    rollback_form += (
                        "<form method='post'><input type='hidden' name='csrf' value='" + _h(csrf) +
                        "'><label><input type='checkbox' name='confirm' value='yes' required>"
                        "Подтверждаю откат файлов из этой транзакции</label><p>"
                        "<button class='danger' type='submit' name='action' value='rollback' " +
                        ("" if allow_changes else "disabled") + ">Откатить</button></p></form>"
                    )
            notification = (
                "<section class='" + ("bad" if error else "ok") + "'>" + _h(message) + "</section>"
                if message else ""
            )
            body = (
                "<!DOCTYPE html><html lang='ru'><head><meta charset='UTF-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>DigitalHouses Sync</title><style>" + STYLE + "</style></head>"
                "<body><header><h1>DigitalHouses Sync · v0.1.0</h1>"
                "<small>Пилот CORE: управление YAML, без изменения агентов и Recorder</small></header>"
                "<main>" + notification + "<section><b>Режим: " + _h(state) + "</b>"
                "<p class='desc'>GitHub → проверка YAML и версий → резервная копия → обновление"
                " → проверка Home Assistant. Никаких автоматических записей.</p>"
                "<p class='" + ("bad" if not plan or plan["blocked"] else "note") + "'>"
                + _h(plan_warn) + "</p></section>"
                "<section><h2>Канонические вкладки</h2><table>"
                "<thead><tr><th>View</th><th>Agent</th><th>Состояние</th><th>Git commit</th></tr></thead>"
                "<tbody>" + rows + "</tbody></table>"
                "<small>Поддержка v0.1: Proxmox, UPS, Plex · только RU · packages не изменяются</small>"
                + apply_form + "</section><section><h2>Последняя операция и откат</h2>"
                + (rollback_form or "<p class='muted'>Пока нет транзакций.</p>") +
                "</section><p class='muted'>Существующие файлы с неизвестными локальными "
                "изменениями никогда не перезаписываются. Storage dashboards не изменяются."
                " Backup сохраняется в /data.</p></main></body></html>"
            )
            self._write(body)

        def log_message(self, fmt, *args):
            # Avoid echoing ingress headers, tokens, user-specific URLs and secrets.
            pass

    return ThreadingHTTPServer(("0.0.0.0", port), Handler)
