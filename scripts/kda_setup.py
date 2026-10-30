"""Minimal collection setup and explicit supported-target discovery."""
import json
from pathlib import Path

import kda_profile as p


def target_support(receipt):
    from kda_observer import reviewed, cpu_reviewed, ame_read_reviewed
    matched = reviewed(receipt)
    return {
        'status': 'reviewed' if matched else 'unreviewed',
        'target': 'XSAI DefaultMatrixConfig, single core, DRAMsim3' if matched else None,
        'emulator_sha256': receipt.get('emulator', {}).get('sha256'),
        'configuration': receipt.get('configuration'),
        'coverage': {'ame_requests': matched, 'ame_read_returns': ame_read_reviewed(receipt),
                     'ordinary_cpu_rvv_requests': cpu_reviewed(receipt),
                     'dram_bytes': False, 'architectural_load_latency': False},
        'reason': 'Exact reviewed receipt and observer identities match; live collection still requires external dependencies.' if matched else
                  'This receipt is outside the reviewed observer set. Generic collection can work, but reviewed memory semantics are unavailable.',
    }


def template(args):
    paths = {name: str(getattr(args, name).absolute()) for name in
             ('blas', 'noop_home', 'rtl_config', 'xsai_env')}
    config = {**paths, 'label': args.label or args.kernel + ' profiling',
        'kernel': args.kernel, 'case': args.case, 'backend': args.backend,
        'rvv_enable': 'yes', 'arch': 'riscv64-xs', 'toolchain': 'LLVM',
        'perf_repeats': 2, 'max_runs': 1, 'diagnostics': ['trace'] if args.memory else [],
        'environment': {'AM_HOME': str(args.am_home.absolute()), 'LLVM_HOME': str(args.llvm_home.absolute())},
        'objdump': str(args.llvm_home.absolute() / 'bin/llvm-objdump'),
        'addr2line': str(args.llvm_home.absolute() / 'bin/llvm-addr2line'),
        'readelf': 'readelf', 'objdump_mattr': '+matrix-xuantie-0.6'}
    # Executable names are resolved now; all config path fields are file-relative.
    import shutil
    config['readelf'] = shutil.which('readelf') or '/usr/bin/readelf'
    if args.memory:
        config.update(memory_trace=True, capture_scope='invocation',
                      ranges={'invocations': [1, 1], 'stages': []})
    return config


def add_parser(commands):
    init = commands.add_parser('init', help='Write a minimal collection config for explicit external paths')
    init.add_argument('--output', '-o', type=Path, required=True)
    for name in ('blas', 'noop-home', 'rtl-config', 'xsai-env', 'am-home', 'llvm-home'):
        init.add_argument('--' + name, type=Path, required=True)
    init.add_argument('--kernel', default='softmax', help='Upstream operator name; default softmax')
    init.add_argument('--case', type=int, default=1, help='Upstream case index; softmax case 1 is nonempty n256 FP32')
    init.add_argument('--backend', choices=['generic', 'scalar', 'rvv', 'ame'], default='rvv')
    init.add_argument('--memory', action='store_true', help='Request scoped trace on an exact reviewed memory observer')
    init.add_argument('--label')


def dispatch(args, kda):
    p.require(args.case >= 0, 'case must be non-negative')
    p.require(not args.output.exists(), 'Config output already exists; choose a new file')
    p.require(not args.output.resolve().is_relative_to(Path(args.blas).resolve()) and
              not args.output.resolve().is_relative_to(Path(args.noop_home).resolve()),
              'Write config outside BLAS and RTL build directories')
    config = template(args)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation prevents accidental overwrite even during concurrent setup.
    with args.output.open('x') as stream:
        stream.write(json.dumps(config, indent=2) + '\n')
    print(json.dumps({'status': 'created', 'config': str(args.output.resolve()),
        'dependencies_checked': False,
        'next': ['xsai-prof doctor --config ' + str(args.output),
                 'xsai-prof collect --config ' + str(args.output) + ' --output NEW_BUNDLE'],
        'note': 'Case indices and shapes belong to the selected BLAS test harness; inspect the recorded shape before comparing.'}))
