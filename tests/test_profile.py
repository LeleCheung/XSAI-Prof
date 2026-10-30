"""Observable profiling contracts: bound evidence, offline views and rejection."""
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import kda_profile as profile
import xsai_kda as kda


class ProfileFixture:
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.serial = 0

    def tearDown(self):
        self.tmp.cleanup()

    def run_input(self, mode='perf', cycles=100, change=None, artifacts=None):
        self.serial += 1
        run = self.root / f'run-{self.serial}'
        run.mkdir()
        manifest = {
            'status': 'passed', 'target': 'rtl', 'mode': mode,
            'instrumentation': 'none' if mode == 'perf' else mode,
            'performance_eligible': mode == 'perf',
            'correctness': {'passed': 1, 'failed': 0},
            'selection': {'kernel': 'softmax', 'case': 1},
            'source': {'revision': 'fixture', 'sha256': 'fixture-source'},
            'rtl': {'emu_sha256': 'fixture-emu', 'config_sha256': 'fixture-config'},
            'compiler': {'sha256': 'fixture-compiler'}, 'runtime_source': {'sha256': 'runtime'},
            'arch': 'riscv64-xs', 'toolchain': 'LLVM', 'build_environment': {},
            'build_overrides': {}, 'rvv_enable': 'yes', 'backend': 'rvv',
            'test_harness': {'test.c': 'same'},
            'measurements': [{'op': 'softmax(n=128)', 'unit': 'RVV-FP32',
                              'cycles_per_run': cycles, 'instret_per_run': 40}],
        }
        if change:
            manifest.update(change)
        manifest['artifacts'] = {}
        for name, content in (artifacts or {'perf.log': b'fixture log'}).items():
            path = run / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            manifest['artifacts'][name] = {'sha256': profile.digest(path)}
        profile.dump(run / 'manifest.json', manifest)
        return {'run': str(run)}

    def build(self, spec, output='report', options=None):
        return profile.publish(self.root / output, lambda out: profile.build_report(
            spec, options or {}, out, kda))


