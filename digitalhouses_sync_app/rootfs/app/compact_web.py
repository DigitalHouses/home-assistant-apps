"""Compact admin Ingress, using only cached registry and completed sync report."""
from datetime import datetime, timezone
from html import escape
from zoneinfo import ZoneInfo
import os
import re

STYLE = """
:root{color-scheme:dark}*{box-sizing:border-box}body{background:#121619;color:#e5e9eb;font:14px/1.4 system-ui,sans-serif;margin:0}
header{position:sticky;top:0;z-index:1;background:#121619;border-bottom:1px solid #343d43;padding:12px 20px;display:flex;align-items:center;gap:10px;flex-wrap:wrap}
.heading{flex:1}h1{font-size:20px;margin:0}small,.muted,th{color:#a8b3ba}
main{margin:0 auto;padding:12px 20px;max-width:none}a{color:#8dcaf1}button,.log{font:inherit;font-weight:600;border:0;border-radius:6px;padding:9px 13px;cursor:pointer;color:white;background:#2382b7;text-decoration:none;white-space:nowrap}
button:disabled{opacity:.55;cursor:wait}.log{background:#242b30;border:1px solid #465159}
.metrics{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:8px}.metric{background:#242b30;border-radius:7px;padding:10px 12px;min-width:0}.metric strong{font-size:24px;display:block;font-variant-numeric:tabular-nums;line-height:1.2}
.ok{color:#87d59c}.warn{color:#ffcf86}.error{color:#ff9999}.status{padding:12px 0}.status-line{display:flex;align-items:center;gap:10px;flex-wrap:wrap}.status-line strong{font-size:15px}.time{margin-left:auto}.status ul{margin:6px 0 0;padding-left:24px;overflow-wrap:anywhere}.status li{margin:2px 0}
section,details{border-top:1px solid #343d43;padding:10px 0;margin:0}h2{font-size:15px;margin:0 0 5px}summary{cursor:pointer;font-weight:600;padding:3px 0}summary small{font-weight:400;margin-left:10px}
table{width:100%;border-collapse:collapse;table-layout:auto}th,td{text-align:left;padding:5px 8px;border-bottom:1px solid #30383d;vertical-align:top;overflow-wrap:anywhere}th{font-size:12px;font-weight:500}tbody tr:last-child td{border-bottom:0}td.num,th.num{text-align:right;white-space:nowrap}.packages{display:flex;justify-content:space-between;gap:8px;flex-wrap:wrap}.table-wrap{overflow-x:auto}.technical{padding-top:6px;color:#a8b3ba}.technical p{margin:3px 0}
@media(max-width:560px){header,main{padding:10px}.metrics{grid-template-columns:repeat(2,minmax(0,1fr))}.time{margin-left:0;width:100%}h1{font-size:17px}th,td{padding:4px}.metric strong{font-size:21px}}
"""


def h(value):
    return escape(str(value), quote=True)


def name(value):
    value = str(value)
    return value.removeprefix("digitalhouses_").removesuffix("_app").removesuffix("_agent").replace("_", " ").title()


def time_text(value):
    if not value:
        return "Ожидание первой проверки"
    try:
        try:
            zone = ZoneInfo(os.environ.get("TZ") or "UTC")
        except (ValueError, KeyError):
            zone = timezone.utc
        return datetime.fromisoformat(value).astimezone(zone).strftime("%d.%m.%Y %H:%M:%S")
    except (ValueError, TypeError):
        return "—"


LABELS = {"Updated": "Обновлено", "Current": "Актуально", "Removed": "Удалено",
          "Error": "Ошибка", "No active views": "Нет активных Views", "Partial": "С ошибками"}


def result_text(value):
    if str(value).startswith("Skipped:"):
        return "Пропущено: " + str(value)[8:].strip()
    return LABELS.get(value, value)


def css_status(value):
    return "ok" if value in ("Updated", "Removed") else "error" if value == "Error" or str(value).startswith("Skipped:") else "muted"


def resource_line(r):
    return h(r.get("name", "—")) + " · " + h(r.get("kind", "Package"))


