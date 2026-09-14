# DH PVE UPS Monitoring Alpha Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add read-only NUT-backed UPS monitoring to `dh_pve_app` 0.2.0-alpha and expose it as a separate Home Assistant MQTT device named `DH UPS` without changing existing PVE monitoring or enabling shutdown behavior.

**Architecture:** Keep one `dh_pve_app` process and one MQTT client. Add a dedicated UPS reader/runtime that queries local NUT with `upsc`, normalizes vendor-neutral facts in Python, applies its own publish thresholds, and publishes to separate UPS state/discovery topics. The existing `DH PVE` runtime, topics and semantics remain unchanged; UPS failures are isolated and cannot block PVE monitoring.

**Tech Stack:** Python 3, `subprocess`, existing `Scheduler`, existing MQTT bridge/paho-mqtt, Home Assistant MQTT Device Discovery, pytest, NUT `upsc` client.

**Spec:** `docs/superpowers/specs/2026-09-12-dh-pve-ups-monitoring-design.md`

## Global Constraints

- UPS data source is NUT only; never access USB directly from `dh_pve_app`.
- No `upsmon`, FSD, host shutdown, guest shutdown, UPS test, beeper control, outlet control, `upscmd`, or `upsrw` code paths in this alpha.
- Existing configs without `[ups]` stay valid and behave as before.
- Existing `DH PVE` MQTT topics and entity IDs do not change.
- UPS MQTT device is separate: `DH UPS`, entity prefix `dh_ups_`.
- One MQTT client connection is retained.
- Remote validation site keeps `nut-monitor` disabled/inactive; app must not alter `/etc/nut/*`.
- UPS polling default is 5 s; publish only on meaningful change, discrete events, reconnect, startup, or manual refresh.
- Initial numeric publish deltas are version-controlled: charge/load 1 percentage point, voltage 1.0 V, runtime 60 s.
- Home Assistant templates do not calculate UPS infrastructure values.

---

### Task 1: Optional UPS configuration

**Files:**
- Modify: `dh_pve_app/app/config.py`
- Modify: `dh_pve_app/tests/test_config.py`
- Modify: `dh_pve_app/examples/dh_pve_app.conf.example`

**Interfaces:**
- Produces: `UpsConfig(enabled: bool, name: str, host: str, port: int, poll_interval_seconds: float, command_timeout_seconds: float)`
- Produces: `AppConfig.ups: UpsConfig`
- Existing callers of `AppConfig.general` and `AppConfig.mqtt` remain unchanged.

- [ ] **Step 1: Write failing config tests**

```python
def test_ups_defaults_to_disabled_for_existing_config(tmp_path):
    path = write_config(tmp_path, "[mqtt]\nhost = broker\n")
    config = load_config(path)
    assert config.ups.enabled is False
    assert config.ups.name == "ups"
    assert config.ups.host == "127.0.0.1"
    assert config.ups.port == 3493
    assert config.ups.poll_interval_seconds == 5.0
    assert config.ups.command_timeout_seconds == 3.0


def test_ups_section_is_parsed(tmp_path):
    path = write_config(tmp_path, """[mqtt]
host = broker
[ups]
enabled = true
name = rackups
host = 127.0.0.1
port = 3493
poll_interval_seconds = 7
command_timeout_seconds = 2
""")
    config = load_config(path)
    assert config.ups.enabled is True
    assert config.ups.name == "rackups"
    assert config.ups.poll_interval_seconds == 7.0
```

- [ ] **Step 2: Run config tests and confirm RED**

Run: `python -m pytest dh_pve_app/tests/test_config.py -q`

Expected: failures because `AppConfig` has no `ups` field.

- [ ] **Step 3: Implement `UpsConfig` and parsers**

Add exact structure:

```python
@dataclass(frozen=True)
class UpsConfig:
    enabled: bool
    name: str
    host: str
    port: int
    poll_interval_seconds: float
    command_timeout_seconds: float
```

Parse booleans from `true/false`, validate port `1..65535`, require non-empty name/host, poll interval `1..300`, timeout `1..30`.

- [ ] **Step 4: Run config tests and confirm GREEN**

