import unittest
from gates import Gates, Z2MProbe

class GateTests(unittest.TestCase):
    def test_fresh_evidence_required_and_expiry(self):
        g = Gates(require_ha=True, require_z2m=True, ttl=15)
        self.assertFalse(g.states(0)["system_ready"])
        g.prove("mqtt_ready", 0)
        g.prove("ha_ready", 1)
        g.prove("zigbee_ready", 2)
        self.assertTrue(g.states(2)["system_ready"])
        self.assertFalse(g.states(16)["system_ready"])
        g.reset()
        self.assertFalse(any(g.states(0).values()))

    def test_optional_components_do_not_block(self):
        g = Gates(require_ha=False, require_z2m=False, ttl=15)
        g.prove("mqtt_ready", 0)
        self.assertTrue(g.states(1)["system_ready"])
        self.assertFalse(g.states(1)["ha_ready"])
        g.invalidate("mqtt_ready", "disconnected")
        self.assertFalse(g.states(1)["system_ready"])

    def test_z2m_requires_correlated_health_and_inventory(self):
        z = Z2MProbe()
        z.observe("state", {"state": "online"})
        z.observe("info", {"version": "2.0.0"})
        z.observe("devices", [])
        z.begin("live")
        self.assertIsNone(z.observe("response/health_check", {"status": "ok", "data": {"healthy": True}, "transaction": "old"}))
        self.assertTrue(z.observe("response/health_check", {"status": "ok", "data": {"healthy": True}, "transaction": "live"}))
        z.begin("again")
        self.assertFalse(z.observe("state", {"state": "offline"}))
        self.assertIsNone(z.observe("response/health_check", {"status": "ok", "data": {"healthy": True}, "transaction": "again"}))

    def test_invalid_health_is_not_ready(self):
        z = Z2MProbe()
        z.observe("state", {"state": "online"})
        z.observe("info", {"version": "2"})
        z.observe("devices", [])
        z.begin("test")
        self.assertFalse(z.observe("response/health_check", {"status": "ok", "data": {"healthy": "true"}, "transaction": "test"}))

if __name__ == "__main__":
    unittest.main()
