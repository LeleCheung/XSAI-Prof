"""Conservative, visibility-scoped interpretations of verified profile evidence."""
import copy
import json
from pathlib import Path
import re
import tempfile

import kda_profile as profile

SCHEMA = 'xsai-kda.diagnosis/v1'
LEVELS = ('cycles', 'hpm', 'trace')
LIMITS = [
    'Retirement gaps are attribution, not exclusive execution time or a stall cause.',
    'Dynamic instruction counts are not measured cache/DRAM bytes.',
    'HPM events and CUTE intervals can overlap; do not add them into a time partition.',
    'CPU/CUTE clock alignment and a cross-engine critical path are not established.',
    'Hypotheses are candidate experiments, not causal bottleneck proofs or guaranteed gains.',
]


def evidence_view(report, level):
    """An allowlist, never subtractive redaction of an unrestricted report."""
    profile.require(level in LEVELS, 'Unknown feedback level')
    measurements = report['sections']['performance']['measurements']
    view = {'performance': {'repeat_count': report['sections']['performance']['repeat_count'],
        'measurements': [{k: copy.deepcopy(row[k]) for k in
            ('op', 'unit', 'cycles', 'median_cycles', 'min_cycles', 'max_cycles')}
            for row in measurements]}}
    if level in ('hpm', 'trace'):
        hpm = report['sections']['hpm']
        view['hpm'] = {'status': hpm['status']}
        if hpm['status'] == 'available':
            view['hpm']['counters'] = [{k: copy.deepcopy(r.get(k)) for k in
                ('counter', 'config', 'rtl_event_names', 'operators', 'per_run', 'encoding_resolved')}
                for r in hpm['counters']]
    if level == 'trace':
        trace = report['sections']['trace']
        view['trace'] = {'status': trace['status']}
        if trace['status'] == 'available':
            functions = sorted(trace['functions'], key=lambda r: r['retirement_cycles'], reverse=True)
            names = {f['function'] for f in functions[:12]}
            view['trace'].update(
                window=copy.deepcopy(trace['window']), functions=copy.deepcopy(functions[:12]),
                mnemonics={k: copy.deepcopy(v) for k, v in trace['mnemonics'].items() if k in names},
                cute=copy.deepcopy(trace['cute']),
                truncation={'functions_total': len(functions), 'functions_shown': min(12, len(functions)),
                            'pcs_per_function_max': 8, 'ordering': 'retirement-gap attribution'},
                pcs={name: [{k: copy.deepcopy(p.get(k)) for k in
                    ('pc', 'instruction', 'instructions', 'retirement_cycles')}
                    for p in sorted((p for p in trace['pcs'] if p['function'] == name),
                                    key=lambda p: p['retirement_cycles'], reverse=True)[:8]]
                     for name in sorted(names)})
    return view


