"""CLI/MQTT auto-update preference and reuse of the existing release checker."""
import io
import time
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from app import cli
from app.auto_update import AutoUpdatePreference
from app.config import AppConfig, GeneralConfig, MqttConfig
from app.discovery import build_discovery_payload
from app.identity import HostIdentity
from app.mqtt_bridge import MqttBridge, MqttEvents
from app.runtime_settings import RuntimeSettings
from app.topics import build_topics
from app.update_manager import UpdateManager


def _topics():
    mqtt = MqttConfig(host='localhost', port=1883, username='', password='',
                      topic_prefix='DigitalHouses/Global/digitalhouses_pve_agent',
                      discovery_prefix='homeassistant', keepalive_seconds=60)
    identity = HostIdentity(machine_id='12345678901234567890123456789012',
                            instance_id='node_a', hostname='pve', node_name='PVE')
    return mqtt, identity, build_topics(mqtt, identity)


def test_persistent_off_by_default_and_idempotent_cli(tmp_path):
    preference = AutoUpdatePreference(tmp_path)
    assert preference.enabled() is False
    with redirect_stdout(io.StringIO()) as output:
        cli.auto_update_cli('status', state_dir=tmp_path)
        cli.auto_update_cli('on', state_dir=tmp_path)
        cli.auto_update_cli('on', state_dir=tmp_path)
    assert output.getvalue().splitlines() == ['OFF', 'CHANGED ON', 'UNCHANGED ON']
    assert AutoUpdatePreference(tmp_path).enabled() is True
    with redirect_stdout(io.StringIO()) as output:
        cli.auto_update_cli('off', state_dir=tmp_path)
    assert output.getvalue().strip() == 'CHANGED OFF'
    assert AutoUpdatePreference(tmp_path).enabled() is False


def test_mqtt_switch_uses_existing_update_state_and_rejects_retained_commands():
    mqtt, identity, topics = _topics()
    config = AppConfig(general=GeneralConfig(instance_id='node_a', node_name='PVE', log_level='info'), mqtt=mqtt)
    discovery = build_discovery_payload(config, identity, version='0.5.90')
    switch = discovery['components']['auto_update']
    assert switch['platform'] == 'switch'
    assert switch['default_entity_id'] == 'switch.dh_pve_agent_auto_update'
    assert switch['command_topic'] == topics.update_auto_set
    assert switch['state_topic'] == topics.update_state
    assert switch['retain'] is False
    assert switch['payload_on'] == 'ON'
    assert switch['payload_off'] == 'OFF'
    events = MqttEvents(topics, RuntimeSettings())
    assert not events.handle_message(topics.update_auto_set, b'garbage')
    assert events.auto_update_updates.empty()
    assert events.handle_message(topics.update_auto_set, b'ON')
    assert events.handle_message(topics.update_auto_set, b'OFF')
    assert events.auto_update_updates.get_nowait() is True
    assert events.auto_update_updates.get_nowait() is False
    bridge = object.__new__(MqttBridge)
    MqttEvents.__init__(bridge, topics, RuntimeSettings())
    bridge.log = Mock()
    bridge.wake_requested = Mock()
    bridge._on_message(None, None, SimpleNamespace(topic=topics.update_auto_set, payload=b'ON', retain=True))
    assert bridge.auto_update_updates.empty()


def test_autoinstall_only_after_new_verified_check_and_only_once(tmp_path):
    manager = UpdateManager(tmp_path, '0.5.89')
    manager._last_check = time.monotonic()
    manager._launch_update = Mock()
    bridge = Mock()
    bridge.publish_update_state.return_value = True
    manager._check_result = ('digitalhouses_pve_agent-v0.5.90', '0.5.90')
    manager.tick(bridge, denial_reason=lambda: None)
    manager._launch_update.assert_not_called()
    assert bridge.publish_update_state.call_args.args[0]['auto_update'] is False
    assert AutoUpdatePreference(tmp_path).set(True)
    # Enabling after an old check does not install from cached/stale state.
    manager.tick(bridge, denial_reason=lambda: None)
    manager._launch_update.assert_not_called()
    manager._check_result = ('digitalhouses_pve_agent-v0.5.90', '0.5.90')
    manager.tick(bridge, denial_reason=lambda: None)
    manager._launch_update.assert_called_once()
    assert bridge.publish_update_state.call_args.args[0]['auto_update'] is True
    manager.tick(bridge, denial_reason=lambda: None)
    manager._launch_update.assert_called_once()


def test_auto_install_deferred_while_card_busy_and_ups_guarded(tmp_path):
    AutoUpdatePreference(tmp_path).set(True)
    manager = UpdateManager(tmp_path, '0.5.89')
    manager._last_check = time.monotonic()
    manager._check_result = ('digitalhouses_pve_agent-v0.5.90', '0.5.90')
    manager._launch_update = Mock()
    bridge = Mock()
    bridge.publish_update_state.return_value = True
    manager.tick(bridge, allow_auto_install=False, denial_reason=lambda: None)
    manager._launch_update.assert_not_called()
    manager.tick(bridge, denial_reason=lambda: 'UPS on battery')
    manager._launch_update.assert_not_called()
    assert bridge.publish_update_state.call_args.args[0]['error'] == 'UPS on battery'
    manager.tick(bridge, denial_reason=lambda: None)
    manager._launch_update.assert_not_called()


def test_check_error_and_invalid_preference_never_install(tmp_path):
    manager = UpdateManager(tmp_path, '0.5.89')
    manager._last_check = time.monotonic()
    manager._launch_update = Mock()
    bridge = Mock()
    bridge.publish_update_state.return_value = True
    AutoUpdatePreference(tmp_path).set(True)
    manager._check_error = 'offline'
    manager.tick(bridge, denial_reason=lambda: None)
    manager._launch_update.assert_not_called()
    (tmp_path/'auto_update.json').write_text('{"enabled":"true"}')
    manager._check_result = ('digitalhouses_pve_agent-v0.5.90', '0.5.90')
    manager.tick(bridge, denial_reason=lambda: None)
    manager._launch_update.assert_not_called()
    assert bridge.publish_update_state.call_args.args[0]['auto_update'] is False
