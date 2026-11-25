"""Opt-in isolated broker integration test. Set DH_TEST_MOSQUITTO to binary."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
import unittest

from core import GLOBAL, PRODUCT


@unittest.skipUnless(os.environ.get("DH_TEST_MOSQUITTO"), "isolated broker binary not configured")
class MqttIntegration(unittest.TestCase):
    def test_live_commands_events_and_restart(self):
        import paho.mqtt.client as mqtt
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            cfg = root / "mosquitto.conf"
            cfg.write_text(f"listener {port} 127.0.0.1\nallow_anonymous true\npersistence false\n")
            with (root / "broker.log").open("w+") as broker_log, (root / "app.log").open("w+") as app_log:
                broker = subprocess.Popen([os.environ["DH_TEST_MOSQUITTO"], "-c", str(cfg)], stdout=broker_log, stderr=broker_log)
                self.addCleanup(self.stop, broker)
                deadline = time.monotonic() + 5
                while True:
                    try:
                        with socket.create_connection(("127.0.0.1", port), timeout=0.2):
                            break
                    except OSError:
                        if time.monotonic() >= deadline:
                            self.fail("Isolated broker failed to start")
                        time.sleep(0.05)
                received = []
                client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, protocol=mqtt.MQTTv5)
                client.on_message = lambda c, u, msg: received.append((msg.topic, msg.payload.decode(), msg.retain))
                client.connect("127.0.0.1", port)
                client.subscribe("DigitalHouses/#", qos=1)
                client.loop_start()
                self.addCleanup(client.loop_stop)
                self.addCleanup(client.disconnect)

                def await_message(topic, predicate=lambda x: True, start=0):
                    until = time.monotonic() + 8
                    while time.monotonic() < until:
                        for t, payload, _ in received[start:]:
                            if t == topic and predicate(payload):
                                return payload
                        time.sleep(0.03)
                    app_log.flush()
                    app_log.seek(0)
                    self.fail("Missing " + topic + "\n" + app_log.read())

                def send(topic, value, retain=False):
                    payload = value if isinstance(value, str) else json.dumps(value)
                    client.publish(topic, payload, qos=1, retain=retain).wait_for_publish(timeout=3)

                def start_app():
                    app = Path(__file__).resolve().parents[1] / "rootfs" / "app" / "runtime.py"
                    p = subprocess.Popen([sys.executable, str(app), "--state", str(root / "state.json"),
                                          "--host", "127.0.0.1", "--port", str(port)],
                                         stdout=app_log, stderr=app_log)
                    self.addCleanup(self.stop, p)
                    return p

                p = start_app()
                await_message(PRODUCT + "/config/state")
                send(GLOBAL + "/set", "off")
                await_message(GLOBAL + "/state", lambda x: x == "off")
                start = len(received)
                send(GLOBAL + "/set", "on")
                await_message(GLOBAL + "/event", lambda x: json.loads(x)["event_type"] == "night_mode_on", start)
                self.assertEqual([x[0] for x in received[start:] if x[0] in (GLOBAL + "/state", GLOBAL + "/event")],
                                 [GLOBAL + "/state", GLOBAL + "/event"])
                send(PRODUCT + "/profiles/set", {"night": {"color_mode": "rgb", "rgb_color": [255, 0, 0]}})
                await_message(GLOBAL + "/profiles", lambda x: json.loads(x)["night"]["rgb_color"] == [255, 0, 0])
                start = len(received)
                send(GLOBAL + "/set", "off", retain=True)
                time.sleep(0.5)
                self.assertFalse(any(t == GLOBAL + "/state" for t, _, _ in received[start:]))
                self.stop(p)
                start = len(received)
                p = start_app()
                await_message(GLOBAL + "/state", lambda x: x == "on", start)
                await_message(PRODUCT + "/config/state", start=start)
                time.sleep(0.3)
                self.assertFalse(any(t == GLOBAL + "/event" for t, _, _ in received[start:]))
                self.assertEqual(json.loads((root / "state.json").read_text())["night_mode"], "on")
                self.stop(p)
                client.disconnect()
                client.loop_stop()
                self.stop(broker)

    @staticmethod
    def stop(proc):
        if proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=8)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()


if __name__ == "__main__":
    unittest.main()
