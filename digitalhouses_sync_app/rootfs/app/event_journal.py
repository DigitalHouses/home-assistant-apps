"""DH Sync event vocabulary and one-time legacy history migration."""
from datetime import datetime, timezone
from pathlib import Path
from contextlib import closing
import logging
import os
import re
import sqlite3
import tempfile

from dh_journal import Journal, LIMIT, LEVELS

PRODUCT = "digitalhouses_sync_app"
LOG = logging.getLogger("dh_sync.journal")
MESSAGES = {
    "product_removed": ("Продукт удалён из MQTT", "Product removed from MQTT"),
    "product_detected": ("Продукт обнаружен", "Product detected"),
    "product_changed": ("Метаданные продукта изменились", "Product metadata changed"),
    "product_version_changed": ("Версия продукта изменилась", "Product version changed"),
    "mqtt_connected": ("MQTT подключён", "MQTT connected"),
    "mqtt_connect_failed": ("Ошибка подключения MQTT", "MQTT connection failed"),
    "mqtt_disconnected": ("MQTT отключён", "MQTT disconnected"),
    "mqtt_rejected": ("Метаданные MQTT отклонены", "MQTT metadata rejected"),
    "sync_started": ("Синхронизация начата", "Synchronization started"),
    "sync_finished": ("Синхронизация завершена", "Synchronization finished"),
    "sync_issue": ("Проблема синхронизации", "Synchronization issue"),
    "backup_created": ("Резервная копия создана", "Backup created"),
    "transaction_prepared": ("Транзакция подготовлена", "Transaction prepared"),
    "package_updated": ("Пакет обновлён", "Package updated"),
    "package_error": ("Ошибка пакета", "Package error"),
    "package_reload_requested": ("Запрошена перезагрузка пакетов", "Package reload requested"),
    "dashboard_created": ("Панель создана", "Dashboard created"),
    "dashboard_updated": ("Панель обновлена", "Dashboard updated"),
    "view_updated": ("Вкладка обновлена", "View updated"),
    "journal_settings": ("Прежние настройки журнала изменены", "Legacy journal settings changed"),
}
LOCALES = {lang: {code: words[i] + "{detail_suffix}" for code, words in MESSAGES.items()}
           for i, lang in enumerate(("ru", "en"))}
SUCCESS = {"package_updated", "dashboard_created", "dashboard_updated", "view_updated",
           "backup_created", "package_reload_requested", "mqtt_connected"}
SAFE_DETAIL = re.compile(r"[A-Za-z0-9_. /·→:=+-]{0,350}\Z")
SENSITIVE = re.compile(r"password|passwd|token|secret|credential|authorization|api.?key|cookie", re.I)


def facts(event, detail, product):
    """Only bounded product identities, paths, versions and controlled summaries."""
    params = {"detail": ""}
    if isinstance(product, str) and re.fullmatch(r"[A-Za-z0-9_.-]{1,96}", product):
        params["source_product"] = product
    if (isinstance(detail, str) and SAFE_DETAIL.fullmatch(detail) and not SENSITIVE.search(detail)):
        if detail:
            params["detail"] = detail
    if not params["detail"] and "source_product" in params and product != PRODUCT:
        params["detail"] = product
    detail = params.pop("detail")
    params["detail_suffix"] = " · " + detail if detail else ""
    return params


def open_journal(path, debug=False, clock=None):
    return Journal(path, product=PRODUCT, product_name="DigitalHouses Sync",
                   locales=LOCALES, debug=debug, clock=clock)


def migrate(path):
    """Replace legacy-only DB atomically; retain original on any failed migration."""
    if not path.exists():
        return
    with closing(sqlite3.connect(f"{path.resolve().as_uri()}?mode=ro", uri=True)) as old:
        columns = {r[1] for r in old.execute("PRAGMA table_info(events)")}
        if not {"product", "event", "detail"}.issubset(columns):
            return
        rows = old.execute("SELECT ts,product,event,level,detail FROM events ORDER BY id DESC LIMIT ?", (LIMIT,)).fetchall()
    fd, name = tempfile.mkstemp(prefix=".dh-sync-journal-", dir=path.parent)
    os.close(fd)
    temp = Path(name)
    journal = None
    try:
        current = datetime.now(timezone.utc)
        journal = open_journal(temp, debug=True, clock=lambda: current)
        if journal.storage != "sqlite":
            raise OSError("journal unavailable")
        for ts, product, event, level, detail in reversed(rows):
            current = datetime.fromtimestamp(ts, timezone.utc)
            if event == "app_started":
                params = {"product_name": "DigitalHouses Sync", "version": detail if SAFE_DETAIL.fullmatch(detail) and not SENSITIVE.search(detail) else "unknown"}
                level = "lifecycle"
            else:
                params = facts(event, "" if event in {"package_error", "mqtt_connect_failed", "sync_issue"} else detail, product)
                level = "lifecycle" if event == "app_stopped" else level if level in LEVELS else "info"
            if not journal.record(level, event, **params):
                raise OSError("legacy event migration failed")
        journal.close()
        if journal.storage != "sqlite":
            raise OSError("journal unavailable")
        os.replace(temp, path)
    finally:
        if journal:
            journal.close()
        for suffix in ("", "-wal", "-shm"):
            Path(str(temp) + suffix).unlink(missing_ok=True)


class EventJournal:
    """Small adapter for existing producers; storage and UI are entirely DH Journal."""
    def __init__(self, path=Path("/data/dh_sync.db"), *, debug=False):
        path = Path(path)
        try:
            migrate(path)
        except (OSError, sqlite3.Error, ValueError, OverflowError):
            LOG.warning("Legacy journal migration failed; old history preserved")
            # Do not let the library open or alter an incompatible old schema.
            self.backend = open_journal(path / ".unavailable", debug)
        else:
            self.backend = open_journal(path, debug)

    def record(self, event, detail="", *, product=PRODUCT, level="info"):
        if event in SUCCESS and level == "info":
            level = "success"
        try:
            return self.backend.record(level, event, **facts(event, detail, product))
        except Exception:
            self.backend.report_failure()
            return False
