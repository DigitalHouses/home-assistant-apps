# Development checkpoint — autonomous core

This branch is a development checkpoint, not an installable HAOS App or release.
Do not connect it to a production broker while the legacy Night Mode publisher is active.
It publishes to the real public contract, including clearing the retained mode if unconfigured.

Implemented: strict JSON state and atomic persistence, day/night schedule, manual override,
CCT/RGB profile validation, MQTT 5 transport for commands, retained snapshots and transient events.
The runtime uses MQTT 5 to preserve the retain flag on live commands and skip retained commands
on subscription. It replaces the client on reconnect rather than replaying old transient events.
Initial configuration establishes a state without claiming a prior on/off transition.
A change while the broker is unavailable is persisted; historical events are not replayed.
For a repeated local time (DST fold) use its first occurrence; skip nonexistent local times.
Clock and storage errors remain observable; do not silently reset invalid persisted data.

From the product directory, using Python 3.11+ and an isolated environment:

```sh
python3 -m pip install -r requirements.txt
PYTHONPATH=app python3 -m unittest discover -s tests -v
DH_TEST_MOSQUITTO=/path/to/mosquitto PYTHONPATH=app python3 -m unittest discover -s tests -v
```

The integration test starts its own loopback-only broker, uses temporary state and stops both processes.
The standalone development entrypoint requires explicit host, port and state path:

```sh
python3 app/runtime.py --host 127.0.0.1 --port 18883 --state /tmp/system-globals-test/state.json
```

Optional MQTT_USERNAME and MQTT_PASSWORD environment variables are not persisted in the profile state.
This entrypoint is for development on a local/trusted MQTT broker; production broker credentials,
transport security and HAOS packaging are not configured here.

Not yet implemented: readiness probes/gates, lifecycle, Ingress, HA Discovery,
DH Sync, Recorder, telemetry, registry integration, HAOS packaging and release automation.
Keep the PR draft until those production requirements and integration checks are complete.