Run: `python -m pytest dh_pve_app/tests/test_config.py -q`

- [ ] **Step 5: Add `[ups]` disabled-by-default example block**

```ini
[ups]
enabled = false
name = ups
host = 127.0.0.1
port = 3493
poll_interval_seconds = 5
command_timeout_seconds = 3
```

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/config.py dh_pve_app/tests/test_config.py dh_pve_app/examples/dh_pve_app.conf.example
git commit -m "feat(dh-pve): add optional UPS configuration"
```

---

### Task 2: NUT `upsc` reader and normalized UPS model

**Files:**
- Create: `dh_pve_app/app/ups_nut.py`
- Create: `dh_pve_app/tests/fixtures/ups/cyberpower_ut2200e.upsc`
- Create: `dh_pve_app/tests/test_ups_nut.py`

**Interfaces:**
- Produces: `parse_upsc_output(text: str) -> UpsSnapshot`
- Produces: `read_ups(config: UpsConfig, runner: Callable[..., CompletedProcess] = subprocess.run) -> UpsSnapshot`
- Produces: `ups_metrics(snapshot: UpsSnapshot) -> dict[str, MetricValue]`

- [ ] **Step 1: Add exact remote UPS fixture**

Fixture contains the observed `upsc ups@localhost` keys including `battery.charge: 100`, `battery.runtime: 2160`, `battery.voltage: 27.2`, `input.voltage: 221.0`, `output.voltage: 221.0`, `ups.load: 8`, `ups.realpower.nominal: 1320`, `ups.status: OL`, `device.model: UT2200E`, `device.mfr: CPS`.

- [ ] **Step 2: Write failing parser tests**

```python
def test_parse_remote_cyberpower_sample():
    snapshot = parse_upsc_output(FIX.read_text())
    assert snapshot.manufacturer == "CPS"
    assert snapshot.model == "UT2200E"
    assert snapshot.status_raw == "OL"
    assert snapshot.line_power is True
    assert snapshot.on_battery is False
    assert snapshot.battery_charge_percent == 100.0
    assert snapshot.runtime_seconds == 2160.0
    assert snapshot.load_percent == 8.0
    assert snapshot.nominal_real_power_w == 1320.0
    assert snapshot.estimated_real_power_w == 105.6


def test_multi_token_status_is_normalized():
    snapshot = parse_upsc_output("ups.status: OB LB DISCHRG\n")
    assert snapshot.on_battery is True
    assert snapshot.low_battery is True
    assert snapshot.discharging is True
```

Also cover unknown tokens, missing optionals, malformed numeric fields, and zero `input.transfer.high/low` being ignored.

- [ ] **Step 3: Run parser tests and confirm RED**

Run: `python -m pytest dh_pve_app/tests/test_ups_nut.py -q`

- [ ] **Step 4: Implement normalized dataclass and parser**

Core dataclass fields:

```python
@dataclass(frozen=True)
class UpsSnapshot:
    raw: dict[str, str]
    manufacturer: str | None
    model: str | None
    serial: str | None
    status_raw: str
    status_tokens: tuple[str, ...]
    line_power: bool
    on_battery: bool
    low_battery: bool
    replace_battery: bool
    overload: bool
    bypass: bool
    charging: bool
    discharging: bool
    battery_charge_percent: float | None
    runtime_seconds: float | None
    battery_voltage_v: float | None
    battery_nominal_voltage_v: float | None
    load_percent: float | None
    nominal_real_power_w: float | None
    estimated_real_power_w: float | None
    input_voltage_v: float | None
    input_nominal_voltage_v: float | None
    output_voltage_v: float | None
    warning_charge_percent: float | None
    low_charge_percent: float | None
    low_runtime_seconds: float | None
    test_result: str | None
    beeper_status: str | None
