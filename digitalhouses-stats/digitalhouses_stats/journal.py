"""Local DH Journal owner and loopback-only dashboard bridge.

Only the ingestion process opens SQLite. The dashboard calls it over loopback
with a per-process credential readable only by the service account.
"""
from __future__ import annotations

import hmac
import logging
import os
import secrets
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.request import Request as URLRequest, ProxyHandler, build_opener

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import JSONResponse

from .dh_journal import Journal, StorageUnavailable
from .dh_journal.http import get as journal_get
from .products import product_name
from .local_timezone import local_zone

LOG = logging.getLogger(__name__)
APP_VERSION = "0.4.9"
RETURN_AFTER = timedelta(days=7)
LOCALES = {
    "ru": {
        "installation_new": "{country_name} ({country}) · {product_name} v{version} · Новая регистрация",
        "country_new": "Новая страна · {flag} {country_name} ({country})",
        "country_new_installation": "Новая страна · {flag} {country_name} ({country}) · {product_name} v{version} · Новая регистрация",
        "version_changed": "{country_name} ({country}) · {product_name} · v{previous_version} → v{version} · Изменение версии",
        "version_upgraded": "{country_name} ({country}) · {product_name} · v{previous_version} → v{version} · Обновление",
        "version_downgraded": "{country_name} ({country}) · {product_name} · v{previous_version} → v{version} · Откат",
        "country_changed": "{product_name} v{version} · {previous_country} → {country_name} ({country}) · Смена страны",
        "installation_returned": "{country_name} ({country}) · {product_name} v{version} · Возврат после отсутствия",
        "telemetry_rejected": "{country_name} ({country}) · HTTP 422 · Телеметрия отклонена ({reason})",
    },
    "en": {
        "installation_new": "{country_name} ({country}) · {product_name} v{version} · New registration",
        "country_new": "New country · {flag} {country_name} ({country})",
        "country_new_installation": "New country · {flag} {country_name} ({country}) · {product_name} v{version} · New registration",
        "version_changed": "{country_name} ({country}) · {product_name} · v{previous_version} → v{version} · Version changed",
        "version_upgraded": "{country_name} ({country}) · {product_name} · v{previous_version} → v{version} · Upgrade",
        "version_downgraded": "{country_name} ({country}) · {product_name} · v{previous_version} → v{version} · Downgrade",
        "country_changed": "{product_name} v{version} · {previous_country} → {country_name} ({country}) · Country changed",
        "installation_returned": "{country_name} ({country}) · {product_name} v{version} · Reporting resumed",
        "telemetry_rejected": "{country_name} ({country}) · HTTP 422 · Telemetry rejected ({reason})",
    },
}
ICONS = {"country_new": "🌍", "country_new_installation": "🌍", "installation_new": "🆕", "version_changed": "🔃", "country_changed": "🌍", "version_upgraded": "⬆️", "version_downgraded": "⬇️",
         "installation_returned": "🟢"}
SAFE_FIELDS = {"schema", "telemetry_policy_version", "installation_id", "product", "version"}
try:
    COUNTRY_NAMES = dict(line.split("\t", 1) for line in
                         Path("/usr/share/zoneinfo/iso3166.tab").read_text(encoding="utf-8").splitlines()
                         if line and not line.startswith("#") and "\t" in line)
except OSError:
    COUNTRY_NAMES = {}


def country_name(code: str) -> str:
    return COUNTRY_NAMES.get(code, "Unknown" if code in {"XX", "ZZ"} else code)


def country_flag(code: str) -> str:
    return "".join(chr(0x1F1E6 + ord(c) - ord("A")) for c in code) if code in COUNTRY_NAMES else ""


def key_path(settings) -> Path:
    return Path(settings.journal_path).with_suffix(".key")


def create_journal(settings):
    return Journal(settings.journal_path, product="digitalhouses_stats",
                   product_name="DigitalHouses Stats", locales=LOCALES, icons=ICONS)


def lifespan_for(settings):
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        journal = None
        app.state.journal = None
        app.state.journal_key = None
        try:
            journal = create_journal(settings)
            journal.start(APP_VERSION)
            app.state.journal = journal
            key = secrets.token_hex(32)
            with NamedTemporaryFile(mode="w", encoding="ascii", dir=key_path(settings).parent,
                                    delete=False) as handle:
                os.fchmod(handle.fileno(), 0o600)
                handle.write(key)
                tmp = Path(handle.name)
            try:
                os.replace(tmp, key_path(settings))
            finally:
                tmp.unlink(missing_ok=True)
            app.state.journal_key = key
        except Exception:
            LOG.warning("DH Stats journal initialization incomplete; telemetry remains available")
        try:
            yield
        finally:
            if journal is not None:
                journal.stop()
                journal.close()
            app.state.journal = None
            app.state.journal_key = None
    return lifespan