class ProfileTests(ProfileFixture, unittest.TestCase):
    def test_shared_views_missing_sections_and_comparison(self):
        a = {'label': '<baseline>', 'perf': [self.run_input(), self.run_input(cycles=102)]}
        b = {'label': 'candidate', 'perf': [self.run_input(cycles=80), self.run_input(cycles=82)]}
        self.build(a, 'a')
        self.build(b, 'b')
        left, ap = profile.verify_saved_report(self.root / 'a', kda)
        right, bp = profile.verify_saved_report(self.root / 'b', kda)
        comparison = profile.compare_reports(left, right, (ap, bp), kda)
        perf = comparison['sections']['performance']['measurements'][0]
        self.assertAlmostEqual(perf['speedup'], 101 / 81)
        self.assertTrue(perf['stable_win_in_recorded_runs'])
        self.assertEqual(left['sections']['hpm']['status'], 'unavailable')
        self.assertEqual(left['sections']['trace']['status'], 'unavailable')
        self.assertIn('[100, 102]', (ap / 'report.md').read_text())
        self.assertIn('&lt;baseline&gt;', (ap / 'index.html').read_text())
        self.assertNotIn('<baseline>', (ap / 'index.html').read_text())
        self.assertIsNone(left['spec'].get('cute'))
        profile.publish(self.root / 'cmp', lambda _: comparison)
        self.assertIn('../a/index.html', (self.root / 'cmp/index.html').read_text())

    def test_duplicate_repeats_and_instrumented_perf_rejected_without_output(self):
        entry = self.run_input()
        with self.assertRaisesRegex(RuntimeError, 'Duplicate perf'):
            self.build({'perf': [entry, entry]})
        self.assertFalse((self.root / 'report').exists())
        hpm = self.run_input(mode='hpm')
        with self.assertRaisesRegex(RuntimeError, 'Expected RTL perf'):
            self.build({'perf': [hpm]})
        self.assertFalse((self.root / 'report').exists())

    def test_diagnostic_binding_rejects_wrong_source_shape_build_or_harness(self):
        perf = self.run_input()
        for field, value in [('source', {'sha256': 'other'}),
                             ('selection', {'kernel': 'softmax', 'case': 2}),
                             ('rtl', {'emu_sha256': 'other'}),
                             ('compiler', {'sha256': 'other'}),
                             ('backend', 'ame'), ('test_harness', {'test.c': 'changed'}),
                             ('measurements', [{'op': 'softmax(n=256)', 'unit': 'RVV-FP32'}])]:
            diagnostic = self.run_input(mode='hpm', change={field: value})
            with self.subTest(field=field), self.assertRaisesRegex(RuntimeError, 'Diagnostic'):
                self.build({'perf': [perf], 'hpm': diagnostic})
            self.assertFalse((self.root / 'report').exists())

    def test_changed_artifact_and_saved_report_rejected(self):
        entry = self.run_input()
        self.build({'perf': [entry]})
        report_file = self.root / 'report/report.json'
        original = report_file.read_bytes()
        report_file.write_bytes(original + b' ')
        with self.assertRaisesRegex(RuntimeError, 'Report artifact changed'):
            profile.verify_saved_report(report_file, kda)
        report_file.write_bytes(original)
        (Path(entry['run']) / 'perf.log').write_text('changed')
        with self.assertRaisesRegex(RuntimeError, 'Artifact changed'):
            profile.verify_saved_report(report_file, kda)
        with self.assertRaisesRegex(RuntimeError, 'Artifact changed'):
            self.build({'perf': [entry]}, 'bad')
        self.assertFalse((self.root / 'bad').exists())

    def test_archived_source_receipt_and_zip_verified(self):
        source = self.root / 'source'
        source.mkdir()
        (source / 'kernel.c').write_text('first\nsecond\nthird\n')
        identity = kda.source_identity(source)
        files = {'kernel.c': profile.digest(source / 'kernel.c')}
        receipt, archive = self.root / 'source.json', self.root / 'source.zip'
        profile.dump(receipt, {'identity': identity, 'files': files})
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.write(source / 'kernel.c', 'kernel.c')
        entry = self.run_input(change={'source': identity})
        entry['source_receipt'] = str(receipt)
        loaded = profile.load_input(entry, kda, 'perf')
        snippet = profile.archived_source('fn at /old/build/kernel.c:2', loaded['source'])
        self.assertEqual(snippet['lines'][1]['text'], 'second')
        self.build({'perf': [entry]})
        with zipfile.ZipFile(archive, 'w') as zipped:
            zipped.writestr('kernel.c', 'changed')
        with self.assertRaisesRegex(RuntimeError, 'Source archive changed'):
            self.build({'perf': [entry]}, 'bad')
        with self.assertRaisesRegex(RuntimeError, 'source_archive changed'):
            profile.verify_saved_report(self.root / 'report', kda)

    def test_hpm_unknown_selector_is_not_zero_or_a_fabricated_delta(self):
        log = b'[xsai-blas-hpm] counter=11 event=UNVERIFIED config=0x43 total=80 per_run=10.00\n'
        reports = []
        for index in range(2):
            spec = {'perf': [self.run_input(cycles=100-index)],
                    'hpm': self.run_input(mode='hpm', artifacts={'perf.log': log, 'rtl-config.json': b'{}'})}
            self.build(spec, f'r{index}')
            reports.append(profile.verify_saved_report(self.root / f'r{index}', kda)[0])
        counter = reports[0]['sections']['hpm']['counters'][0]
        self.assertFalse(counter['encoding_resolved'])
        result = profile.compare_reports(*reports, (self.root / 'r0', self.root / 'r1'), kda)
        self.assertIsNone(result['sections']['hpm']['counters'][0]['delta_per_call'])

    def test_output_cannot_overwrite_runs_or_reports(self):
        entry = self.run_input()
        with self.assertRaisesRegex(RuntimeError, 'inside an existing run'):
            self.build({'perf': [entry]}, str(Path(entry['run']) / 'new'))
        self.build({'perf': [entry]})
        with self.assertRaisesRegex(RuntimeError, 'already exists'):
            self.build({'perf': [entry]})