```

Status token mapping is explicit: `OL`, `OB`, `LB`, `RB`, `OVER`, `BYPASS`, `CHRG`, `DISCHRG`.

- [ ] **Step 5: Implement bounded subprocess reader**

Call exactly:

```python
subprocess.run(
    ["upsc", f"{config.name}@{config.host}:{config.port}"],
    capture_output=True,
    text=True,
    timeout=config.command_timeout_seconds,
    check=True,
)
```

Convert missing command, timeout, and non-zero exit into a dedicated `NutReadError`; never execute any other NUT command.

- [ ] **Step 6: Implement metric mapping**

Use `MetricValue` policies:

```python
"available" -> discrete
"status" -> discrete
"on_battery" -> discrete
"low_battery" -> discrete
"replace_battery" -> discrete
"overload" -> discrete
"bypass" -> discrete
"charging" -> discrete
"discharging" -> discrete
"battery_charge_percent" -> ups_percent
"load_percent" -> ups_percent
"runtime_seconds" -> ups_runtime_seconds
"battery_voltage_v" -> ups_voltage
"input_voltage_v" -> ups_voltage
"output_voltage_v" -> ups_voltage
```

Estimated power rides in the state payload and is refreshed whenever load causes publication.

- [ ] **Step 7: Run UPS reader tests and confirm GREEN**

Run: `python -m pytest dh_pve_app/tests/test_ups_nut.py -q`

- [ ] **Step 8: Commit**

```bash
git add dh_pve_app/app/ups_nut.py dh_pve_app/tests/fixtures/ups/cyberpower_ut2200e.upsc dh_pve_app/tests/test_ups_nut.py
git commit -m "feat(dh-pve): add read-only NUT UPS reader"
```

---

### Task 3: UPS publish thresholds

**Files:**
- Modify: `dh_pve_app/app/publish_policy.py`
- Modify: `dh_pve_app/tests/test_publish_policy.py`

**Interfaces:**
- Existing `PublishPolicy` API is unchanged.
- New policy names: `ups_percent`, `ups_voltage`, `ups_runtime_seconds`.

- [ ] **Step 1: Write failing threshold test**

```python
def test_ups_numeric_thresholds():
    policy = _policy()
    policy.mark_published({
        "charge": MetricValue(100.0, "ups_percent"),
        "voltage": MetricValue(221.0, "ups_voltage"),
        "runtime": MetricValue(2160.0, "ups_runtime_seconds"),
    })
    assert policy.evaluate({
        "charge": MetricValue(99.5, "ups_percent"),
        "voltage": MetricValue(221.5, "ups_voltage"),
        "runtime": MetricValue(2130.0, "ups_runtime_seconds"),
    }).publish is False
    assert policy.evaluate({
        "charge": MetricValue(99.0, "ups_percent"),
        "voltage": MetricValue(221.0, "ups_voltage"),
        "runtime": MetricValue(2160.0, "ups_runtime_seconds"),
    }).publish is True
```

- [ ] **Step 2: Run test and confirm RED**

Run: `python -m pytest dh_pve_app/tests/test_publish_policy.py -q`

- [ ] **Step 3: Add fixed thresholds**

```python
_FIXED_THRESHOLDS = {
    "frequency_mhz": 100.0,
    "ups_percent": 1.0,
    "ups_voltage": 1.0,
    "ups_runtime_seconds": 60.0,
}
```

- [ ] **Step 4: Run publish-policy tests and confirm GREEN**

Run: `python -m pytest dh_pve_app/tests/test_publish_policy.py -q`

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/publish_policy.py dh_pve_app/tests/test_publish_policy.py
git commit -m "feat(dh-pve): add UPS publish thresholds"
```

---

### Task 4: Separate UPS MQTT topics and capability-driven Discovery

**Files:**
- Modify: `dh_pve_app/app/topics.py`
- Create: `dh_pve_app/app/discovery_ups.py`
- Create: `dh_pve_app/tests/test_ups_discovery.py`

**Interfaces:**
- Produces: `UpsTopics(state, availability, refresh, discovery, device_id)`
- Produces: `build_ups_topics(mqtt: MqttConfig, identity: HostIdentity) -> UpsTopics`
- Produces: `build_ups_discovery_payload(config, identity, version, snapshot) -> dict`

- [ ] **Step 1: Write failing topic/discovery tests**

