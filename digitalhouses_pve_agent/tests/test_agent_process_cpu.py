"""Agent process CPU load, sustained-overload hysteresis and HA discovery."""
import contextlib
import io
from unittest.mock import patch

from app.agent_process_cpu import AgentProcessCpu
from app import cli
from app.discovery_metrics import build_full_discovery_payload
from app.discovery_groups import _problem_components
from app.problems import PveProblemEngine
from app.pve_problem_events import semantic_pve_problem_event


def test_overload_requires_five_minutes_over_80_percent():
    cpu = AgentProcessCpu()
    assert cpu.observe(now=0, cpu_time=0) is None
    for second in range(10, 311, 10):
        result = cpu.observe(now=second, cpu_time=second * 0.81)
        assert result == 81.0
        assert cpu.overloaded is (second == 310)
    assert cpu.snapshot()['overloaded'] is True


def test_recovery_requires_two_minutes_below_40_percent():
    cpu = AgentProcessCpu()
    cpu.observe(now=0, cpu_time=0)
    for second in range(10, 311, 10):
        cpu.observe(now=second, cpu_time=second * .90)
    assert cpu.overloaded is True
    current = 310 * .90
    for second in range(320, 441, 10):
        current += 3
        cpu.observe(now=second, cpu_time=current)
        assert cpu.overloaded is (second != 440)


def test_transient_spike_and_recovery_interrupt_do_not_trigger():
    cpu = AgentProcessCpu()
    cpu.observe(now=0, cpu_time=0)
    accumulated = 0.0
    for second in range(10, 291, 10):
        accumulated += 8.5
        cpu.observe(now=second, cpu_time=accumulated)
    assert cpu.overloaded is False
    accumulated += 4.0
    cpu.observe(now=300, cpu_time=accumulated)  # interrupts overload countdown
    for second in range(310, 601, 10):
        accumulated += 8.5
        cpu.observe(now=second, cpu_time=accumulated)
        assert cpu.overloaded is False


def test_process_percent_is_per_core_can_exceed_100_and_gap_breaks_window():
    cpu = AgentProcessCpu()
    cpu.observe(now=1,cpu_time=1)
    assert cpu.observe(now=11,cpu_time=16) == 150.0
    assert cpu.overloaded is False
    assert cpu.observe(now=111,cpu_time=50) is None
    assert cpu.overloaded is False
    assert cpu.observe(now=121,cpu_time=59) == 90.0
    assert cpu.overloaded is False


def test_problem_state_and_semantic_event_use_agent_specific_identity():
    engine = PveProblemEngine()
    assert engine.observe_agent_cpu(5.0, False) is None
    started = engine.observe_agent_cpu(91.0, True)
    assert started is not None
    assert started.current.problem_id == 'agent_cpu_overload'
    assert engine.aggregate().count == 1
    event = semantic_pve_problem_event(started, observed_at='2026-11-13T00:00:00Z')
    assert event['event_type'] == 'agent_cpu_overload_started'
    recovered = engine.observe_agent_cpu(31.0, False)
    assert recovered is not None
    assert semantic_pve_problem_event(recovered, observed_at='2026-11-13T00:10:00Z')['event_type'] == 'agent_cpu_overload_cleared'
    assert engine.aggregate().count == 0


def test_discovery_has_independent_process_cpu_sensor_and_problem_binary():
    class Topics:
        device_id = 'testdevice'
        base = 'DigitalHouses/System/Proxmox/test'
        availability = 'DigitalHouses/System/Proxmox/test/availability'
    problems = _problem_components(Topics(), {})
    binary = problems['agent_cpu_overload']
    assert binary['default_entity_id'] == 'binary_sensor.dh_pve_agent_cpu_overload'
    assert binary['device_class'] == 'problem'
    assert binary['state_topic'].endswith('/problems/agent_cpu_overload/state')
    assert binary['payload_on'] == 'ON'
    assert binary['payload_off'] == 'OFF'

    from app.config import load_config
    from pathlib import Path
    import tempfile
    from app.identity import resolve_identity
    with tempfile.TemporaryDirectory() as dirname:
        path = Path(dirname) / 'config.ini'
        path.write_text('[mqtt]\nhost=192.168.11.222\n')
        config = load_config(path)
        identity = resolve_identity(config.general)
        components = build_full_discovery_payload(config, identity, version='0.5.88')['components']
        sensor = components['agent_process_cpu_usage']
        assert sensor['default_entity_id'] == 'sensor.dh_pve_agent_process_cpu_usage'
        assert sensor['state_class'] == 'measurement'
        assert sensor['unit_of_measurement'] == '%'
        assert components['cpu_usage']['default_entity_id'] == 'sensor.dh_pve_agent_cpu_usage'


def test_local_cli_displays_agent_cpu_without_mqtt():
    from pathlib import Path
    import tempfile
    with tempfile.TemporaryDirectory() as dirname:
        cfg = Path(dirname)/'cfg'
        cfg.write_text('[mqtt]\nhost=127.0.0.1\n')
        runtime = {'agent_process_cpu':{'usage_percent':97.4,'overloaded':True},
                   'samples':{}, 'ups_configured':False}
        with patch.object(cli, 'service_info', return_value={'ActiveState':'active'}), \
             patch('app.runtime_status.read_status', return_value=(runtime, True)), \
             patch('app.runtime_status.host_identity', return_value={'hostname':'pve','ip':'192.168.11.220'}), \
             contextlib.redirect_stdout(io.StringIO()) as stream:
            cli.print_status(cfg)
        assert 'Agent CPU: 97% | overload ON' in stream.getvalue()



def test_runtime_stores_offline_problem_state_without_queuing_stale_events():
    from app.runtime_problems import ProblemAwareRuntime
    engine = PveProblemEngine()
    runtime = object.__new__(ProblemAwareRuntime)
    runtime.problem_engine = engine
    runtime._pending_problem_transitions = []
    runtime._published_problem_ids = set()
    runtime._problem_snapshot_dirty = False

    runtime.observe_agent_cpu(91.0, True, online=False)
    assert engine.aggregate().count == 1
    assert runtime._pending_problem_transitions == []
    assert runtime._problem_snapshot_dirty is True

    runtime.observe_agent_cpu(30.0, False, online=False)
    assert engine.aggregate().count == 0
    assert runtime._pending_problem_transitions == []

    runtime.observe_agent_cpu(93.0, True, online=True)
    assert len(runtime._pending_problem_transitions) == 1
    assert runtime._pending_problem_transitions[0].current.problem_id == 'agent_cpu_overload'
