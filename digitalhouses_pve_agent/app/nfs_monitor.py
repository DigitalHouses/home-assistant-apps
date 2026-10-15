from __future__ import annotations

"""Passive NFS availability incidents from PVE journald and fresh PVE RRD.

Never performs filesystem operations on an NFS mount or calls pvesm.
"""

import json
import logging
import re
import subprocess
import time
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path

from .pve_cache import read_pve_rrd, read_storage_config
from .state_store import StateStore

LOG = logging.getLogger(__name__)
POLL_SECONDS = 15
CONFIRM_WINDOW_SECONDS = 60
RECOVERY_QUIET_SECONDS = 20
RECOVERY_SAMPLE_SPACING_SECONDS = 15
JOURNAL_LIMIT_BYTES = 1_000_000

_OFFLINE = re.compile(r"storage ['\u2018]([^'\u2019]+)['\u2019] is not online", re.I)
_NFS_TIMEOUT = re.compile(r"\bnfs:\s*server\s+(\S+)\s+not responding\b", re.I)
_JOURNAL_GREP = r"storage .* is not online|nfs: server .* not responding"


def _iso(epoch: float) -> str:
    return datetime.fromtimestamp(epoch, timezone.utc).isoformat()


def _enabled_nfs(config_path: Path, node_name: str) -> dict[str, str]:
    """Storage ID -> configured NFS server, excluding disabled/foreign nodes."""
    result: dict[str, str] = {}
    for storage_id, config in read_storage_config(config_path).items():
        if config.storage_type != "nfs":
            continue
        options = config.options
        if options.get("disable", "0").strip().lower() in {"1", "yes", "true", "on"}:
            continue
        nodes = {s.strip() for s in options.get("nodes", "").split(",") if s.strip()}
        if nodes and node_name not in nodes:
            continue
        result[storage_id] = options.get("server", "").strip()
    return result


def _journal(since: float, until: float) -> list[dict[str, object]]:
    # Filter messages in journald, not by systemd unit: pvestatd entries may
    # have SYSLOG_IDENTIFIER but not _SYSTEMD_UNIT=pvestatd.service.
    result = subprocess.run(
        [
            "journalctl", "-b", "--quiet", "--no-pager", "--output=json",
            "--since", f"@{max(0, int(since))}",
            "--until", f"@{max(0, int(until))}",
            "--grep", _JOURNAL_GREP,
        ],
        capture_output=True,
        text=True,
        timeout=8,
        check=False,
    )
    if result.returncode not in (0, 1) or result.stderr.strip():
        raise RuntimeError(result.stderr.strip() or f"journalctl rc={result.returncode}")
    if len(result.stdout.encode("utf-8")) > JOURNAL_LIMIT_BYTES:
        raise RuntimeError("NFS journal window too large; refusing partial evidence")
    records: list[dict[str, object]] = []
    for line in result.stdout.splitlines():
        try:
            item = json.loads(line)
        except ValueError:
            continue
        if isinstance(item, dict):
            records.append(item)
    return records


