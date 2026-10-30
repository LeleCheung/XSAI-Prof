"""Product workflow tests: evidence, availability, selection, timelines and batch."""
import argparse
from contextlib import redirect_stdout
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import cli
import kda_catalog as catalog
import kda_collect as collect
import kda_demo as demo
import kda_batch as batch
import kda_profile as profile
import kda_timeline as timeline
import xsai_kda as kda
import test_profile
from test_profile import ProfileFixture


class ProductTests(ProfileFixture, unittest.TestCase):
    def test_snapshot_does_not_inherit_outer_repository_revision(self):
        repo = self.root / 'repository'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), '-c', 'user.name=Fixture', '-c',
                        'user.email=fixture@example.invalid', 'commit', '-q', '--allow-empty', '-m', 'fixture'],
                       check=True)
        snapshot = repo / 'bundle/source'
        snapshot.mkdir(parents=True)
        (snapshot / 'kernel.c').write_text('void kernel(void) {}')
        self.assertIsNotNone(kda.revision(repo))
        self.assertIsNone(kda.revision(snapshot))
        self.assertIsNone(kda.source_identity(snapshot)['revision'])

    def test_section_presets_and_missing_evidence(self):
        self.assertEqual(catalog.selection(preset='basic')['diagnostics'], [])
        self.assertEqual(catalog.selection(['rvv'])['diagnostics'], ['trace'])
        self.assertEqual(catalog.selection(['hpm', 'ame'])['diagnostics'], ['hpm', 'trace'])
        for args in [([], None), (['unknown'], None), (['rvv', 'rvv'], None), (['rvv'], 'basic')]:
            with self.assertRaises(ValueError):
                catalog.selection(*args)
        self.assertTrue(all(r['status'] == 'requires_evidence' for r in catalog.catalog('metrics')['items']))
        entry = self.run_input()
        self.build({'perf': [entry]})
        report, _ = profile.verify_saved_report(self.root / 'report', kda)
        items = {r['name']: r for r in catalog.catalog('metrics', report)['items']}
        self.assertEqual(items['cute_stage_cycles']['status'], 'unavailable')
        self.assertEqual(items['elements_per_cycle']['status'], 'unavailable')
        self.assertIn('not exclusive', items['retirement_gap_cycles']['limitations'])
        self.assertTrue((self.root / 'report/metrics.json').is_file())

    def test_collection_section_cli_and_config_validation(self):
        p = argparse.ArgumentParser()
        commands = p.add_subparsers()
        collect.add_parser(commands)
        args = p.parse_args(['collect', '--blas', '/tmp/blas', '--noop-home', '/tmp/rtl', '--rtl-config', '/tmp/rtl.json',
                             '--kernel', 'softmax', '--set', 'basic', '--output', '/tmp/unused'])
        cfg = collect.settings(args)
        self.assertEqual(cfg['diagnostics'], [])
        self.assertEqual(cfg['sections'], ['performance'])
        args.diagnostics = ['hpm']
        with self.assertRaisesRegex(RuntimeError, 'Do not mix'):
            collect.settings(args)

    def test_synthetic_demo_batch_regression_and_unmeasured(self):
        out = self.root / 'demo'
        demo.demo(out, kda)
        state = batch.batch(out / 'batch-config.json', self.root / 'batch', kda)
        self.assertEqual([r['outcome'] for r in state['rows']], ['improved', 'regressed', None])
        self.assertEqual(state['rows'][2]['state'], 'unmeasured')
        report, _ = profile.verify_saved_report(out / 'baseline', kda)
        self.assertTrue(any('SYNTHETIC' in s for s in report['warnings']))
        spec = {'cases': [{'id': 'bad', 'baseline': {'report': 'no-such-report'}, 'candidate': {'report': 'baseline'}},
                          {'id': 'good', 'baseline': {'spec': 'baseline-spec.json'}, 'candidate': {'spec': 'candidate-spec.json'}}]}
        profile.dump(out / 'mixed.json', spec)
        state = batch.batch(out / 'mixed.json', self.root / 'mixed', kda)
        self.assertEqual(state['status'], 'completed_with_failures')
        self.assertEqual([c['state'] for c in state['cases']], ['failed', 'compared'])
        self.assertIsNone(state['rows'][0]['speedup'])
        profile.dump(out / 'specs.json', {'cases': [spec['cases'][1]]})
        sibling = batch.batch(out / 'specs.json', out / 'same-directory-output', kda)
        self.assertEqual(sibling['status'], 'completed')

    def test_batch_collect_configs_run_sequentially_and_use_private_destinations(self):
        cfg = {'blas': '/tmp/external-blas', 'noop_home': '/tmp/external-rtl',
               'rtl_config': '/tmp/external-rtl.json', 'kernel': 'softmax', 'set': 'basic'}
        profile.dump(self.root / 'collect.json', cfg)
        profile.dump(self.root / 'batch-collect.json', {'cases': [
            {'id': 'collect-case', 'baseline': {'collect': 'collect.json'}, 'candidate': {'collect': 'collect.json'}}]})
        calls = []
        def fake_collect(config, output, resume, adapter):
            calls.append(output.name)
            self.assertEqual(config['diagnostics'], [])
            self.assertFalse(resume)
            output.mkdir(parents=True)
            self.build({'perf': [self.run_input(), self.run_input()]}, str(output / 'report'))
        with patch.object(collect, 'collect', side_effect=fake_collect):
            state = batch.batch(self.root / 'batch-collect.json', self.root / 'collect-results', kda)
        self.assertEqual(calls, ['baseline', 'candidate'])
        self.assertEqual(state['rows'][0]['outcome'], 'unchanged')

    def test_batch_rejects_workload_mismatch_and_preserves_failure(self):
        left, right = self.run_input(), self.run_input(change={'selection': {'kernel': 'softmax', 'case': 2}})
        self.build({'perf': [left]}, 'left')
        self.build({'perf': [right]}, 'right')
        cfg = self.root / 'batch.json'
        profile.dump(cfg, {'cases': [{'id': 'mismatch', 'baseline': {'report': 'left'}, 'candidate': {'report': 'right'}}]})
        state = batch.batch(cfg, self.root / 'results', kda)
        self.assertEqual(state['cases'][0]['state'], 'failed')
        self.assertIsNone(state['rows'][0]['speedup'])
        self.assertTrue((self.root / 'results/cases/mismatch/failure.json').is_file())

    def test_batch_ids_and_overlapping_ranges(self):
        cfg = self.root / 'cfg.json'
        for ids in [['../unsafe'], ['same', 'same']]:
            profile.dump(cfg, {'cases': [{'id': v} for v in ids]})
            with self.assertRaises(RuntimeError):
                batch.config(cfg)
        comparison = {'sections': {'performance': {'measurements': [
            {'op': 'x', 'unit': 'u', 'baseline_cycles': [100, 110], 'candidate_cycles': [101, 102],
             'speedup': 105 / 101.5, 'cycle_reduction_pct': 1, 'independent_repeats_both': True}]}}}
        self.assertEqual(batch.result_rows('id', comparison)[0]['outcome'], 'inconclusive')

    def test_doctor_exit_status_and_legacy_query(self):
        with redirect_stdout(io.StringIO()) as output:
            code = cli.main(['doctor'])
        self.assertEqual(code, 0)
        self.assertTrue(json.loads(output.getvalue())['offline_ready'])
        cfg = self.root / 'broken-config.json'
        profile.dump(cfg, {})
        with redirect_stdout(io.StringIO()) as output:
            code = cli.main(['doctor', '--config', str(cfg)])
        self.assertEqual(code, 1)
        self.assertEqual(json.loads(output.getvalue())['rtl_collection']['status'], 'unavailable')
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/xsai_kda.py'), 'profile', 'query', 'sets', '--format', 'json'], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)['kind'], 'sets')


