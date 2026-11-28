from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import text

from digitalhouses_stats.db import engine
from digitalhouses_stats.main import app, settings
from digitalhouses_stats.dashboard_api import app as dashboard_app
from digitalhouses_stats.journal import create_journal, observe, key_path, version_key


def test_journal_observations_and_retention(tmp_path):
    j = create_journal(SimpleNamespace(journal_path=str(tmp_path / "journal.sqlite3")))
    now = datetime.now(timezone.utc)
    facts = dict(product="digitalhouses_internet_app", version="0.1.28", country="KZ", now=now)
    try:
        observe(j, **facts, new=True, previous=None)
        prev = SimpleNamespace(version="0.1.28", country="KZ", received_at=now)
        observe(j, **facts, new=False, previous=prev)
        assert [r["code"] for r in j.snapshot()["rows"]] == ["installation_new"]
        prev.version = "0.1.9"
        prev.country = "DE"
        prev.received_at = now - timedelta(days=8)
        observe(j, **facts, new=False, previous=prev)
        rows = j.snapshot()["rows"]
        assert [r["code"] for r in rows] == [
            "installation_new", "version_upgraded", "country_changed", "installation_returned"]
        assert rows[1]["params"]["previous_version"] == "0.1.9"
        assert rows[1]["params"]["country"] == "KZ"
        assert "installation_id" not in rows[1]["params"]
        assert version_key("0.5.107") > version_key("0.5.96")
        assert version_key("1.0.0") > version_key("1.0.0-rc.1")
        assert version_key("1.0.0-rc.10") > version_key("1.0.0-rc.2")
        assert version_key("1.0.0+x") == version_key("1.0.0+y")
    finally:
        j.close()


