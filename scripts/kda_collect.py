"""Correctness-gated RTL collection bundles with frozen sources and resume."""
import datetime as dt
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

import kda_profile as profile
from kda_jobs import run_stage

from kda_paths import ROOT, ADAPTER
ENV_KEYS = ('AM_HOME', 'LLVM_HOME', 'RISCV', 'MARCH', 'CFLAGS', 'CPPFLAGS',
            'CC_OPT', 'ASFLAGS', 'LDFLAGS', 'PERF_MAX_RUNS', 'PERF_TARGET_FLOPS',
            'PERF_CPU_HZ', 'CMAKE_TOOLCHAIN_FILE', 'OBJDUMP_MATTR')
PATH_KEYS = ('blas', 'noop_home', 'non_trace_home', 'rtl_config', 'xsai_env', 'objdump', 'addr2line', 'readelf')
EXCLUDED = {'.git', 'build', 'profile', '__pycache__'}


def now():
    return dt.datetime.now(dt.timezone.utc).isoformat()


def add_parser(commands):
    parser = commands.add_parser('collect', help='Freeze sources, collect RTL evidence, generate a report; supports explicit resume')
    parser.add_argument('--config', type=Path, help='JSON collection config; paths relative to this file')
    parser.add_argument('--output', '-o', type=Path, required=True, help='New bundle directory, or matching bundle with --resume')
    parser.add_argument('--stage-timeout', type=float, help='Wall seconds per adapter stage, including correctness/build/lock wait')
    parser.add_argument('--resume', action='store_true', help='Validate and reuse passed stages; preserve earlier failed attempts')
    parser.add_argument('--dry-run', action='store_true', help='Read-only acquisition plan; never build, snapshot or start RTL')
    parser.add_argument('--format', choices=['json', 'text'], default='json', help='Plan/result output format')
    parser.add_argument('--blas', type=Path)
    parser.add_argument('--noop-home', type=Path)
    parser.add_argument('--non-trace-home', type=Path, help='Existing byte-identical emulator copy for perf/HPM with isolated outputs; trace keeps --noop-home')
    parser.add_argument('--rtl-config', type=Path)
    parser.add_argument('--xsai-env', type=Path)
    parser.add_argument('--kernel')
    parser.add_argument('--case', type=int)
    parser.add_argument('--backend', choices=['generic', 'scalar', 'rvv', 'ame', 'triton'])
    parser.add_argument('--rvv-enable', choices=['yes', 'no'])
    parser.add_argument('--arch')
    parser.add_argument('--toolchain', choices=['LLVM', 'GNU'])
    parser.add_argument('--perf-repeats', type=int)
    parser.add_argument('--diagnostics', nargs='*', choices=['hpm', 'trace'])
    parser.add_argument('--max-runs', type=int, help='Set PERF_MAX_RUNS explicitly')
    parser.add_argument('--set', choices=['basic', 'counters', 'detailed'])
    parser.add_argument('--sections', '--section', nargs='+', action='extend', help='Sections, space/comma separated; repeatable')
    parser.add_argument('--metrics', nargs='+', action='extend', help='Metric names, space/comma separated; native modes are shared')
    parser.add_argument('--hpm-profile', choices=['memstall', 'default'])
    parser.add_argument('--capture-scope', help='full, invocation, or stage:NAME; reviewed observer required for filtering')
    parser.add_argument('--memory-trace', action='store_true', default=None, help='Record reviewed AME and ordinary CPU/RVV memory events')
    parser.add_argument('--label')
    parser.add_argument('--cute-warmup-tasks', type=int)
    parser.add_argument('--cute-measured-tasks', type=int)
    for name in ('objdump', 'addr2line', 'readelf', 'objdump-mattr'):
        parser.add_argument('--' + name)