```python
def test_ups_topics_are_separate_from_pve_topics():
    pve = build_topics(mqtt, identity)
    ups = build_ups_topics(mqtt, identity)
    assert ups.state == f"{pve.base}/ups/state"
    assert ups.availability == f"{pve.base}/ups/availability"
    assert ups.refresh == f"{pve.base}/ups/refresh"
    assert ups.discovery == f"homeassistant/device/dh_ups_{identity.instance_id}/config"
    assert ups.device_id == f"dh_ups_{identity.instance_id}"


def test_discovery_only_creates_supported_numeric_entities():
    payload = build_ups_discovery_payload(config, identity, version="0.2.0-alpha", snapshot=snapshot)
    components = payload["components"]
    assert "battery_charge" in components
    assert "battery_runtime" in components
    assert "input_voltage" in components
    assert "unsupported_temperature" not in components
```

- [ ] **Step 2: Run tests and confirm RED**

Run: `python -m pytest dh_pve_app/tests/test_ups_discovery.py -q`

- [ ] **Step 3: Implement stable UPS topic contract**

Do not modify existing `build_topics()` output.

- [ ] **Step 4: Implement UPS Device Discovery**

Always include:
- `sensor.dh_ups_status`
- `binary_sensor.dh_ups_available`
- `button.dh_ups_refresh`
- `sensor.dh_ups_last_refresh`

Conditionally include supported telemetry/diagnostics from the current snapshot.

Device metadata uses manufacturer/model/serial when available and identifiers `[dh_ups_<instance>]`.

For telemetry components, availability uses both:
1. existing app LWT topic (`topics.availability`) so one MQTT client crash makes both devices unavailable;
2. UPS state template `value_json.available` so NUT failure only affects UPS telemetry.

`binary_sensor.dh_ups_available` itself depends only on app LWT and reads `value_json.available`, so NUT failure displays `off` rather than making the sensor unavailable.

- [ ] **Step 5: Run discovery tests and confirm GREEN**

Run: `python -m pytest dh_pve_app/tests/test_ups_discovery.py -q`

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/topics.py dh_pve_app/app/discovery_ups.py dh_pve_app/tests/test_ups_discovery.py
git commit -m "feat(dh-pve): add separate DH UPS discovery"
```

---

### Task 5: Extend one MQTT bridge for UPS auxiliary channel

**Files:**
- Modify: `dh_pve_app/app/mqtt_bridge.py`
- Modify: `dh_pve_app/tests/test_mqtt_bridge.py`

**Interfaces:**
- Adds: `configure_ups(topics: UpsTopics) -> None`
- Adds events: `ups_refresh_requested`, `ups_reconnect_requested`
- Adds: `publish_ups_discovery(payload)`, `publish_ups_state(payload)`, `publish_ups_availability(online: bool)`
- Existing PVE bridge methods remain unchanged.

- [ ] **Step 1: Write failing MQTT event test**

```python
def test_ups_refresh_uses_separate_event():
    events = MqttEvents(_topics(), RuntimeSettings())
    ups = build_ups_topics(_mqtt(), _identity())
    events.configure_ups(ups)
    assert events.handle_message(ups.refresh, b"PRESS") is True
    assert events.ups_refresh_requested.is_set()
    assert not events.refresh_requested.is_set()
```

Add a reconnect test proving both reconnect events are set when HA publishes `online`.

- [ ] **Step 2: Run MQTT tests and confirm RED**

Run: `python -m pytest dh_pve_app/tests/test_mqtt_bridge.py -q`

- [ ] **Step 3: Implement auxiliary UPS subscriptions/publications**

Keep the single PVE app LWT unchanged. On normal app shutdown publish UPS availability `offline` before disconnect when UPS is configured.

- [ ] **Step 4: Run MQTT tests and confirm GREEN**

Run: `python -m pytest dh_pve_app/tests/test_mqtt_bridge.py -q`

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/mqtt_bridge.py dh_pve_app/tests/test_mqtt_bridge.py
git commit -m "feat(dh-pve): publish UPS over shared MQTT bridge"
```

---

### Task 6: Dedicated UPS runtime with failure isolation

**Files:**
- Create: `dh_pve_app/app/ups_runtime.py`
- Create: `dh_pve_app/tests/test_ups_runtime.py`

