"""Hardware interpretations must respect RTL build, predicate and scope evidence."""
import argparse
import copy
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kda_hardware as hardware
from kda_hardware_contract import CONTRACT
import kda_profile as profile
import xsai_kda as kda
from test_profile import ProfileFixture


def reviewed_receipt():
    b = CONTRACT['build']
    return {'emulator': {'sha256': b['emulator_sha256']},
        'build_log_sha256': b['build_log_sha256'], 'configuration': copy.deepcopy(b['configuration']),
        'sources': copy.deepcopy(b['sources']),
        'hpm_event_coding': [{'group': key.rsplit('/', 1)[0], 'id': int(key.rsplit('/', 1)[1]), **value}
                             for key, value in CONTRACT['coding'].items()]}


class HardwareTests(ProfileFixture, unittest.TestCase):
    def hpm_report(self, receipt=None, unresolved=False, line=None):
        receipt = reviewed_receipt() if receipt is None else receipt
        if unresolved:
            receipt['hpm_event_coding'] = []
        run = self.run_input('hpm', cycles=200, artifacts={
            'perf.log': line or b'[xsai-blas-hpm] counter=11 event=EXEC_STALL_CYCLE config=0x43 total=160 per_run=80.00\n',
            'rtl-config.json': json.dumps(receipt).encode()})
        self.build({'perf': [self.run_input(cycles=100)], 'hpm': run})
        return profile.verify_saved_report(self.root / 'report', kda)[0]

    def test_build_binding_requires_exact_emulator_source_and_configuration(self):
        self.assertEqual(hardware.binding(None)['status'], 'unavailable')
        self.assertEqual(hardware.binding(reviewed_receipt())['status'], 'matched')
        for kind in ['emulator', 'configuration', 'sources', 'build_log_sha256']:
            receipt = reviewed_receipt()
            receipt[kind] = [] if kind == 'sources' else {} if kind != 'build_log_sha256' else 'different'
            self.assertEqual(hardware.binding(receipt)['status'], 'unreviewed', kind)

    def test_selector_tree_uses_pairwise_hardware_operator_order(self):
        row = {'rtl_event_names': ['A', 'B', 'C', 'D'], 'event_ids': [1, 2, 3, 4],
               'operators': ['and', 'xor', 'add']}
        self.assertEqual(hardware.expression(row), '((A and B) add (C xor D))')

    def test_rate_uses_hpm_run_cycles_not_faster_uninstrumented_perf(self):
        report = self.hpm_report()
        hpm = hardware.hpm_explanation(report, kda)
        row = hpm['counters'][0]
        self.assertEqual(row['semantic_status'], 'source_reviewed')
        self.assertEqual(row['normalization']['denominator_cycles_per_call'], 200)
        self.assertEqual(row['normalization']['approx_events_per_instrumented_cycle'], 0.4)
        self.assertEqual(row['normalization']['status'], 'approximate')
        self.assertIn('fewer than four', row['issues'][0])
        self.assertIsNone(hpm['cache_miss_rate']['value'])

    def test_unknown_build_explanations_are_reference_only(self):
        receipt = reviewed_receipt()
        receipt['emulator']['sha256'] = 'new-build'
        report = self.hpm_report(receipt)
        hpm = hardware.hpm_explanation(report, kda)
        self.assertEqual(hpm['build_binding']['status'], 'unreviewed')
        self.assertEqual(hpm['counters'][0]['semantic_status'], 'partial')
        self.assertEqual(hpm['counters'][0]['event_definitions'][0]['status'], 'reference_only')

    def test_same_named_event_with_other_signal_does_not_inherit_semantics(self):
        receipt = reviewed_receipt()
        event = next(e for e in receipt['hpm_event_coding'] if e['group'] == 'backend' and e['id'] == 67)
        event['signal'] = 'DifferentSignal'
        report = self.hpm_report(receipt)
        row = hardware.hpm_explanation(report, kda)['counters'][0]
        self.assertEqual(row['semantic_status'], 'partial')
        self.assertEqual(row['event_definitions'][0]['status'], 'reference_only')

    def test_custom_l2_selector_zero_slots_bind_to_reviewed_io_wrapper(self):
        receipt = reviewed_receipt()
        receipt['hpm_event_coding'].append({'group': 'l2 cache', 'id': 0,
            **hardware.CONTRACT['coding']['l2 cache/0']})
        report = self.hpm_report(receipt, line=b'[xsai-blas-hpm] counter=27 event=custom_27 config=0xe total=920 per_run=460.00\n')
        row = hardware.hpm_explanation(report, kda)['counters'][0]
        self.assertEqual(row['event_ids'], [14, 0, 0, 0])
        self.assertEqual(row['semantic_status'], 'source_reviewed')
        self.assertTrue(all(d['status'] == 'source_reviewed' for d in row['event_definitions']))
        self.assertEqual(row['normalization']['events_per_call'], 460)

    def test_unresolved_counters_keep_null_values_and_no_rate(self):
        report = self.hpm_report(unresolved=True)
        row = hardware.hpm_explanation(report, kda)['counters'][0]
        self.assertEqual(row['semantic_status'], 'unresolved')
        self.assertIsNone(row['normalization']['events_per_call'])
        self.assertIsNone(row['normalization']['approx_events_per_instrumented_cycle'])

    def test_missing_diagnostics_are_explicit_and_export_preserves_input(self):
        self.build({'perf': [self.run_input()]})
        before = profile.digest(self.root / 'report/report.json')
        with redirect_stdout(io.StringIO()):
            hardware.dispatch(argparse.Namespace(report=self.root / 'report', output=self.root / 'hardware'), kda)
        result = profile.read_json(self.root / 'hardware/hardware.json')
        self.assertEqual(result['hpm']['status'], 'unavailable')
        self.assertEqual(result['cute_phases']['status'], 'unavailable')
        self.assertIsNone(result['clocks']['cross_engine_overlap'])
        self.assertEqual(profile.digest(self.root / 'report/report.json'), before)
        self.assertTrue((self.root / 'hardware/index.html').exists())
        with self.assertRaises(RuntimeError):
            hardware.dispatch(argparse.Namespace(report=self.root / 'report', output=self.root / 'report/derivative'), kda)

    def test_tampered_raw_hpm_is_rejected_without_output(self):
        report = self.hpm_report()
        (Path(report['sections']['hpm']['run']) / 'perf.log').write_text('changed')
        with self.assertRaises(RuntimeError):
            hardware.dispatch(argparse.Namespace(report=self.root / 'report', output=self.root / 'bad'), kda)
        self.assertFalse((self.root / 'bad').exists())

    def test_pinned_contract_captures_misleading_event_predicates(self):
        ready = hardware.event_definition('IssueQueueAluCsrFenceDivMcfg_full', 'backend')
        self.assertIn('ready', ready['predicate'])
        self.assertIn('no negation', ready['caveat'])
        miss = hardware.event_definition('l1D_write_dcache_miss', 'memblock')
        self.assertIn('including hits', miss['caveat'])
        self.assertIsNone(hardware.event_definition('unreviewed', 'backend'))

    def test_aggregate_cache_counter_warns_about_store_predicate(self):
        receipt = reviewed_receipt()
        for event in receipt['hpm_event_coding']:
            event['group'] = event['group'].title()
        report = self.hpm_report(receipt, line=b'[xsai-blas-hpm] counter=22 event=l1D_dcache_miss_all config=0x001084158771c069 total=160 per_run=80.00\n')
        row = hardware.hpm_explanation(report, kda)['counters'][0]
        self.assertEqual(row['semantic_status'], 'source_reviewed')
        self.assertTrue(any('including hits' in s for s in row['issues']))