def settings(args):
    keys = (*PATH_KEYS, 'kernel', 'case', 'backend', 'rvv_enable', 'arch', 'toolchain',
            'perf_repeats', 'diagnostics', 'max_runs', 'hpm_profile', 'label', 'objdump_mattr', 'set', 'sections', 'metrics', 'stage_timeout', 'ranges', 'hpm_events', 'capture_scope', 'memory_trace')
    if args.config:
        profile.require(not any(getattr(args, k, None) is not None for k in
                        (*(k for k in keys if k not in ('set', 'sections', 'metrics')), 'cute_warmup_tasks', 'cute_measured_tasks')),
                        '--config cannot be mixed with collection options')
        config = profile.read_json(args.config)
        profile.require(isinstance(config, dict), 'Collection config must be an object')
        profile.require(not (set(config) - set(keys) - {'environment', 'cute'}),
                        'Unknown collection config fields: ' + str(sorted(set(config) - set(keys) - {'environment', 'cute'})))
        base = args.config.resolve().parent
        overrides = {key: getattr(args, key) for key in ('set', 'sections', 'metrics') if getattr(args, key, None) is not None}
        if overrides:
            for key in ('set', 'sections', 'metrics', 'diagnostics'):
                config.pop(key, None)
            config.update(overrides)
    else:
        config = {k: str(getattr(args, k)) if isinstance(getattr(args, k, None), Path)
                  else getattr(args, k) for k in keys if getattr(args, k, None) is not None}
        if args.cute_warmup_tasks is not None or args.cute_measured_tasks is not None:
            config['cute'] = {'warmup_tasks': args.cute_warmup_tasks, 'measured_tasks': args.cute_measured_tasks}
        base = Path.cwd()
    if any(config.get(key) is not None for key in ('sections', 'set', 'metrics')):
        import kda_plan
        profile.require('diagnostics' not in config, 'Do not mix sections/set with diagnostics')
        plan = kda_plan.selection(config.get('sections'), config.get('set'), config.get('metrics'))
        config.pop('set', None)
        config['sections'] = plan['sections']
        config['diagnostics'] = plan['diagnostics']
        if plan['metrics']:
            config['metrics'] = plan['metrics']
        if 'memory' in plan['sections']:
            config['memory_trace'] = True
        elif args.config and overrides:
            config.pop('memory_trace', None)
        if args.config and overrides and 'trace' not in plan['diagnostics']:
            for key in ('capture_scope', 'ranges', 'cute'):
                config.pop(key, None)
    defaults = {'backend': 'generic', 'rvv_enable': 'no', 'arch': 'riscv64-xs',
                'toolchain': 'LLVM', 'perf_repeats': 2, 'diagnostics': ['hpm', 'trace'],
                'hpm_profile': 'memstall', 'xsai_env': str(ROOT / 'dependencies/xsai-env')}
    config = {**defaults, **config}
    for name in ('blas', 'noop_home', 'rtl_config', 'kernel'):
        profile.require(config.get(name), f'Collection requires {name}')
    for key in PATH_KEYS:
        if config.get(key):
            # Keep tool symlink names for LLVM multicall binaries.
            config[key] = os.path.abspath(base / config[key])
    for key in ('backend', 'rvv_enable', 'toolchain', 'hpm_profile'):
        choices = {'backend': ('generic', 'scalar', 'rvv', 'ame', 'triton'),
                   'rvv_enable': ('yes', 'no'), 'toolchain': ('LLVM', 'GNU'),
                   'hpm_profile': ('memstall', 'default')}[key]
        profile.require(config[key] in choices, f'Invalid {key}')
    if config.get('stage_timeout') is not None:
        import math
        t = config['stage_timeout']
        profile.require(type(t) in (int, float) and math.isfinite(t) and t > 0, 'stage_timeout must be positive finite seconds')
    if config.get('ranges') is not None:
        import kda_capture
        kda_capture.validate_ranges(config['ranges'])
        profile.require('trace' in config['diagnostics'], 'ranges requires trace diagnostics')
    if config.get('hpm_events') is not None:
        import kda_capture
        kda_capture.hpm_plan(config['hpm_events'], profile.read_json(config['rtl_config']))
        profile.require('hpm' in config['diagnostics'], 'hpm_events requires HPM diagnostics')
    scope = config.get('capture_scope', 'full')
    profile.require(isinstance(scope, str), 'capture_scope must be a string')
    profile.require(type(config.get('memory_trace', False)) is bool, 'memory_trace must be boolean')
    if scope != 'full' or config.get('memory_trace'):
        from kda_observer import reviewed
        profile.require('trace' in config['diagnostics'], 'Scoped/memory capture requires trace diagnostics')
        if not getattr(args, 'dry_run', False):
            profile.require(reviewed(profile.read_json(config['rtl_config'])), 'Scoped/memory capture requires the reviewed observer build')
    if scope != 'full':
        profile.require(config.get('ranges') is not None, 'Filtered capture requires ranges annotations')
        stages = [s['name'] for s in config['ranges'].get('stages', [])]
        profile.require(scope == 'invocation' or (scope.startswith('stage:') and scope[6:] in stages), 'capture_scope must be full, invocation or a declared stage:NAME')
    repeats = config['perf_repeats']
    profile.require(type(repeats) is int and repeats > 0, 'perf_repeats must be a positive integer')
    if config.get('case') is not None:
        profile.require(type(config['case']) is int and config['case'] >= 0, 'case must be a non-negative integer')
    modes = config['diagnostics']
    profile.require(isinstance(modes, list) and all(isinstance(v, str) and v in ('hpm', 'trace') for v in modes) and
                    len(set(modes)) == len(modes), 'Invalid or duplicate diagnostics')
    env = config.get('environment', {})
    profile.require(isinstance(env, dict) and set(env) <= set(ENV_KEYS), 'Unsupported collection environment keys')
    env = {k: env[k] if k in env else os.environ.get(k) for k in ENV_KEYS}
    profile.require(all(v is None or isinstance(v, str) for v in env.values()), 'Environment values must be strings or null')
    for key in ('AM_HOME', 'LLVM_HOME', 'RISCV', 'CMAKE_TOOLCHAIN_FILE'):
        if env.get(key):
            env[key] = os.path.abspath(base / env[key])
    if config.get('max_runs') is not None:
        profile.require(type(config['max_runs']) is int and config['max_runs'] > 0, 'max_runs must be positive')
        env['PERF_MAX_RUNS'] = str(config.pop('max_runs'))
    config['environment'] = env
    cute = config.get('cute')
    if cute is not None:
        profile.require(isinstance(cute, dict) and set(cute) == {'warmup_tasks', 'measured_tasks'} and
                        type(cute['warmup_tasks']) is int and cute['warmup_tasks'] >= 0 and
                        type(cute['measured_tasks']) is int and cute['measured_tasks'] > 0,
                        'cute requires non-negative warmup_tasks and positive measured_tasks')
        profile.require('trace' in modes, 'CUTE scope requires trace collection')
    if config.get('metrics') and not getattr(args, 'dry_run', False):
        from kda_plan import requirements
        unavailable = [row for row in requirements(config) if row['status'] == 'unsupported_target']
        profile.require(not unavailable, 'Requested metrics unsupported by target: ' + ', '.join(row['metric'] for row in unavailable))
    return config


