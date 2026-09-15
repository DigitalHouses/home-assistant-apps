import pytest

from app.ups_control import NutControlError, verify_nut_credentials


class FakeSocket:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.writes = []
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.closed = True

    def makefile(self, mode):
        assert mode == "rwb"
        return self

    def write(self, data):
        self.writes.append(data)
        return len(data)

    def flush(self):
        return None

    def readline(self):
        return next(self.responses)


def test_verify_nut_credentials_uses_safe_connection_local_auth_probe():
    sock = FakeSocket([b"OK\n", b"OK\n", b"OK\n", b"OK Goodbye\n"])
    connections = []

    def connector(address, timeout):
        connections.append((address, timeout))
        return sock

    verify_nut_credentials(
        host="127.0.0.1",
        port=3493,
        username="dh_primary_user",
        password="super-secret",
        timeout_seconds=3.0,
        connector=connector,
    )

    assert connections == [(('127.0.0.1', 3493), 3.0)]
    assert sock.writes == [
        b"USERNAME dh_primary_user\n",
        b"PASSWORD super-secret\n",
        b"SET TRACKING OFF\n",
        b"LOGOUT\n",
    ]
    assert sock.closed is True


def test_verify_nut_credentials_fails_closed_without_leaking_secret():
    sock = FakeSocket([b"OK\n", b"OK\n", b"ERR ACCESS-DENIED\n"])

    with pytest.raises(NutControlError) as exc_info:
        verify_nut_credentials(
            host="127.0.0.1",
            port=3493,
            username="dh_primary_user",
            password="super-secret",
            timeout_seconds=3.0,
            connector=lambda address, timeout: sock,
        )

    text = str(exc_info.value)
    assert "super-secret" not in text
    assert "dh_primary_user" not in text
    assert "ACCESS-DENIED" in text
