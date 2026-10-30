"""Recovery, process ownership and portable evidence failure contracts."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import kda_batch as batch
import kda_demo as demo
import kda_jobs as jobs
import kda_capture as capture
import kda_clock as clock
import kda_analyze as analyze
import kda_reference_model as model
import kda_ame_activity as ame
import kda_portable as portable
import kda_profile as p
import xsai_kda as kda
from test_profile import ProfileFixture


class NightTests(ProfileFixture, unittest.TestCase):
    def test_custom_event_groups_and_source_markers_fail_closed(self):
        import sqlite3
        source = self.root / 'source'
        (source / 'test').mkdir(parents=True)
        (source / 'include').mkdir()
        (source / 'CMakeLists.txt').write_text('cmake_minimum_required(VERSION 3.25)\nproject(fixture C)\n')
        (source / 'test/Makefile').write_text('-DXSAI_BLAS_ENABLE_DEBUG_INFO=$(XSAI_BLAS_DEBUG_INFO) \\n')
        (source / 'test/test.h').write_text('#define PERF_MAX_RUNS 8 // upstream\n')
        (source / 'test/test-ops.c').write_text('''typedef struct {
  int counter;
} dummy;
void f(void) {
    for (int r = 0; r < n_runs; r++) {
      tc->run_opt(tc);
    }
}
uint64_t total = end->value[i] - start->value[i];
''')
        (source / 'kernel.c').write_text('void update(void) {\n  begin();\n  end();\n}\n')
        rtl = {'hpm_event_coding': [{'group': 'Backend', 'id': 0, 'name': 'noEvent', 'signal': 'zero'},
                                    {'group': 'Backend', 'id': 67, 'name': 'EXEC_STALL_CYCLE', 'signal': 'pred'}]}
        p.dump(self.root / 'rtl.json', rtl)
        cfg = {'ranges': {'invocations': [2, 2], 'stages': [{'name': 'update', 'file': 'kernel.c', 'begin': '  begin();', 'end': '  end();'}]},
               'hpm_events': [{'counter': 11, 'events': ['EXEC_STALL_CYCLE']}], 'rtl_config': str(self.root / 'rtl.json'),
               'environment': {'PERF_MAX_RUNS': '2'}}
        before = json.dumps(cfg)
        metadata = capture.apply(source, cfg)
        self.assertEqual(json.dumps(cfg), before)
        self.assertEqual(metadata['hpm_events'][0]['selector'], 67)
        self.assertIn('#define PERF_MAX_RUNS 2', (source / 'test/test.h').read_text())
        self.assertIn('value[index]', (source / 'test/test-ops.c').read_text())
        self.assertIn('XSAI_PROF_MARK(1536)', (source / 'kernel.c').read_text())
        with self.assertRaisesRegex(RuntimeError, 'group'):
            capture.hpm_plan([{'counter': 19, 'events': [67]}], rtl)
        with self.assertRaises(RuntimeError):
            capture.hpm_plan([{'counter': 11, 'events': [67]}, {'counter': 11, 'events': [67]}], rtl)
        db = self.root / 'markers.db'
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE LifeTimeCommitTrace(SN INT, DisAsm INT, AtCommit INT)')
            for sn, imm in enumerate([1443, 1536, 1537, 1444], 1):
                c.execute('INSERT INTO LifeTimeCommitTrace VALUES(?,?,?)', (sn, capture.instruction(imm), 100+sn))
        selected = capture.ranges_from_db(db, metadata, {'begin_sn': 0, 'end_sn': 5})
        self.assertEqual(selected['selected_invocations'], 1)
        self.assertTrue(all(e['invocation'] == 2 for e in selected['events']))
        with sqlite3.connect(db) as c:
            c.execute('DELETE FROM LifeTimeCommitTrace WHERE SN=3')
        with self.assertRaisesRegex(RuntimeError, 'unfinished stage'):
            capture.ranges_from_db(db, metadata, {'begin_sn': 0, 'end_sn': 5})

    def test_clock_anchor_requires_exact_event_coverage_and_constant_offset(self):
        import sqlite3
        run = self.root / 'clock-run'
        run.mkdir()
        db = run / 'chiseldb.db'
        with sqlite3.connect(db) as c:
            c.execute('CREATE TABLE XSAIClockSync(TABLE_NAME TEXT, SEQID INT, SITE TEXT, CPU_STAMP INT, CUTE_STAMP INT)')
            for table in clock.TABLES:
                c.execute(f'CREATE TABLE {table}(SEQID INT, SITE TEXT, STAMP INT)')
                for i in (1, 2):
                    c.execute(f'INSERT INTO {table} VALUES(?,?,?)', (i,'site',i*100))
                    c.execute('INSERT INTO XSAIClockSync VALUES(?,?,?,?,?)', (table,i,'site',i*100-5,i*100))
        receipt = {'configuration': {'NUM_CORES': '1'}, 'emulator': {'sha256': clock.OBSERVER['emulator_sha256']},
                   'clock_bridge': {'schema': 'xsai-prof.clock-bridge/v1', 'observer_sha256': clock.OBSERVER['logger_sha256'],
                                    'base_emulator_sha256': clock.OBSERVER['base_emulator_sha256'], 'single_core_only': True}}
        report = {'sections': {'trace': {'status': 'available', 'run': str(run)}}}
        def seal():
            p.dump(run / 'manifest.json', {'rtl': {'emu_sha256': clock.OBSERVER['emulator_sha256']}, 'artifacts': {'chiseldb.db': {'sha256': p.digest(db)}}})
        seal()
        result = clock.anchors(report, receipt)
        self.assertEqual(result['status'], 'validated')
        self.assertEqual(result['mapping']['offset'], -5)
        import kda_hardware as hardware
        with patch.object(hardware, 'receipt_for', return_value=receipt):
            contract = hardware.clock_contract(report)
        self.assertTrue(all(k in contract for k in ('cpu', 'rvv', 'cute')))
        receipt['configuration']['NUM_CORES'] = '2'
        self.assertEqual(clock.anchors(report, receipt)['status'], 'unproven')
        receipt['configuration']['NUM_CORES'] = '1'
        with sqlite3.connect(db) as c:
            c.execute('UPDATE XSAIClockSync SET CPU_STAMP=CPU_STAMP+1 WHERE TABLE_NAME=?', (clock.TABLES[0],))
        seal()
        self.assertEqual(clock.anchors(report, receipt)['status'], 'unproven')
        with sqlite3.connect(db) as c:
            c.execute('DELETE FROM XSAIClockSync WHERE TABLE_NAME=?', (clock.TABLES[0],))
        seal()
        with self.assertRaisesRegex(RuntimeError, 'exact same CUTE events'):
            clock.anchors(report, receipt)

    def test_dashboard_escapes_embedded_script_and_reference_model_rejects_bad_units(self):
        demo.demo(self.root / 'demo', kda)
        report, directory = p.verify_saved_report(self.root / 'demo/baseline', kda)
        data = analyze.analyze(report, kda, directory=directory)
        data['label'] = '</script><script>alert(1)</script>'
        rendered = analyze.html_view(data)
        self.assertNotIn('</script><script>alert', rendered)
        self.assertIn('\\u003c/script>', rendered)
        with self.assertRaisesRegex(RuntimeError, 'known precision'):
            model.model(report, {'work': {'mixed_ops': 10}, 'references': [], 'assumptions': ['test']}, self.root, kda)

    def test_reference_model_keeps_precision_and_does_not_claim_peak(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'kernel.c').write_text('/* declared 100 reference FLOPs */')
        identity = kda.source_identity(source)
        receipt = self.root / 'source.json'
        p.dump(receipt, {'identity': identity, 'files': {'kernel.c': p.digest(source / 'kernel.c')}})
        with zipfile.ZipFile(self.root / 'source.zip', 'w') as z:
            z.write(source / 'kernel.c', 'kernel.c')
        entries = []
        for cycles in (10, 12):
            entry = self.run_input(cycles=cycles, change={'source': identity})
            entry['source_receipt'] = str(receipt)
            entries.append(entry)
        self.build({'perf': entries}, 'reference')
        self.build({'perf': [self.run_input(cycles=40)]}, 'target')
        target, _ = p.verify_saved_report(self.root / 'target', kda)
        cfg = {'work': {'fp32_lane_flop': 200}, 'references': [{'report': 'reference', 'unit': 'fp32_lane_flop', 'work': 100}], 'assumptions': ['Explicit reference kernel work; cache-hot']}
        result = model.model(target, cfg, self.root, kda)
        self.assertAlmostEqual(result['rows'][0]['equivalent_reference_cycles'], 22)
        self.assertIsNone(result['hardware_peak'])
        self.assertIsNone(result['measured_hardware_efficiency'])
        cfg['references'].append(cfg['references'][0])
        with self.assertRaisesRegex(RuntimeError, 'no silent pooling'):
            model.model(target, cfg, self.root, kda)

    def test_ame_intervals_do_not_double_count_or_invent_boundary_overlap(self):
        result = ame.activity([(0, 10), (5, 15), (15, 20)])
        self.assertEqual(result['task_interval_union_cycles'], 20)
        self.assertEqual(result['sum_task_interval_cycles'], 25)
        self.assertEqual(result['peak_outstanding_task_intervals'], 2)
        self.assertEqual(ame.activity([(0, 10), (10, 20)])['peak_outstanding_task_intervals'], 1)

    def test_portable_survives_original_removal_and_detects_tampering(self):
        source = self.root / 'original'
        demo.demo(source, kda)
        archive = self.root / 'evidence.zip'
        portable.export(source / 'baseline', archive, kda)
        source.rename(self.root / 'unavailable-original')
        target = self.root / 'relocated'
        portable.import_archive(archive, target, kda)
        report, _ = p.verify_saved_report(target / 'report', kda)
        self.assertTrue(all(Path(i['run']).is_relative_to(target) for i in report['inputs']))
        old = p.read_json(target / 'original-report/report.json')
        self.assertEqual(report['sections']['performance'], old['sections']['performance'])
        self.assertEqual(p.digest(target / 'original-report/report.json'), p.read_json(target / 'portable.json')['original_report_sha256'])
        manifest = Path(report['inputs'][0]['run']) / 'manifest.json'
        manifest.write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'manifest changed'):
            p.verify_saved_report(target / 'report', kda)

    def test_archive_rejects_traversal_symlinks_duplicates_and_inventory_changes(self):
        import stat
        for index, kind in enumerate(('traversal', 'symlink', 'duplicate', 'inventory')):
            archive = self.root / (kind + '.zip')
            with zipfile.ZipFile(archive, 'w') as z:
                z.writestr('portable.json', json.dumps({'schema': portable.SCHEMA, 'files': {}}))
                if kind == 'traversal':
                    z.writestr('../escape', 'bad')
                elif kind == 'symlink':
                    info = zipfile.ZipInfo('link')
                    info.external_attr = (stat.S_IFLNK | 0o777) << 16
                    z.writestr(info, '/etc/passwd')
                elif kind == 'duplicate':
                    import warnings
                    with warnings.catch_warnings():
                        warnings.simplefilter('ignore')
                        z.writestr('portable.json', '{}')
                else:
                    z.writestr('unlisted', 'bad')
            out = self.root / ('import-' + str(index))
            with self.assertRaises(RuntimeError):
                portable.import_archive(archive, out, kda)
            self.assertFalse(out.exists())
        self.assertFalse((self.root.parent / 'escape').exists())

    def test_batch_retry_resume_revalidates_and_reuses_sides(self):
        demo.demo(self.root / 'demo', kda)
        cfg = self.root / 'demo/batch-config.json'
        output = self.root / 'batch'
        real_obtain = batch.obtain
        calls = []
        def transient(entry, base, destination, adapter):
            calls.append(destination.name)
            if len(calls) == 2:
                raise RuntimeError('temporary collector failure')
            return real_obtain(entry, base, destination, adapter)
        with patch.object(batch, 'obtain', side_effect=transient):
            state = batch.batch(cfg, output, kda, retries=1)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual([a['state'] for a in state['cases'][0]['attempts']], ['failed', 'passed'])
        self.assertEqual(calls[:3], ['baseline', 'candidate', 'candidate'])
        comparison_hash = p.digest(output / state['cases'][0]['comparison'] / 'report.json')
        with patch.object(batch, 'obtain', side_effect=AssertionError('must reuse')):
            batch.batch(cfg, output, kda, resume=True)
        self.assertEqual(comparison_hash, p.digest(output / state['cases'][0]['comparison'] / 'report.json'))
        (self.root / 'demo/baseline/report.json').write_text('{}')
        with self.assertRaisesRegex(RuntimeError, 'input changed'):
            batch.batch(cfg, output, kda, resume=True)

    def test_batch_explicit_resume_after_failure_preserves_attempt(self):
        demo.demo(self.root / 'demo', kda)
        cfg = self.root / 'demo/batch-config.json'
        out = self.root / 'batch'
        with patch.object(batch, 'obtain', side_effect=RuntimeError('offline')):
            state = batch.batch(cfg, out, kda)
        self.assertEqual(state['status'], 'completed_with_failures')
        state = batch.batch(cfg, out, kda, resume=True)
        self.assertEqual(state['status'], 'completed')
        self.assertEqual(len(state['cases'][0]['attempts']), 2)
        self.assertTrue((out / 'cases' / state['cases'][0]['id'] / 'failure-1.json').is_file())

    def test_managed_timeout_terminates_grandchild_and_records_heartbeat(self):
        pidfile = self.root / 'grandchild.pid'
        code = ('import subprocess,time,pathlib; '
                'p=subprocess.Popen(["sleep","40"]); '
                'pathlib.Path(' + repr(str(pidfile)) + ').write_text(str(p.pid)); time.sleep(40)')
        beats = []
        with (self.root / 'child.log').open('w') as stream:
            with self.assertRaises(TimeoutError):
                jobs.run_stage([sys.executable, '-c', code], stdout=stream, stderr=subprocess.STDOUT,
                               cwd=self.root, env=os.environ.copy(), pass_fds=(), timeout=0.3, heartbeat=beats.append)
        self.assertTrue(beats)
        pid = int(pidfile.read_text())
        proc = Path('/proc') / str(pid) / 'stat'
        # A terminated grandchild may briefly remain a zombie until init reaps
        # it; either absent or zombie establishes it cannot hold locks/run work.
        try:
            state = proc.read_text().split()[2]
        except FileNotFoundError:
            state = 'gone'
        self.assertIn(state, ('Z', 'gone'))


if __name__ == '__main__':
    unittest.main()