def source_files(directory):
    return sorted(p for p in directory.rglob('*') if p.is_file() and p.name != '.xsai-kda.lock'
                  and not set(p.relative_to(directory).parts) & EXCLUDED)


def freeze_source(origin, output, kda, config=None):
    """Build from a private byte snapshot, never the user's mutable checkout."""
    before = kda.source_identity(origin)
    destination = output / 'source'
    destination.mkdir()
    files = {}
    for path in source_files(origin):
        relative = path.relative_to(origin)
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
        target.chmod(path.stat().st_mode & 0o777)
        files[str(relative)] = profile.digest(target)
    identity = kda.source_identity(destination)
    profile.require(kda.source_identity(origin) == before and identity['sha256'] == before['sha256'],
                    'Source changed while freezing; start a new bundle')
    annotations = None
    if config and (config.get('ranges') is not None or config.get('hpm_events') is not None or
                   config.get('environment', {}).get('PERF_MAX_RUNS') is not None):
        import kda_capture
        annotations = kda_capture.apply(destination, config)
        identity = kda.source_identity(destination)
        files = {str(p.relative_to(destination)): profile.digest(p) for p in source_files(destination)}
    archive = output / 'source.zip'
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as zipped:
        for name in files:
            zipped.write(destination / name, name)
    receipt = {'identity': identity, 'files': files, 'origin': str(origin),
               'origin_identity': before, 'annotations': annotations, 'created_utc': now(),
               'policy': 'Private source snapshot; no Git metadata or build outputs. Snapshot revision is null; origin revision is preserved here.'}
    kda.write_json(output / 'source.json', receipt)
    return receipt