class CuteTests(unittest.TestCase):
    def database(self):
        connection = sqlite3.connect(':memory:')
        self.addCleanup(connection.close)
        connection.row_factory = sqlite3.Row
        for table, begin, end in [('CUTELoadEvent', 'LoadIssue', 'LoadFinish'),
                                  ('CUTEComputeEvent', 'ComputeIssue', 'ComputeWriteCFinish'),
                                  ('CUTEStoreEvent', 'StoreIssue', 'StoreFinish')]:
            connection.execute(f'CREATE TABLE {table}(SEQID INT,STAMP INT,SITE TEXT,NEEDMASK INT)')
            for seq, duration in enumerate([1000, 20, 30]):
                for site, stamp in [(begin, seq * 2000), (end, seq * 2000 + duration)]:
                    connection.execute(f'INSERT INTO {table} VALUES(?,?,?,1)', (seq, stamp, site))
        connection.execute('CREATE TABLE CUTEReleaseEvent(SEQID INT)')
        connection.executemany('INSERT INTO CUTEReleaseEvent VALUES(?)', [(0,), (1,), (2,)])
        return connection

    def test_warmup_scope_explicit_and_stage_intervals_not_summed(self):
        c = self.database()
        all_tasks = profile.cute_summary(c, {})
        self.assertEqual(all_tasks['status'], 'unscoped')
        selected = profile.cute_summary(c, {'warmup_tasks': 1, 'measured_tasks': 2})
        self.assertEqual([s['median_cycles'] for s in selected['stages']], [25, 25, 25])
        self.assertNotIn('total_cycles', selected)
        with self.assertRaisesRegex(RuntimeError, 'task count differs'):
            profile.cute_summary(c, {'warmup_tasks': 0, 'measured_tasks': 2})

    def test_partial_duplicate_missing_tasks_and_missing_tables(self):
        c = self.database()
        c.execute("INSERT INTO CUTELoadEvent VALUES(0,1,'LoadIssue',1)")
        with self.assertRaisesRegex(RuntimeError, 'Duplicate CUTE site'):
            profile.cute_summary(c, {})
        c.execute("DELETE FROM CUTELoadEvent WHERE STAMP=1")
        c.execute("DELETE FROM CUTELoadEvent WHERE SITE='LoadFinish' AND SEQID=0")
        with self.assertRaisesRegex(RuntimeError, 'Incomplete CUTE task'):
            profile.cute_summary(c, {})
        empty = sqlite3.connect(':memory:')
        self.addCleanup(empty.close)
        self.assertEqual(profile.cute_summary(empty, {})['status'], 'unavailable')


