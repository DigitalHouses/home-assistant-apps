from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session


def _rows(result) -> list[dict[str, object]]:
    return [dict(row) for row in result.mappings().all()]


def summary(db: Session) -> dict[str, int]:
    row = db.execute(
        text(
            """
            SELECT
                (SELECT count(*) FROM installations) AS observed_installations,
                (
                    SELECT count(DISTINCT (product, installation_id))
                    FROM heartbeats
                    WHERE received_at >= now() - interval '24 hours'
                ) AS active_24h,
                (
                    SELECT count(DISTINCT (product, installation_id))
                    FROM heartbeats
                    WHERE received_at >= now() - interval '7 days'
                ) AS active_7d,
                (
                    SELECT count(DISTINCT (product, installation_id))
                    FROM heartbeats
                    WHERE received_at >= now() - interval '30 days'
                ) AS active_30d,
                (SELECT count(*) FROM heartbeats) AS heartbeats
            """
        )
    ).mappings().one()
    return {key: int(value) for key, value in row.items()}


def products(db: Session) -> list[dict[str, object]]:
    result = db.execute(
        text(
            """
            WITH last_seen AS (
                SELECT
                    product,
                    installation_id,
                    max(received_at) AS last_seen
                FROM heartbeats
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
            FROM installations AS i
            LEFT JOIN last_seen AS l
              ON l.product = i.product
             AND l.installation_id = i.installation_id
            GROUP BY i.product
            ORDER BY i.product
            """
        )
    )
    rows = _rows(result)
    for row in rows:
        for key in (
            "observed_installations",
            "active_24h",
            "active_7d",
            "active_30d",
        ):
            row[key] = int(row[key])
    return rows


def versions(
    db: Session,
    *,
    product: str | None = None,
) -> list[dict[str, object]]:
    result = db.execute(
        text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (product, installation_id)
                    product,
                    installation_id,
                    version,
                    received_at
                FROM heartbeats
                WHERE (:product IS NULL OR product = :product)
                ORDER BY
                    product,
                    installation_id,
                    received_at DESC,
                    id DESC
            )
            SELECT
                product,
                version,
                count(*) AS observed_installations,
                count(*) FILTER (
                    WHERE received_at >= now() - interval '7 days'
                ) AS active_7d,
                count(*) FILTER (
                    WHERE received_at >= now() - interval '30 days'
                ) AS active_30d
            FROM latest
            GROUP BY product, version
            ORDER BY product, observed_installations DESC, version
            """
        ),
        {"product": product},
    )
    rows = _rows(result)
    for row in rows:
        for key in ("observed_installations", "active_7d", "active_30d"):
            row[key] = int(row[key])
    return rows


def countries(
    db: Session,
    *,
    product: str | None = None,
) -> list[dict[str, object]]:
    result = db.execute(
        text(
            """
            WITH latest AS (
                SELECT DISTINCT ON (product, installation_id)
                    product,
                    installation_id,
                    country,
                    received_at
                FROM heartbeats
                WHERE (:product IS NULL OR product = :product)
                ORDER BY
                    product,
                    installation_id,
                    received_at DESC,
                    id DESC
            )
            SELECT
                country,
                count(*) AS observed_installations,
                count(*) FILTER (
                    WHERE received_at >= now() - interval '7 days'
                ) AS active_7d,
                count(*) FILTER (
                    WHERE received_at >= now() - interval '30 days'
                ) AS active_30d
            FROM latest
            GROUP BY country
            ORDER BY observed_installations DESC, country
            """
        ),
        {"product": product},
    )
    rows = _rows(result)
    for row in rows:
        for key in ("observed_installations", "active_7d", "active_30d"):
            row[key] = int(row[key])
    return rows


def history(
    db: Session,
    *,
    days: int,
    product: str | None = None,
) -> list[dict[str, object]]:
    result = db.execute(
        text(
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
                FROM heartbeats
                WHERE received_at >= (
                    CURRENT_DATE - (:days - 1)
                )::timestamptz
                  AND received_at < (
                    CURRENT_DATE + 1
                )::timestamptz
                  AND (:product IS NULL OR product = :product)
                GROUP BY (received_at AT TIME ZONE 'UTC')::date
            )
            SELECT
                s.day,
                coalesce(d.active_installations, 0) AS active_installations,
                coalesce(d.heartbeats, 0) AS heartbeats
            FROM series AS s
            LEFT JOIN daily AS d USING (day)
            ORDER BY s.day
            """
        ),
        {"days": days, "product": product},
    )
    rows = _rows(result)
    for row in rows:
        row["day"] = row["day"].isoformat()
        row["active_installations"] = int(row["active_installations"])
        row["heartbeats"] = int(row["heartbeats"])
    return rows