**Interfaces:**
- Produces: `UpsRuntime(config, bridge, identity, version, state_store, now_iso, now_monotonic)`
- Methods: `startup()`, `tick(now)`, `process_events()`, `republish_after_reconnect()`, `manual_refresh()`
- Does not subclass PVE runtime; it owns an independent policy/scheduler/state baseline.

- [ ] **Step 1: Write failing runtime tests**

Cover:
- startup queries NUT, publishes capability-driven discovery, availability, and state;
- unchanged poll produces no MQTT state publication;
- `OL -> OB` publishes immediately;
- 30 s runtime drift is suppressed, 60 s publishes;
- reader failure publishes `available=false` without raising into PVE runtime;
- successful manual refresh advances UPS `last_refresh`;
- reconnect forces UPS discovery and last known state;
- a failed poll does not delete last known capability inventory.

- [ ] **Step 2: Run UPS runtime tests and confirm RED**

Run: `python -m pytest dh_pve_app/tests/test_ups_runtime.py -q`

- [ ] **Step 3: Implement independent scheduler**

Use existing `Scheduler`:

```python
self.scheduler.add(
    "ups",
    interval_seconds=config.poll_interval_seconds,
    now=now_monotonic(),
)
```

State payload shape:

```json
{
  "available": true,
  "collected_at": "...",
  "last_refresh": null,
  "data": {"...normalized UpsSnapshot fields..."},
  "error": null
}
```

On failure publish `available=false`, preserve last valid `data` internally for capability/discovery continuity, and put a concise error string in state/log without leaking secrets.

- [ ] **Step 4: Implement capability fingerprint**

Fingerprint Discovery payload with sorted JSON. Republish only when capability shape changes or startup/reconnect/manual refresh forces it.

- [ ] **Step 5: Run UPS runtime tests and confirm GREEN**

Run: `python -m pytest dh_pve_app/tests/test_ups_runtime.py -q`

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/ups_runtime.py dh_pve_app/tests/test_ups_runtime.py
git commit -m "feat(dh-pve): add isolated UPS runtime"
```

---

### Task 7: Wire UPS runtime into `dh_pve_app` without blocking PVE

**Files:**
- Modify: `dh_pve_app/app/main.py`
- Modify: `dh_pve_app/tests/test_main_contract.py`
- Create: `dh_pve_app/tests/test_ups_main_integration.py`

**Interfaces:**
- Existing `build_runtime(config)` continues returning `(bridge, pve_runtime)` for compatibility.
- Add: `build_ups_runtime(config, bridge, state_dir) -> UpsRuntime | None`.

- [ ] **Step 1: Write failing integration tests**

```python
def test_ups_disabled_builds_no_aux_runtime(config):
    bridge, pve = build_runtime(config, state_dir=tmp_path)
    assert build_ups_runtime(config, bridge, state_dir=tmp_path) is None


def test_ups_failure_does_not_block_pve_initialization(...):
    # fake PVE runtime startup succeeds; fake UPS startup fails
    # main-loop orchestration must keep PVE initialized/running
```

Add contract assertion that normal loop calls UPS `process_events()` and `tick()` only when enabled.

- [ ] **Step 2: Run integration tests and confirm RED**

Run: `python -m pytest dh_pve_app/tests/test_main_contract.py dh_pve_app/tests/test_ups_main_integration.py -q`

- [ ] **Step 3: Implement optional UPS wiring**

Main-loop rule:
- PVE startup success controls `initialized` exactly as today;
- UPS startup is attempted independently;
- UPS exceptions are logged in Russian and never flip PVE `initialized` false;
- UPS runtime keeps retrying on its own scheduled polls/reconnects.

- [ ] **Step 4: Run integration tests and confirm GREEN**

Run: `python -m pytest dh_pve_app/tests/test_main_contract.py dh_pve_app/tests/test_ups_main_integration.py -q`

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/main.py dh_pve_app/tests/test_main_contract.py dh_pve_app/tests/test_ups_main_integration.py
git commit -m "feat(dh-pve): wire optional UPS monitoring"
```

---

### Task 8: Version, safety contract, docs, and full verification

