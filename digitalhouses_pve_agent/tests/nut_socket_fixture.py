"""Test-only socket fixture; never sends a real UPS instant command."""


class Connection:
    def __init__(self, responses=None):
        self.responses = iter(responses or (b"OK\n", b"OK\n", b"OK\n"))
        self.writes = []

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def makefile(self, mode):
        assert mode == "rwb"
        return self

    def write(self, value):
        self.writes.append(value)
        return len(value)

    def flush(self):
        pass

    def readline(self, maxlen=1024):
        return next(self.responses, b"")


def connection_factory(responses=None):
    connections = []
    addresses = []

    def connector(address, timeout):
        addresses.append((address, timeout))
        conn = Connection(responses)
        connections.append(conn)
        return conn

    return connector, connections, addresses
