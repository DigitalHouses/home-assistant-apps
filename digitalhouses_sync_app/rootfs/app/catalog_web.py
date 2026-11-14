"""Admin-only, GET-only Ingress catalog of MQTT product source claims."""
from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs

from discovery_contract import ProductSources
from inventory import Inventory

STYLE = """body{background:#121619;color:#e5e9eb;font:15px system-ui,sans-serif;
margin:0;line-height:1.5}a{color:#8dcaf1}header{padding:22px;border-bottom:1px solid #343d43}
h1{font-size:23px;margin:0}main{margin:30px auto;max-width:1040px;padding:0 22px}
section{border:1px solid #343d43;border-radius:10px;background:#1c2225;
padding:18px;margin:18px 0}table{width:100%;border-collapse:collapse}
th,td{text-align:left;padding:12px 8px;border-bottom:1px solid #30383d;
vertical-align:top;overflow-wrap:anywhere}th,small{color:#a8b3ba}
code{font:12px ui-monospace,monospace;color:#bddbf1}
.ok{color:#87d59c}.muted{color:#b9c8d1}
"""

def _h(value: object) -> str:
    return html.escape(str(value), quote=True)

def make_server(sources: ProductSources, inventory: Inventory, *, version: str = 'development', port: int = 8099, inspect=None):
    class Handler(BaseHTTPRequestHandler):
        server_version = "DHSync/" + version

        def _send(self, code: int, content: str) -> None:
            body = content.encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header(
                "Content-Security-Policy",
                "default-src 'none'; style-src 'unsafe-inline'; "
                "base-uri 'none'; form-action 'none'; frame-ancestors 'self'",
            )
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/health":
                self._send(200, "<html><body>ok</body></html>")
                return
            if path not in ("/", ""):
                self._send(404, "<html><body>Not found</body></html>")
                return
            records = sources.snapshot()
            rows = ""
            for identity, item in records.items():
                online = inventory.known.get(identity, "unknown")
                label = {
                    "online": "Online", "offline": "Offline", "unknown": "Unknown",
                }.get(online, "Unknown")
                rows += (
                    "<tr><td><b>" + _h(item["product_id"]) +
                    "</b><br><small>" + _h(identity.split("/", 1)[1]) +
                    "</small></td><td><code>" + _h(item["version"]) +
                    "</code><br><small>" + _h(item["type"]) +
                    "</small></td><td><span class='" +
                    ("ok" if online == "online" else "muted") + "'>" +
                    _h(label) + "</span></td><td><code>" +
                    _h(item["repository"]) + "</code><br><small>" +
                    _h(item["product_path"]) + "</small></td></tr>"
                )
            if not records:
                rows = ("<tr><td colspan='4' class='muted'>"
                        "MQTT metadata пока не обнаружены. Ожидаются retained /sync."
                        "</td></tr>")
            # An explicit GET is required to query GitHub. The default page
            # only reads local MQTT inventory. Neither route can write HA YAML.
            preview_html = (
                "<section><h2>Канонические dashboards · RU</h2>"
                "<p>GitHub-файлы обнаруживаются в dashboards/ru/ из "
                "закреплённых commit SHA, а не перечисляются в MQTT.</p>"
                "<p><a href='?resources=1'>Проверить GitHub-ресурсы</a></p>"
            )
            if inspect is not None and parse_qs(urlsplit(self.path).query).get("resources") == ["1"]:
                preview_html += (
                    "<table><thead><tr><th>Продукт / Git SHA</th>"
                    "<th>Dashboard / файл</th><th>Ревизия / совместимость</th>"
                    "<th>Результат</th></tr></thead><tbody>"
                )
                try:
                    for product in inspect(records):
                        header = (
                            _h(product["product"]) + "<br><code>" +
                            _h(product["commit"][:12]) + "</code><br><small>" +
                            _h(product["label"]) + "</small>"
                        )
                        if product["error"]:
                            preview_html += (
                                "<tr><td>" + header + "</td><td>—</td>"
                                "<td>—</td><td>" + _h(product["error"]) + "</td></tr>"
                            )
                        for view in product["views"]:
                            preview_html += (
                                "<tr><td>" + header + "</td><td>" +
                                _h(view["title"]) + "<br><code>" +
                                _h(view["file"]) + "</code><br><small>" +
                                _h(view["path"]) + "</small></td><td><code>" +
                                _h(view["revision"]) + "</code><br><small>" +
                                _h(view["constraint"]) + "</small></td><td>" +
                                _h(view["status"]) + "</td></tr>"
                            )
                except Exception:
                    preview_html += (
                        "<tr><td colspan='4'>Не удалось проверить GitHub. "
                        "Установка недоступна.</td></tr>"
                    )
                preview_html += "</tbody></table>"
            preview_html += (
                "<p class='muted'>Предпросмотр не сравнивает локальные YAML, "
                "не устанавливает ресурсы и не подтверждает готовность Apply. "
                "Требуется отдельная проверка установленного HA и согласование "
                "совместимости с версиями агентов.</p></section>"
            )
            page = (
                "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>DigitalHouses Sync</title><style>" + STYLE +
                "</style></head><body><header><h1>DigitalHouses Sync · v" + _h(version) + "</h1>"
                "<small>Каталог MQTT продуктов · только чтение</small></header><main>"
                "<section><h2>Обнаруженные агенты и приложения (" +
                str(len(records)) + ")</h2><table><thead><tr>"
                "<th>Продукт / Instance</th><th>Версия</th><th>Доступность</th>"
                "<th>Репозиторий / Каталог</th></tr></thead><tbody>" +
                rows + "</tbody></table></section>" + preview_html + "<section>"
                "<p>Принимаются только репозитории GitHub организации "
                "<b>DigitalHouses</b>. Метаданные получены из MQTT и сами по "
                "себе не разрешают установку.</p>"
                "<p class='muted'>В этой версии нет обновления YAML, доступа "
                "к конфигурации Home Assistant, запуска агентов или "
                "автоматического удаления продуктов.</p></section></main>"
                "</body></html>"
            )
            self._send(200, page)

        def do_POST(self) -> None:
            self._send(405, "<html><body>Read-only catalog</body></html>")

        def log_message(self, fmt, *args) -> None:
            # Do not expose Ingress URLs, credentials or client headers.
            pass

    return ThreadingHTTPServer(("0.0.0.0", port), Handler)
