import unittest
import json
from gates import Gates, Z2MProbe, Z2MRegistry, bridge_topic

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

    def test_multiple_arbitrary_namespaces_and_independent_freshness(self):
        registry = Z2MRegistry(20, 10)
        g = Gates(require_ha=False, require_z2m=True, ttl=20)
        a, b = "zigbee-east", "building/floor/zigbee-west"
        def observe(base, field, value, t=0, retained=True):
            registry.observe(base+"/bridge/"+field, json.dumps(value), retained, t)
            registry.update_gate(g, t)
        def discover(base, t=0):
            observe(base,"state",{"state":"online"},t)
            observe(base,"info",{"version":"2.0.0"},t)
            observe(base,"devices",[],t)
        def reply(base, nonce, t, retained=False):
            observe(base,"response/health_check",{"transaction":nonce,"status":"ok","data":{"healthy":True}},t,retained)
        registry.update_gate(g,0)
        self.assertFalse(g.states(0)["zigbee_ready"])
        discover(a)
        discover(b)
        nonces=iter([1,2,3,4])
        req=dict(registry.requests(1,lambda:next(nonces)))
        self.assertEqual(set(req),{a+"/bridge/request/health_check",b+"/bridge/request/health_check"})
        reply(a,1,2)
        reply(b,1,2)
        reply(b,2,2,True)
        self.assertFalse(g.states(2)["zigbee_ready"])
        reply(b,2,3)
        self.assertTrue(g.states(3)["zigbee_ready"])
        self.assertEqual(g.evidence["zigbee_ready"],2)
        req=dict(registry.requests(5,lambda:next(nonces)))
        reply(b,req[b+"/bridge/request/health_check"],6)
        registry.update_gate(g,22)
        self.assertFalse(g.states(22)["zigbee_ready"])
        observe(a,"state",{"state":"offline"},23)
        self.assertFalse(g.states(23)["zigbee_ready"])
        for field in ("state","info","devices"):
            registry.observe(a+"/bridge/"+field,"",True,23)
        registry.update_gate(g,23)
        self.assertEqual(set(registry.bridges),{b})
        self.assertTrue(g.states(23)["zigbee_ready"])
        discover("late/new",24)
        self.assertFalse(g.states(24)["zigbee_ready"])
        self.assertIsNone(bridge_topic("anything/bridge/logging"))

if __name__ == "__main__":
    unittest.main()