@unittest.skipUnless(shutil.which('riscv64-linux-gnu-gcc'), 'Requires RISC-V compiler')
class TraceTests(ProfileFixture, unittest.TestCase):
    def trace_input(self, mismatch=False):
        elf = self.root / 'fixture.elf'
        subprocess.run(['riscv64-linux-gnu-gcc', '-nostdlib', '-static', '-march=rv64gc', '-g',
                        '-Wl,-Ttext=0x80000000', '-Wl,--build-id=none', str(ROOT / 'tests/roi_fixture.S'),
                        '-o', str(elf)], check=True, capture_output=True)
        db = self.root / 'trace.db'
        with sqlite3.connect(db) as connection:
            connection.execute('CREATE TABLE LifeTimeCommitTrace(SN INTEGER,PC INTEGER,DisAsm INTEGER,AtFetch INTEGER,AtIssueQue INTEGER,AtFU INTEGER,AtCommit INTEGER)')
            for sn, encoding, cycle in [(1, 0x5a100013, 101), (2, 0x00350513 if mismatch else 0x00150513, 104),
                                         (3, 0x00250513, 108), (4, 0x5a200013, 113)]:
                connection.execute('INSERT INTO LifeTimeCommitTrace VALUES(?,?,?,?,?,?,?)',
                                   (sn, 0x80000000 + 4*(sn-1), encoding, cycle-4, cycle-3, cycle-1, cycle))
        return self.run_input(mode='trace', artifacts={
            'chiseldb.db': db.read_bytes(), 'profile.elf': elf.read_bytes(), 'perf.elf': elf.read_bytes()})

    def test_raw_trace_reanalysis_and_all_pc_source_assembly_view(self):
        trace = self.trace_input()
        original_hash = profile.digest(Path(trace['run']) / 'chiseldb.db')
        self.build({'perf': [self.run_input()], 'trace': trace}, options={'recompute_roi': True})
        report, directory = profile.verify_saved_report(self.root / 'report', kda)
        section = report['sections']['trace']
        self.assertEqual(section['window']['roi_cycles'], 12)
        self.assertEqual(section['window']['committed_instructions'], 2)
        self.assertEqual(section['elf_validation']['native_32bit_pcs_checked'], 2)
        self.assertEqual(section['cute']['status'], 'unavailable')
        self.assertTrue((directory / 'source-assembly.html').is_file())
        self.assertIn('addi', (directory / 'source-assembly.html').read_text())
        self.assertEqual(profile.digest(Path(trace['run']) / 'chiseldb.db'), original_hash)

    def test_wrong_trace_elf_pair_even_with_correct_artifact_checksums(self):
        trace = self.trace_input(mismatch=True)
        kda.load_run(trace['run'])  # This is not an artifact-tampering test.
        with self.assertRaisesRegex(RuntimeError, 'trace and ELF do not match'):
            self.build({'perf': [self.run_input()], 'trace': trace}, options={'recompute_roi': True})
        self.assertFalse((self.root / 'report').exists())

    def test_archived_report_is_checked_against_raw_db_and_elf(self):
        trace = self.trace_input()
        perf = self.run_input()
        self.build({'perf': [perf], 'trace': trace}, 'original', {'recompute_roi': True})
        run = Path(trace['run'])
        (run / 'roi').mkdir()
        shutil.copyfile(self.root / 'original/roi/hotspots.json', run / 'roi/hotspots.json')
        manifest = profile.read_json(run / 'manifest.json')
        manifest['artifacts']['roi/hotspots.json'] = {'sha256': profile.digest(run / 'roi/hotspots.json')}
        profile.dump(run / 'manifest.json', manifest)
        self.build({'perf': [perf], 'trace': trace}, 'archived')
        # A stale report and different raw DB, both correctly hashed, must fail
        # the fresh all-PC check rather than being accepted from the receipt.
        with sqlite3.connect(run / 'chiseldb.db') as connection:
            connection.execute('UPDATE LifeTimeCommitTrace SET DisAsm=0x00350513 WHERE SN=3')
        manifest['artifacts']['chiseldb.db']['sha256'] = profile.digest(run / 'chiseldb.db')
        profile.dump(run / 'manifest.json', manifest)
        with self.assertRaisesRegex(RuntimeError, 'Trace and ELF do not match'):
            self.build({'perf': [perf], 'trace': trace}, 'bad')
        self.assertFalse((self.root / 'bad').exists())

    def test_different_collected_elf_pair_is_rejected(self):
        trace = self.trace_input()
        run = Path(trace['run'])
        (run / 'profile.elf').write_bytes((run / 'profile.elf').read_bytes() + b'different')
        manifest = profile.read_json(run / 'manifest.json')
        manifest['artifacts']['profile.elf']['sha256'] = profile.digest(run / 'profile.elf')
        profile.dump(run / 'manifest.json', manifest)
        with self.assertRaisesRegex(RuntimeError, 'differs from collected perf.elf'):
            self.build({'perf': [self.run_input()], 'trace': trace})


if __name__ == '__main__':
    unittest.main()
