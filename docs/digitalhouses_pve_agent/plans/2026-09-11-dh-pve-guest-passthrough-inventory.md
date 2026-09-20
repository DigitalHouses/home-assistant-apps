# DH PVE Guest / Passthrough Inventory Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add autonomous VM/LXC inventory and shared passthrough topology to `dh_pve_app`, use it to recover SMART telemetry for physical disks hidden behind VM PCI passthrough, preserve guest GPU telemetry, and expose read-only guest status in Home Assistant.

**Architecture:** Introduce a focused topology module and a process-local `TopologyManager`. A full topology scan runs at app startup and manual refresh; a separate lightweight guest-status collector polls VM/LXC state and performs targeted rescans when a guest transitions to `running`. SMART and GPU collectors consume the cached topology rather than reparsing Proxmox configuration on each fast poll. Dynamic MQTT Discovery exposes compact guest entities and guest-derived physical disks through the existing `dh_pve_*` contract.

**Tech Stack:** Python 3, Proxmox CLI (`qm`, `pct`, `lspci`), QEMU Guest Agent (`qm guest exec`, `qm agent`), smartmontools JSON, Home Assistant MQTT Device Discovery, pytest.

**Spec:** `docs/superpowers/specs/2026-09-11-dh-pve-guest-passthrough-inventory-design.md`

## Global Constraints

- VM/LXC monitoring is read-only; publish no lifecycle control commands.
- Normal installations must not require site-specific `disk_vms`, `gpu_vms`, or `passthrough_vms` lists.
- Full topology discovery runs at startup and manual refresh, not on every fast poll.
- VM/LXC status is lightweight polling and status transitions publish immediately.
- A `stopped`/`paused` → `running` transition triggers a targeted topology refresh for that guest.
- VM `hostpciN` passthrough and the existing LXC `/dev/dri` GPU mapping are in scope; arbitrary LXC device/mount passthrough is out of scope.
- Guest-derived disks use the same SMART parser, stable identity, health evaluation, daily statistics, and Discovery contract as host-local disks.
- Stable disk identity remains WWN → serial → stable fallback and must not depend on `/dev/sdX`.
- A stopped VM or failed QEMU Guest Agent makes guest telemetry unavailable but must not immediately delete the physical disk entity.
- Existing VM 501 Intel GPU owner/transcoding telemetry must remain functional.
- Home Assistant templates must not calculate infrastructure health; health remains a Python result.
- Existing Bash monitoring remains untouched during validation.

---

## File structure

Create:

- `dh_pve_app/app/collectors/guests.py` — guest list parsing, PCI topology models/parsers, guest block-device parsing, QGA result parsing.
- `dh_pve_app/app/topology.py` — `TopologyManager`, full/targeted scan cache, QGA capability state, source lookup APIs for SMART/GPU.
- `dh_pve_app/tests/test_guests.py` — pure parser/model tests.
- `dh_pve_app/tests/test_topology.py` — topology manager lifecycle and transition tests.
- `dh_pve_app/tests/fixtures/guests/qm_list.txt` — representative VM list.
- `dh_pve_app/tests/fixtures/guests/pct_list.txt` — representative LXC list.
- `dh_pve_app/tests/fixtures/guests/vm_700.conf` — TrueNAS PCI SATA-controller passthrough.
- `dh_pve_app/tests/fixtures/guests/vm_501.conf` — Plex Intel GPU passthrough.
- `dh_pve_app/tests/fixtures/guests/qga_lsblk_vm700.json` — QGA wrapper containing QEMU system disk + Samsung 850 EVO.
- `dh_pve_app/tests/fixtures/guests/samsung_850_evo_smart.json` — guest SMART fixture.

Modify:

- `dh_pve_app/app/production.py` — consume shared topology for GPU; add guest-status collector helper where appropriate.
- `dh_pve_app/app/production_v1.py` — guest SMART merge and resilient unavailable behavior.
- `dh_pve_app/app/main.py` — construct shared topology, add unscheduled full-topology collector and lightweight guests scheduler.
- `dh_pve_app/app/discovery_metrics.py` — dynamic VM/LXC status and summary Discovery.
- `dh_pve_app/app/runtime_dynamic.py` and/or `dh_pve_app/app/app.py` — only if needed to guarantee manual refresh executes full topology before dependent collectors; prefer collector ordering first.
- `dh_pve_app/tests/test_production_v1.py` — guest SMART production behavior.
- `dh_pve_app/tests/test_gpu.py` — shared-topology GPU regression.
- `dh_pve_app/tests/test_full_discovery.py` — guest entity Discovery.
- `dh_pve_app/tests/test_main_contract.py` / `test_app_runtime.py` — startup/manual-refresh ordering if required.
- `dh_pve_app/examples/dh_pve_dashboard.yaml` — four-column production layout plus dynamic VM/LXC list.
- `dh_pve_app/tests/test_dashboard_contract.py` — guest-list and four-section contract.
- `dh_pve_app/README.md`, `dh_pve_app/CHANGELOG.md` — document new capability and live validation procedure.

