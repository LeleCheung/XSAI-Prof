"""Measured reference throughput models with explicit workload assumptions.

These are not hardware peaks, measured DRAM traffic, or efficiency ceilings.
"""
import json
import math
from pathlib import Path
import statistics

import kda_profile as p

UNITS = ('fp32_lane_flop', 'int8_mac', 'int8_to_fp32_element', 'algorithmic_byte')


def positive(value):
    return type(value) in (int, float) and math.isfinite(value) and value > 0


def model(report, calibration, base, kda):
    p.require(isinstance(calibration, dict) and set(calibration) == {'work', 'references', 'assumptions'},
              'Model config needs work, references and assumptions')
    p.require(isinstance(calibration['work'], dict) and calibration['work'] and
              set(calibration['work']) <= set(UNITS) and all(positive(v) for v in calibration['work'].values()), 'Work needs positive finite counts with known precision-specific units')
    p.require(isinstance(calibration['assumptions'], list) and calibration['assumptions'] and
              all(isinstance(v, str) and v for v in calibration['assumptions']), 'Explicit workload/cache/reuse assumptions required')
    p.require(isinstance(calibration['references'], list) and calibration['references'], 'At least one measured reference required')
    p.require(len(report['sections']['performance']['measurements']) == 1, 'Reference model requires one target shape')
    rows, identities = [], []
    seen = set()
    for entry in calibration['references']:
        p.require(isinstance(entry, dict) and set(entry) == {'report', 'unit', 'work'} and entry['unit'] in calibration['work'] and positive(entry['work']), 'Reference needs report, matching unit and positive work')
        unit = entry['unit']
        p.require(unit not in seen, 'One reference per work unit; no silent pooling')
        seen.add(unit)
        reference, directory = p.verify_saved_report(base / entry['report'], kda)
        p.require(reference['validation'].get('source_archives') == 'verified', 'Reference calibration requires archived source evidence')
        for field in ('rtl', 'arch', 'toolchain', 'compiler', 'runtime_source', 'rvv_enable'):
            p.require(reference['identity'].get(field) == report['identity'].get(field), 'Reference/target hardware or compiler differs: ' + field)
        measurements = reference['sections']['performance']['measurements']
        p.require(len(measurements) == 1 and len(measurements[0]['cycles']) >= 2, 'Calibration requires one shape and at least two independent perf repeats')
        cycles = measurements[0]['cycles']
        p.require(all(positive(c) for c in cycles), 'Invalid calibration cycles')
        rate = entry['work'] / statistics.median(cycles)
        reference_cycles = calibration['work'][unit] / rate
        rows.append({'unit': unit, 'target_declared_work': calibration['work'][unit], 'reference_declared_work': entry['work'],
                     'reference_cycles': cycles, 'observed_reference_work_per_cycle': rate,
                     'equivalent_reference_cycles': reference_cycles, 'report': str(directory)})
        identities.append({'report_sha256': p.digest(directory / 'report.json'), 'inputs': reference['inputs']})
    p.require(seen == set(calibration['work']), 'Every declared target work unit needs its own reference')
    target_cycles = report['sections']['performance']['measurements'][0]['median_cycles']
    return {'schema': 'xsai-prof.reference-model/v1', 'kind': 'reference-model', 'label': report['label'],
            'rows': rows, 'target_perf_cycles': target_cycles,
            'max_of_equivalent_reference_cycles': max(r['equivalent_reference_cycles'] for r in rows),
            'sum_of_equivalent_reference_cycles': sum(r['equivalent_reference_cycles'] for r in rows),
            'measured_hardware_efficiency': None, 'hardware_peak': None, 'measured_dram_bandwidth': None,
            'assumptions': calibration['assumptions'], 'provenance': identities,
            'target_inputs': report['inputs'],
            'limitations': ['Declared work is an explicit caller/model contract; the tool does not infer algorithm counts from instruction names.',
                'Measured references include loop, setup-in-call and synchronization costs; neither max nor sum is a proven latency bound.',
                'Precision-specific work units stay separate. Cache-hot algorithmic bytes are not memory-controller traffic.',
                'A target can exceed the reference throughput; no hardware utilization, upper bound or optimization speedup follows from this model.']}


def add_parser(commands):
    a = commands.add_parser('model', help='Calibrate explicit work against verified repeated reference kernels; no hardware-peak claim')
    a.add_argument('report', type=Path)
    a.add_argument('--config', type=Path, required=True)
    a.add_argument('--output', '-o', type=Path, required=True)


def dispatch(args, kda):
    report, directory = p.verify_saved_report(args.report, kda)
    result = model(report, p.read_json(args.config), args.config.resolve().parent, kda)
    out = args.output.resolve()
    p.require(not out.exists() and not out.is_relative_to(directory) and not out.is_relative_to(p.ROOT / 'dependencies') and not any((x / 'manifest.json').exists() for x in (out, *out.parents)), 'Model output must be a new directory outside evidence/dependencies')
    out.mkdir(parents=True)
    p.dump(out / 'model.json', result)
    import html
    (out / 'index.html').write_text('<!doctype html><meta charset="utf-8"><title>XSAI reference model</title><h1>Measured reference model</h1><pre>' + html.escape(json.dumps(result, indent=2)) + '</pre>')
    p.dump(out / 'checksums.json', {'files': {n: p.digest(out / n) for n in ('model.json', 'index.html')}})
    print(json.dumps({'status': 'passed', 'model': str(out / 'model.json')}))