class CutePhaseTests(ProfileFixture, unittest.TestCase):
    def phase_report(self):
        db = self.root / 'chiseldb.db'
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE CUTEComputeEvent(SEQID INTEGER,SITE TEXT,STAMP INTEGER)')
            for site, stamp in [('ComputeIssue', 1000), ('ComputeReadAFinish', 1010),
                                 ('ComputeReadBFinish', 1015), ('ComputeWriteCFinish', 1050)]:
                connection.execute('INSERT INTO CUTEComputeEvent VALUES(1,?,?)', (site, stamp))
        return {'sections': {'trace': {'status': 'available', 'run': str(self.root), 'cute': {
            'status': 'unscoped', 'scope': 'all tasks', 'stages': [
                {'table': 'CUTEComputeEvent', 'role': 'all', 'tasks': [{'seq_id': 1}]}]}}}}

    def test_subphases_overlap_and_keep_unscoped_status(self):
        phases = hardware.cute_phases(self.phase_report())
        self.assertEqual(phases['status'], 'unscoped')
        self.assertEqual([p['median_cycles'] for p in phases['stages'][0]['phases']], [10, 15, 50])
        self.assertIn('overlap', phases['semantics'])

    def test_missing_and_out_of_order_sites_do_not_become_zero(self):
        report = self.phase_report()
        with sqlite3.connect(self.root / 'chiseldb.db') as db:
            db.execute("DELETE FROM CUTEComputeEvent WHERE SITE='ComputeReadAFinish'")
            db.execute("UPDATE CUTEComputeEvent SET STAMP=999 WHERE SITE='ComputeReadBFinish'")
        phases = hardware.cute_phases(report)['stages'][0]['phases']
        self.assertEqual([p['median_cycles'] for p in phases], [None, None, 50])
        self.assertEqual([p['missing_tasks'] for p in phases], [1, 1, 0])


if __name__ == '__main__':
    unittest.main()