@unittest.skipUnless(__import__('shutil').which('riscv64-linux-gnu-gcc'), 'RISC-V fixture compiler required')
class TimelineProductTests(ProfileFixture, unittest.TestCase):
    trace_input = test_profile.TraceTests.trace_input

    def report(self):
        trace = self.trace_input()
        self.build({'perf': [self.run_input()], 'trace': trace}, options={'recompute_roi': True})
        return profile.verify_saved_report(self.root / 'report', kda)[0], trace

    def test_cpu_exact_stamps_filters_and_explicit_truncation(self):
        report, trace = self.report()
        data = timeline.timeline(report, max_instructions=1)
        self.assertEqual(data['cpu_selection']['instructions_matched'], 2)
        self.assertTrue(data['cpu_selection']['truncated'])
        self.assertEqual(data['events'][0]['begin'], 100)
        self.assertEqual(data['events'][0]['end'], 104)
        self.assertEqual(data['cross_domain_alignment'], 'unproven')
        self.assertEqual(data['domains'][1]['status'], 'unavailable')
        self.assertEqual(timeline.timeline(report, function='not-a-function')['events'], [])
        one = timeline.timeline(report, cpu_range=[108, 108])
        self.assertEqual(one['cpu_selection']['instructions_matched'], 1)
        with self.assertRaises(RuntimeError):
            timeline.timeline(report, cpu_range=[10, 1])
        with self.assertRaises(RuntimeError):
            timeline.timeline(report, max_instructions=0)
        # A second dynamic marker pair must retain its own timestamps, rather
        # than reusing the first ROI's interval or archived hotspot window.
        run = Path(trace['run'])
        with sqlite3.connect(run / 'chiseldb.db') as db:
            rows = db.execute('SELECT * FROM LifeTimeCommitTrace').fetchall()
            for sn, pc, code, fetched, issued, fu, committed in rows:
                db.execute('INSERT INTO LifeTimeCommitTrace VALUES(?,?,?,?,?,?,?)',
                           (sn + 4, pc, code, fetched + 100, issued + 100, fu + 100, committed + 100))
        manifest = profile.read_json(run / 'manifest.json')
        manifest['artifacts']['chiseldb.db']['sha256'] = profile.digest(run / 'chiseldb.db')
        profile.dump(run / 'manifest.json', manifest)
        self.build({'perf': [self.run_input()], 'trace': trace}, 'second-window',
                   {'window': 2, 'recompute_roi': True})
        second, _ = profile.verify_saved_report(self.root / 'second-window', kda)
        selected = timeline.timeline(second)
        self.assertEqual(selected['domains'][0]['origin'], 200)
        self.assertEqual(second['sections']['trace']['window']['window'], 2)
        self.assertEqual(selected['cpu_selection']['instructions_in_roi'], 2)

    def test_missing_fetch_is_commit_instant_and_html_escapes(self):
        report, trace = self.report()
        with sqlite3.connect(Path(trace['run']) / 'chiseldb.db') as db:
            db.execute('UPDATE LifeTimeCommitTrace SET AtFetch=0 WHERE SN=2')
        data = timeline.timeline(report)
        self.assertEqual(data['events'][0]['kind'], 'commit')
        self.assertEqual(data['events'][0]['begin'], data['events'][0]['end'])
        self.assertEqual(data['cpu_selection']['missing_or_invalid_stamps']['fetch_to_commit'], 1)
        data['label'] = '<script>unsafe</script>'
        self.assertNotIn('<script>unsafe', timeline.html_view(data))

    def test_export_revalidates_evidence_and_cute_independent_clock(self):
        report, trace = self.report()
        args = argparse.Namespace(report=self.root / 'report', output=self.root / 'timeline', function=None,
                                  max_instructions=10, cpu_cycle_range=None)
        with redirect_stdout(io.StringIO()):
            timeline.dispatch(args, kda)
        data = profile.read_json(args.output / 'timeline.json')
        self.assertEqual(len(data['events']), 2)
        self.assertTrue((args.output / 'events.csv').exists())
        self.assertTrue((args.output / 'checksums.json').exists())
        (Path(trace['run']) / 'chiseldb.db').write_bytes(b'changed')
        args.output = self.root / 'bad-timeline'
        with self.assertRaises(RuntimeError):
            timeline.dispatch(args, kda)
        self.assertFalse(args.output.exists())
        report['sections']['trace']['cute'] = {'status': 'available', 'scope': {'warmup_tasks': 1, 'measured_tasks': 1},
              'stages': [{'table': 'CUTEComputeEvent', 'role': 'all', 'tasks': [{'seq_id': 1, 'begin_stamp': 100000, 'end_stamp': 100020}]}]}
        # Test independent-clock rendering using restored original fixture DB.
        _, new_trace = self.report_fresh_trace(report)
        data = timeline.timeline(report)
        self.assertEqual(data['domains'][1]['origin'], 100000)
        self.assertEqual(data['domains'][0]['origin'], 100)
        selected = timeline.timeline(report, cute_stage='compute', cute_task_range=[1, 1])
        self.assertEqual(len([e for e in selected['events'] if e['domain'] == 'cute']), 1)
        selected = timeline.timeline(report, cute_stage='store')
        self.assertEqual(selected['domains'][1]['status'], 'unavailable')
        with self.assertRaises(RuntimeError):
            timeline.timeline(report, cute_task_range=[2, 1])

    def report_fresh_trace(self, report):
        (self.root / 'trace.db').unlink()
        trace = self.trace_input()
        report['sections']['trace']['run'] = trace['run']
        return report, trace

if __name__ == '__main__':
    unittest.main()