def diagnose(report, level='trace'):
    profile.require(report.get('schema') == profile.SCHEMA and report.get('kind') == 'profile',
                    'Diagnosis needs a profile report, not a comparison')
    view = evidence_view(report, level)
    facts, hypotheses, missing = [], [], []

    def fact(identifier, statement, pointers, values):
        facts.append({'id': identifier, 'statement': statement,
                      'evidence': pointers, 'values': values, 'scope': 'recorded workload/configuration'})

    def hypothesis(identifier, statement, evidence, experiment, predictions, falsifier, missing_items):
        hypotheses.append({'id': identifier, 'statement': statement, 'status': 'untested',
            'confidence': 'hypothesis_only', 'evidence': evidence,
            'validation_experiment': experiment, 'predicted_observations': predictions,
            'falsifying_observation': falsifier, 'missing_evidence': missing_items})

    perf = view['performance']
    fact('measured_cycles', 'Uninstrumented cycles are the performance outcome.',
         ['/performance'], perf)
    if perf['repeat_count'] < 2:
        missing.append('Independent repeat performance measurement.')
    if any(r['max_cycles'] != r['min_cycles'] for r in perf['measurements']):
        fact('repeat_variation', 'Recorded independent perf repeats differ.',
             ['/performance/measurements'], perf['measurements'])
    if level == 'cycles':
        missing += ['HPM hidden at cycles visibility.', 'Trace hidden at cycles visibility.',
                    'Cycles alone do not identify a bottleneck.']
    else:
        hpm = view['hpm']
        if hpm['status'] != 'available':
            missing.append('Resolved HPM evidence unavailable.')
        else:
            resolved = [r for r in hpm['counters'] if r['encoding_resolved']]
            unresolved = [r['counter'] for r in hpm['counters'] if not r['encoding_resolved']]
            if unresolved:
                missing.append('Unresolved HPM selectors: ' + str(unresolved))
            fact('resolved_hpm', 'Only resolved selectors have verified RTL event names.',
                 ['/hpm/counters'], resolved)
            stalls = [r for r in resolved if any('stall' in str(n).lower() for n in r['rtl_event_names'] or [])]
            if stalls:
                fact('stall_counters', 'Resolved stall-related counts exist; they overlap and are not a time partition.',
                     ['/hpm/counters'], stalls)
                hypothesis('stall_disambiguation',
                    'Some counted waiting may respond to dependency scheduling, memory behavior, or accelerator completion.',
                    ['stall_counters'],
                    'Change one scheduling/reuse property, retain ordering and numerical contracts, then collect comparable perf and resolved HPM.',
                    ['A useful change reduces uninstrumented cycles; the selected event change should agree with its proposed mechanism.'],
                    'A lower stall count without a cycle gain does not establish an optimization.',
                    ['Per-instruction dependency/resource attribution; isolated intervention.'])
        if level == 'hpm':
            missing.append('Trace hidden at HPM visibility; no source-local cause established.')
    if level == 'trace':
        trace = view['trace']
        if trace['status'] != 'available':
            missing.append('Paired trace unavailable; no source-local diagnosis.')
        else:
            functions = trace['functions']
            fact('roi_hotspots', 'Functions ranked by retirement-gap attribution, not exclusive runtime.',
                 ['/trace/functions', '/trace/window'], functions[:5])
            for function in functions:
                name = function['function']
                counts = trace['mnemonics'].get(name, {})
                if re.search(r'(^|_)(memset|bzero|memcpy|memmove)($|_)', name):
                    identifier = 'buffer_work_' + name
                    fact(identifier, 'Buffer initialization/copy is present in the measured ROI.',
                         ['/trace/functions', '/trace/mnemonics'], function)
                    hypothesis('inspect_' + name,
                        'A portion of this buffer work may be avoidable if later writes cover every byte read.',
                        [identifier],
                        'Inspect every consumer and overwrite/padding range. Remove only proven redundant writes; test poisoned workspace, tails, partial tiles and immediate input rewrites.',
                        ['Relevant initialization/copy instructions decrease.',
                         'Untouched compute instruction counts and numerical results remain stable.',
                         'Independent perf determines whether reduced work helps.'],
                        'Poison/tail tests fail, required bytes remain uninitialized, or cycles do not improve.',
                        ['Overwrite and read-before-write proof from source; adversarial correctness gates.'])
                loads = sum(v for k, v in counts.items() if re.match(r'vl[eus].*', k))
                conversions = sum(v for k, v in counts.items() if re.match(r'v(sext|zext|fwcvt|fcvt)', k))
                fmas = sum(v for k, v in counts.items() if k.startswith(('vfmacc', 'vfmadd', 'vfnmacc')))
                row_match = re.search(r'(?:q|q_len|rows)\s*=\s*(\d+)',
                    ' '.join(r['op'] for r in perf['measurements']))
                # Loads + conversion + FMA alone also match exponent polynomials.
                # Limit this domain rule to multi-row update kernels; source must
                # still prove that the vectors consumed by those rows are equal.
                if (loads and conversions and fmas and 'update' in name.lower()
                        and row_match and int(row_match.group(1)) > 1):
                    identifier = 'converted_vector_work_' + name
                    fact(identifier, 'This function emits vector loads, conversions and fused arithmetic.',
                         ['/trace/mnemonics/' + name],
                         {'loads': loads, 'extensions_or_conversions': conversions, 'fused_arithmetic': fmas})
                    hypothesis('reuse_' + name,
                        'If independent output rows consume identical input vectors, sharing their loaded/converted value may reduce repeated work.',
                        [identifier],
                        'Verify input identity and alias contracts in source; share conversion across a small row block, preserving odd-row/tail fallback and accumulator order.',
                        ['Input load/extension/conversion counts fall for reused rows.',
                         'Arithmetic count for the original output work remains unchanged.',
                         'Check spills and loop overhead; fewer loads alone need not improve cycles.'],
                        'Inputs differ, new spills/loops offset reuse, numerical gates fail, or independent cycles do not improve.',
                        ['Trace has no memory-address equality proof; source/dataflow validation required.'])
                spills = {k: v for k, v in counts.items() if re.match(r'v(s[1248]r|l[1248]re)', k)}
                if spills:
                    identifier = 'whole_register_memory_' + name
                    fact(identifier, 'Whole-register vector memory instructions are emitted; verify stack addresses before labeling spills.',
                         ['/trace/mnemonics/' + name], spills)
                    hypothesis('register_pressure_' + name,
                        'Stack spill traffic may be reduced by lowering live vector state, but VL and dependency tradeoffs can erase the gain.',
                        [identifier],
                        'Confirm stack operands in ELF. Change one live range or accumulator schedule; retain approximation/tolerance and measure loop, spill and arithmetic counts.',
                        ['Confirmed stack traffic decreases without excessive extra vector iterations or a longer dependency chain.'],
                        'Cycles increase despite reduced whole-register memory instructions.',
                        ['Stack operand confirmation; register liveness and dependent instruction timing.'])
            cute = trace['cute']
            if cute['status'] == 'available':
                fact('cute_intervals', 'Explicitly scoped accelerator stage durations are available; overlapping intervals must not be summed.',
                     ['/trace/cute'], cute)
            else:
                missing.append('Scoped CUTE stage intervals unavailable.')
            missing += ['Critical-path/resource-stall attribution has not been collected.',
                        'Sustained bandwidth/compute ceilings have not been calibrated.']
    return {'schema': SCHEMA, 'kind': 'diagnosis', 'visibility': level,
            'evidence_view': view, 'observations': facts, 'hypotheses': hypotheses,
            'missing_evidence': missing, 'limitations': LIMITS,
            'conclusion': 'Hypotheses require intervention; no causal bottleneck is asserted.',
            'producer': {'diagnoser_sha256': profile.digest(Path(__file__))}}


