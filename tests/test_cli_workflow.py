"""Public workflow: no-op plans, truthful metric selection and read-only views."""
import argparse
from contextlib import redirect_stdout, redirect_stderr
import csv
import io
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'scripts'))
import cli
import kda_catalog as catalog
import kda_collect as collect
import kda_output as output
import kda_plan as plan
import kda_profile as p
import kda_view as view
import xsai_kda as kda
from test_profile import ProfileFixture


class WorkflowTests(ProfileFixture, unittest.TestCase):
    def command(self, argv, expected=0):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(cli.main(list(map(str,argv))), expected, stderr.getvalue())
        return stdout.getvalue()

    def config(self, **changes):
        receipt = self.root/'rtl.json'
        p.dump(receipt, {})
        value = {'blas': str(self.root/'blas'), 'noop_home': str(self.root/'rtl'),
            'rtl_config': str(receipt), 'kernel': 'softmax', 'case': 1,
            'diagnostics': [], 'perf_repeats': 2, **changes}
        target = self.root/'config.json'
        p.dump(target,value)
        return target

    def test_discovery_aliases_and_csv_filter_have_equal_catalogs(self):
        for alias,kind in [('--query-metrics','metrics'),('--list-sections','sections'),('--list-sets','sets')]:
            self.assertEqual(json.loads(self.command([alias,'--format','json'])),
                             json.loads(self.command(['query',kind,'--format','json'])))
        rows = list(csv.DictReader(io.StringIO(self.command(['--query-metrics','--filter','ame_read','--format','csv']))))
        self.assertTrue(rows)
        self.assertTrue(all(row['name'].startswith('ame_read') for row in rows))
        self.assertTrue(all(row['status']=='requires_evidence' for row in rows))

    def test_shared_native_modes_are_not_run_per_requested_metric(self):
        value = plan.selection(metrics=['cycles_per_call,ame_read_payload_bytes','cpu_pma_store_enabled_bytes'])
        self.assertEqual(value['diagnostics'], ['trace'])
        self.assertEqual(value['sections'], ['performance','memory'])
        self.assertEqual(plan.selection(metrics=['cycles_per_call'])['diagnostics'], [])
        self.assertEqual(plan.selection(preset='counters')['diagnostics'], ['hpm'])
        with self.assertRaisesRegex(RuntimeError, 'Unsupported metrics'):
            plan.selection(metrics=['dram_bytes'])

    def test_dry_run_never_snapshots_locks_or_runs_collect(self):
        config = self.config()
        destination = self.root/'not-created'
        with patch.object(collect,'collect',side_effect=AssertionError('must not collect')), \
             patch.object(collect,'freeze_source',side_effect=AssertionError('must not snapshot')), \
             patch.object(collect,'preflight',return_value={'fixture':'read-only'}):
            result = json.loads(self.command(['collect','--config',config,'--metrics','cycles_per_call',
                '--dry-run','-o',destination]))
        self.assertEqual(result['status'],'ready')
        self.assertEqual([s['mode'] for s in result['stages']], ['perf','perf'])
        self.assertEqual(result['cost']['fresh_emulator_invocations'],4)
        self.assertFalse(destination.exists())

    def test_unreviewed_memory_is_blocked_before_writing(self):
        destination=self.root/'not-created'
        config=self.config()
        result=json.loads(self.command(['collect','--config',config,'--metrics','ame_read_payload_bytes',
            '--dry-run','-o',destination],expected=1))
        self.assertEqual(result['status'],'blocked')
        self.assertEqual(result['metric_requirements'][0]['status'],'unsupported_target')
        with patch.object(collect,'collect',side_effect=AssertionError('must fail before collect')):
            self.command(['collect','--config',config,'--metrics','ame_read_payload_bytes','-o',destination],expected=1)
        self.assertFalse(destination.exists())

    def test_selector_override_disables_unrequested_trace_and_memory(self):
        config=self.config(diagnostics=['trace'],memory_trace=True,capture_scope='invocation',
            ranges={'invocations':[1,1],'stages':[]},cute={'warmup_tasks':1,'measured_tasks':1})
        parser=argparse.ArgumentParser();collect.add_parser(parser.add_subparsers())
        args=parser.parse_args(['collect','--config',str(config),'--metrics','cycles_per_call','-o',str(self.root/'unused')])
        value=collect.settings(args)
        self.assertEqual(value['diagnostics'],[])
        self.assertFalse(value.get('memory_trace'))
        self.assertNotIn('ranges',value)
        self.assertNotIn('cute',value)
        args.case=2
        with self.assertRaisesRegex(RuntimeError,'cannot be mixed'):
            collect.settings(args)

    def test_saved_report_view_preserves_missing_values_and_input_bytes(self):
        self.build({'perf':[self.run_input()]})
        directory=self.root/'report';before={f.name:p.digest(f) for f in directory.iterdir() if f.is_file()}
        data=json.loads(self.command(['report',directory,'--metrics','ame_read_payload_bytes','--format','json']))
        self.assertEqual(data['rows'][0]['status'],'unavailable')
        self.assertIsNone(data['rows'][0]['value'])
        self.assertEqual(before,{f.name:p.digest(f) for f in directory.iterdir() if f.is_file()})
        self.command(['report',directory,'--perf',directory],expected=1)

    def test_comparison_view_uses_medians_and_keeps_speedup_separate(self):
        self.build({'perf':[self.run_input(cycles=100),self.run_input(cycles=102)]},'a')
        self.build({'perf':[self.run_input(cycles=80),self.run_input(cycles=82)]},'b')
        data=json.loads(self.command(['view',self.root/'b','--page','comparison','--baseline',self.root/'a','--format','json']))
        row=data['rows'][0]
        self.assertEqual((row['baseline'],row['candidate'],row['delta'],row['value']),(101,81,-20,81))
        self.assertAlmostEqual(row['speedup'],101/81)
        missing=json.loads(self.command(['view',self.root/'b','--page','comparison','--baseline',self.root/'a',
            '--metrics','hpm_events_per_call','--format','json']))
        self.assertEqual(missing['rows'][0]['status'],'unavailable')
        self.assertIsNone(missing['rows'][0]['value'])

    def test_csv_escaping_and_exclusive_export_are_lossless(self):
        self.build({'perf':[self.run_input(change={'measurements':[{'op':'operator(a=1,b=2)',
            'unit':'RVV-FP32','cycles_per_run':100,'instret_per_run':40}]})]})
        path=self.root/'export.csv'
        self.command(['view',self.root/'report','--metrics','cycles_per_call','--format','csv','-o',path])
        rows=list(csv.DictReader(io.StringIO(path.read_text())))
        self.assertEqual(rows[0]['op'],'operator(a=1,b=2)')
        before=path.read_bytes()
        self.command(['view',self.root/'report','--format','csv','-o',path],expected=1)
        self.assertEqual(before,path.read_bytes())
        self.command(['view',self.root/'report','-o',self.root/'report/new.txt'],expected=1)

    def test_function_filter_does_not_reassign_global_metrics(self):
        self.build({'perf':[self.run_input()]})
        data=json.loads(self.command(['view',self.root/'report','--function','softmax','--format','json']))
        self.assertEqual(data['rows'],[])
        self.assertIn('never attributed',data['warnings'][-1])

    def test_open_revalidates_artifacts_without_starting_browser(self):
        self.build({'perf':[self.run_input()]})
        with patch.object(view.webbrowser,'open',side_effect=AssertionError('browser must not start')):
            result=json.loads(self.command(['open',self.root/'report','--no-browser']))
        self.assertTrue(result['url'].startswith('file:'))
        (self.root/'report/index.html').write_text('changed')
        self.command(['open',self.root/'report','--no-browser'],expected=1)


if __name__=='__main__':unittest.main()