def version_key(version):
    main, _, prerelease = version.split("+", 1)[0].partition("-")
    identifiers = tuple((0, int(part)) if part.isascii() and part.isdigit() else (1, part)
                        for part in prerelease.split(".")) if prerelease else ()
    return tuple(int(part) for part in main.split(".")), not bool(prerelease), identifiers


def observe(journal, *, product, version, country, previous, new, new_country=False, now=None):
    """Called only after the PostgreSQL transaction commits; never log IDs."""
    if journal is None:
        return
    try:
        facts = dict(product=product, product_name=product_name(product),
                     version=version, country=country, country_name=country_name(country))
        if new or previous is None:
            journal.success("installation_new", notify=not new_country, **facts)
            if new_country:
                journal.info("country_new_installation", notify=True, flag=country_flag(country), **facts)
            return
        if new_country:
            journal.info("country_new", notify=True, flag=country_flag(country),
                         country=country, country_name=country_name(country))
        if previous.version != version:
            before, after = version_key(previous.version), version_key(version)
            code = "version_upgraded" if after > before else "version_downgraded" if after < before else "version_changed"
            journal.info(code, previous_version=previous.version, **facts)
        if previous.country != country:
            journal.info("country_changed", previous_country=previous.country, **facts)
        if (now or datetime.now(timezone.utc)) - previous.received_at >= RETURN_AFTER:
            journal.success("installation_returned", **facts)
    except Exception:
        journal.report_failure()


_rejection_lock = Lock()
_rejection_last = {}


def rejected(journal, errors, country):
    """Bound unauthenticated rejection noise; never store submitted field values."""
    if journal is None:
        return
    try:
        fields = {e["loc"][-1] for e in errors if e.get("loc") and
                  isinstance(e["loc"][-1], str) and e["loc"][-1] in SAFE_FIELDS}
        reason = ", ".join(sorted(fields)) or "invalid_payload"
        with _rejection_lock:
            now = time.monotonic()
            if now - _rejection_last.get(reason, -float("inf")) < 60:
                return
            _rejection_last[reason] = now
        journal.warning("telemetry_rejected", country=country, country_name=country_name(country),
                        reason=reason)
    except Exception:
        journal.report_failure()


def require_internal(request):
    key = getattr(request.app.state, "journal_key", None)
    supplied = request.headers.get("x-dh-journal-key", "")
    if not key or not supplied.isascii() or not hmac.compare_digest(supplied, key):
        raise HTTPException(404)
    journal = getattr(request.app.state, "journal", None)
    if journal is None:
        raise HTTPException(503, "Journal unavailable")
    return journal


def internal_get(request, settings, path):
    journal = require_internal(request)
    try:
        body, mime, filename = journal_get(journal, path + "?" + request.url.query, local_zone())
    except (ValueError, OverflowError):
        raise HTTPException(400, "Invalid journal request")
    except StorageUnavailable:
        raise HTTPException(503, "Journal unavailable")
    headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
    if filename:
        headers["Content-Disposition"] = 'attachment; filename="' + filename + '"'
    if mime == "application/json":
        return JSONResponse(body, headers=headers)
    return Response(body, media_type=mime, headers=headers)


async def clear_internal(request):
    journal = require_internal(request)
    await require_confirmation(request)
    if not journal.clear():
        raise HTTPException(409, "Journal unavailable")
    return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})


async def require_confirmation(request):
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/json":
        raise HTTPException(415)
    if request.headers.get("sec-fetch-site") == "cross-site":
        raise HTTPException(403)
    try:
        body = await request.body()
        if len(body) > 128:
            raise ValueError()
        data = await request.json()
    except (ValueError, UnicodeError):
        raise HTTPException(400, "Invalid clear request")
    if type(data) is not dict or set(data) != {"confirm"} or data["confirm"] is not True:
        raise HTTPException(400, "Invalid clear request")


def dashboard_proxy(settings, path, query="", *, clear=False):
    """Fixed loopback endpoint; no caller-controlled upstream or credential."""
    try:
        key = key_path(settings).read_text(encoding="ascii").strip()
        req = URLRequest("http://127.0.0.1:8080/internal/journal" + path +
                         ("?" + query if query else ""),
                         headers={"X-DH-Journal-Key": key, "Content-Type": "application/json"},
                         data=b'{"confirm":true}' if clear else None,
                         method="POST" if clear else "GET")
        try:
            upstream = build_opener(ProxyHandler({})).open(req, timeout=5)
        except HTTPError as e:
            upstream = e
        with upstream:
            headers = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}
            for name in ("Content-Type", "Content-Disposition"):
                if upstream.headers.get(name):
                    headers[name] = upstream.headers[name]
            return Response(upstream.read(), status_code=upstream.code, headers=headers)
    except (OSError, URLError, ValueError):
        raise HTTPException(503, "Journal unavailable")