---

### Task 1: Guest and passthrough parsing primitives

**Files:**
- Create: `dh_pve_app/app/collectors/guests.py`
- Create: `dh_pve_app/tests/test_guests.py`
- Create fixtures under `dh_pve_app/tests/fixtures/guests/`

**Interfaces:**
- Produces `GuestRecord`, `PassthroughDevice`, `GuestBlockDevice` dataclasses.
- Produces `parse_qm_list(text: str) -> dict[str, GuestRecord]`.
- Produces `parse_pct_list(text: str) -> dict[str, GuestRecord]`.
- Produces `parse_hostpci(config: str, pci_catalog: Mapping[str, Mapping[str, str]]) -> tuple[PassthroughDevice, ...]`.
- Produces `parse_lspci_catalog(text: str) -> dict[str, dict[str, str]]`.
- Produces `parse_qga_lsblk(text: str) -> tuple[GuestBlockDevice, ...]`.
- Produces `is_physical_guest_disk(device: GuestBlockDevice) -> bool`.

- [ ] **Step 1: Write failing parser tests**

```python
def test_parse_qm_and_pct_lists_normalizes_status_and_names():
    vms = parse_qm_list((FIX / "qm_list.txt").read_text())
    lxcs = parse_pct_list((FIX / "pct_list.txt").read_text())
    assert vms["700"].name == "TrueNAS"
    assert vms["700"].status == "running"
    assert vms["110"].status == "stopped"
    assert lxcs["500"].kind == "lxc"


def test_parse_hostpci_resolves_storage_controller_and_gpu():
    catalog = parse_lspci_catalog(LSPCI_TEXT)
    storage = parse_hostpci((FIX / "vm_700.conf").read_text(), catalog)
    gpu = parse_hostpci((FIX / "vm_501.conf").read_text(), catalog)
    assert storage[0].pci_address == "0000:00:17.0"
    assert storage[0].pci_class.startswith("01")
    assert gpu[0].pci_class.startswith("03")


def test_qga_lsblk_excludes_qemu_system_disk_and_keeps_physical_ssd():
    items = parse_qga_lsblk((FIX / "qga_lsblk_vm700.json").read_text())
    physical = [item for item in items if is_physical_guest_disk(item)]
    assert [item.path for item in physical] == ["/dev/sdb"]
    assert physical[0].model == "Samsung SSD 850 EVO 1TB"
    assert physical[0].wwn == "0x5002538d41046527"
```

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_guests.py`

Expected: FAIL because `collectors.guests` does not exist.

- [ ] **Step 3: Implement minimal parser/model module**

Use immutable dataclasses and normalize PCI BDFs to `0000:bb:dd.f`. `is_physical_guest_disk` must exclude known virtual signatures such as model `QEMU HARDDISK` and serial beginning `drive-`, but must not require `TRAN` or `WWN` to be present for a disk to remain eligible.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_guests.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/collectors/guests.py dh_pve_app/tests/test_guests.py dh_pve_app/tests/fixtures/guests
git commit -m "feat(dh-pve): add guest passthrough parsers"
```

---

### Task 2: Shared topology manager and lightweight guest state

**Files:**
- Create: `dh_pve_app/app/topology.py`
- Create: `dh_pve_app/tests/test_topology.py`
- Modify: `dh_pve_app/app/production.py`

**Interfaces:**
- Consumes Task 1 parser/model functions.
- Produces `TopologyManager.full_scan() -> TopologySnapshot`.
- Produces `TopologyManager.poll_guest_status() -> GuestStatusSnapshot`.
- Produces `TopologyManager.rescan_guest(kind: str, guest_id: str) -> None`.
- Produces `TopologyManager.vm_storage_sources() -> tuple[GuestStorageSource, ...]`.
- Produces `TopologyManager.gpu_owner(pci_address: str) -> ...` or equivalent lookup used by GPU collector.
- Produces a production `guests()` collector returning compact VM/LXC data and discrete status metrics.
- Produces a production `topology()` collector returning only compact revision/count diagnostics while retaining rich topology in process memory.