def environment(config):
    env = dict(os.environ)
    for key, value in config['environment'].items():
        env.pop(key, None)
        if value is not None:
            env[key] = value
    return env


def preflight(config, kda):
    source = Path(config['blas'])
    profile.require((source / 'Makefile').is_file(), f'BLAS Makefile missing: {source}')
    emu = Path(config['noop_home']) / 'build/emu'
    profile.require(emu.is_file() and os.access(emu, os.X_OK), f'RTL emulator unavailable: {emu}')
    kda.validate_rtl_inputs(Path(config['rtl_config']), emu)
    if config.get('non_trace_home'):
        worker = Path(config['non_trace_home']) / 'build/emu'
        profile.require(worker.is_file() and os.access(worker, os.X_OK), f'Worker emulator unavailable: {worker}')
        profile.require(profile.digest(worker) == profile.digest(emu) and
                        kda.revision(Path(config['non_trace_home'])) == kda.revision(Path(config['noop_home'])),
                        'Non-trace worker must have identical emulator bytes and recorded RTL revision')
        kda.validate_rtl_inputs(Path(config['rtl_config']), worker)
    env = environment(config)
    profile.require(env.get('AM_HOME') and (Path(env['AM_HOME']) / 'Makefile.app').is_file(), 'AM_HOME must provide Makefile.app')
    if config['toolchain'] == 'LLVM':
        compiler = Path(env.get('LLVM_HOME') or '') / 'bin/clang'
    else:
        compiler = Path(shutil.which('riscv64-linux-gnu-gcc') or 'missing')
    profile.require(compiler.is_file(), f'Compiler unavailable: {compiler}')
    return {'emu_sha256': profile.digest(emu), 'rtl_config_sha256': profile.digest(config['rtl_config']),
            'compiler_sha256': profile.digest(compiler),
            'runtime_source': kda.source_identity(Path(env['AM_HOME']))}


def command_for(config, output, mode, stage_runs):
    home = config.get('non_trace_home') if mode != 'trace' else None
    command = [sys.executable, str(ADAPTER),
               '--blas', str(output / 'source'), '--noop-home', home or config['noop_home'],
               '--xsai-env', config['xsai_env'], '--runs', str(stage_runs), 'rtl',
               '--mode', mode, '--rtl-config', config['rtl_config'],
               '--backend', config['backend'], '--rvv-enable', config['rvv_enable'],
               '--arch', config['arch'], '--toolchain', config['toolchain'],
               '--hpm-profile', config['hpm_profile'], '--kernel', config['kernel']]
    if config.get('case') is not None:
        command += ['--case', str(config['case'])]
    if home:
        command += ['--isolate-outputs']
    if mode == 'trace':
        scope = config.get('capture_scope', 'full')
        if scope.startswith('stage:'):
            names = [s['name'] for s in config['ranges']['stages']]
            scope = 'stage:' + str(names.index(scope[6:]))
        command += ['--trace-scope', scope]
        if config.get('memory_trace'):
            command += ['--memory-trace']
    for name in ('objdump', 'addr2line', 'readelf', 'objdump_mattr'):
        if config.get(name):
            command += ['--' + name.replace('_', '-'), config[name]]
    return command