**Files:**
- Modify: `dh_pve_app/VERSION`
- Modify: `dh_pve_app/tests/test_repository_contract.py`
- Create: `dh_pve_app/tests/test_ups_safety_contract.py`
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`

**Interfaces:**
- Version becomes `0.2.0-alpha`.
- Installer remains the same service/install path and does not touch `/etc/nut/*`.

- [ ] **Step 1: Write safety/version tests**

```python
def test_version_allows_semver_prerelease():
    version = (ROOT / "VERSION").read_text().strip()
    assert re.fullmatch(r"\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?", version)
    assert version == "0.2.0-alpha"


def test_alpha_has_no_power_control_commands():
    app_text = "\n".join(p.read_text() for p in (ROOT / "app").glob("*.py"))
    forbidden = ("upscmd", "upsrw", "FSD", "shutdown -h", "poweroff")
    for token in forbidden:
        assert token not in app_text
```

Also assert `install.sh` does not modify `/etc/nut`, invoke `systemctl ... nut-monitor`, or install/configure `nut-server`.

- [ ] **Step 2: Run safety tests and confirm RED on version**

Run: `python -m pytest dh_pve_app/tests/test_repository_contract.py dh_pve_app/tests/test_ups_safety_contract.py -q`

- [ ] **Step 3: Set version and update docs**

`VERSION`:

```text
0.2.0-alpha
```

README must document:
- optional `[ups]` configuration;
- prerequisite: working NUT + `upsc` client;
- separate `DH UPS` device;
- read-only alpha;
- explicit statement that app does not configure shutdown.

CHANGELOG gets `0.2.0-alpha` entry.

- [ ] **Step 4: Run focused UPS suite**

Run:

```bash
python -m pytest \
  dh_pve_app/tests/test_config.py \
  dh_pve_app/tests/test_ups_nut.py \
  dh_pve_app/tests/test_ups_discovery.py \
  dh_pve_app/tests/test_mqtt_bridge.py \
  dh_pve_app/tests/test_ups_runtime.py \
  dh_pve_app/tests/test_ups_main_integration.py \
  dh_pve_app/tests/test_ups_safety_contract.py \
  -q
```

Expected: all PASS.

- [ ] **Step 5: Run complete DH PVE suite**

Run: `python -m pytest dh_pve_app/tests -q`

Expected: zero failures.

- [ ] **Step 6: Compile application**

Run: `python -m compileall -q dh_pve_app/app`

Expected: exit 0.

- [ ] **Step 7: Commit**

```bash
git add dh_pve_app/VERSION dh_pve_app/tests/test_repository_contract.py dh_pve_app/tests/test_ups_safety_contract.py dh_pve_app/README.md dh_pve_app/CHANGELOG.md
git commit -m "docs(dh-pve): prepare 0.2.0-alpha UPS validation"
```

- [ ] **Step 8: Push branch and verify GitHub Actions**

Wait for the repository workflow. Inspect the DH PVE job logs and confirm the full test count with zero failures before giving the remote-site install command.

---

## Remote-site acceptance procedure

After CI is green, install the alpha branch on the remote Proxmox with the existing installer source-ref mechanism, preserve MQTT credentials, enable only the `[ups]` section, restart `dh_pve_app`, and collect two evidence sets.

**PVE evidence:**

```bash
cat /opt/digitalhouses/dh_pve_app/BUILD_INFO
systemctl status dh_pve_app --no-pager
journalctl -u dh_pve_app --since "-5 min" --no-pager
upsc ups@127.0.0.1:3493
systemctl is-enabled nut-monitor.service || true
systemctl is-active nut-monitor.service || true
```

Do not print the app config because it contains the MQTT password.

**HAOS evidence:** provide the `DH UPS` device entity list plus state/attributes for:

```text
sensor.dh_ups_status
binary_sensor.dh_ups_available
sensor.dh_ups_battery_charge
sensor.dh_ups_battery_runtime
sensor.dh_ups_load
sensor.dh_ups_estimated_real_power
sensor.dh_ups_input_voltage
sensor.dh_ups_output_voltage
```

For the observed remote CyberPower UT2200E, expected baseline is approximately charge `100%`, runtime `2160 s`, load `8%`, estimated power `105.6 W`, input/output `221 V`, and normalized status equivalent to line power / normal operation.
