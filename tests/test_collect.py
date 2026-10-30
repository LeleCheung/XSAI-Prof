"""Collect pipeline contracts, with simulated execution and real evidence files."""
import argparse
import copy
import fcntl
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import kda_collect as collect
import kda_profile as profile
import xsai_kda as kda


class CollectTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        source = self.root / 'blas'
        source.mkdir()
        (source / 'Makefile').write_text('all:\n\ttrue\n')
        (source / 'kernel.c').write_text('void kernel(void) {}\n')
        (source / 'test').mkdir()
        (source / 'test/test.h').write_text('#define PERF_MAX_RUNS 8\n')
        (source / 'test/test-ops.c').write_text('/* simulated harness */\n')
        (source / 'build').mkdir()
        (source / 'build/ignored').write_text('generated')
        runtime = self.root / 'am'
        runtime.mkdir()
        (runtime / 'Makefile.app').write_text('all:\n')
        llvm = self.root / 'llvm/bin'
        llvm.mkdir(parents=True)
        (llvm / 'clang').write_text('fixture compiler')
        rtl = self.root / 'rtl/build'
        rtl.mkdir(parents=True)
        (rtl / 'emu').write_text('#!/bin/sh\nexit 0\n')
        (rtl / 'emu').chmod(0o755)
        config = self.root / 'rtl-config.json'
        profile.dump(config, {'emulator': {'sha256': profile.digest(rtl / 'emu')}})
        self.config = {
            'blas': str(source), 'noop_home': str(rtl.parent), 'rtl_config': str(config),
            'xsai_env': str(self.root), 'kernel': 'softmax', 'case': 1,
            'backend': 'rvv', 'rvv_enable': 'yes', 'arch': 'riscv64-xs',
            'toolchain': 'LLVM', 'perf_repeats': 2, 'diagnostics': ['hpm'],
            'hpm_profile': 'memstall', 'environment': {k: None for k in collect.ENV_KEYS}}
        self.config['environment'].update(AM_HOME=str(runtime), LLVM_HOME=str(llvm.parent), PERF_MAX_RUNS='8')
        self.output = self.root / 'bundle'
        self.executed = []
        self.fail_stage = None
        self.mutate_source = False

    def tearDown(self):
        self.tmp.cleanup()

    def execute(self, command, stdout, stderr, cwd, env, pass_fds, **kwargs):
        def value(name):
            return command[command.index(name) + 1]
        mode, runs, source = value('--mode'), Path(value('--runs')), Path(value('--blas'))
        self.assertEqual(source, self.output / 'source')
        self.assertTrue(pass_fds)
        self.assertTrue(Path('/proc/self/fd/' + str(pass_fds[0])).exists())
        self.executed.append((mode, runs))
        args = SimpleNamespace(blas=str(source), runs=str(runs), kernel='softmax', case=1, backend='rvv')
        run = kda.Run(args, 'rtl')
        run.data.update(target='rtl', mode=mode, instrumentation='none' if mode=='perf' else mode,
            performance_eligible=mode=='perf', arch='riscv64-xs', toolchain='LLVM',
            rtl={'emu_sha256': 'same', 'config_sha256': 'same'}, compiler={'sha256': 'same'},
            runtime_source={'sha256': 'same'}, build_environment={}, build_overrides={},
            rvv_enable='yes', test_harness={'test.c': 'same'},
            correctness={'passed': 1, 'failed': 0},
            measurements=[{'op': 'softmax(n=256)', 'unit': 'RVV-FP32', 'cycles_per_run': 100}])
        (run.path / 'perf.log').write_text('[xsai-blas-hpm] counter=11 event=EVENT config=0x43 total=80 per_run=10.00\n')
        (run.path / 'rtl-config.json').write_text('{}')
        run.artifact(run.path / 'perf.log')
        run.artifact(run.path / 'rtl-config.json')
        if self.mutate_source:
            (source / 'kernel.c').write_text('changed during build')
        if self.fail_stage == runs.parent.name:
            run.data.update(status='failed', error='synthetic failure')
            run.save()
            stdout.write('synthetic failed attempt\n')
            return SimpleNamespace(returncode=1)
        run.finish()
        stdout.write('Run: ' + str(run.path) + '\n')
        return SimpleNamespace(returncode=0)

    def invoke(self, resume=False):
        with patch.object(collect, 'run_stage', side_effect=self.execute):
            return collect.collect(self.config, self.output, resume, kda)

    def test_frozen_source_full_pipeline_report_and_noop_resume(self):
        original = profile.digest(Path(self.config['blas']) / 'kernel.c')
        result = self.invoke()
        self.assertEqual(result['status'], 'passed')
        self.assertEqual([m for m, _ in self.executed], ['perf', 'perf', 'hpm'])
        self.assertFalse((self.output / 'source/build/ignored').exists())
        report, _ = profile.verify_saved_report(self.output / 'report', kda)
        self.assertEqual(report['sections']['performance']['repeat_count'], 2)
        self.assertEqual(report['sections']['hpm']['status'], 'available')
        self.assertEqual(report['validation']['source_archives'], 'verified')
        self.assertEqual(profile.digest(Path(self.config['blas']) / 'kernel.c'), original)
        # Original source changes cannot contaminate a resumed frozen bundle.
        (Path(self.config['blas']) / 'kernel.c').write_text('new original version')
        with patch.object(collect, 'command_for', side_effect=AssertionError('must not collect')):
            self.assertEqual(self.invoke(True)['status'], 'passed')
        self.assertEqual(len(self.executed), 3)

    def test_failure_preserved_resume_reuses_passed_stage(self):
        self.fail_stage = 'perf-2'
        with self.assertRaisesRegex(RuntimeError, 'perf-2 failed'):
            self.invoke()
        saved = profile.read_json(self.output / 'collection.json')
        self.assertEqual(saved['status'], 'failed')
        first = saved['stages'][0]['attempts'][0]
        manifest_hash = profile.digest(self.output / first['run'] / 'manifest.json')
        self.assertEqual(saved['stages'][1]['attempts'][0]['status'], 'failed')
        self.fail_stage = None
        self.invoke(True)
        self.assertEqual(profile.digest(self.output / first['run'] / 'manifest.json'), manifest_hash)
        saved = profile.read_json(self.output / 'collection.json')
        self.assertEqual([a['status'] for a in saved['stages'][1]['attempts']], ['failed', 'passed'])
        self.assertEqual([m for m, _ in self.executed], ['perf', 'perf', 'perf', 'hpm'])

    def test_resume_rejects_changed_config_or_completed_evidence(self):
        self.invoke()
        self.config['case'] = 2
        with self.assertRaisesRegex(RuntimeError, 'configuration differs'):
            self.invoke(True)
        self.config['case'] = 1
        spec = profile.read_json(self.output / 'spec.json')
        (self.output / spec['perf'][0]['run'] / 'perf.log').write_text('tampered')
        with self.assertRaisesRegex(RuntimeError, 'Artifact changed'):
            self.invoke(True)
        self.assertEqual(len(self.executed), 3)

    def test_runtime_or_source_change_stops_collection(self):
        self.fail_stage = 'perf-2'
        with self.assertRaises(RuntimeError):
            self.invoke()
        (Path(self.config['environment']['AM_HOME']) / 'Makefile.app').write_text('modified runtime')
        with self.assertRaisesRegex(RuntimeError, 'runtime changed'):
            self.invoke(True)
        self.assertEqual(len(self.executed), 2)

    def test_completed_bundle_spec_and_logs_cannot_silently_change(self):
        self.invoke()
        spec_path = self.output / 'spec.json'
        spec_bytes = spec_path.read_bytes()
        spec_path.write_bytes(spec_bytes + b' ')
        with self.assertRaisesRegex(RuntimeError, 'spec/report changed'):
            self.invoke(True)
        spec_path.write_bytes(spec_bytes)
        state = profile.read_json(self.output / 'collection.json')
        log = self.output / state['stages'][0]['attempts'][0]['log']
        log.write_text('changed log')
        with self.assertRaisesRegex(RuntimeError, 'command log changed'):
            self.invoke(True)
        self.assertEqual(len(self.executed), 3)

    def test_source_mutation_during_build_is_rejected(self):
        self.mutate_source = True
        with self.assertRaisesRegex(RuntimeError, 'Source archive|Source changed'):
            self.invoke()
        self.assertFalse((self.output / 'report').exists())
        self.assertEqual(profile.read_json(self.output / 'collection.json')['status'], 'failed')

    def test_interrupted_child_manifest_is_retained_with_terminal_state(self):
        self.fail_stage = 'perf-2'
        with self.assertRaises(RuntimeError):
            self.invoke()
        state = profile.read_json(self.output / 'collection.json')
        attempt = state['stages'][1]['attempts'][0]
        run_manifest = self.output / attempt['run'] / 'manifest.json'
        manifest = profile.read_json(run_manifest)
        manifest['status'] = 'running'
        profile.dump(run_manifest, manifest)
        attempt['status'] = 'running'
        profile.dump(self.output / 'collection.json', state)
        self.fail_stage = None
        self.invoke(True)
        saved = profile.read_json(self.output / 'collection.json')
        self.assertEqual(saved['stages'][1]['attempts'][0]['status'], 'interrupted')
        self.assertEqual(profile.read_json(run_manifest)['status'], 'failed')
        self.assertEqual(saved['stages'][1]['attempts'][1]['status'], 'passed')

    def test_same_bundle_cannot_collect_concurrently(self):
        self.invoke()
        with (self.output / '.collect.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            with self.assertRaisesRegex(RuntimeError, 'already running'):
                self.invoke(True)
        self.assertEqual(len(self.executed), 3)

    def test_resume_can_route_to_identical_existing_nontrace_worker(self):
        self.fail_stage = 'perf-2'
        with self.assertRaises(RuntimeError):
            self.invoke()
        worker = self.root / 'worker/build'
        worker.mkdir(parents=True)
        shutil.copy2(Path(self.config['noop_home']) / 'build/emu', worker / 'emu')
        self.config['non_trace_home'] = str(worker.parent)
        self.fail_stage = None
        self.invoke(True)
        state = profile.read_json(self.output / 'collection.json')
        self.assertEqual(len(state['routing_history']), 1)
        command = state['stages'][1]['attempts'][-1]['command']
        self.assertEqual(command[command.index('--noop-home')+1], str(worker.parent))
        self.assertIn('--isolate-outputs', command)
        trace = collect.command_for(self.config, self.output, 'trace', self.root / 'trace-runs')
        self.assertEqual(trace[trace.index('--noop-home')+1], self.config['noop_home'])
        self.assertNotIn('--isolate-outputs', trace)
        (worker / 'emu').write_text('changed emulator')
        with self.assertRaisesRegex(RuntimeError, 'identical emulator bytes'):
            self.invoke(True)

    def test_output_overwrite_and_source_containment_rejected(self):
        self.output = Path(self.config['blas']) / 'profile-output'
        with self.assertRaisesRegex(RuntimeError, 'must not contain each other'):
            self.invoke()
        self.assertFalse(self.output.exists())
        self.output = self.root / 'bundle'
        self.invoke()
        with self.assertRaisesRegex(RuntimeError, 'Output exists'):
            self.invoke()

    def test_cli_config_paths_and_validation(self):
        config = copy.deepcopy(self.config)
        config['blas'] = 'blas'
        config['max_runs'] = 8
        path = self.root / 'input.json'
        profile.dump(path, config)
        parser = argparse.ArgumentParser()
        profile.add_parser(parser.add_subparsers())
        args = parser.parse_args(['profile', 'collect', '--config', str(path), '--output', str(self.output)])
        result = collect.settings(args)
        self.assertEqual(result['blas'], str(self.root / 'blas'))
        self.assertEqual(result['environment']['PERF_MAX_RUNS'], '8')
        args = parser.parse_args(['profile', 'collect', '--config', str(path), '--output', str(self.output), '--case', '1'])
        with self.assertRaisesRegex(RuntimeError, 'cannot be mixed'):
            collect.settings(args)
        config['cute'] = {'warmup_tasks': 1, 'measured_tasks': 8}
        profile.dump(path, config)
        args.case = None
        with self.assertRaisesRegex(RuntimeError, 'requires trace'):
            collect.settings(args)


if __name__ == '__main__':
    unittest.main()
