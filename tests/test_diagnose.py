"""Diagnosis validity: restricted observations, explicit uncertainty and safe output."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kda_diagnose as d
import kda_profile as p
import xsai_kda as kda
from test_profile import ProfileFixture


def report():
    return {'schema': p.SCHEMA, 'kind': 'profile', 'label': 'SECRET_LABEL',
            'spec': {'hpm': 'SECRET_PATH'},
            'sections': {
                'performance': {'repeat_count': 2, 'measurements': [{
                    'op': 'flash_attention(q=7,kv=33,d=35)', 'unit': 'RVV', 'cycles': [100, 100],
                    'median_cycles': 100, 'min_cycles': 100, 'max_cycles': 100,
                    'instret': ['SECRET_INSTRET']} ]},
                'hpm': {'status': 'available', 'counters': [
                    {'counter': 1, 'config': '0x1', 'rtl_event_names': ['EXEC_STALL_CYCLE'],
                     'operators': [], 'per_run': 70, 'encoding_resolved': True},
                    {'counter': 2, 'config': '0x2', 'rtl_event_names': ['SECRET_UNRESOLVED'],
                     'operators': [], 'per_run': 9999, 'encoding_resolved': False}]},
                'trace': {'status': 'available', 'window': {'roi_cycles': 800},
                    'functions': [{'function': 'memset', 'instructions': 200, 'retirement_cycles': 400},
                                  {'function': 'update', 'instructions': 100, 'retirement_cycles': 200}],
                    'mnemonics': {'memset': {'sd': 20}, 'update': {
                        'vle8.v': 17, 'vsext.vf2': 17, 'vfwcvt.f.x.v': 17, 'vfmacc.vf': 17}},
                    'pcs': [], 'cute': {'status': 'unavailable'}}}}


class DiagnosisTests(unittest.TestCase):
    def test_cycles_allowlist_cannot_leak_instret_diagnostics_or_input_paths(self):
        result = d.diagnose(report(), 'cycles')
        encoded = json.dumps(result)
        for forbidden in ('SECRET', 'memset', 'EXEC_STALL', 'vle8', '9999'):
            self.assertNotIn(forbidden, encoded)
        self.assertEqual(result['hypotheses'], [])
        self.assertIn('Cycles alone do not identify a bottleneck.', result['missing_evidence'])

    def test_hpm_cannot_infer_trace_local_causes_or_treat_unknown_as_resolved(self):
        result = d.diagnose(report(), 'hpm')
        self.assertNotIn('memset', json.dumps(result))
        observed = next(x for x in result['observations'] if x['id'] == 'resolved_hpm')
        self.assertEqual(len(observed['values']), 1)
        self.assertEqual(observed['values'][0]['counter'], 1)
        self.assertIn('Unresolved HPM selectors: [2]', result['missing_evidence'])

    def test_trace_reuse_and_initialization_are_falsifiable_not_causal_claims(self):
        result = d.diagnose(report())
        hypotheses = {x['id']: x for x in result['hypotheses']}
        self.assertIn('inspect_memset', hypotheses)
        self.assertIn('reuse_update', hypotheses)
        for hypothesis in hypotheses.values():
            self.assertEqual(hypothesis['status'], 'untested')
            self.assertEqual(hypothesis['confidence'], 'hypothesis_only')
            self.assertTrue(hypothesis['falsifying_observation'])
            self.assertTrue(hypothesis['missing_evidence'])
        self.assertIn('no causal bottleneck', result['conclusion'])
        self.assertIn('Poison/tail', hypotheses['inspect_memset']['falsifying_observation'])

    def test_conversions_without_arithmetic_are_not_row_reuse_evidence(self):
        fixture = report()
        fixture['sections']['trace']['mnemonics']['update'].pop('vfmacc.vf')
        self.assertNotIn('reuse_update', [x['id'] for x in d.diagnose(fixture)['hypotheses']])

    def test_softmax_polynomial_does_not_trigger_multirow_conversion_reuse(self):
        fixture = report()
        fixture['sections']['performance']['measurements'][0]['op'] = 'softmax(n=1024)'
        self.assertNotIn('reuse_update', [x['id'] for x in d.diagnose(fixture)['hypotheses']])

    def test_whole_register_traffic_requires_stack_operand_confirmation(self):
        fixture = report()
        fixture['sections']['trace']['mnemonics']['update']['vs8r.v'] = 8
        result = d.diagnose(fixture)
        h = next(x for x in result['hypotheses'] if x['id'] == 'register_pressure_update')
        self.assertIn('stack', h['validation_experiment'].lower())
        self.assertIn('Cycles increase', h['falsifying_observation'])

    def test_absent_evidence_and_changed_repeats_stay_explicit(self):
        fixture = report()
        fixture['sections']['hpm'] = fixture['sections']['trace'] = {'status': 'unavailable'}
        fixture['sections']['performance']['measurements'][0].update(cycles=[100, 101], max_cycles=101)
        result = d.diagnose(fixture)
        self.assertEqual(result['hypotheses'], [])
        self.assertTrue(any(x['id'] == 'repeat_variation' for x in result['observations']))
        self.assertTrue(any('unavailable' in x for x in result['missing_evidence']))

    def test_comparison_and_invalid_level_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'not a comparison'):
            d.diagnose({**report(), 'kind': 'comparison'})
        with self.assertRaisesRegex(RuntimeError, 'Unknown feedback'):
            d.diagnose(report(), 'all')


class DiagnosisOutputTests(ProfileFixture, unittest.TestCase):
    def test_verified_input_atomic_shared_views_and_changed_input_rejection(self):
        self.build({'perf': [self.run_input(), self.run_input()]})
        output = self.root / 'diagnosis'
        result = d.publish(self.root / 'report', output, 'cycles', kda)
        self.assertEqual(result['status'], 'passed')
        saved = p.read_json(output / 'diagnosis.json')
        self.assertEqual(saved['input']['report_sha256'], p.digest(self.root / 'report/report.json'))
        self.assertTrue((output / 'index.html').exists())
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            d.publish(self.root / 'report', output, 'cycles', kda)
        path = self.root / 'report/report.json'
        path.write_bytes(path.read_bytes() + b' ')
        with self.assertRaisesRegex(RuntimeError, 'artifact changed'):
            d.publish(self.root / 'report', self.root / 'bad', 'trace', kda)
        self.assertFalse((self.root / 'bad').exists())


if __name__ == '__main__':
    unittest.main()
