"""Explicit 0.1.11 pilot permission contract and denied privilege escalation."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from validators.common import ValidationError
from validators.products.presence_app import validate_presence_network_policy


def approved():
    return {
        "host_network": True, "privileged": ["NET_RAW"], "ingress": True,
        "ingress_port": 8099, "panel_admin": False,
    }


class PresencePrivilegedPilotTests(unittest.TestCase):
    def test_exactly_approved_0111_pilot_rights_pass(self):
        validate_presence_network_policy(approved(), "0.1.11")

    def test_admin_debug_patch_0112_reuses_exact_same_rights(self):
        validate_presence_network_policy(approved(), "0.1.12")

    def test_0113_uses_unchanged_approved_network_rights(self):
        validate_presence_network_policy(approved(), "0.1.13")

    def test_wifi_positive_only_0114_uses_same_narrow_privileges(self):
        validate_presence_network_policy(approved(), "0.1.14")

    def test_wifi_notifications_0115_keep_same_minimal_network_rights(self):
        validate_presence_network_policy(approved(), "0.1.15")

    def test_0116_preserves_exact_previous_network_rights(self):
        validate_presence_network_policy(approved(), "0.1.16")

    def test_0117_uses_same_exact_arp_privileges_no_escalation(self):
        validate_presence_network_policy(approved(), "0.1.17")

    def test_0118_notification_switches_use_same_exact_rights(self):
        validate_presence_network_policy(approved(), "0.1.18")

    def test_0119_log_hygiene_keeps_identical_network_rights(self):
        validate_presence_network_policy(approved(), "0.1.19")

    def test_0120_branding_changes_preserve_approved_minimal_rights(self):
        validate_presence_network_policy(approved(), "0.1.20")

    def test_old_gps_only_0110_does_not_require_raw_sockets(self):
        validate_presence_network_policy({}, "0.1.10")

    def test_refuse_privilege_change_in_any_unreviewed_version(self):
        with self.assertRaisesRegex(ValidationError, "Unreviewed Presence version"):
            validate_presence_network_policy(approved(), "0.1.21")

    def test_disallow_net_admin_full_access_docker_api_and_disabled_apparmor(self):
        for additional in (
            {"privileged": ["NET_RAW", "NET_ADMIN"]},
            {"privileged": ["SYS_ADMIN"]},
            {"full_access": True},
            {"docker_api": True},
            {"apparmor": False},
            {"hassio_role": "manager"},
            {"host_pid": True},
            {"map": ["homeassistant_config:rw"]},
        ):
            with self.subTest(additional=additional):
                with self.assertRaises(ValidationError):
                    validate_presence_network_policy({**approved(), **additional}, "0.1.11")

    def test_disallow_any_public_ports_or_disabled_ingress(self):
        for extra in (
            {"ingress": False},
            {"ingress_port": 9999},
            {"panel_admin": True},
            {"ports": {"8099/tcp": 8099}},
            {"privileged": []},
            {"host_network": False},
        ):
            with self.subTest(extra=extra):
                with self.assertRaises(ValidationError):
                    validate_presence_network_policy({**approved(), **extra}, "0.1.11")


if __name__ == "__main__":
    unittest.main()