- [ ] **Step 1: Write failing topology lifecycle tests**

```python
def test_full_scan_builds_vm700_storage_and_vm501_gpu_ownership(fake_runner):
    manager = TopologyManager(runner=fake_runner, pve_root=FIX_PVE)
    snapshot = manager.full_scan()
    assert snapshot.vms["700"].name == "TrueNAS"
    assert snapshot.pci["0000:00:17.0"].owner_id == "700"
    assert snapshot.pci["0000:00:17.0"].device_class.startswith("01")
    assert snapshot.pci["0000:00:02.0"].owner_id == "501"


def test_guest_status_transition_to_running_triggers_targeted_rescan(fake_runner):
    manager = TopologyManager(runner=fake_runner, pve_root=FIX_PVE)
    manager.full_scan()
    fake_runner.set_vm_status("700", "running")
    status = manager.poll_guest_status()
    assert status.vms["700"].status == "running"
    assert fake_runner.targeted_config_reads("700") == 1
```

Also assert that repeated unchanged status polls do not reread every guest config.

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_topology.py`

Expected: FAIL because `TopologyManager` is missing.

- [ ] **Step 3: Implement `TopologyManager`**

Implementation rules:

```text
full_scan:
  qm list + pct list
  read current VM/LXC configs
  lspci catalog once
  parse VM hostpci mappings
  preserve existing LXC /dev/dri ownership mapping
  probe configured/running VM QGA capability once
  cache snapshot + revision fingerprint

poll_guest_status:
  qm list + pct list only
  compare normalized status with prior status
  on non-running -> running: rescan that guest config and QGA capability
  do not reread all configs when no status changed
```

QGA retry: for a configured/running VM marked unavailable, allow a cached re-probe no more often than every 60 seconds when a dependent collector asks for guest execution capability.

- [ ] **Step 4: Add `topology()` and `guests()` production collector methods**

`guests()` data shape:

```python
{
    "vms": {
        "700": {
            "kind": "vm", "guest_id": "700", "name": "TrueNAS",
            "status": "running", "agent_enabled": True,
            "qemu_agent": "available", "passthrough_count": 1,
        }
    },
    "lxcs": {...},
    "summary": {
        "vms": {"total": 3, "running": 2, "paused": 0, "stopped": 1, "unknown": 0},
        "lxcs": {"total": 1, "running": 1, "paused": 0, "stopped": 0, "unknown": 0},
    },
}
```

Status metrics use policy `discrete`. Do not place the full PCI topology in the MQTT state payload.

- [ ] **Step 5: Run focused tests**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_guests.py dh_pve_app/tests/test_topology.py dh_pve_app/tests/test_gpu.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/topology.py dh_pve_app/app/production.py dh_pve_app/tests/test_topology.py
git commit -m "feat(dh-pve): add shared guest topology cache"
```

---

### Task 3: Guest SMART through QEMU Guest Agent

**Files:**
- Modify: `dh_pve_app/app/production_v1.py`
- Modify: `dh_pve_app/tests/test_production_v1.py`
- Add fixture: `dh_pve_app/tests/fixtures/guests/samsung_850_evo_smart.json`

**Interfaces:**
- Consumes `TopologyManager.vm_storage_sources()` and QGA capability checks.
- Reuses `parse_smart_json`, `stable_disk_id`, `evaluate_disk_health`, `update_daily_stats`, and existing `_metrics_for_disk`.
- Guest physical disks are merged into the same `smart` subsystem dictionary as local disks.

- [ ] **Step 1: Write failing guest SMART tests**

```python
def test_smart_merges_local_nvme_and_vm700_passthrough_ssd(collector, fake_topology):
    sample = collector.smart()
    assert "wwn_eui_0025382451a05c68" in sample.data
    guest = next(v for v in sample.data.values() if v.get("serial") == "S2PWNX0H603177N")
    assert guest["model"] == "Samsung SSD 850 EVO 1TB"
    assert guest["source_type"] == "guest"
    assert guest["source_guest_id"] == "700"
    assert guest["source_guest_name"] == "TrueNAS"
    assert guest["source_device_path"] == "/dev/sdb"


def test_stopped_vm_marks_guest_disk_unavailable_without_removing_local_disk(...):
    first = collector.smart()
    fake_topology.set_vm_status("700", "stopped")
    second = collector.smart()
    guest = find_serial(second.data, "S2PWNX0H603177N")
    assert guest["available"] is False
    assert find_serial(second.data, "S7M3NL0Y413841D")["available"] is True
```

