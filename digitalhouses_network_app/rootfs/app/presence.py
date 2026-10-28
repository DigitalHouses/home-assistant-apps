"""Presence subscriptions react only to completed global LAN discovery snapshots.

No independent ICMP/ARP scanner is launched by this engine. Negative evidence
requires successful global ARP scans, never a failed or stale source.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from uuid import NAMESPACE_URL, uuid5

ROOT = "DigitalHouses/Global/dh_network_app"


def utc(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


class PresenceRunner:
    def cycle(self, conn: sqlite3.Connection, transport: Any) -> None:
        conn.row_factory = sqlite3.Row
        self.observe(conn)
        self.publish(conn, transport)

    def observe(self, conn: sqlite3.Connection) -> None:
        source = conn.execute(
            "SELECT status,last_success FROM sources WHERE kind='lan_arp' LIMIT 1"
        ).fetchone()
        config = conn.execute(
            "SELECT scan_interval_seconds,confirm_successes,confirm_failures FROM discovery_settings WHERE id=1"
        ).fetchone()
        if config is None:
            return
        scan_seconds, needed_up, needed_down = map(int, config)
        now = datetime.now(timezone.utc)
        source_ok = bool(source and source["status"] in ("ok", "empty", "degraded")
                         and source["last_success"])
        scan = str(source["last_success"]) if source_ok else ""
        # Never treat a stale or failed source as proof of disappearance.
        if source_ok:
            try:
                source_ok = 0 <= (now - utc(scan)).total_seconds() <= (scan_seconds * 3 + 90)
            except ValueError:
                source_ok = False
        active = conn.execute(
            "SELECT kind,target,notifications FROM presence_subscriptions WHERE enabled=1"
        ).fetchall()
        for item in active:
            kind, target = item["kind"], item["target"]
            existing = conn.execute(
                "SELECT * FROM presence_states WHERE kind=? AND target=?", (kind, target)
            ).fetchone()
            if existing is None:
                with conn:
                    conn.execute(
                        """INSERT OR IGNORE INTO presence_states
                        (kind,target,state,reason) VALUES(?,?,'unknown','not_checked')""",
                        (kind, target),
                    )
                existing = conn.execute(
                    "SELECT * FROM presence_states WHERE kind=? AND target=?", (kind, target)
                ).fetchone()
            if not source_ok:
                with conn:
                    conn.execute(
                        """UPDATE presence_states SET state='unknown',reason='source_unavailable'
                        WHERE kind=? AND target=?""", (kind, target)
                    )
                continue
            if existing["last_sample_at"] == scan:
                continue  # No new global scan: never count the same result again.
            if kind == "mac":
                found = conn.execute(
                    """SELECT 1 FROM lan_positive lp
                       JOIN devices d ON d.id=lp.device_id
                       WHERE d.mac=? AND lp.last_seen>=? LIMIT 1""", (target, scan)
                ).fetchone() is not None
            else:
                found = conn.execute(
                    """SELECT 1 FROM ipv4_evidence
                       WHERE ipv4=? AND source='arp' AND state='observed'
                       AND last_seen>=? LIMIT 1""", (target, scan)
                ).fetchone() is not None
            successes = (int(existing["successes"]) + 1) if found else 0
            failures = (int(existing["failures"]) + 1) if not found else 0
            successes = min(successes, needed_up)
            failures = min(failures, needed_down)
            previous = existing["last_confirmed"]
            accepted = (found and successes >= needed_up) or (
                not found and failures >= needed_down
            )
            current = ("present" if kind == "mac" else "reachable") if found else (
                "absent" if kind == "mac" else "unreachable"
            )
            new_confirmed = current if accepted else previous
            state = new_confirmed or "unknown"
            reason = ("confirmed_by_arp" if found else "missing_from_successful_arp_scans")
            positive_at = scan if found else existing["last_positive"]
            changed = bool(accepted and previous and previous != current)
            changed_at = scan if changed else existing["last_changed"]
            with conn:
                conn.execute(
                    """UPDATE presence_states SET state=?,last_confirmed=?,last_sample_at=?,
                    last_check=?,last_positive=?,last_changed=?,successes=?,failures=?,reason=?
                    WHERE kind=? AND target=?""",
                    (state, new_confirmed, scan, scan, positive_at, changed_at,
                     successes, failures, reason, kind, target),
                )
                if changed:
                    suffix = ("present" if found else "absent") if kind == "mac" else (
                        "reachable" if found else "unreachable"
                    )
                    event_id = str(uuid5(
                        NAMESPACE_URL,
                        f"dh_network_app:presence:{kind}:{target}:{scan}:{previous}:{current}",
                    ))
                    event = {
                        "schema_version": 2,
                        "event_id": event_id,
                        "event_type": f"tracked_device_{suffix}",
                        "observed_at": scan,
                        "check_method": "discovery_arp",
                        "detection_source": "LAN ARP",
                        "watch_id": f"{kind}:{target}",
                        "previous": previous,
                        "current": current,
                        "reason": reason,
                        "consecutive_successes": successes,
                        "consecutive_failures": failures,
                        "notifications_requested": bool(item["notifications"]),
                        kind: target,
                    }
                    payload = json.dumps(event, ensure_ascii=False, separators=(",", ":"))
                    conn.execute(
                        """INSERT OR IGNORE INTO presence_outbox
                        (event_id,kind,target,occurred_at,payload_json)
                        VALUES(?,?,?,?,?)""",
                        (event_id, kind, target, scan, payload),
                    )
                    conn.execute(
                        """INSERT OR IGNORE INTO event_delivery_log
                        (event_id,event_type,occurred_at,status,payload_json)
                        VALUES(?,?,?,'queued',?)""",
                        (event_id, event["event_type"], scan, payload),
                    )
                    conn.execute(
                        "DELETE FROM event_delivery_log WHERE event_id NOT IN "
                        "(SELECT event_id FROM event_delivery_log ORDER BY occurred_at DESC LIMIT 3000)"
                    )

    def publish(self, conn: sqlite3.Connection, transport: Any) -> None:
        if not transport.connected.is_set():
            return
        pending = conn.execute(
            """SELECT event_id,kind,target,payload_json FROM presence_outbox
            ORDER BY occurred_at,event_id LIMIT 32"""
        ).fetchall()
        for row in pending:
            # A subscription removed since generation must not emit obsolete alerts.
            live = conn.execute(
                """SELECT 1 FROM presence_subscriptions
                WHERE kind=? AND target=? AND enabled=1""",
                (row["kind"], row["target"]),
            ).fetchone()
            if live is None:
                with conn:
                    conn.execute("DELETE FROM presence_outbox WHERE event_id=?", (row["event_id"],))
                    conn.execute("DELETE FROM event_delivery_log WHERE event_id=? AND status='queued'", (row["event_id"],))
                continue
            ok = transport.publish_checked(ROOT + "/event", row["payload_json"], False)
            with conn:
                conn.execute(
                    """UPDATE event_delivery_log SET attempts=attempts+1,
                    status=?,published_at=CASE WHEN ? THEN ? ELSE published_at END
                    WHERE event_id=?""",
                    ("broker_acked" if ok else "retrying", int(ok),
                     datetime.now(timezone.utc).isoformat() if ok else "", row["event_id"]),
                )
                if ok:
                    conn.execute("DELETE FROM presence_outbox WHERE event_id=?", (row["event_id"],))
            if not ok:
                return