def markdown(result):
    lines = ['# XSAI evidence-driven diagnosis', '', 'Visibility: `' + result['visibility'] + '`.', '',
             result['conclusion'], '', '## Observations', '']
    for f in result['observations']:
        lines += ['- **' + f['id'] + '**: ' + f['statement'],
                  '  Evidence: ' + ', '.join('`' + p + '`' for p in f['evidence'])]
    lines += ['', '## Testable hypotheses', '']
    for h in result['hypotheses']:
        lines += ['### ' + h['id'], '', h['statement'], '',
                  '**Validation:** ' + h['validation_experiment'], '',
                  '**Predictions:** ' + ' '.join(h['predicted_observations']), '',
                  '**Falsifier:** ' + h['falsifying_observation'], '',
                  '**Missing:** ' + ' '.join(h['missing_evidence']), '']
    lines += ['## Missing evidence', ''] + ['- ' + x for x in result['missing_evidence']]
    lines += ['', '## Interpretation limits', ''] + ['- ' + x for x in result['limitations']]
    lines += ['', '## Evidence values', '', '```json',
              json.dumps(result['evidence_view'], ensure_ascii=False, indent=2), '```', '']
    return '\n'.join(lines)


def publish(report_path, output, level, kda):
    report, directory = profile.verify_saved_report(report_path, kda)
    output = Path(output).resolve()
    profile.require(not output.exists(), 'Diagnosis output already exists')
    profile.require(not output.is_relative_to(profile.ROOT / 'dependencies'), 'Output cannot modify dependencies')
    profile.require(not any((p / 'manifest.json').is_file() for p in (output, *output.parents)),
                    'Output cannot be inside a run')
    result = diagnose(report, level)
    result['input'] = {'report': str(directory / 'report.json'),
                       'report_sha256': profile.digest(directory / 'report.json'),
                       'checksums_sha256': profile.digest(directory / 'checksums.json')}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.diagnosis-', dir=output.parent) as tmp:
        staging = Path(tmp) / 'diagnosis'
        staging.mkdir()
        profile.dump(staging / 'diagnosis.json', result)
        md = markdown(result)
        (staging / 'diagnosis.md').write_text(md)
        (staging / 'index.html').write_text(profile.html_document(md, 'XSAI diagnosis'))
        profile.dump(staging / 'checksums.json', {'schema': 'xsai-kda.diagnosis-files/v1',
            'files': {p.name: profile.digest(p) for p in sorted(staging.iterdir()) if p.is_file()}})
        staging.rename(output)
    return {'status': 'passed', 'diagnosis': str(output / 'diagnosis.json'),
            'html': str(output / 'index.html'), 'visibility': level,
            'hypotheses': len(result['hypotheses'])}


def add_parser(commands):
    parser = commands.add_parser('diagnose', help='Separate verified observations from testable bottleneck hypotheses')
    parser.add_argument('report', type=Path)
    parser.add_argument('--level', choices=LEVELS, default='trace')
    parser.add_argument('--output', '-o', type=Path, required=True)


def dispatch(args, kda):
    print(json.dumps(publish(args.report, args.output, args.level, kda), ensure_ascii=False, indent=2))
