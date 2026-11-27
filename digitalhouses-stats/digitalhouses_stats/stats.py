from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.orm import Session

from .products import PRODUCTS, PRODUCT_SUCCESSORS, canonical_product, product_name


# Read-only normalized relations. A shared UUID within one lineage is one
# installation; distinct UUIDs remain distinct even if they share a country.
_NORMALIZED = """
WITH lineage AS (
    SELECT key AS original, value AS canonical
    FROM jsonb_each_text(CAST(:lineage AS jsonb))
),
normalized_installations AS (
    SELECT coalesce(l.canonical, i.product) AS product, i.installation_id,
           min(i.created_at) AS created_at
    FROM installations i LEFT JOIN lineage l ON l.original = i.product
    GROUP BY 1, 2
),
normalized_heartbeats AS (
    SELECT coalesce(l.canonical, h.product) AS product, h.installation_id,
           h.product AS original_product, h.id, h.received_at,
           h.version, h.country
    FROM heartbeats h LEFT JOIN lineage l ON l.original = h.product
)
"""


def _execute(db: Session, sql: str, params: dict | None = None, *, raw: bool = False):
    sql = sql.lstrip()
    if sql.startswith("WITH "):
        sql = _NORMALIZED + ", " + sql[5:]
    else:
        sql = _NORMALIZED + sql
    return db.execute(text(sql), {"lineage": json.dumps({} if raw else PRODUCT_SUCCESSORS), **(params or {})})


def _rows(result) -> list[dict[str, object]]:
    return [dict(row) for row in result.mappings().all()]


def summary(db: Session) -> dict[str, object]:
    row = _execute(db,
            """
            SELECT
                (SELECT count(*) FROM normalized_installations) AS observed_installations,
                (
                    SELECT count(DISTINCT (product, installation_id))
                    FROM normalized_heartbeats
                    WHERE received_at >= now() - interval '24 hours'
                ) AS active_24h,
                (
                    SELECT count(DISTINCT (product, installation_id))
                    FROM normalized_heartbeats
                    WHERE received_at >= now() - interval '7 days'
                ) AS active_7d,
                (
                    SELECT count(DISTINCT (product, installation_id))
                    FROM normalized_heartbeats
                    WHERE received_at >= now() - interval '30 days'
                ) AS active_30d,
                (SELECT count(*) FROM normalized_heartbeats) AS heartbeats,
                (SELECT max(received_at) FROM normalized_heartbeats) AS last_heartbeat
            """
    ).mappings().one()

    last_heartbeat = row["last_heartbeat"]
    return {
        "observed_installations": int(row["observed_installations"]),
        "active_24h": int(row["active_24h"]),
        "active_7d": int(row["active_7d"]),
        "active_30d": int(row["active_30d"]),
        "heartbeats": int(row["heartbeats"]),
        "last_heartbeat": (
            last_heartbeat.isoformat() if last_heartbeat is not None else None
        ),
    }


def products(db: Session, *, raw: bool = False) -> list[dict[str, object]]:
    result = _execute(db,
            """
            WITH last_seen AS (
                SELECT
                    product,
                    installation_id,
                    max(received_at) AS last_seen
                FROM normalized_heartbeats
                GROUP BY product, installation_id
            )
            SELECT
                i.product,
                count(*) AS observed_installations,
                count(*) FILTER (
                    WHERE l.last_seen >= now() - interval '24 hours'
                ) AS active_24h,
                count(*) FILTER (
                    WHERE l.last_seen >= now() - interval '7 days'
                ) AS active_7d,
                count(*) FILTER (
                    WHERE l.last_seen >= now() - interval '30 days'
                ) AS active_30d
            FROM normalized_installations AS i
            LEFT JOIN last_seen AS l
              ON l.product = i.product
             AND l.installation_id = i.installation_id
            GROUP BY i.product
            """, raw=raw
    )
    observed = {row["product"]: row for row in _rows(result)}

    rows: list[dict[str, object]] = []
    for product in PRODUCTS:
        if not raw and product.superseded_by is not None:
            continue
        row = observed.get(product.identifier)
        rows.append(
            {
                "product": product.identifier,
                "name": product.display_name,
                "observed_installations": (
                    int(row["observed_installations"]) if row is not None else 0
                ),
                "active_24h": int(row["active_24h"]) if row is not None else 0,
                "active_7d": int(row["active_7d"]) if row is not None else 0,
                "active_30d": int(row["active_30d"]) if row is not None else 0,
            }
        )
    return rows


def versions(
    db: Session,
    *,
    product: str | None = None,
) -> list[dict[str, object]]:
    result = _execute(db,
            """
            WITH latest AS (
                SELECT DISTINCT ON (product, installation_id)
                    product,
                    installation_id,
                    version,
                    original_product,
                    received_at
                FROM normalized_heartbeats
                WHERE (CAST(:product AS text) IS NULL OR product = CAST(:product AS text))
                ORDER BY
                    product,
                    installation_id,
                    received_at DESC,
                    id DESC
            )
            SELECT
                product,
                version,
                original_product <> product AS legacy,
                count(*) AS observed_installations,
                count(*) FILTER (
                    WHERE received_at >= now() - interval '7 days'
                ) AS active_7d,
                count(*) FILTER (
                    WHERE received_at >= now() - interval '30 days'
                ) AS active_30d
            FROM latest
            GROUP BY product, version, legacy
            ORDER BY product, observed_installations DESC, version
            """,
        {"product": canonical_product(product) if product else None},
    )
    rows = _rows(result)
    for row in rows:
        if not row["legacy"]:
            row.pop("legacy")
        row["name"] = product_name(str(row["product"]))
        for key in ("observed_installations", "active_7d", "active_30d"):
            row[key] = int(row[key])
    return rows


