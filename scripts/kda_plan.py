"""Shared metric selection and a read-only preview of native acquisition work."""
from pathlib import Path

import kda_catalog as catalog
import kda_profile as p


def names(values):
    if isinstance(values, str):
        values = [values]
    return [name.strip() for value in values or [] for name in value.split(',') if name.strip()]


def selection(sections=None, preset=None, metrics=None):
    requested = names(metrics)
    p.require(metrics is None or requested, 'Metrics must be nonempty; use query metrics')
    p.require(len(requested) == len(set(requested)), 'Duplicate metrics requested')
    registry = {row[0]: row[1] for row in catalog.METRICS}
    unknown = sorted(set(requested) - registry.keys())
    p.require(not unknown, 'Unsupported metrics: ' + ', '.join(unknown) + '; use xsai-prof query metrics. No values are inferred.')
    p.require(not (sections is not None and preset is not None), 'Choose --section/--sections or --set, not both')
    if sections is not None or preset is not None:
        result = catalog.selection(names(sections) if sections is not None else None, preset)
    elif requested:
        result = catalog.selection(list(dict.fromkeys(registry[name] for name in requested)))
    else:
        result = catalog.selection()
    # Explicit metrics extend the selected set rather than silently losing a
    # requested metric. Shared stages are collected once, not once per metric.
    for name in requested:
        if registry[name] not in result['sections']:
            result['sections'].append(registry[name])
    result['diagnostics'] = [mode for mode in ('hpm', 'trace')
        if any(mode in catalog.SECTIONS[section]['modes'] for section in result['sections'])]
    result['metrics'] = requested
    return result


def requirements(config):
    from kda_observer import reviewed, cpu_reviewed, ame_read_reviewed
    receipt_path = Path(config['rtl_config'])
    receipt = p.read_json(receipt_path) if receipt_path.is_file() else {}
    flags = {'ame': reviewed(receipt), 'cpu': cpu_reviewed(receipt), 'returns': ame_read_reviewed(receipt)}
    rows = []
    selected = set(config.get('sections', []))
    requested = config.get('metrics') or [name for name, section, *_ in catalog.METRICS if section in selected]
    for name in requested:
        row = next(row for row in catalog.METRICS if row[0] == name)
        status, reason = 'requires_collection', 'Value and numerical availability are established only by recorded evidence.'
        capability = ('returns' if name in {'ame_read_payload_bytes', 'ame_read_service_cycles',
            'ame_read_outstanding_max', 'ame_read_return_backpressure_cycles'} else
            'cpu' if name.startswith(('cpu_', 'rvv_read_')) else 'ame')
        if row[1] == 'memory' and not flags[capability]:
            status, reason = 'unsupported_target', 'This metric requires the exact reviewed ' + capability + ' memory observer.'
        rows.append({'metric': name, 'section': row[1], 'status': status, 'reason': reason,
                     'modes': ['perf', *catalog.SECTIONS[row[1]]['modes']]})
    if config.get('memory_trace') and not flags['ame']:
        rows.append({'metric': 'memory_trace', 'section': 'memory', 'status': 'unsupported_target',
                     'reason': 'Memory capture requires an exact reviewed observer.', 'modes': ['trace']})
    return rows


def preview(config, output, kda, resume=False):
    import kda_collect as collect
    from kda_setup import target_support
    output = Path(output).resolve()
    checks = []
    try:
        identity = collect.preflight(config, kda)
        checks.append({'status': 'passed', 'name': 'external_dependencies', 'identity': identity})
    except (OSError, RuntimeError, ValueError, KeyError) as exc:
        checks.append({'status': 'blocked', 'name': 'external_dependencies', 'reason': str(exc)})
    try:
        collect.validate_destination(config, output, resume)
        checks.append({'status': 'passed', 'name': 'destination'})
    except (OSError, RuntimeError, ValueError) as exc:
        checks.append({'status': 'blocked', 'name': 'destination', 'reason': str(exc)})
    rows = requirements(config)
    if any(row['status'] == 'unsupported_target' for row in rows):
        checks.append({'status': 'blocked', 'name': 'metric_capabilities',
                       'reason': 'Some requested metrics are unsupported by this recorded target.'})
    stage_modes = [('perf-' + str(i+1), 'perf') for i in range(config['perf_repeats'])]
    stage_modes += [(mode, mode) for mode in config['diagnostics']]
    stages = []
    for name, mode in stage_modes:
        stages.append({'name': name, 'mode': mode,
            'steps': ['build correctness image', 'run RTL correctness gate',
                      'build ' + mode + ' image', 'run RTL ' + mode],
            'emulator_invocations_on_fresh_attempt': 2,
            'command': collect.command_for(config, output, mode, output/'runs'/name/'attempt-1')})
    receipt = p.read_json(config['rtl_config']) if Path(config['rtl_config']).is_file() else {}
    return {'schema': 'xsai-prof.plan/v1', 'status': 'blocked' if any(c['status'] == 'blocked' for c in checks) else 'ready',
        'dry_run': True, 'output': str(output), 'resume': resume, 'config': config,
        'target': target_support(receipt), 'checks': checks, 'metric_requirements': rows,
        'stages': stages, 'cost': {'fresh_adapter_stages': len(stages),
            'fresh_emulator_invocations': 2*len(stages), 'wall_seconds_estimate': None,
            'trace_requested': 'trace' in config['diagnostics'],
            'notes': ['Each adapter stage has its own correctness gate and measurement execution.',
                'Repeated harness calls inside an image are distinct from emulator invocations.',
                'Native HPM/trace stages may record additional metrics sharing those stages.',
                'Resume revalidates frozen artifacts and may reuse passed stages; counts above describe a fresh run.',
                'No build, snapshot, collection lock or emulator was started by dry-run.']}}
