import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sync_web import make_server


class DummyEngine:
    def __init__(self):
        self.called = 0

    def plan(self):
        return {"blocked": False, "changes": 0, "fingerprint": "a" * 64,
                "items": [], "locale": "ru"}

    def last_transaction(self):
        return None

    def apply(self, fingerprint, *, approved):
        self.called += 1
        return {"status": "applied"}


class UIConstructorTests(unittest.TestCase):
    def test_admin_ingress_server_is_local_and_inert_until_request(self):
        dummy = DummyEngine()
        server = make_server(dummy, allow_changes=False, port=0)
        try:
            self.assertEqual(dummy.called, 0)
            self.assertEqual(server.server_address[0], "0.0.0.0")
        finally:
            server.server_close()


if __name__ == "__main__":
    unittest.main()
