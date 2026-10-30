"""Public setup, honest metric discovery and useful analysis without trace."""
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import cli
import kda_catalog as catalog
import kda_profile as profile
import kda_setup as setup
import kda_analyze as analyze
import kda_summary as summary
import xsai_kda as kda
import kda_observer as observer
import kda_portable as portable
from test_profile import ProfileFixture


class BetaTests(ProfileFixture, unittest.TestCase):
    def replay_spec(self, change=None, image=b'correctness-image'):
        known = observer.OBSERVER
        receipt = {'emulator': {'sha256': known['emulator_sha256']},
            'configuration': {'NUM_CORES': '1'},
            'clock_bridge': {'observer_sha256': known['logger_sha256'],
                'base_emulator_sha256': known['base_emulator_sha256'], 'single_core_only': True},
            'memory_observer': {'schema': 'xsai-prof.observer/v1', 'beat_bytes': 64,
                'rtl_regenerated': False, 'chisel_db.cpp': known['logger_sha256'],
                'perfCCT.cpp': known['lifetime_sha256'], 'observer.h': known['header_sha256']}}
        payload = json.dumps(receipt).encode()
        import hashlib
        rtl = {'emu_sha256': known['emulator_sha256'], 'config_sha256': hashlib.sha256(payload).hexdigest()}
        return {'perf': [self.run_input(artifacts={'test.bin': b'correctness-image', 'test.elf': b'correctness-elf'})],
            'trace': self.run_input(mode='trace', change={'rtl': rtl, **(change or {})},
                artifacts={'test.bin': image, 'test.elf': b'correctness-elf', 'rtl-config.json': payload})}

    def test_observation_only_import_preserves_independent_perf_identity(self):
        spec = self.replay_spec()
        original = {'validation': {'diagnostics_bound_to_perf': False,
            'observation_replay': 'Same software; independent reviewed observer'}}
        output = self.root / 'rebuild'
        output.mkdir()
        trace = {'status': 'available', 'functions': [], 'cute': {'status': 'unscoped'}}
        with patch.object(profile, 'trace_section', return_value=trace):
            result = portable.build_imported_report(spec, {}, output, kda, original)
        self.assertFalse(result['validation']['diagnostics_bound_to_perf'])
        self.assertEqual(result['identity']['rtl']['emu_sha256'], 'fixture-emu')
        self.assertEqual(result['sections']['performance']['measurements'][0]['median_cycles'], 100)
        self.assertEqual(len(result['inputs']), 2)
        self.assertIn('No new speedup claim.', result['warnings'][-1])

    def test_observation_only_import_cannot_bypass_software_or_correctness_binding(self):
        original = {'validation': {'diagnostics_bound_to_perf': False, 'observation_replay': 'Explicit replay'}}
        for change, image, error in [({'source': {'sha256': 'changed'}}, b'correctness-image', 'source identity'),
                ({}, b'changed-image', 'correctness image'),
                ({'rtl': {'emu_sha256': 'unknown', 'config_sha256': 'unknown'}}, b'correctness-image', 'reviewed observer')]:
            spec = self.replay_spec(change, image)
            with self.subTest(error=error), self.assertRaisesRegex(RuntimeError, error):
                portable.build_imported_report(spec, {}, self.root, kda, original)

    def test_normal_import_keeps_strict_rtl_binding(self):
        spec = self.replay_spec()
        with self.assertRaisesRegex(RuntimeError, 'Diagnostic workload/build differs: rtl'):
            portable.build_imported_report(spec, {}, self.root, kda, {'validation': {'diagnostics_bound_to_perf': True}})

    def test_init_is_explicit_non_destructive_and_doctor_explains_missing_paths(self):
        out = self.root / 'collection.json'
        argv = ['init', '--output', str(out)]
        for flag in ['blas', 'noop-home', 'rtl-config', 'xsai-env', 'am-home', 'llvm-home']:
            argv += ['--' + flag, str(self.root / ('missing-' + flag))]
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(argv), 0)
        config = profile.read_json(out)
        self.assertEqual((config['kernel'], config['case']), ('softmax', 1))
        self.assertEqual(config['diagnostics'], [])
        original = out.read_bytes()
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cli.main(argv), 1)
        self.assertEqual(out.read_bytes(), original)
        doctor = catalog.doctor(out, kda)
        self.assertEqual(doctor['rtl_collection']['status'], 'unavailable')
        self.assertTrue(doctor['rtl_collection']['next_steps'])

    def test_unknown_target_does_not_inherit_reviewed_metrics(self):
        result = setup.target_support({'emulator': {'sha256': 'unknown'}})
        self.assertEqual(result['status'], 'unreviewed')
        self.assertFalse(any(result['coverage'].values()))

    def test_perf_only_analysis_has_no_invented_memory_hypothesis(self):
        self.build({'perf': [self.run_input()]})
        report, path = profile.verify_saved_report(self.root / 'report', kda)
        result = analyze.analyze(report, kda, directory=path)
        self.assertEqual(result['overview']['hypotheses'], [])
        self.assertEqual(result['overview']['coverage']['memory'], 'unavailable')
        self.assertEqual(result['overview']['coverage']['trace'], 'unavailable')
        self.assertEqual(result['overview']['performance']['repeat_count'], 1)
        self.assertIn('Experiments to validate', analyze.html_view(result))

    def test_legacy_memory_catalog_does_not_advertise_unobserved_returns(self):
        self.build({'perf': [self.run_input()]})
        report, _ = profile.verify_saved_report(self.root / 'report', kda)
        report['sections']['trace'] = {'status': 'available', 'memory': {
            'status': 'available', 'metrics': {'read_payload_bytes': None},
            'cpu': {'status': 'unavailable', 'metrics': None}}}
        for name in ['ame_read_payload_bytes', 'ame_read_service_cycles', 'cpu_read_request_enabled_bytes']:
            self.assertEqual(catalog.metric_availability(name, 'memory', report)[0], 'unavailable')

    def test_read_events_produce_a_falsifiable_experiment(self):
        result = summary.overview({'performance': {'repeat_count': 1, 'measurements': []},
            'memory': {'status': 'available', 'metrics': {'observed_read_completions': 4,
                'read_completion_latency': 7, 'read_outstanding_max': 4}},
            'diagnosis': {'observations': []}, 'ranges': {'status': 'available'}})
        idea = result['hypotheses'][0]
        self.assertEqual(idea['status'], 'untested')
        self.assertTrue(idea['experiment'] and idea['prediction'] and idea['falsifier'])
        self.assertEqual(result['coverage']['dram_bytes'], 'unavailable')

    def test_unscoped_release_groups_are_not_assumed_one_per_task(self):
        with sqlite3.connect(':memory:') as connection:
            connection.row_factory = sqlite3.Row
            for table in ['CUTELoadEvent', 'CUTEComputeEvent', 'CUTEStoreEvent']:
                connection.execute('CREATE TABLE '+table+'(SEQID INT,SITE TEXT,STAMP INT,NEEDMASK INT)')
            connection.execute('CREATE TABLE CUTEReleaseEvent(STAMP INT)')
            connection.executemany('INSERT INTO CUTEReleaseEvent VALUES(?)', [(20,), (30,)])
            connection.executemany('INSERT INTO CUTEStoreEvent VALUES(?,?,?,?)',
                [(1, 'StoreIssue', 22, 0), (1, 'StoreFinish', 25, 0)])
            result = profile.cute_summary(connection, {})
            self.assertEqual(result['status'], 'unscoped')
            self.assertFalse(result['task_release_count_agreement'])


if __name__ == '__main__':
    unittest.main()
