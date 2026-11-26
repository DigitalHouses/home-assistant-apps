"""HTML for the admin Ingress journal; no JavaScript or external dependencies."""
import html
from urllib.parse import urlencode

from event_journal import display_time


def h(value):
    return html.escape(str(value), quote=True)


def filters(params):
    return tuple(params.get(key, [""])[0][:200] for key in ("product", "event"))


def section(journal, token, params):
    if not journal.ready:
        return "<section><h2>Журнал событий</h2><p class='warn'>SQLite недоступна.</p></section>"
    try:
        product, event = filters(params)
        days, maximum, visible = journal.settings()
        rows = journal.rows(product, event)
        products, events = journal.facets()
    except Exception:
        return "<section><h2>Журнал событий</h2><p class='warn'>Не удалось прочитать SQLite.</p></section>"
    def select(name, values, selected, title):
        options = "<option value=''>" + h(title) + "</option>"
        for value in sorted(set(values) | ({selected} if selected else set())):
            options += "<option value='" + h(value) + "'" + (" selected" if value == selected else "") + ">" + h(value) + "</option>"
        return "<select name='" + name + "'>" + options + "</select>"
    hidden = "<input type='hidden' name='token' value='" + h(token) + "'>"
    export = "?" + urlencode({"journal_export": "1", "product": product, "event": event})
    content = ("<section id='journal'><h2>Журнал событий</h2>"
               "<p>История сохраняется в SQLite. Последние " + str(visible) + " записей.</p>"
               + ("<p class='warn'>" + h(journal.error) + "</p>" if journal.error else "") +
               "<form action='./#journal' method='get'>" +
               select("product", products, product, "Все продукты") + " " +
               select("event", events, event, "Все события") +
               " <button type='submit'>Показать / обновить</button> "
               "<a href='" + h(export) + "'>Скачать журнал JSONL</a></form>"
               "<table><thead><tr><th>Время</th><th>Продукт</th><th>Событие</th>"
               "<th>Подробности</th></tr></thead><tbody>")
    for row in rows:
        style = "warn" if row["level"] in ("warning", "error") else ""
        content += ("<tr><td>" + h(display_time(row["ts"])) + "</td><td>" +
                    h(row["product"]) + "</td><td class='" + style + "'>" +
                    h(row["event"]) + " · " + h(row["level"]) + "</td><td>" +
                    h(row["detail"]) + "</td></tr>")
    if not rows:
        content += "<tr><td colspan='4'>Нет событий</td></tr>"
    return (content + "</tbody></table><details><summary>Retention / настройки журнала</summary>"
            "<form method='post' action='./'>" + hidden +
            "<input type='hidden' name='op' value='journal_settings'>"
            "<p><label>Дней <input type='number' name='days' min='1' max='365' required value='" + str(days) +
            "'></label> <label>Максимум записей <input type='number' name='max_rows' min='100' max='100000' required value='" + str(maximum) +
            "'></label> <label>Показывать <input type='number' name='visible' min='10' max='1000' required value='" + str(visible) +
            "'></label> <button type='submit'>Сохранить</button></p></form>"
            "<form method='post' action='./'>" + hidden +
            "<input type='hidden' name='op' value='journal_clear'>"
            "<label><input type='checkbox' name='confirm' value='YES' required> Удалить историю событий</label> "
            "<button type='submit'>Очистить журнал</button></form></details></section>")