Also test stable ID equality for the same WWN parsed from host versus guest source.

- [ ] **Step 2: Run tests and verify RED**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_production_v1.py`

Expected: new guest-SMART tests FAIL because only local `_smart_scan()` is consumed.

- [ ] **Step 3: Implement cached guest disk source discovery**

At topology scan / targeted guest rescan, use QGA `lsblk -J -b -d -o NAME,PATH,TYPE,SIZE,MODEL,SERIAL,WWN,TRAN,ROTA` once to identify eligible physical disks behind storage-class passthrough. Keep paths in `GuestStorageSource` cache.

At SMART poll, for each cached eligible guest device execute inside the guest:

```text
smartctl -a -j /dev/sdb
```

Parse the QGA wrapper, feed the JSON to the existing `parse_smart_json`, then append only source metadata. Never fork a second health implementation.

- [ ] **Step 4: Preserve unavailable semantics**

If VM is stopped/paused, QGA unavailable, or guest smartctl fails, preserve the last successful disk data and set `available=False` with an error. Do not increment authoritative physical-missing confirmation merely because a known guest source is offline.

- [ ] **Step 5: Run focused tests and verify GREEN**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_production_v1.py dh_pve_app/tests/test_smart.py dh_pve_app/tests/test_disk_health.py dh_pve_app/tests/test_daily_disk_stats.py`

Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/production_v1.py dh_pve_app/tests/test_production_v1.py dh_pve_app/tests/fixtures/guests/samsung_850_evo_smart.json
git commit -m "feat(dh-pve): collect SMART from passthrough guests"
```

---

### Task 4: Move GPU ownership/guest execution onto shared topology

**Files:**
- Modify: `dh_pve_app/app/production.py`
- Modify: `dh_pve_app/tests/test_gpu.py`

**Interfaces:**
- Consumes cached PCI owner mapping from `TopologyManager`.
- Preserves existing `GpuSnapshot` and `parse_qemu_guest_exec_transcoding` external behavior.

- [ ] **Step 1: Write regression test proving GPU collector does not reparse all guest configs per fast poll**

```python
def test_gpu_uses_cached_topology_and_keeps_vm501_transcoding(...):
    first = collector.gpu()
    second = collector.gpu()
    gpu = first.data["pci_0000_00_02_0"]
    assert gpu["owner"] == "VM 501"
    assert gpu["source_name"] == "plex-vm"
    assert gpu["transcoding_load_percent"] == 71.3
    assert fake_runner.all_guest_config_reads == 0  # topology already primed
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_gpu.py`

Expected: new test FAIL while `_gpu_context()` reparses guest configuration itself.

- [ ] **Step 3: Refactor GPU collector to consume topology cache**

Keep local GPU enumeration/temperature/`intel_gpu_top` ownership-specific telemetry in GPU code. Move only ownership and guest lifecycle knowledge to shared topology. Preserve LXC shared-DRI support.

- [ ] **Step 4: Run and verify GREEN**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_gpu.py dh_pve_app/tests/test_topology.py`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/production.py dh_pve_app/tests/test_gpu.py
git commit -m "refactor(dh-pve): share passthrough topology with GPU collector"
```

---

### Task 5: Runtime scheduling and refresh semantics

**Files:**
- Modify: `dh_pve_app/app/main.py`
- Modify if required: `dh_pve_app/app/app.py`, `dh_pve_app/app/runtime_dynamic.py`
- Modify: `dh_pve_app/tests/test_main_contract.py`
- Modify if required: `dh_pve_app/tests/test_app_runtime.py`, `test_runtime_dynamic.py`

**Interfaces:**
- `topology` is a collector present in mapping but not scheduled periodically.
- `guests` is scheduled every 10 seconds initially.
- Collector insertion/order guarantees topology is collected before guest-dependent SMART/GPU on startup and manual refresh.

- [ ] **Step 1: Write failing runtime contract tests**

Assert:

```python
assert "topology" in collectors
assert "guests" in collectors
assert scheduler.interval("guests") == 10.0
assert not scheduler.has_periodic_task("topology")
```

Add a manual-refresh ordering test proving `topology` runs before `smart` and `gpu` during a full refresh.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_main_contract.py dh_pve_app/tests/test_app_runtime.py dh_pve_app/tests/test_runtime_dynamic.py`

