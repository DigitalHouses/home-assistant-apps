"""Negative and positive checks for Supervisor environment preflight."""
import importlib.util
import unittest
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[1] / "rootfs/app/preflight.py"
spec = importlib.util.spec_from_file_location("dh_network_preflight", SCRIPT)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


class TestPreflight(unittest.TestCase):
    def setUp(self):
        self.env = {"APP_VERSION": "0.1.5", "DH_PORT": "8099", "DH_DB": "/data/network.sqlite3", "DH_INTERVAL": "60", "DH_SCAN_INTERVAL": "180", "DH_MDNS_INTERVAL": "300", "SUPERVISOR_TOKEN": "test-token"}

    def test_valid_configuration(self):
        module.validate_environment(self.env)

    def test_missing_version_is_contract_failure(self):
        self.env.pop("APP_VERSION")
        with self.assertRaises(ValueError):
            module.validate_environment(self.env)

    def test_invalid_port_is_contract_failure(self):
        self.env["DH_PORT"] = "unknown"
        with self.assertRaises(ValueError):
            module.validate_environment(self.env)

    def test_invalid_lan_scan_interval(self):
        self.env["DH_SCAN_INTERVAL"] = "0"
        with self.assertRaises(ValueError):
            module.validate_environment(self.env)

    def test_invalid_mdns_interval(self):
        self.env["DH_MDNS_INTERVAL"] = "10"
        with self.assertRaises(ValueError):
            module.validate_environment(self.env)

    def test_missing_ha_access_is_contract_failure(self):
        self.env.pop("SUPERVISOR_TOKEN")
        with self.assertRaises(ValueError):
            module.validate_environment(self.env)

    def test_invalid_interval_is_contract_failure(self):
        self.env["DH_INTERVAL"] = "10"
        with self.assertRaises(ValueError):
            module.validate_environment(self.env)

    def test_nonpersistent_database_is_contract_failure(self):
        self.env["DH_DB"] = "/tmp/network.sqlite3"
        with self.assertRaises(ValueError):
            module.validate_environment(self.env)


if __name__ == "__main__":
    unittest.main()
