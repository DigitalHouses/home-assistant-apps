from __future__ import annotations

import json
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Mapping

from .app import CollectorSample
from .collectors.disks import stable_disk_id
from .collectors.smart import SmartSnapshot, parse_smart_json
from .daily_disk_stats import DailyDiskStats, update_daily_stats
from .disk_health import evaluate_disk_health
from .production import ProductionCollectors, _checkpoint, _run
from .publish_policy import MetricValue

MISSING_CONFIRMATIONS = 3


def boot_time_iso(epoch: int | float | None) -> str | None:
    if not isinstance(epoch, (int, float)) or isinstance(epoch, bool):
        return None
    try:
        return datetime.fromtimestamp(float(epoch), timezone.utc).isoformat()
    except (OverflowError, OSError, ValueError):
        return None


def parse_primary_ip(text: str) -> str | None:
    try:
        routes = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(routes, list):
        return None
    for route in routes:
        if not isinstance(route, Mapping):
            continue
        value = route.get("prefsrc")
        if isinstance(value, str) and value.strip():
            return value.strip()
        value = route.get("src")
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _metric(value: object, policy: str) -> MetricValue:
    return MetricValue(value=value, policy=policy)


class ResilientProductionCollectors(ProductionCollectors):
    """Phase-1 collectors with per-disk SMART fault isolation.

    An authoritative smartctl scan may remove a disk only after three
    consecutive missing scans. A failed SMART read keeps the last successful
    disk payload but marks only that disk unavailable.
    """

    def host(self) -> CollectorSample:
        sample = super().host()
        if not isinstance(sample.data, Mapping):
            return sample
        data = dict(sample.data)
        data["boot_time"] = boot_time_iso(data.get("boot_time_epoch"))

        primary_ip = None
        try:
            primary_ip = parse_primary_ip(
                _run(["ip", "-j", "route", "get", "1.1.1.1"], timeout=5)
            )
        except Exception:
            primary_ip = None
        data["primary_ip"] = primary_ip

        metrics = dict(sample.metrics)
        if data["boot_time"] is not None:
            metrics["boot_time"] = _metric(data["boot_time"], "discrete")
        if primary_ip is not None:
            metrics["primary_ip"] = _metric(primary_ip, "discrete")
        return CollectorSample(data=data, metrics=metrics)

    def fans(self) -> CollectorSample:
        sample = super().fans()
        if not isinstance(sample.data, Mapping):
            return sample

        fan_items = dict(sample.data)
        count = len(fan_items)
        detected = count > 0
        data: dict[str, object] = {
            "detected": detected,
            "count": count,
            "status": "Detected" if detected else "Not detected",
            **fan_items,
        }
        metrics = dict(sample.metrics)
        metrics["detected"] = _metric(detected, "discrete")
        metrics["count"] = _metric(count, "discrete")
        return CollectorSample(data=data, metrics=metrics)

    def _smart_scan(self) -> tuple[tuple[str, ...], ...]:
        text = _run(["smartctl", "--scan-open"], timeout=20)
        return self._smart_scan_entries(text)

    def _smart_read(self, entry: tuple[str, ...]) -> str:
        return _run(["smartctl", "-a", "-j", *entry], timeout=25)

    @staticmethod
    def _daily_from_mapping(value: object) -> DailyDiskStats | None:
        if not isinstance(value, Mapping):
            return None
        try:
            return DailyDiskStats(**dict(value))
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _metrics_for_disk(
        disk_id: str,
        data: Mapping[str, object],
        snapshot: SmartSnapshot | None,
    ) -> dict[str, MetricValue]:
        result: dict[str, MetricValue] = {
            f"{disk_id}.available": _metric(bool(data.get("available")), "discrete")
        }
        if not data.get("available") or snapshot is None:
            return result

        health = data.get("health_state")
        if health is not None:
            result[f"{disk_id}.health"] = _metric(health, "discrete")

        for field in (
            "media_errors",
            "reallocated_sectors",
            "pending_sectors",
            "offline_uncorrectable",
            "uncorrectable_errors",
            "program_failures",
            "erase_failures",
            "runtime_bad_blocks",
            "unsafe_shutdowns",
        ):
            value = getattr(snapshot, field)
            if value is not None:
                result[f"{disk_id}.{field}"] = _metric(value, "counter")

        if snapshot.temperature_c is not None:
            result[f"{disk_id}.temperature_c"] = _metric(
                snapshot.temperature_c, "temperature_c"
            )
        if snapshot.wear_used_percent is not None:
            result[f"{disk_id}.wear_used_percent"] = _metric(
                snapshot.wear_used_percent, "discrete"
            )
        return result

    def smart(self) -> CollectorSample:
        entries = self._smart_scan()
        persisted = self.disk_state_store.load()

        checkpoints_raw = persisted.get("checkpoints", {})
        daily_raw = persisted.get("daily", {})
        path_map_raw = persisted.get("path_map", {})
        inventory_raw = persisted.get("inventory", {})
        last_data_raw = persisted.get("last_data", {})
        missing_raw = persisted.get("missing_counts", {})

        checkpoints = dict(checkpoints_raw) if isinstance(checkpoints_raw, Mapping) else {}
        daily = dict(daily_raw) if isinstance(daily_raw, Mapping) else {}
        path_map = dict(path_map_raw) if isinstance(path_map_raw, Mapping) else {}
        inventory = dict(inventory_raw) if isinstance(inventory_raw, Mapping) else {}
        last_data = dict(last_data_raw) if isinstance(last_data_raw, Mapping) else {}
        missing_counts = dict(missing_raw) if isinstance(missing_raw, Mapping) else {}

        output: dict[str, dict[str, object]] = {}
        metrics: dict[str, MetricValue] = {}
        scan_paths: set[str] = set()
        present_ids: set[str] = set()

        for entry in entries:
            device = entry[0]
            scan_paths.add(device)
            prior_id = path_map.get(device)
            try:
                raw = self._smart_read(entry)
                snapshot = parse_smart_json(json.loads(raw), device)
                disk_id = stable_disk_id(
                    wwn=snapshot.wwn,
                    serial=snapshot.serial,
                    path=device,
                    model=snapshot.model,
                    size_bytes=snapshot.capacity_bytes,
                )
                prior = checkpoints.get(disk_id)
                prior = dict(prior) if isinstance(prior, Mapping) else None
                health = evaluate_disk_health(snapshot, prior)
                current_daily = self._daily_from_mapping(daily.get(disk_id))
                daily_stats, _completed = update_daily_stats(
                    current_daily, snapshot, datetime.now().astimezone()
                )
                item: dict[str, object] = {
                    **asdict(snapshot),
                    "disk_id": disk_id,
                    "available": True,
                    "error": None,
                    "health_state": health.state.value,
                    "health_reasons": list(health.reasons),
                    "recommendation": health.recommendation,
                    "daily": asdict(daily_stats),
                }
                output[disk_id] = item
                metrics.update(self._metrics_for_disk(disk_id, item, snapshot))

                checkpoints[disk_id] = _checkpoint(snapshot)
                daily[disk_id] = asdict(daily_stats)
                path_map[device] = disk_id
                inventory[disk_id] = {"path": device}
                last_data[disk_id] = dict(item)
                missing_counts[disk_id] = 0
                present_ids.add(disk_id)

                if isinstance(prior_id, str) and prior_id != disk_id:
                    path_map = {
                        key: value for key, value in path_map.items()
                        if value != prior_id or key == device
                    }
            except Exception as exc:
                disk_id = prior_id if isinstance(prior_id, str) else None
                previous_item = last_data.get(disk_id) if disk_id else None
                if disk_id and isinstance(previous_item, Mapping):
                    item = dict(previous_item)
                    item["available"] = False
                    item["error"] = f"{type(exc).__name__}: {exc}"
                    output[disk_id] = item
                    metrics.update(self._metrics_for_disk(disk_id, item, None))
                    missing_counts[disk_id] = 0
                    present_ids.add(disk_id)

        for disk_id, raw_inventory in list(inventory.items()):
            if disk_id in present_ids:
                continue
            path = None
            if isinstance(raw_inventory, Mapping):
                raw_path = raw_inventory.get("path")
                if isinstance(raw_path, str):
                    path = raw_path

            if path is not None and path in scan_paths:
                continue

            count = int(missing_counts.get(disk_id, 0) or 0) + 1
            missing_counts[disk_id] = count
            if count < MISSING_CONFIRMATIONS:
                previous_item = last_data.get(disk_id)
                if isinstance(previous_item, Mapping):
                    item = dict(previous_item)
                    item["available"] = False
                    item["error"] = "disk missing from authoritative SMART scan"
                    output[str(disk_id)] = item
                    metrics.update(
                        self._metrics_for_disk(str(disk_id), item, None)
                    )
                continue

            inventory.pop(disk_id, None)
            checkpoints.pop(disk_id, None)
            daily.pop(disk_id, None)
            last_data.pop(disk_id, None)
            missing_counts.pop(disk_id, None)
            path_map = {
                key: value for key, value in path_map.items() if value != disk_id
            }

        self.disk_state_store.save(
            {
                "checkpoints": checkpoints,
                "daily": daily,
                "path_map": path_map,
                "inventory": inventory,
                "last_data": last_data,
                "missing_counts": missing_counts,
            }
        )
        return CollectorSample(data=output, metrics=metrics)