- [ ] **Step 3: Wire one shared `TopologyManager` into production collectors**

`build_runtime()` creates exactly one manager. `ResilientProductionCollectors` and inherited GPU logic receive the same instance.

Mapping order for full collection must begin with `topology`, then `guests`, before dependent `smart`/`gpu`. If relying on dictionary insertion order is insufficiently explicit, add a small ordered-full-refresh mechanism in runtime rather than a hidden side effect.

- [ ] **Step 4: Ensure manual refresh forces full topology scan**

The existing `button.dh_pve_refresh` must run the unscheduled `topology` collector as part of the full collection. Normal scheduler ticks must not run it.

- [ ] **Step 5: Run and verify GREEN**

Run focused runtime tests, then:

`PYTHONPATH=. pytest -q dh_pve_app/tests/test_main_contract.py dh_pve_app/tests/test_app_runtime.py dh_pve_app/tests/test_runtime_dynamic.py dh_pve_app/tests/test_topology.py`

- [ ] **Step 6: Commit**

```bash
git add dh_pve_app/app/main.py dh_pve_app/app/app.py dh_pve_app/app/runtime_dynamic.py dh_pve_app/tests/test_main_contract.py dh_pve_app/tests/test_app_runtime.py dh_pve_app/tests/test_runtime_dynamic.py
git commit -m "feat(dh-pve): schedule guest status and topology refresh"
```

Only add files actually changed.

---

### Task 6: MQTT Discovery for VM/LXC inventory

**Files:**
- Modify: `dh_pve_app/app/discovery_metrics.py`
- Modify: `dh_pve_app/tests/test_full_discovery.py`
- Modify: `dh_pve_app/tests/test_discovery_polish.py` if semantic metadata coverage is centralized there.

**Interfaces:**
- Consumes `inventory["guests"]` data shape from Task 2.
- Produces `sensor.dh_pve_vm_<id>_status`, `sensor.dh_pve_lxc_<id>_status`, `sensor.dh_pve_vms`, `sensor.dh_pve_lxcs`.

- [ ] **Step 1: Write failing Discovery tests**

```python
def test_full_discovery_exposes_read_only_guest_status_entities():
    payload = build_full_discovery_payload(..., inventory=INVENTORY_WITH_GUESTS)
    vm = payload["components"]["vm_700_status"]
    assert vm["default_entity_id"] == "sensor.dh_pve_vm_700_status"
    assert "command_topic" not in vm
    assert "guest_id" in vm["json_attributes_template"]
    assert "qemu_agent" in vm["json_attributes_template"]


def test_full_discovery_exposes_vm_and_lxc_summaries():
    ...
    assert payload["components"]["vms"]["default_entity_id"] == "sensor.dh_pve_vms"
    assert payload["components"]["lxcs"]["default_entity_id"] == "sensor.dh_pve_lxcs"
```

Also assert semantic metadata:

```text
proxmox_section = guests
proxmox_subject = vm | lxc | summary
proxmox_metric = status | running
```

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_full_discovery.py`

- [ ] **Step 3: Implement guest Discovery components**

Each per-guest entity state is exactly normalized `running|paused|stopped|unknown`. Summary state is running count; attributes are only total/running/paused/stopped/unknown.

No button, switch, command topic, or action entity is added.

- [ ] **Step 4: Run and verify GREEN**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_full_discovery.py dh_pve_app/tests/test_discovery.py dh_pve_app/tests/test_discovery_polish.py`

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/app/discovery_metrics.py dh_pve_app/tests/test_full_discovery.py dh_pve_app/tests/test_discovery_polish.py
git commit -m "feat(dh-pve): discover VM and LXC status entities"
```

Only add files actually changed.

---

### Task 7: Production dashboard parity plus guest list

**Files:**
- Modify: `dh_pve_app/examples/dh_pve_dashboard.yaml`
- Modify: `dh_pve_app/tests/test_dashboard_contract.py`

**Interfaces:**
- Uses only `dh_pve_*` entities and `proxmox_*` semantic metadata.
- Consumes guest statuses dynamically; no hard-coded VMIDs/CTIDs.

- [ ] **Step 1: Extend dashboard contract test and verify RED**

Require:

```python
assert text.count("  - type: grid\n    cards:") == 4
assert "proxmox_section: guests" in text
assert "sensor.dh_pve_vms" in text
assert "sensor.dh_pve_lxcs" in text
assert "custom:entity-progress-card-template" in text
assert "digitalhouses_proxmox_" not in text
assert "input_number.dh_proxmox" not in text
```

Do not weaken existing rules that prohibit HA infrastructure-health calculation.

- [ ] **Step 2: Run and verify RED**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_dashboard_contract.py`