def countries(
    db: Session,
    *,
    product: str | None = None,
) -> list[dict[str, object]]:
    # Group the latest report from each installation by both country and
    # product, so totals and the per-product breakdown share identical rules.
    result = _execute(db,
            """
            WITH latest AS (
                SELECT DISTINCT ON (product, installation_id)
                    product,
                    installation_id,
                    country,
                    received_at
                FROM normalized_heartbeats
                WHERE (CAST(:product AS text) IS NULL OR product = CAST(:product AS text))
                ORDER BY
                    product,
                    installation_id,
                    received_at DESC,
                    id DESC
            ),
            first_seen AS (
                SELECT country, min(received_at) AS first_seen
                FROM normalized_heartbeats
                GROUP BY country
            )
            SELECT
                l.country,
                l.product,
                f.first_seen,
                count(*) AS observed_installations,
                count(*) FILTER (
                    WHERE l.received_at >= now() - interval '7 days'
                ) AS active_7d,
                count(*) FILTER (
                    WHERE l.received_at >= now() - interval '30 days'
                ) AS active_30d
            FROM latest AS l
            JOIN first_seen AS f ON f.country = l.country
            GROUP BY l.country, l.product, f.first_seen
            ORDER BY l.country, observed_installations DESC, l.product
            """,
        {"product": canonical_product(product) if product else None},
    )
    by_country: dict[str, dict[str, object]] = {}
    counters = ("observed_installations", "active_7d", "active_30d")
    for row in _rows(result):
        country = str(row["country"])
        group = by_country.setdefault(
            country,
            {
                "country": country,
                "first_seen": row["first_seen"].isoformat(),
                "observed_installations": 0,
                "active_7d": 0,
                "active_30d": 0,
                "products": [],
            },
        )
        entry: dict[str, object] = {
            "product": str(row["product"]),
            "name": product_name(str(row["product"])),
        }
        for counter in counters:
            count = int(row[counter])
            entry[counter] = count
            group[counter] += count
        group["products"].append(entry)

    return sorted(
        by_country.values(),
        key=lambda row: (-int(row["observed_installations"]), str(row["country"])),
    )


def history(
    db: Session,
    *,
    days: int,
    product: str | None = None,
) -> list[dict[str, object]]:
    result = _execute(db,
            """
            WITH series AS (
                SELECT generate_series(
                    CURRENT_DATE - (:days - 1),
                    CURRENT_DATE,
                    interval '1 day'
                )::date AS day
            ),
            daily AS (
                SELECT
                    (received_at AT TIME ZONE 'UTC')::date AS day,
                    count(DISTINCT (product, installation_id))
                        AS active_installations,
                    count(*) AS heartbeats
                FROM normalized_heartbeats
                WHERE received_at >= (
                    CURRENT_DATE - (:days - 1)
                )::timestamptz
                  AND received_at < (
                    CURRENT_DATE + 1
                )::timestamptz
                  AND (CAST(:product AS text) IS NULL OR product = CAST(:product AS text))
                GROUP BY (received_at AT TIME ZONE 'UTC')::date
            )
            SELECT
                s.day,
                coalesce(d.active_installations, 0) AS active_installations,
                coalesce(d.heartbeats, 0) AS heartbeats
            FROM series AS s
            LEFT JOIN daily AS d USING (day)
            ORDER BY s.day
            """,
        {"days": days, "product": canonical_product(product) if product else None},
    )
    rows = _rows(result)
    for row in rows:
        row["day"] = row["day"].isoformat()
        row["active_installations"] = int(row["active_installations"])
        row["heartbeats"] = int(row["heartbeats"])
    return rows


def installation_history(db: Session, *, days: int = 7) -> list[dict[str, object]]:
    """Total registered vs. active in the preceding 7 days, as of each UTC day.

    A row represents the end of a UTC day. Today ends at the current instant,
    not an assumed future midnight. Only currently retained registrations can
    be reconstructed: explicitly deleted installations have been removed.
    """
    result = _execute(db,
            """
            WITH days AS (
                SELECT generate_series(
                    (now() AT TIME ZONE 'UTC')::date - (:days - 1),
                    (now() AT TIME ZONE 'UTC')::date,
                    interval '1 day'
                )::date AS day
            ),
            cutoffs AS (
                SELECT
                    day,
                    least(
                        (day + interval '1 day') AT TIME ZONE 'UTC',
                        now()
                    ) AS cutoff
                FROM days
            )
            SELECT
                c.day,
                (
                    SELECT count(*)
                    FROM normalized_installations i
                    WHERE i.created_at < c.cutoff
                ) AS total_installations,
                (
                    SELECT count(DISTINCT (h.product, h.installation_id))
                    FROM normalized_heartbeats h
                    WHERE h.received_at >= c.cutoff - interval '7 days'
                      AND h.received_at < c.cutoff
                ) AS active_installations
            FROM cutoffs c
            ORDER BY c.day
            """,
        {"days": days},
    )
    return [
        {
            "day": row["day"].isoformat(),
            "total_installations": int(row["total_installations"]),
            "active_installations": int(row["active_installations"]),
        }
        for row in _rows(result)
    ]