def test_accepted_heartbeat_journal_and_private_routes(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "journal_path", str(tmp_path / "journal.sqlite3"))
    from digitalhouses_stats import local_timezone
    from pathlib import Path
    link = tmp_path / "localtime"
    link.symlink_to(Path('/usr/share/zoneinfo/UTC'))
    monkeypatch.setattr(local_timezone, 'LOCALTIME', link)
    # Like test_api, run against the disposable CI PostgreSQL database.
    with engine.begin() as connection:
        connection.execute(text("DELETE FROM heartbeats"))
        connection.execute(text("DELETE FROM installations"))
    product = "digitalhouses_internet_app"
    installation_id = str(uuid4())
    token = "af" * 32
    headers = {"Authorization": f"Bearer {token}", "CF-IPCountry": "DE"}
    payload = {"schema": 1, "telemetry_policy_version": 2,
               "installation_id": installation_id, "product": product, "version": "0.1.9"}
    with TestClient(app) as client:
        key = key_path(settings).read_text()
        assert key_path(settings).stat().st_mode & 0o777 == 0o600
        internal = {"X-DH-Journal-Key": key}
        assert client.get("/internal/journal/log").status_code == 404
        assert client.get("/internal/journal/log/toasts").status_code == 404
        baseline = client.get("/internal/journal/log/toasts?lang=en", headers=internal).json()
        assert baseline["rows"] == []
        assert baseline["cursor"] == 1
        assert client.post("/internal/journal/log/clear", json={"confirm": True}).status_code == 404
        assert client.post("/v1/heartbeat", json=payload, headers=headers).status_code == 204
        assert client.post("/v1/heartbeat", json=payload, headers=headers).status_code == 204
        payload["version"] = "0.1.28"
        assert client.post("/v1/heartbeat", json=payload, headers=headers).status_code == 204
        assert client.post("/v1/heartbeat", json={**payload, "product": "private-secret-invalid"}, headers=headers).status_code == 422
        assert client.post("/v1/heartbeat", json=payload, headers={**headers, "Authorization": "Bearer " + "bb"*32}).status_code == 401
        response = client.get("/internal/journal/log?lang=en", headers=internal)
        assert response.status_code == 200
        data = response.json()
        assert data["app_version"] == "0.4.10"
        assert [r["code"] for r in data["rows"]] == [
            "app_started", "installation_new", "country_new_installation", "version_upgraded", "telemetry_rejected"]
        toasts = client.get("/internal/journal/log/toasts?lang=en&after=1", headers=internal).json()
        assert len(toasts["rows"]) == 1
        assert "New country" in toasts["rows"][0]["message"]
        assert "🇩🇪" in toasts["rows"][0]["message"] or "DE" in toasts["rows"][0]["message"]
        assert "v0.1.9" in toasts["rows"][0]["message"]
        assert client.get("/internal/journal/log/toasts?lang=en", headers=internal).json()["rows"] == []
        assert client.get("/internal/journal/log/toasts?after=-1", headers=internal).status_code == 400
        assert "Germany" in data["rows"][1]["message"] or "DE" in data["rows"][1]["message"]
        assert "private-secret-invalid" not in response.text
        assert token not in response.text and installation_id not in response.text
        export = client.get("/internal/journal/log/export?lang=ru", headers=internal)
        assert export.status_code == 200
        assert "digitalhouses_stats_" in export.headers["content-disposition"]
        assert "Обновление" in export.text
        # Known country: a new installation gets only its registration toast.
        second_id = str(uuid4())
        second = {**payload, "installation_id": second_id}
        assert client.post("/v1/heartbeat", json=second, headers=headers).status_code == 204
        next_toasts = client.get(f"/internal/journal/log/toasts?lang=en&after={toasts['cursor']}", headers=internal).json()
        assert len(next_toasts["rows"]) == 1
        assert "New registration" in next_toasts["rows"][0]["message"]
        assert "New country" not in next_toasts["rows"][0]["message"]
        # Existing installation reporting from a new country gets one country toast.
        assert client.post("/v1/heartbeat", json=second, headers={**headers, "CF-IPCountry": "FR"}).status_code == 204
        country_toasts = client.get(f"/internal/journal/log/toasts?lang=en&after={next_toasts['cursor']}", headers=internal).json()
        assert len(country_toasts["rows"]) == 1
        assert "New country" in country_toasts["rows"][0]["message"]
        assert "FR" in country_toasts["rows"][0]["message"]
        assert client.request("DELETE", "/v1/installation", json={"schema":1,"product":product,"installation_id":second_id}, headers=headers).status_code == 204
        assert client.post("/internal/journal/log/clear", json={}, headers=internal).status_code == 400
        assert client.post("/internal/journal/log/clear", json={"confirm": True}, headers=internal).status_code == 200
        assert [r["code"] for r in client.get("/internal/journal/log", headers=internal).json()["rows"]] == ["journal_cleared"]
        with engine.begin() as connection:
            count = connection.execute(text("SELECT count(*) FROM heartbeats WHERE installation_id=:id"), {"id": installation_id}).scalar_one()
            assert count == 3
        assert client.request("DELETE", "/v1/installation", json={"schema":1,"product":product,"installation_id":installation_id}, headers=headers).status_code == 204


def test_dashboard_bridge_uses_only_fixed_private_routes(monkeypatch):
    from fastapi import Response
    from digitalhouses_stats import dashboard_api
    calls = []
    def proxy(settings, path, query="", *, clear=False):
        calls.append((path, query, clear))
        return Response("ok")
    monkeypatch.setattr(dashboard_api, "dashboard_proxy", proxy)
    with TestClient(dashboard_app) as client:
        assert client.get("/v1/stats/log?lang=en&after=10").status_code == 200
        assert client.get("/v1/stats/log/export?lang=ru").status_code == 200
        assert client.get("/v1/stats/log/toasts?lang=en&after=12").status_code == 200
        assert client.post("/v1/stats/log/clear", json={"confirm":False}).status_code == 400
        assert client.post("/v1/stats/log/clear", json={"confirm":True}, headers={"Sec-Fetch-Site":"cross-site"}).status_code == 403
        assert client.post("/v1/stats/log/clear", json={"confirm":True}).status_code == 200
    assert calls == [("/log","lang=en&after=10",False),("/log/export","lang=ru",False),("/log/toasts","lang=en&after=12",False),("/log/clear","",True)]
