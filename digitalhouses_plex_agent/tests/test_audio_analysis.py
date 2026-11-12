import sys
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.activity_classifier import classify_activity
from app.models import ProcessSample, MonitorSnapshot, CpuMetrics, CpuGroupMetrics, BuildInfo, build_state_payload
from app.presentation_plex import PlexPresentationRouter, _activity_payload
from app.publish_policy import PublishPolicy
from app.discovery import build_discovery_payload, build_topics, state_group_topic
from app.config import load_config


def process(pid=10, options=('-af', 'loudnorm=I=-16:TP=-1:LRA=9:print_format=json', '-f', 'null', '-')):
    return ProcessSample(pid, 1, 'Plex Transcoder', ('/usr/lib/plexmediaserver/Plex Transcoder', '-i', '/serzhan-pool/media/movies/Inception (2010)/Inception (2010) Remux-2160p.mkv', '-map', '0:5', *options), 12.3)


def snapshot(activity):
    zero = CpuGroupMetrics(0, 0, 0)
    return MonitorSnapshot('now', activity, CpuMetrics(zero, zero, zero), 1, 'ok', None)


class AudioAnalysisTests(unittest.TestCase):
    def test_real_command_and_legacy_diagnostics(self):
        a = classify_activity([process()])
        self.assertEqual(a.activity, 'audio_analysis')
        self.assertTrue(a.transcoder_running)
        self.assertEqual(a.transcoder_count, 1)
        self.assertTrue(a.audio_analysis_running)
        self.assertEqual(a.audio_analysis_count, 1)
        self.assertEqual(a.background_processes[0].current_item, 'Inception (2010) Remux-2160p.mkv')

    def test_option_variants_and_false_positives(self):
        for option in ('-af', '-filter:a', '-filter:a:0'):
            for args in ((option, 'volume=1,loudnorm=I=-16,aresample=48000', '-f', 'null', '-'), (option + '=loudnorm', '-f=null', '-')):
                with self.subTest(args=args):
                    self.assertEqual(classify_activity([process(options=args)]).activity, 'audio_analysis')
        for args in (('-f', 'null', '-'), ('-af', 'loudnormalize', '-f', 'null', '-'), ('-vf', 'loudnorm', '-f', 'null', '-'), ('-af', 'ametadata=value=loudnorm', '-f', 'null', '-'), ('-af', "ametadata=value='x,loudnorm=I=-16'", '-f', 'null', '-'), ('-af', 'loudnorm', '-f', 'null', '-f', 'dash', '/tmp/out'), ('-f', 'null', '-i', '/media/input', '-af', 'loudnorm', '/tmp/out'), ('-af', 'loudnorm', '-f', 'mp4', '/tmp/out'), ('-i', '/media/loudnorm.mkv', '-f', 'null', '-')):
            with self.subTest(args=args):
                self.assertEqual(classify_activity([process(options=args)]).activity, 'transcoding')

    def test_parallel_processes_and_bound(self):
        tasks = [process(i) for i in range(30, 0, -1)]
        a = classify_activity(tasks)
        self.assertEqual(a.audio_analysis_count, 30)
        self.assertEqual([p.pid for p in a.background_processes], list(range(1, 25)))
        self.assertEqual(a.background_processes, classify_activity(list(reversed(tasks))).background_processes)
        self.assertEqual(classify_activity([process(), process(50, ())]).activity, 'multiple')
        scanner = ProcessSample(60, 1, 'Plex Media Scanner', ('Plex Media Scanner', '--server-action', 'credits', '--file', '/media/other.mkv'), 1)
        mixed = classify_activity([process(), scanner, process(50, ())])
        self.assertEqual(mixed.activity, 'multiple')
        self.assertEqual(len(mixed.background_processes), 2)
        self.assertEqual(mixed.background_processes[1].kind, 'credits_detection')

    def test_payload_publication_and_transitions(self):
        a = classify_activity([process()])
        s = snapshot(a)
        payload = _activity_payload(s)
        self.assertEqual(payload['background_process_count'], 1)
        self.assertNotIn('cpu_percent', payload['background_processes'][0])
        self.assertNotIn('/serzhan', str(payload))
        for key in ('audio_analysis_running', 'audio_analysis_count', 'background_processes', 'background_process_count'):
            self.assertEqual(build_state_payload(s, BuildInfo('0.8.8', 'test', 'unknown'))[key], payload[key])
        policy = PublishPolicy(5, 80, 60)
        policy.mark_published(s, 0)
        changed = snapshot(classify_activity([process(11)]))
        self.assertIn('activity_change', policy.evaluate(changed, 1).reasons)
        router = PlexPresentationRouter(source_interval_seconds=5)
        self.assertIn('activity', [p.group for p in router.route(s, {}, now=0)])
        self.assertNotIn('activity', [p.group for p in router.route(s, {}, now=1)])
        for current in (changed, snapshot(classify_activity([process(11, ())])), snapshot(classify_activity([]))):
            self.assertIn('activity', [p.group for p in router.route(current, {}, now=2)])

    def test_discovery(self):
        with TemporaryDirectory() as tmp:
            path = Path(tmp) / 'config'
            path.write_text('[mqtt]\nhost = mqtt\n')
            cfg = load_config(path)
        topics = build_topics(cfg)
        components = build_discovery_payload(cfg, BuildInfo('0.8.8', 'test', 'unknown'))['components']
        sensor = components['background_processes']
        self.assertEqual(sensor['default_entity_id'], 'sensor.dh_plex_agent_background_processes')
        self.assertEqual(sensor['state_topic'], state_group_topic(topics, 'activity'))
        self.assertEqual(sensor['json_attributes_topic'], sensor['state_topic'])
        self.assertIn('background_process_count', sensor['value_template'])
        self.assertNotIn('entity_category', sensor)
        self.assertIn(topics.collector_availability, str(sensor['availability']))
        binary = components['audio_analysis_running']
        self.assertEqual(binary['state_topic'], sensor['state_topic'])
        self.assertNotIn('json_attributes_topic', binary)

    def test_dashboard_compact_and_storage_preserved(self):
        text = (Path(__file__).resolve().parents[1] / 'examples/lovelace/plex-dashboard.yaml').read_text()
        section = text.split('heading: Фоновые задачи')[1].split('heading: Библиотеки')[0]
        self.assertEqual(section.count('type: custom:mushroom-template-card'), 1)
        self.assertNotIn('type: entities', section)
        self.assertNotIn('Process Details', text)
        self.assertIn('sensor.dh_plex_agent_background_processes', section)
        self.assertIn('condition: numeric_state', section)
        self.assertIn('above: 0', section)
        self.assertIn("state_attr('sensor.dh_plex_agent_background_processes', 'processes')", section)
        self.assertNotIn('state_attr(entity', section)
        self.assertIn("is_state('binary_sensor.dh_plex_agent_audio_analysis_running', 'on')", text)
        self.assertIn("plex_section') == 'library_storage'", text)
        self.assertIn('custom:entity-progress-card-template', text)
        self.assertIn('sensor.dh_plex_agent_library_storage_', text)
