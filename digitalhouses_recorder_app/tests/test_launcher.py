"""Regression tests for the Bashio launcher contract."""

from __future__ import annotations

import os
import subprocess
import unittest
from pathlib import Path


RUN_SCRIPT = Path(__file__).resolve().parents[1] / "rootfs" / "run.sh"


class LauncherTests(unittest.TestCase):
    def test_deprecated_addon_calls_are_not_used(self):
        source = RUN_SCRIPT.read_text(encoding="utf-8")
        self.assertNotIn("bashio::addon.", source)
        self.assertIn("bashio::app.options", source)
        self.assertIn("bashio::app.option 'poll'", source)
        self.assertIn("bashio::app.option 'timezone'", source)

    def test_mysql_supervisor_lookup_is_only_used_when_needed(self):
        source = RUN_SCRIPT.read_text(encoding="utf-8")
        marker = 'export MYSQL_SERVICE_HOST=""'
        start = source.index(marker)
        end = source.index("exec python3 /app/app.py", start)
        mysql_block = source[start:end]

        stubs = """
bashio::config() {
    if [[ "$1" == "database_type" ]]; then
        printf '%s\\n' "$TEST_DATABASE_TYPE"
    else
        printf '%s\\n' "$TEST_MARIADB_CONNECTION"
    fi
}
bashio::services() {
    printf 'LOOKUP:%s:%s\\n' "$1" "$2" >&2
    case "$2" in
        host) printf 'mysql.local\\n' ;;
        port) printf '3306\\n' ;;
        username) printf 'hauser\\n' ;;
        password) printf 'secret\\n' ;;
    esac
}
bashio::log.info() { :; }
"""
        for database_type, connection, should_query in (
            ("postgresql", "supervisor", False),
            ("mariadb", "manual", False),
            ("mariadb", "supervisor", True),
        ):
            with self.subTest(database_type=database_type, connection=connection):
                env = os.environ.copy()
                env.update(
                    TEST_DATABASE_TYPE=database_type,
                    TEST_MARIADB_CONNECTION=connection,
                )
                run = subprocess.run(
                    [
                        "bash",
                        "-c",
                        chr(10).join(
                            [stubs, mysql_block, 'echo "MYSQL_HOST=$MYSQL_SERVICE_HOST"']
                        ),
                    ],
                    env=env,
                    capture_output=True,
                    text=True,
                    check=True,
                )
                self.assertEqual("LOOKUP:mysql:port" in run.stderr, should_query)
                expected_host = "mysql.local" if should_query else ""
                self.assertIn(f"MYSQL_HOST={expected_host}", run.stdout)


if __name__ == "__main__":
    unittest.main()
