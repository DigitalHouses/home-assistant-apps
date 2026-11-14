"""Admin-only Ingress catalog with explicit plan / Apply / Rollback controls."""
from __future__ import annotations

import html
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs, quote

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
table.views{table-layout:fixed}table.views th:nth-child(1){width:23%}
table.views th:nth-child(2){width:22%}table.views th:nth-child(3){width:22%}
table.views th:nth-child(4){width:33%}
table.views td{overflow-wrap:anywhere;word-break:normal}
pre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:370px;overflow:auto;
background:#111619;padding:12px;border:1px solid #343d43;border-radius:6px;
font:12px ui-monospace,monospace}
details{margin-top:8px}summary{cursor:pointer;color:#91caed}
.warn{color:#ffcf86}
"""

def _h(value: object) -> str:
    return html.escape(str(value), quote=True)

def make_server(sources: ProductSources, inventory: Inventory, *, version: str = 'development', port: int = 8099, inspect=None, audit=None, apply_manager=None):
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
                "base-uri 'none'; form-action 'self'; frame-ancestors 'self'",
            )
            self.end_headers()
            self.wfile.write(body)


        def _action_shell(self, title: str, content: str, code: int = 200) -> None:
            self._send(code, (
                "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>DH Sync</title><style>" + STYLE + "</style></head><body>"
                "<main><h1>" + _h(title) + "</h1>" + content +
                "<p><a href='./?local=1'>Вернуться к сравнению</a></p>"
                "</main></body></html>"
            ))

        def _plan_page(self, identity: str) -> None:
            if apply_manager is None:
                self._action_shell("Apply недоступен", "Режим только чтение", 403)
                return
            try:
                plan = apply_manager.prepare(sources.snapshot(), identity)
            except Exception as exc:
                self._action_shell("План не подготовлен",
                                   "<p class='warn'>" + _h(exc) + "</p>", 409)
                return
            content = (
                "<p>Продукт: <b>" + _h(plan["product"]) + "</b></p>"
                "<p>Репозиторий: <code>" + _h(plan["repository"]) + "</code></p>"
                "<p>Git commit: <code>" + _h(plan["commit"]) + "</code></p>"
                "<p>Этот план действует 10 минут, применяется однократно. "
                "Проверки версий продуктов отсутствуют.</p>"
                "<table><thead><tr><th>Действие</th><th>Файл / View</th>"
                "<th>SHA-256</th><th>Разница</th></tr></thead><tbody>"
            )
            for item in plan["entries"]:
                source_url = (plan["repository"] + "/blob/" + plan["commit"] +
                              "/" + item["source_path"])
                delta = item["diff"]
                details = ("<details><summary>Изменения</summary><pre>" +
                           _h(delta["preview"]) + "</pre></details>") if delta else "—"
                content += (
                    "<tr><td>" + _h(item["action"]) + "</td><td><b>" +
                    _h(item["filename"]) + "</b><br><small>" +
                    _h(item["view_path"]) + " · " + str(item["bytes"]) +
                    " байт</small><br><a href='" + _h(source_url) +
                    "' target='_blank' rel='noopener noreferrer'>Исходный YAML в GitHub</a>"
                    "</td><td><small>До: " + _h(item["before"] or "отсутствует") +
                    "<br>После: " + _h(item["after"]) + "</small></td><td>" +
                    details + "</td></tr>"
                )
            content += "</tbody></table>"
            if plan["changes"]:
                content += (
                    "<p class='warn'>Изменяется только каталог dashboards/dh/views/. "
                    "Перед записью сохраняются оригиналы. Lovelace Storage, пакеты "
                    "и агенты не изменяются. Home Assistant не перезапускается.</p>"
                    "<form action='./' method='post'>"
                    "<input type='hidden' name='op' value='apply'>"
                    "<input type='hidden' name='token' value='" + _h(plan["token"]) + "'>"
                    "<p><label><input type='checkbox' name='confirm' value='YES' required>"
                    " Подтверждаю запись перечисленных YAML</label></p>"
                    "<button type='submit'>Применить " + str(plan["changes"]) +
                    " файл(ов)</button></form>"
                )
            else:
                content += "<p class='ok'>Все файлы полностью совпадают; запись не нужна.</p>"
            self._action_shell("Предпросмотр Apply", content)

        def _rollback_page(self) -> None:
            if apply_manager is None:
                self._action_shell("Rollback недоступен", "Режим только чтение", 403)
                return
            preview = apply_manager.rollback_preview()
            if preview is None:
                self._action_shell("Rollback", "<p>Нет применённых транзакций.</p>")
                return
            transaction = preview["transaction"]
            content = "<p>Транзакция: <code>" + _h(transaction["id"]) + "</code></p>"
            content += "<ul>" + "".join(
                "<li>" + _h(item["file"]) + " — " +
                ("восстановить оригинал" if item["before"] else "удалить созданный файл") +
                "</li>" for item in transaction["entries"]
            ) + "</ul>"
            content += (
                "<p class='warn'>Если пользователь изменил эти YAML после Apply, "
                "откат будет заблокирован. Другие файлы не затрагиваются.</p>"
                "<form action='./' method='post'>"
                "<input type='hidden' name='op' value='rollback'>"
                "<input type='hidden' name='token' value='" + _h(preview["token"]) + "'>"
                "<p><label><input type='checkbox' name='confirm' value='YES' required>"
                " Подтверждаю откат</label></p>"
                "<button type='submit'>Откатить транзакцию</button></form>"
            )
            self._action_shell("Подтверждение Rollback", content)

        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == "/health":
                self._send(200, "<html><body>ok</body></html>")
                return
            if path not in ("/", ""):
                self._send(404, "<html><body>Not found</body></html>")
                return
            params = parse_qs(urlsplit(self.path).query)
            if "plan" in params:
                identity = params["plan"][0][:200]
                self._plan_page(identity)
                return
            if params.get("rollback") == ["1"]:
                self._rollback_page()
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
            # GitHub is read only; Apply requires separate plan + explicit POST.
            preview_html = (
                "<section><h2>Канонические dashboards · RU</h2>"
                "<p>GitHub-файлы обнаруживаются в dashboards/ru/ из "
                "репозитория организации DigitalHouses. SHA фиксируется для "
                "каждого просмотра автоматически.</p>"
                "<p><a href='?resources=1'>Проверить GitHub-ресурсы</a></p>"
            )
            if inspect is not None and parse_qs(urlsplit(self.path).query).get("resources") == ["1"]:
                preview_html += (
                    "<table class=\'views\'><thead><tr><th>Продукт / Git SHA</th>"
                    "<th>Dashboard / файл</th><th>Ревизия</th>"
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
                                _h(view["revision"]) + "</code></td><td>" +
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
                "Единственное правило допуска источника — владелец "
                "DigitalHouses. При применении потребуются резервные копии "
                "и отдельное подтверждение.</p></section>"
            )
            # Local comparison is explicit and does not write to HA.
            audit_html = (
                "<section><h2>Файлы CORE · локальное сравнение</h2>"
                "<p>Проверка локальных YAML панели DigitalHouses и конфликтов "
                "Lovelace Storage. Само сравнение ничего не меняет.</p>"
                "<p><a href='?local=1'>Сравнить с файлами CORE</a></p>"
            )
            if audit is not None and parse_qs(urlsplit(self.path).query).get("local") == ["1"]:
                try:
                    result = audit(records)
                    if not result["ready"]:
                        audit_html += "<p class='warn'>Аудит недоступен. Никаких изменений.</p>"
                    else:
                        audit_html += (
                            "<p class='muted'>Проверено файлов Lovelace Storage: " +
                            str(result["storage_files_examined"]) + ". "
                            "Содержимое Storage не показывается.</p>"
                        )
                    for issue in result["issues"]:
                        audit_html += "<p class='warn'>Проверка: " + _h(issue) + "</p>"
                    if result["ready"]:
                        audit_html += (
                            "<table class='views'><thead><tr>"
                            "<th>Продукт</th><th>View / файл CORE</th>"
                            "<th>SHA-256 (начало)</th><th>Сравнение</th>"
                            "</tr></thead><tbody>"
                        )
                        for item in result["products"]:
                            if (apply_manager is not None and item.get("identity")
                                    and item["views"] and not item["source_error"]):
                                audit_html += (
                                    "<tr><td colspan='4'><a href='?plan=" +
                                    quote(item["identity"], safe="") +
                                    "'>Подготовить Apply: " + _h(item["product"]) +
                                    "</a></td></tr>"
                                )
                            if item["source_error"]:
                                audit_html += (
                                    "<tr><td>" + _h(item["product"]) +
                                    "</td><td>—</td><td>—</td><td>" +
                                    _h(item["source_error"]) + "</td></tr>"
                                )
                            for view in item["views"]:
                                source = view["source_sha256"][:12] or "—"
                                local = view["local_sha256"][:12] or "—"
                                row = (
                                    "<tr><td>" + _h(item["product"]) +
                                    "<br><small>v" + _h(item["version"]) +
                                    "</small></td><td>" + _h(view["title"]) +
                                    "<br><code>" + _h(view["local_file"] or "нет файла") +
                                    "</code><br><small>" + _h(view["view_path"]) +
                                    "</small></td><td><code>GitHub " + _h(source) +
                                    "<br>CORE " + _h(local) +
                                    "</code></td><td>" + _h(view["status"])
                                )
                                delta = view.get("diff")
                                if delta and delta.get("preview"):
                                    row += (
                                        "<details><summary>Различия +" +
                                        str(delta["added"]) + " / -" +
                                        str(delta["removed"]) +
                                        "</summary><pre>" +
                                        _h(delta["preview"]) + "</pre></details>"
                                    )
                                audit_html += row + "</td></tr>"
                        audit_html += "</tbody></table>"
                except Exception:
                    audit_html += (
                        "<p class='warn'>Ошибка локального аудита. "
                        "Никаких изменений HAOS не производилось.</p>"
                    )
            audit_html += (
                "<p class='muted'>Сравнение не выполняет запись. Для Apply "
                "нужен отдельный предпросмотр, подтверждение и backup.</p></section>"
            )
            if apply_manager is not None:
                audit_html += (
                    "<section><h2>Управление изменениями</h2>"
                    "<p><a href='?rollback=1'>Просмотреть последний Apply / Rollback</a></p>"
                    "<p>Автоматическое обновление отключено. Пакеты и .storage "
                    "не изменяются.</p></section>"
                )
            page = (
                "<!doctype html><html lang='ru'><head><meta charset='utf-8'>"
                "<meta name='viewport' content='width=device-width,initial-scale=1'>"
                "<title>DigitalHouses Sync</title><style>" + STYLE +
                "</style></head><body><header><h1>DigitalHouses Sync · v" + _h(version) + "</h1>"
                "<small>MQTT · предпросмотр · ручной Apply и Rollback</small></header><main>"
                "<section><h2>Обнаруженные агенты и приложения (" +
                str(len(records)) + ")</h2><table><thead><tr>"
                "<th>Продукт / Instance</th><th>Версия</th><th>Доступность</th>"
                "<th>Репозиторий / Каталог</th></tr></thead><tbody>" +
                rows + "</tbody></table></section>" + preview_html + audit_html + "<section>"
                "<p>Принимаются только репозитории GitHub организации "
                "<b>DigitalHouses</b>. Метаданные получены из MQTT и сами по "
                "себе не разрешают установку.</p>"
                "<p class='muted'>Запись только вручную в DigitalHouses YAML views "
                "после предпросмотра и подтверждения. Агенты не запускаются и "
                "не обновляются, удаление продуктов автоматикой запрещено.</p>"
                "</section></main>"
                "</body></html>"
            )
            self._send(200, page)

        def do_POST(self) -> None:
            # Only HA Supervisor ingress can submit a plan in production.
            if apply_manager is None:
                self._send(405, "<html><body>Read-only catalog</body></html>")
                return
            allowed = (self.client_address[0] == "172.30.32.2"
                       or (port == 0 and self.client_address[0] == "127.0.0.1"))
            if not allowed:
                self._action_shell("Access denied", "Supervisor Ingress required", 403)
                return
            if urlsplit(self.path).path not in ("", "/"):
                self._action_shell("Invalid request", "Unknown URL", 404)
                return
            if not self.headers.get("Content-Type", "").startswith(
                    "application/x-www-form-urlencoded"):
                self._action_shell("Invalid request", "Form encoding required", 400)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if size <= 0 or size > 1024:
                    raise ValueError("invalid form length")
                fields = parse_qs(self.rfile.read(size).decode("ascii"), strict_parsing=True)
                op, token, confirm = (
                    fields.get("op", [""])[0], fields.get("token", [""])[0],
                    fields.get("confirm", [""])[0],
                )
                if len(token) > 80 or op not in ("apply", "rollback"):
                    raise ValueError("invalid request")
                if op == "apply":
                    result = apply_manager.apply(token, confirmed=confirm == "YES")
                else:
                    result = apply_manager.rollback(token, confirmed=confirm == "YES")
            except Exception as exc:
                self._action_shell("Операция отклонена",
                                   "<p class='warn'>" + _h(exc) + "</p>", 409)
                return
            self._action_shell(
                "Операция выполнена",
                "<p class='ok'>" + _h(result["status"]) + ": " +
                str(result["count"]) + " файлов. Транзакция: " +
                _h(result["id"] or "—") + ".</p>"
                "<p>Перезапуск Home Assistant не производился. "
                "Проверьте вкладки в браузере.</p>"
                "<p><a href='?rollback=1'>Rollback</a></p>"
            )

        def log_message(self, fmt, *args) -> None:
            # Do not expose Ingress URLs, credentials or client headers.
            pass

    return ThreadingHTTPServer(("0.0.0.0", port), Handler)
