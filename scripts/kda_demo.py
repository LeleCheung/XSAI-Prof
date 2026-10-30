"""Generate portable, explicitly synthetic fixtures; never simulator evidence."""
import json
from pathlib import Path

import kda_profile as profile


def fixture_run(directory, mode, cycles, source, kda, shape='softmax(n=128)'):
    directory.mkdir(parents=True)
    manifest = {
        'status': 'passed', 'target': 'rtl', 'mode': mode,
        'instrumentation': 'none' if mode == 'perf' else mode,
        'performance_eligible': mode == 'perf',
        'synthetic_fixture': True,
        'metric_semantics': 'Synthetic test fixture; not measured XSAI hardware or simulator performance.',
        'correctness': {'passed': 1, 'failed': 0},
        'selection': {'kernel': 'softmax', 'case': 1},
        'source': {'revision': None, 'sha256': source},
        'rtl': {'emu_sha256': 'synthetic-emulator', 'config_sha256': 'synthetic-config'},
        'compiler': {'sha256': 'synthetic-compiler'}, 'runtime_source': {'sha256': 'synthetic-runtime'},
        'arch': 'riscv64-xs', 'toolchain': 'LLVM', 'build_environment': {},
        'build_overrides': {}, 'rvv_enable': 'yes', 'backend': 'rvv',
        'test_harness': {'test.c': 'synthetic-harness'},
        'measurements': [{'op': shape, 'unit': 'RVV-FP32', 'cycles_per_run': cycles, 'instret_per_run': 40}],
        'artifacts': {}}
    log = '[xsai-blas-hpm] counter=11 event=EXAMPLE config=0x1 total=80 per_run=10.00\n' if mode == 'hpm' else 'Synthetic example, no simulator was executed.\n'
    (directory / 'perf.log').write_text(log)
    names = ['perf.log']
    if mode == 'hpm':
        profile.dump(directory / 'rtl-config.json', {'hpm_event_coding': []})
        names.append('rtl-config.json')
    for name in names:
        manifest['artifacts'][name] = {'sha256': profile.digest(directory / name)}
    profile.dump(directory / 'manifest.json', manifest)
    return directory


def demo(output, kda):
    output = output.resolve()
    profile.require(not output.exists(), 'Demo output already exists')
    profile.require(not output.is_relative_to(profile.ROOT / 'dependencies') and not any(
        (p / 'manifest.json').exists() for p in (output, *output.parents)), 'Demo must not modify evidence or dependencies')
    output.mkdir(parents=True)
    specs = {}
    for variant, values in [('baseline', (100, 102)), ('candidate', (80, 82))]:
        source = 'synthetic-' + variant
        perf = [fixture_run(output / 'evidence' / (variant + '-perf-' + str(i)), 'perf', n, source, kda)
                for i, n in enumerate(values, 1)]
        hpm = fixture_run(output / 'evidence' / (variant + '-hpm'), 'hpm', 0, source, kda)
        # Relative specs are portable before building a report; generated reports retain the
        # normal immutable evidence paths and should be regenerated after moving a bundle.
        specs[variant] = {'label': 'SYNTHETIC ' + variant,
                          'perf': [str(p.relative_to(output)) for p in perf],
                          'hpm': str(hpm.relative_to(output))}
        profile.dump(output / (variant + '-spec.json'), specs[variant])
        profile.publish(output / variant, lambda staging, v=variant: profile.build_report(
            profile.normalize_spec(specs[v], output), {}, staging, kda))
    a, ap = profile.verify_saved_report(output / 'baseline', kda)
    b, bp = profile.verify_saved_report(output / 'candidate', kda)
    profile.publish(output / 'comparison', lambda _: profile.compare_reports(a, b, (ap, bp), kda))
    profile.dump(output / 'batch-config.json', {'cases': [
        {'id': 'synthetic-improvement', 'baseline': {'report': 'baseline'}, 'candidate': {'report': 'candidate'}},
        {'id': 'synthetic-regression', 'baseline': {'report': 'candidate'}, 'candidate': {'report': 'baseline'}},
        {'id': 'unmeasured', 'baseline': {'report': 'baseline'}}]})
    (output / 'README.md').write_text('# Synthetic profiler demo\n\nNo simulator was executed. Values are fixtures, not measured performance.\nUse batch-config.json with xsai-prof batch. Trace is deliberately unavailable.\n')
    return {'status': 'passed', 'synthetic': True, 'output': str(output), 'report': str(output / 'comparison/index.html')}


def add_parser(commands):
    p = commands.add_parser('demo', help='Create portable synthetic perf/HPM fixtures, without simulator dependencies')
    p.add_argument('--output', '-o', type=Path, required=True)


def dispatch(args, kda):
    print(json.dumps(demo(args.output, kda)))