def entry_for(run, output):
    return {'run': str(run.relative_to(output)), 'source_receipt': 'source.json', 'source_archive': 'source.zip'}


def validate_destination(config, output, resume=False):
    output = Path(output).resolve()
    profile.require(not output.is_relative_to(ROOT / 'dependencies'), 'Collection must not modify dependencies')
    source = Path(config['blas']).resolve()
    profile.require(not output.is_relative_to(source) and not source.is_relative_to(output),
                    'Collection output and source must not contain each other')
    profile.require(not any((p / 'manifest.json').exists() for p in (output, *output.parents)),
                    'Collection must not be written inside an existing run')
    if output.exists():
        profile.require(resume and (output / 'collection.json').is_file(),
                        'Output exists; use --resume only with a matching collection bundle')
    else:
        profile.require(not resume, '--resume requires an existing collection bundle')


def collect(config, output, resume, kda):
    output = Path(output).resolve()
    validate_destination(config, output, resume)
    source = Path(config['blas']).resolve()
    if not output.exists():
        output.mkdir(parents=True)
    with (output / '.collect.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Collection is already running; wait for its collector/child') from exc
        state_path = output / 'collection.json'
        if resume:
            state = profile.read_json(state_path)
            profile.require(state.get('schema') == 'xsai-kda.collection/v1' and
                            {k:v for k,v in state['config'].items() if k != 'non_trace_home'} ==
                            {k:v for k,v in config.items() if k != 'non_trace_home'},
                            'Resume configuration differs; use the original configuration or a new bundle')
            profile.require('source_receipt_sha256' in state and 'source_archive_sha256' in state,
                            'Preparation did not complete; preserve this attempt and use a new bundle')
            receipt = profile.read_json(output / 'source.json')
            profile.require(profile.digest(output / 'source.json') == state['source_receipt_sha256'] and
                            profile.digest(output / 'source.zip') == state['source_archive_sha256'],
                            'Frozen source receipt/archive changed')
            if state.get('status') == 'passed':
                profile.require(profile.digest(output / 'spec.json') == state['spec_sha256'] and
                                profile.digest(output / 'report/report.json') == state['report_sha256'],
                                'Completed collection spec/report changed')
            for stage in state['stages']:
                for number, attempt in enumerate(stage['attempts'], 1):
                    if attempt['status'] == 'running':
                        attempt.update(status='interrupted', finished_utc=now(),
                                       error='Collector did not record completion; retained on explicit resume')
                    # The inherited bundle lock proves no prior adapter remains.
                    # Give an interrupted child run a terminal state without
                    # changing any completed evidence or discarding artifacts.
                    if attempt['status'] in ('failed', 'interrupted', 'timed_out'):
                        candidates = list((output / 'runs' / stage['name'] /
                                           f'attempt-{number}').glob('*/manifest.json'))
                        if len(candidates) == 1:
                            manifest = profile.read_json(candidates[0])
                            if manifest.get('status') == 'running':
                                manifest.update(status='failed', error='Collection adapter interrupted before completion',
                                                collection_recovery_utc=now())
                                kda.write_json(candidates[0], manifest)
                                attempt.update(run=str(candidates[0].parent.relative_to(output)),
                                               manifest_sha256=profile.digest(candidates[0]))
        else:
            state = {'schema': 'xsai-kda.collection/v1', 'status': 'preparing', 'created_utc': now(),
                     'config': config, 'stages': [], 'producer_sha256': profile.digest(Path(__file__))}
            kda.write_json(state_path, state)
            try:
                state['prerequisites'] = preflight(config, kda)
                receipt = freeze_source(source, output, kda, config)
                state.update(source_identity=receipt['identity'],
                             source_receipt_sha256=profile.digest(output / 'source.json'),
                             source_archive_sha256=profile.digest(output / 'source.zip'))
                state['stages'] = [{'name': f'perf-{i+1}', 'mode': 'perf', 'attempts': []}
                                   for i in range(config['perf_repeats'])]
                state['stages'] += [{'name': mode, 'mode': mode, 'attempts': []} for mode in config['diagnostics']]
                kda.write_json(state_path, state)
            except Exception as exc:
                state.update(status='failed', error=str(exc), updated_utc=now())
                kda.write_json(state_path, state)
                raise
        try:
            profile.require(kda.source_identity(output / 'source') == receipt['identity'], 'Frozen source tree changed')
            # Resumption never needs to rebuild from the original checkout.
            frozen_config = {**config, 'blas': str(output / 'source')}
            profile.require(preflight(frozen_config, kda) == state['prerequisites'], 'RTL/compiler/runtime changed since collection')
            if state['config'].get('non_trace_home') != config.get('non_trace_home'):
                state.setdefault('routing_history', []).append({
                    'changed_utc': now(), 'from': state['config'].get('non_trace_home'),
                    'to': config.get('non_trace_home'),
                    'validation': 'Identical emulator SHA-256/revision/config and per-stage output isolation; workload and build unchanged.'})
                state['config'] = config
                kda.write_json(state_path, state)
            state.pop('error', None)
            spec = {'label': config.get('label') or output.name, 'perf': []}
            if config.get('cute'):
                spec['cute'] = config['cute']
            reference = None
            for stage in state['stages']:
                profile.require(preflight(frozen_config, kda) == state['prerequisites'],
                                'RTL/compiler/runtime changed before collection stage')
                passed = next((a for a in reversed(stage['attempts']) if a.get('status') == 'passed'), None)
                if passed:
                    run = output / passed['run']
                    profile.require(profile.digest(run / 'manifest.json') == passed['manifest_sha256'], 'Completed stage manifest changed')
                    profile.require(profile.digest(output / passed['log']) == passed['log_sha256'], 'Completed stage command log changed')
                    print(f'[xsai-prof] reuse {stage["name"]}: {run}', file=sys.stderr, flush=True)
                else:
                    number = len(stage['attempts']) + 1
                    stage_runs = output / 'runs' / stage['name'] / f'attempt-{number}'
                    stage_runs.mkdir(parents=True)
                    log = output / 'logs' / f'{stage["name"]}-attempt-{number}.log'
                    log.parent.mkdir(exist_ok=True)
                    command = command_for(config, output, stage['mode'], stage_runs)
                    attempt = {'status': 'running', 'started_utc': now(), 'command': command,
                               'log': str(log.relative_to(output))}
                    stage['attempts'].append(attempt)
                    state.update(status='running', active_stage=stage['name'], updated_utc=now())
                    kda.write_json(state_path, state)
                    print(f'[xsai-prof] collect {stage["name"]}; log: {log}', file=sys.stderr, flush=True)
                    with log.open('w') as stream:
                        # Inherited lock prevents duplicate collection even if the
                        # parent dies while the original RTL adapter is still alive.
                        def heartbeat(value):
                            state['heartbeat'] = {**value, 'updated_utc': now(), 'stage': stage['name']}
                            kda.write_json(state_path, state)
                        result = run_stage(command, stdout=stream, stderr=subprocess.STDOUT,
                                           cwd=ROOT, env=environment(config), pass_fds=(lock.fileno(),),
                                           timeout=config.get('stage_timeout'), heartbeat=heartbeat)
                    attempt.update(exit_code=result.returncode, finished_utc=now(), log_sha256=profile.digest(log))
                    manifests = sorted(stage_runs.glob('*/manifest.json'))
                    if len(manifests) == 1:
                        attempt['run'] = str(manifests[0].parent.relative_to(output))
                        attempt['manifest_sha256'] = profile.digest(manifests[0])
                    profile.require(result.returncode == 0 and len(manifests) == 1,
                                    f'Collection {stage["name"]} failed ({result.returncode}); see {log}')
                    run = manifests[0].parent
                item = profile.load_input({'run': str(run), 'source_receipt': str(output / 'source.json')}, kda, stage['mode'])
                if reference:
                    profile.bind(reference, item)
                else:
                    reference = item
                profile.require(kda.source_identity(output / 'source') == receipt['identity'], 'Source changed during collection')
                if not passed:
                    attempt['status'] = 'passed'
                entry = entry_for(run, output)
                if stage['mode'] == 'perf':
                    spec['perf'].append(entry)
                else:
                    spec[stage['mode']] = entry
                kda.write_json(output / 'spec.json', spec)
                kda.write_json(state_path, state)
            options = {k: config.get(k) for k in ('objdump', 'addr2line', 'readelf', 'objdump_mattr')}
            options.update(window=1, recompute_roi=False)
            if config.get('sections'):
                options['collection_sections'] = config['sections']
            if config.get('metrics'):
                options['collection_metrics'] = config['metrics']
            report_path = output / 'report'
            if report_path.exists():
                saved, _ = profile.verify_saved_report(report_path, kda)
                profile.require(saved['spec'] == profile.normalize_spec(spec, output), 'Existing report has different inputs')
            else:
                profile.publish(report_path, lambda out: profile.build_report(profile.normalize_spec(spec, output), options, out, kda))
            state.pop('heartbeat', None)
            state.update(status='passed', active_stage=None, updated_utc=now(),
                         spec_sha256=profile.digest(output / 'spec.json'),
                         report_sha256=profile.digest(report_path / 'report.json'))
            state.pop('error', None)
            kda.write_json(state_path, state)
            return {'status': 'passed', 'collection': str(state_path), 'spec': str(output / 'spec.json'),
                    'report': str(report_path / 'report.json'), 'html': str(report_path / 'index.html')}
        except BaseException as exc:
            for stage in state.get('stages', []):
                for attempt in stage['attempts']:
                    if attempt['status'] == 'running':
                        attempt.update(status='timed_out' if isinstance(exc, TimeoutError) else 'interrupted' if isinstance(exc, KeyboardInterrupt) else 'failed', error=str(exc), finished_utc=now())
                        if (output / attempt['log']).is_file():
                            attempt['log_sha256'] = profile.digest(output / attempt['log'])
            state.update(status='failed', error=str(exc), updated_utc=now())
            kda.write_json(state_path, state)
            raise


def dispatch(args, kda):
    config = settings(args)
    if getattr(args, 'dry_run', False):
        from kda_plan import preview
        result = preview(config, args.output, kda, args.resume)
        if args.format == 'text':
            print('Acquisition plan: ' + result['status'])
            for stage in result['stages']:
                print(stage['name'] + ': ' + ' -> '.join(stage['steps']))
            print('Fresh emulator invocations: ' + str(result['cost']['fresh_emulator_invocations']))
            for row in result['metric_requirements']:
                print(row['metric'] + ': ' + row['status'] + ' — ' + row['reason'])
            for row in result['checks']:
                if row['status'] == 'blocked': print('Blocked: ' + row['reason'])
        else:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        return 1 if result['status'] == 'blocked' else 0
    result = collect(config, args.output, args.resume, kda)
    if args.format == 'text':
        print('Collection: ' + result['status'])
        for name in ('collection', 'report', 'html'):
            print(name + ': ' + result[name])
    else:
        print(json.dumps(result, ensure_ascii=False, indent=2))
