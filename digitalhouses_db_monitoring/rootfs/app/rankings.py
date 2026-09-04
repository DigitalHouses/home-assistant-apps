from __future__ import annotations

from datetime import datetime
from typing import Any, Iterable
from zoneinfo import ZoneInfo

TOP_ENTITIES_24H_INTERVAL_SECONDS = 3600
TOP_ENTITIES_ALL_TIME_INTERVAL_SECONDS = 86400


def build_top_entities_snapshot(
    rows: Iterable[tuple[str, int]],
    period: str,
    generated_ts: float,
    timezone_name: str,
) -> dict[str, Any]:
    items = [
        {'entity_id': str(entity_id), 'records': int(records)}
        for entity_id, records in rows
    ][:10]
    generated_at = datetime.fromtimestamp(float(generated_ts), ZoneInfo(timezone_name)).isoformat()
    return {
        'top_entity': items[0]['entity_id'] if items else None,
        'top_records': items[0]['records'] if items else 0,
        'generated_at': generated_at,
        'period': period,
        'top_10': items,
    }