def render(records, report, *, running=False, failure=""):
    resources = report.get("resources") or []
    issues = list(report.get("issues") or [])
    if failure:
        issues.append(failure)
    changed = [r for r in resources if r.get("status") in ("Updated", "Removed")]
    updated = report.get("updated", 0)
    current = report.get("unchanged", 0)
    metrics = ""
    for label, value, cls in (("Продуктов", len(records), ""), ("Изменено", updated, "ok"),
                              ("Без изменений", current, ""), ("Ошибок", len(issues), "error" if issues else "ok")):
        metrics += f'<div class="metric"><strong class="{cls}">{h(value)}</strong><small>{label}</small></div>'
    if running:
        message, cls = "⟳ Выполняется проверка GitHub…", "muted"
    elif issues or report.get("state") in ("Error", "Partial"):
        message, cls = f"⚠ Синхронизация завершена с ошибками ({len(issues)})", "warn"
    elif not report.get("last_run"):
        message, cls = "Ожидание первой проверки", "muted"
    elif updated:
        message, cls = f"✓ Обновлено: {updated} ресурсов", "ok"
    elif not resources:
        message, cls = "Нет ресурсов для синхронизации", "muted"
    else:
        message, cls = "✓ Все ресурсы актуальны", "ok"
    trigger = {"manual": "Вручную", "automatic": "Авто"}.get(report.get("trigger"), "")
    status = f'<div class="status-line"><strong class="{cls}">{message}</strong><small class="time">Последняя проверка: {h(time_text(report.get("last_run")))} {h(trigger)} · Авто / 60 мин</small></div>'
    if not running:
        if issues:
            status += '<ul class="error">' + "".join(f"<li>{h(i)}</li>" for i in issues) + "</ul>"
        if changed:
            status += '<ul class="ok">' + "".join(f"<li>{resource_line(r)} · {h(result_text(r.get('status')))}</li>" for r in changed) + "</ul>"
    dashboard = report.get("dashboard") or {}
    panels = ""
    for panel in dashboard.get("dashboards", []):
        slug = str(panel.get("slug", ""))
        title = h(slug)
        if re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)+", slug):
            title = f'<a href="/{h(slug)}/" target="_top">{title} ↗</a>'
        state = panel.get("state", "")
        panels += f'<tr><td>{title}</td><td class="num">{h(panel.get("views",0))}</td><td class="num {css_status(state)}">{h(result_text(state))}</td></tr>'
    if not panels:
        panels = '<tr><td colspan="3" class="muted">Нет данных</td></tr>'
    packages = report.get("packages") or {}
    loader = {"Configured":"Подключение создано","Current":"Подключены","Unavailable":"Ошибка подключения"}.get(packages.get("loader"), "Нет данных")
    reload = {"Requested":" · YAML-перезагрузка запрошена","Unavailable":" · YAML-перезагрузка недоступна","Not available":" · YAML-перезагрузка недоступна"}.get(packages.get("reload"), "")
    package_class = "error" if packages.get("loader") == "Unavailable" or packages.get("reload") in ("Unavailable","Not available") else "ok" if packages else "muted"
    package_html = f'<strong>Packages</strong><span class="{package_class}">{h(loader+reload)}</span>'
    product_rows = ""
    for identity, item in sorted(records.items()):
        product = item.get("product_id", "")
        instance = identity.partition("/")[2]
        product_rows += f'<tr><td title="{h(product)}">{h(name(product))}</td><td>{h(item.get("version",""))}</td><td>{h(item.get("type",""))}</td><td>{h(instance)}</td></tr>'
    if not product_rows:
        product_rows = '<tr><td colspan="4" class="muted">Ожидаются retained /sync</td></tr>'
    resource_rows = "".join(f'<tr><td>{resource_line(r)}</td><td class="{css_status(r.get("status"))}">{h(result_text(r.get("status","")))}</td></tr>' for r in resources)
    if not resource_rows:
        resource_rows = '<tr><td colspan="2" class="muted">Нет данных</td></tr>'
    technical = '<p>Источник реестра: MQTT retained /sync</p><p>Источник ресурсов: GitHub DigitalHouses</p><p>DH Journal 1.0.3 · SQLite · 3000 записей</p><p>Home Assistant автоматически не перезапускается. Новые интеграции в пакетах могут требовать обычного перезапуска HA.</p>'
    repos = sorted({(str(x.get("repository","")),str(x.get("product_path",""))) for x in records.values()})
    if repos:
        technical += '<p>Источники продуктов:</p>' + "".join(f'<p>{h(repo)} / {h(path)}</p>' for repo,path in repos)
    return {"metrics":metrics,"status":status,"panels":panels,"packages":package_html,
            "product_count":str(len(records)),"product_rows":product_rows,
            "resource_count":str(len(resources)),"resource_rows":resource_rows,"technical":technical}


def page(version, token, fragments, *, can_sync, can_log, running=False):
    f = fragments
    button = f'<button id="sync" type="button" data-token="{h(token)}"{" disabled" if running else ""}>⟳ {"Выполняется проверка…" if running else "Проверить и обновить"}</button>' if can_sync else ""
    log = '<a class="log" href="./log">LOG</a>' if can_log else ""
    return f'''<!doctype html><html lang="ru"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>DH Sync</title><link rel="stylesheet" href="./sync-ui.css"></head><body>
<header><div class="heading"><h1>DigitalHouses Sync</h1><small>v{h(version)}</small></div>{button}{log}</header>
<main><div id="metrics" class="metrics">{f["metrics"]}</div>
<div class="status"><div id="status" role="status" aria-live="polite">{f["status"]}</div><div id="request_error" class="error" role="alert"></div></div>
<section><h2>Dashboards</h2><table><thead><tr><th>Панель</th><th class="num">Views</th><th class="num">Состояние</th></tr></thead><tbody id="panels">{f["panels"]}</tbody></table></section>
<section id="packages" class="packages">{f["packages"]}</section>
<details><summary>Продукты (<span id="product_count">{f["product_count"]}</span>) <small>MQTT /sync</small></summary><div class="table-wrap"><table><thead><tr><th>Продукт</th><th>Версия</th><th>Тип</th><th>Instance</th></tr></thead><tbody id="product_rows">{f["product_rows"]}</tbody></table></div></details>
<details><summary>Все ресурсы (<span id="resource_count">{f["resource_count"]}</span>)</summary><table><thead><tr><th>Ресурс</th><th>Состояние</th></tr></thead><tbody id="resource_rows">{f["resource_rows"]}</tbody></table></details>
<details><summary>Техническая информация</summary><div id="technical" class="technical">{f["technical"]}</div></details>
</main><script src="./sync-ui.js"></script></body></html>'''