- [ ] **Step 3: Rebuild the production view as four long sections**

Use the previously validated visual structure:

```text
Column 1: Host → State → Performance → System → Disk diagnostics
Column 2: Physical disks → Proxmox storage → monitoring/runtime settings
Column 3: CPU/RAM/Swap → CPU & throttling → Cooling → Graphics → VM/LXC list → collector diagnostics
Column 4: History
```

Guest list format:

```text
VMs 2 / 3 running
110 · HAOS · stopped
501 · plex-vm · running
700 · TrueNAS · running

LXCs 1 / 1 running
500 · recorder · running
```

Physical disks remain dynamic. Do not mention VM 700 or Samsung 850 explicitly in YAML; the second disk must appear because Discovery exposes it.

Storage progress cards must use Python-provided `used_gib`, `total_gib`, and `usage_percent`, never calculate used as total-free in HA.

- [ ] **Step 4: Run and verify GREEN**

Run: `PYTHONPATH=. pytest -q dh_pve_app/tests/test_dashboard_contract.py`

- [ ] **Step 5: Commit**

```bash
git add dh_pve_app/examples/dh_pve_dashboard.yaml dh_pve_app/tests/test_dashboard_contract.py
git commit -m "feat(dh-pve): add guest inventory to production dashboard"
```

---

### Task 8: Documentation, full regression, and live validation handoff

**Files:**
- Modify: `dh_pve_app/README.md`
- Modify: `dh_pve_app/CHANGELOG.md`

**Interfaces:**
- Documents autonomous topology behavior and exact live verification commands.

- [ ] **Step 1: Update README and CHANGELOG**

Document:

```text
full topology scan at startup/manual refresh
guest status polling
stopped→running targeted rescan
VM hostpci and LXC shared-DRI awareness
guest SMART through QGA
read-only VM/LXC entities
no site-specific passthrough VM list required
```

Include live verification examples for VM 700 and VM 501 without exposing MQTT secrets.

- [ ] **Step 2: Run the entire DH PVE test suite**

Run:

```bash
PYTHONPATH=. pytest -q dh_pve_app/tests
python -m compileall -q dh_pve_app/app
bash -n dh_pve_app/install.sh
systemd-analyze verify dh_pve_app/systemd/dh_pve_app.service
```

Expected: all PASS / no syntax or unit-file errors.

- [ ] **Step 3: Run repository validator**

Run the repository's normal validator command used by `.github/workflows/validate.yml` and confirm the DH PVE contract passes.

- [ ] **Step 4: Commit docs**

```bash
git add dh_pve_app/README.md dh_pve_app/CHANGELOG.md
git commit -m "docs(dh-pve): document guest passthrough monitoring"
```

- [ ] **Step 5: Verify GitHub Actions before live deployment**

Wait for the commit's workflow run and confirm every job succeeds before telling the operator to upgrade the live PVE host.

- [ ] **Step 6: Live PVE acceptance sequence**

After CI is green, update live app through the normal installer. Then verify in this order:

```text
1. DH PVE service active and MQTT initial publication successful.
2. VM/LXC entities appear with correct IDs, names and states.
3. VM 700 topology maps hostpci0 0000:00:17.0 to TrueNAS.
4. Samsung SSD 850 EVO 1TB appears alongside Samsung SSD 990 EVO 1TB.
5. 850 EVO reports WWN 0x5002538d41046527 / serial S2PWNX0H603177N and HEALTHY/WARNING/CRITICAL from Python.
6. VM 501 Intel GPU remains owner=VM 501 and guest transcoding telemetry still updates.
7. Manual Refresh rebuilds topology and updates last_refresh.
8. Dashboard renders as four continuous columns without floating section gaps.
```

Do not decommission the legacy Bash cron in this task. Legacy retirement is a separate acceptance step after side-by-side parity is confirmed.
