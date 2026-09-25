from __future__ import annotations

from typing import Any

import psycopg2

from config import DatabaseConfig
from db.base import DatabaseAdapter


class PostgresAdapter(DatabaseAdapter):
    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config

    def _connect(self):
        connection = psycopg2.connect(
            host=self.config.host,
            port=self.config.port,
            dbname=self.config.database,
            user=self.config.username,
            password=self.config.password,
            connect_timeout=10,
            application_name='digitalhouses_db_monitoring',
        )
        connection.autocommit = True
        with connection.cursor() as cursor:
            cursor.execute('SET statement_timeout = 30000')
        return connection

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row[0] if row else None
        finally:
            connection.close()

    def _rows(self, sql: str, params: tuple[Any, ...] = ()) -> list[tuple[Any, ...]]:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                return list(cursor.fetchall())
        finally:
            connection.close()

    def fast_metrics(self, hour_cutoff: float | None = None) -> dict[str, Any]:
        del hour_cutoff
        return {'db_last_ts': self._one('SELECT MAX(last_updated_ts) FROM states')}

    def medium_metrics(self, hour_cutoff: float) -> dict[str, Any]:
        return {
            'records_last_hour': self._one(
                'SELECT COUNT(*) FROM states WHERE last_updated_ts >= %s',
                (hour_cutoff,),
            ),
            'db_size_bytes': self._one('SELECT pg_database_size(current_database())'),
        }

    def slow_metrics(self, yesterday_start: float, today_start: float) -> dict[str, Any]:
        return {
            'db_start_ts': self._one('SELECT MIN(last_updated_ts) FROM states'),
            'records_total': self._one('SELECT COUNT(*) FROM states'),
            'records_yesterday': self._one(
                'SELECT COUNT(*) FROM states WHERE last_updated_ts >= %s AND last_updated_ts < %s',
                (yesterday_start, today_start),
            ),
        }

    def static_metrics(self) -> dict[str, Any]:
        return {
            'db_name': self._one('SELECT current_database()'),
            'db_user': self._one('SELECT current_user'),
            'db_version': self._one("SELECT substring(version() from 1 for 80)"),
        }

    def top_entities(self, since_ts: float | None) -> list[tuple[str, int]]:
        where = ''
        params: tuple[Any, ...] = ()
        if since_ts is not None:
            where = ' WHERE s.last_updated_ts >= %s'
            params = (since_ts,)
        rows = self._rows(
            'SELECT sm.entity_id, COUNT(*) AS records '
            'FROM states AS s '
            'JOIN states_meta AS sm ON sm.metadata_id = s.metadata_id'
            + where +
            ' GROUP BY sm.entity_id '
            'ORDER BY records DESC, sm.entity_id ASC '
            'LIMIT 10',
            params,
        )
        return [(str(entity_id), int(records)) for entity_id, records in rows]

    def data_directory(self) -> str:
        return str(self._one('SHOW data_directory'))
