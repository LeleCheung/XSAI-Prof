"""Protocol bytes and scope omission must remain distinct from unavailable data."""
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kda_memory as memory
import kda_roi as roi
import kda_profile as p
import kda_observer as observer
import kda_collect as collect
import argparse
import kda_catalog as catalog


def a(ident, cpu, source=1, mask=-1, opcode=1, address=0, size=6):
    return (ident, 'A', 'TLA_near_cute', cpu, cpu - 1, opcode, 0, size, source, address, mask, 0, 0)


def d(ident, cpu, source=1, denied=0, corrupt=0):
    return (ident, 'D', 'TLD_near_cute', cpu, cpu - 1, 0, 0, 6, source, 0, 0, denied, corrupt)


class MemoryTests(unittest.TestCase):
    def test_memory_comparison_preserves_unknown_and_rejects_other_scope(self):
        left = {'collector': {'mode': 'invocation'}, 'memory': memory.decode([a(1, 10), d(2, 20)], 5, 30)}
        right = {'collector': {'mode': 'invocation'}, 'memory': memory.decode([a(1, 10, mask=0xffff), d(2, 20)], 5, 30)}
        result = memory.compare(left, right)
        self.assertEqual(result['status'], 'available')
        values = {row['metric']: row for row in result['metrics']}
        self.assertEqual(values['write_payload_bytes']['delta'], -48)
        self.assertIsNone(values['dram_bytes']['delta'])
        self.assertIsNone(values['read_payload_bytes']['candidate'])
        right['collector']['mode'] = 'stage:0'
        self.assertEqual(memory.compare(left, right)['status'], 'unavailable')
        self.assertEqual(memory.compare(left, {})['status'], 'unavailable')

    def test_available_memory_query_has_no_missing_capture_reason(self):
        report = {'sections': {'trace': {'status': 'available', 'memory': {'status': 'available'}}}}
        self.assertEqual(catalog.availability('memory', report), ('available', None))

    def test_cute_scope_keeps_entering_and_leaving_tasks(self):
        trace = {'cute': {'scope': {'status': 'unscoped'}, 'stages': [{'table': 'CUTEStoreEvent', 'role': 'store',
                 'tasks': [{'seq_id': 1, 'begin_stamp': 5, 'end_stamp': 12},
                           {'seq_id': 2, 'begin_stamp': 14, 'end_stamp': 25},
                           {'seq_id': 3, 'begin_stamp': 25, 'end_stamp': 30}]}]}}
        result = memory.intersect_tasks(trace, [20, 30], {'offset': 10})
        self.assertEqual([t['seq_id'] for t in result['tasks']], [1, 2])
        self.assertTrue(result['tasks'][0]['began_before_scope'])
        self.assertTrue(result['tasks'][1]['finishes_at_or_after_scope_end'])
        self.assertEqual(result['tasks'][1]['end_cpu_stamp'], 35)
        self.assertIn('not critical path', result['semantics'])

    def test_actual_mask_lanes_and_reused_source(self):
        result = memory.decode([a(1, 10), d(2, 15), a(3, 15, mask=0xfffff), d(4, 30)])
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['metrics']['write_payload_bytes'], 84)
        self.assertEqual(result['metrics']['observed_write_completions'], 2)
        self.assertEqual([t['latency_cycles'] for t in result['transactions']], [5, 15])
        self.assertIsNone(result['metrics']['dram_bytes'])

    def test_requests_and_completion_across_both_scope_boundaries(self):
        result = memory.decode([a(1, 10), d(2, 25), a(3, 26), d(4, 45)], 20, 40)
        self.assertEqual(result['metrics']['write_requests'], 1)
        self.assertEqual(result['boundary']['entering_writes'], 1)
        self.assertEqual(result['boundary']['leaving_writes'], 1)
        self.assertEqual(result['transactions'][0]['response_cpu_stamp'], 45)

    def test_read_bypass_is_unknown_not_missing_response_error(self):
        result = memory.decode([a(1, 10, opcode=4), a(2, 20, opcode=4)])
        self.assertEqual(result['status'], 'available')
        self.assertEqual(result['metrics']['read_requested_bytes'], 128)
        self.assertIsNone(result['metrics']['read_payload_bytes'])
        self.assertIsNone(result['boundary']['read_inflight'])

    def test_lossy_real_mask_is_rejected(self):
        with self.assertRaisesRegex(RuntimeError, 'integer bits'):
            memory.decode([a(1, 10, mask=float(2**64 - 1))])

    def test_multibeat_unreviewed_site_and_orphan_ack(self):
        self.assertEqual(memory.decode([a(1, 10, size=7)])['status'], 'invalid')
        self.assertEqual(memory.decode([d(1, 10)])['status'], 'invalid')
        row = list(a(1, 10)); row[2] = 'TLA_near_manager'
        with self.assertRaisesRegex(RuntimeError, 'Unreviewed interface'):
            memory.decode([row])

    def test_error_response_preserved(self):
        result = memory.decode([a(1, 10), d(2, 20, denied=1, corrupt=1)])
        self.assertEqual(result['metrics']['denied_writes'], 1)
        self.assertEqual(result['metrics']['corrupt_writes'], 1)

    def test_misaligned_or_partial_putfull_is_not_valid_traffic(self):
        self.assertEqual(memory.decode([a(1, 10, address=4)])['status'], 'invalid')
        self.assertEqual(memory.decode([a(1, 10, opcode=0, mask=0xffff)])['status'], 'invalid')

    def test_empty_observed_ame_scope_does_not_claim_cpu_or_dram_zero(self):
        result = memory.decode([], 10, 20)
        self.assertEqual(result['metrics']['write_payload_bytes'], 0)
        self.assertEqual(result['metrics']['read_requests'], 0)
        self.assertIsNone(result['metrics']['cpu_rvv_memory_bytes'])
        self.assertIsNone(result['metrics']['dram_bytes'])
        self.assertFalse(result['timestamps']['constant_unit_slope'])

    def test_incomplete_write_preserved(self):
        result = memory.decode([a(1, 10)], 5, 15)
        self.assertEqual(result['metrics']['observed_write_completions'], 0)
        self.assertEqual(result['boundary']['unclosed_writes_in_full_capture'], 1)
        self.assertEqual(result['boundary']['leaving_writes'], 1)

    def test_collector_row_accounting_and_stage_window(self):
        with sqlite3.connect(':memory:') as c:
            c.execute('CREATE TABLE XSAICollector(MODE TEXT, SEEN_INST INT, KEPT_INST INT, SEEN_ROWS INT, KEPT_ROWS INT, OPENS INT, CLOSES INT, ACTIVE INT, LAST INT, SCHEMA TEXT)')
            c.execute("INSERT INTO XSAICollector VALUES('stage:0',100,3,150,4,1,1,0,60,'xsai-prof.observer/v1')")
            c.execute('CREATE TABLE LifeTimeCommitTrace(SN INT,PC INT,DisAsm INT,AtCommit INT)')
            c.executemany('INSERT INTO LifeTimeCommitTrace VALUES(?,?,?,?)', [(10, 100, (1536 << 20) | 0x13, 20), (11, 104, 0x33, 25), (11, 104, 0x33, 25), (12, 108, (1537 << 20) | 0x13, 30)])
            self.assertEqual(roi.collector(c)['seen_rows'], 150)
            w = p.analyzer_module().select_window(c, 1)
            self.assertEqual((w['begin_sn'], w['end_sn']), (10, 12))
            self.assertEqual(w['collector_mode'], 'stage:0')
            c.execute('UPDATE XSAICollector SET KEPT_ROWS=5')
            with self.assertRaisesRegex(RuntimeError, 'accounting'):
                roi.collector(c)

    def test_collector_missing_end_fails(self):
        with sqlite3.connect(':memory:') as c:
            c.execute('CREATE TABLE XSAICollector(MODE,SEEN,KEPT,SEEN_ROWS,KEPT_ROWS,OPENS,CLOSES,ACTIVE,LAST,SCHEMA)')
            c.execute("INSERT INTO XSAICollector VALUES('invocation',10,5,10,5,1,0,1,60,'xsai-prof.observer/v1')")
            with self.assertRaisesRegex(RuntimeError, 'Incomplete'):
                roi.collector(c)

    def test_receipt_requires_full_observer_identity(self):
        self.assertFalse(observer.reviewed({'emulator': {'sha256': observer.OBSERVER['emulator_sha256']}}))
        self.assertFalse(observer.reviewed(None))

    def test_named_scope_routes_only_to_trace(self):
        config = {'blas': '/source', 'noop_home': '/observer', 'rtl_config': '/receipt',
                  'xsai_env': '/env', 'backend': 'ame', 'rvv_enable': 'yes', 'arch': 'riscv64-xs',
                  'toolchain': 'LLVM', 'hpm_profile': 'memstall', 'kernel': 'fa',
                  'capture_scope': 'stage:update', 'memory_trace': True,
                  'ranges': {'invocations': [2, 2], 'stages': [{'name': 'update'}]}}
        trace = collect.command_for(config, Path('/output'), 'trace', Path('/runs'))
        self.assertEqual(trace[trace.index('--trace-scope') + 1], 'stage:0')
        self.assertIn('--memory-trace', trace)
        perf = collect.command_for(config, Path('/output'), 'perf', Path('/runs'))
        self.assertNotIn('--trace-scope', perf)
        self.assertNotIn('--memory-trace', perf)

    def test_unknown_scope_cannot_pass_config_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            config = {'blas': '/source', 'noop_home': '/observer', 'rtl_config': str(root / 'rtl.json'),
                      'kernel': 'fa', 'diagnostics': ['trace'], 'capture_scope': 'invocation'}
            p.dump(root / 'rtl.json', {})
            p.dump(root / 'config.json', config)
            parser = argparse.ArgumentParser()
            collect.add_parser(parser.add_subparsers(dest='command'))
            args = parser.parse_args(['collect', '--config', str(root / 'config.json'), '--output', str(root / 'out')])
            with self.assertRaisesRegex(RuntimeError, 'reviewed observer'):
                collect.settings(args)

    def test_store_only_cute_keeps_absent_compute_explicit(self):
        with sqlite3.connect(':memory:') as c:
            c.row_factory = sqlite3.Row
            for table in ('CUTELoadEvent', 'CUTEComputeEvent', 'CUTEStoreEvent'):
                c.execute(f'CREATE TABLE {table}(SEQID INT,SITE TEXT,STAMP INT,NEEDMASK INT)')
            c.execute('CREATE TABLE CUTEReleaseEvent(STAMP INT)')
            c.executemany('INSERT INTO CUTEStoreEvent VALUES(?,?,?,?)', [(1, 'StoreIssue', 10, 0), (1, 'StoreFinish', 20, 0)])
            c.execute('INSERT INTO CUTEReleaseEvent VALUES(30)')
            result = p.cute_summary(c, {})
            self.assertEqual(result['status'], 'unscoped')
            self.assertEqual(result['absent_stages'], ['CUTELoadEvent', 'CUTEComputeEvent'])
            self.assertEqual(len(result['stages']), 1)
            with self.assertRaisesRegex(RuntimeError, 'Empty CUTE'):
                p.cute_summary(c, {'warmup_tasks': 0, 'measured_tasks': 1})


if __name__ == '__main__':
    unittest.main()
