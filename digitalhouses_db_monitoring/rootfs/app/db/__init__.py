from __future__ import annotations

from config import DatabaseConfig
from db.base import DatabaseAdapter


def create_adapter(config: DatabaseConfig) -> DatabaseAdapter:
    if config.engine == 'postgresql':
        from db.postgres import PostgresAdapter
        return PostgresAdapter(config)
    if config.engine == 'mariadb':
        from db.mariadb import MariaDBAdapter
        return MariaDBAdapter(config)
    raise ValueError(f'Unsupported database engine: {config.engine}')