class NfsFailureMonitor:
    """Persistent incident/outbox machine; independently polled by a worker."""

    def __init__(
        self,
        store: StateStore,
        *,
        node_name: str,
        bridge,
        config_path: Path = Path("/etc/pve/storage.cfg"),
        rrd_path: Path = Path("/etc/pve/.rrd"),
        journal_reader: Callable[[float, float], list[dict[str, object]]] = _journal,
        rrd_reader: Callable[[float], Mapping[str, float]] | None = None,
    ) -> None:
        self.store = store
        self.node_name = node_name
        self.bridge = bridge
        self.config_path = config_path
        self.rrd_path = rrd_path
        self.journal_reader = journal_reader
        self.rrd_reader = rrd_reader or self._rrd_online
        self.state = store.load()
        if self.state.get("schema_version") not in (None, 1):
            raise ValueError("unsupported NFS monitor persisted state")
        self.state.setdefault("schema_version", 1)
        self.state.setdefault("incidents", {})
        self.state.setdefault("candidates", {})
        self.state.setdefault("history", [])
        self.state.setdefault("pending_events", [])
        self.state.setdefault("seen_cursors", [])
        self.state.setdefault("last_scan_at", None)
        self._last_state_sent: str | None = None

    def _rrd_online(self, now: float) -> Mapping[str, float]:
        snapshot = read_pve_rrd(
            self.rrd_path,
            node_name=self.node_name,
            now_epoch=now,
            stale_after_seconds=45.0,
        )
        return {sid: float(entry.ctime) for sid, entry in snapshot.storages.items()}

    def _persist(self) -> None:
        self.store.save(self.state)

    def _queue_event(
        self,
        *,
        kind: str,
        sid: str,
        server: str,
        incident_id: str,
        at: float,
        first_at: float,
        evidence: str,
    ) -> None:
        payload: dict[str, object] = {
            "schema_version": 2,
            "event_type": kind,
            "observed_at": _iso(at),
            "category": "storage",
            "severity": "critical" if kind == "storage_nfs_unavailable" else "info",
            "object_id": sid,
            "object_name": sid,
            "storage_type": "nfs",
            "server": server,
            "incident_id": incident_id,
            "started_at": _iso(first_at),
            "reason": "NFS storage unavailable" if kind == "storage_nfs_unavailable" else "PVE storage responding",
            "evidence": evidence,
            "cause": "unknown",
        }
        if kind == "storage_nfs_restored":
            payload["duration_seconds"] = max(0, int(at - first_at))
        self.state["pending_events"].append({"key": kind + ":" + incident_id, "payload": payload})

    def _observe_failure(self, sid: str, server: str, at: float, evidence: str) -> None:
        incidents = self.state["incidents"]
        active = incidents.get(sid)
        if active is not None:
            active["last_bad_at"] = max(float(active["last_bad_at"]), at)
            active["healthy_since"] = None
            active["healthy_ctime"] = None
            return

        if evidence == "pvestatd":
            candidate = self.state["candidates"].get(sid)
            if not candidate or at - float(candidate["first_at"]) > CONFIRM_WINDOW_SECONDS:
                self.state["candidates"][sid] = {"first_at": at, "count": 1}
                return
            candidate["count"] += 1
            if candidate["count"] < 2:
                return
            first_at = float(candidate["first_at"])
        else:
            candidate = self.state["candidates"].get(sid)
            first_at = min(float(candidate["first_at"]), at) if candidate else at

        self.state["candidates"].pop(sid, None)
        incident_id = f"{sid}:{int(first_at * 1_000_000)}"
        incidents[sid] = {
            "incident_id": incident_id,
            "started_at": first_at,
            "last_bad_at": at,
            "server": server,
            "evidence": evidence,
            "healthy_since": None,
            "healthy_ctime": None,
        }
        self._queue_event(
            kind="storage_nfs_unavailable", sid=sid, server=server,
            incident_id=incident_id, at=at, first_at=first_at, evidence=evidence,
        )

    def _process_journal(
        self, records: list[dict[str, object]], servers: Mapping[str, str]
    ) -> None:
        seen = list(self.state["seen_cursors"])
        known = set(seen)
        records = sorted(records, key=lambda x: int(x.get("__REALTIME_TIMESTAMP", 0)))
        for item in records:
            try:
                at = int(item["__REALTIME_TIMESTAMP"]) / 1_000_000
            except (TypeError, ValueError, KeyError):
                continue
            message = item.get("MESSAGE")
            if not isinstance(message, str):
                continue
            cursor = str(item.get("__CURSOR") or f"{at}:{message}")
            if cursor in known:
                continue
            seen.append(cursor)
            known.add(cursor)

            identifier = str(item.get("SYSLOG_IDENTIFIER") or item.get("_COMM") or "")
            transport = str(item.get("_TRANSPORT") or "")
            match = _OFFLINE.search(message)
            if match and identifier == "pvestatd":
                sid = match.group(1)
                if sid in servers:
                    self._observe_failure(sid, servers[sid], at, "pvestatd")
                continue
            match = _NFS_TIMEOUT.search(message)
            if match and (transport == "kernel" or identifier == "kernel"):
                host = match.group(1).rstrip(":")
                for sid, server in servers.items():
                    if server and host == server:
                        self._observe_failure(sid, server, at, "kernel_nfs_timeout")

        self.state["seen_cursors"] = seen[-256:]

    def _check_recovery(self, now: float, servers: Mapping[str, str]) -> None:
        if not self.state["incidents"]:
            return
        online = self.rrd_reader(now)
        for sid, incident in list(self.state["incidents"].items()):
            if sid not in servers:
                continue  # changed configuration must not imply recovery
            ctime = online.get(sid)
            last_bad = float(incident["last_bad_at"])
            if (
                ctime is None
                or float(ctime) <= last_bad
                or now - last_bad < RECOVERY_QUIET_SECONDS
            ):
                incident["healthy_since"] = None
                incident["healthy_ctime"] = None
                continue
            first_healthy = incident.get("healthy_since")
            first_ctime = incident.get("healthy_ctime")
            if first_healthy is None:
                incident["healthy_since"] = now
                incident["healthy_ctime"] = float(ctime)
                continue
            if (
                now - float(first_healthy) < RECOVERY_SAMPLE_SPACING_SECONDS
                or float(ctime) <= float(first_ctime)
            ):
                continue

            started = float(incident["started_at"])
            self._queue_event(
                kind="storage_nfs_restored",
                sid=sid, server=servers[sid], incident_id=str(incident["incident_id"]),
                at=now, first_at=started, evidence="fresh_pve_rrd",
            )
            self.state["history"].append({
                "storage_id": sid, "server": servers[sid],
                "started_at": _iso(started), "restored_at": _iso(now),
                "duration_seconds": max(0, int(now - started)),
            })
            self.state["history"] = self.state["history"][-40:]
            del self.state["incidents"][sid]

    def _publish(self, servers: Mapping[str, str]) -> None:
        # Outbox is persisted *before* publishing. An offline broker never
        # discards incidents. Publish is QoS 1, but cannot prove HA consumed it.
        while self.state["pending_events"]:
            item = self.state["pending_events"][0]
            if not self.bridge.publish_diagnostic_event(item["payload"]):
                break
            self.state["pending_events"].pop(0)
            self._persist()

        payload = {
            "schema_version": 1,
            "configured": dict(servers),
            "active": {
                sid: {
                    "started_at": _iso(float(incident["started_at"])),
                    "last_error_at": _iso(float(incident["last_bad_at"])),
                    "server": incident["server"],
                    "evidence": incident["evidence"],
                }
                for sid, incident in self.state["incidents"].items()
            },
            "recent_history": self.state["history"][-20:],
        }
        encoded = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        if encoded != self._last_state_sent:
            if self.bridge.publish_nfs_diagnostics(payload):
                self._last_state_sent = encoded

    def scan(self, now: float | None = None) -> None:
        current = time.time() if now is None else float(now)
        try:
            servers = _enabled_nfs(self.config_path, self.node_name)
            prior = self.state.get("last_scan_at")
            since = min(float(prior), current) - 2 if prior is not None else current - 2
            records = self.journal_reader(since, current)
            self._process_journal(records, servers)
            self.state["last_scan_at"] = current
            for sid, candidate in list(self.state["candidates"].items()):
                if current - float(candidate["first_at"]) > CONFIRM_WINDOW_SECONDS:
                    del self.state["candidates"][sid]
            if self.state["incidents"]:
                self._check_recovery(current, servers)
            self._persist()
            self._publish(servers)
        except Exception:
            # The monitor is advisory: it must never break primary PVE/UPS work.
            LOG.exception("NFS passive monitoring failed; no inferred recovery")
            raise
