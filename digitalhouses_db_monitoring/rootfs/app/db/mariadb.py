from __future__ import annotations

from typing import Any

import pymysql

from config import DatabaseConfig
from db.base import DatabaseAdapter


class MariaDBAdapter(DatabaseAdapter):
    def __init__(self, config: DatabaseConfig) -> None:
        self.config = config

    def _connect(self):
        return pymysql.connect(
            host=self.config.host,
            port=self.config.port,
            database=self.config.database,
            user=self.config.username,
            password=self.config.password,
            connect_timeout=10,
            read_timeout=30,
            write_timeout=30,
            autocommit=True,
            charset='utf8mb4',
        )

    def _one(self, sql: str, params: tuple[Any, ...] = ()) -> Any:
        connection = self._connect()
        try:
            with connection.cursor() as cursor:
                cursor.execute(sql, params)
                row = cursor.fetchone()
                return row[0] if row else None
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
            'db_size_bytes': self._one(
                'SELECT COALESCE(SUM(data_length + index_length), 0) '
                'FROM information_schema.tables WHERE table_schema = DATABASE()'
            ),
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
            'db_name': self._one('SELECT DATABASE()'),
            'db_user': self._one('SELECT CURRENT_USER()'),
            'db_version': self._one('SELECT VERSION()'),
        }
