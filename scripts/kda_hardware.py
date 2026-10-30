"""Source-reviewed hardware contracts applied only to matching recorded RTL builds.

This is an offline explanation layer. It neither changes frozen diagnosis
feedback nor infers unmeasured bandwidth, utilization or cross-clock overlap.
"""
import copy
import json
from pathlib import Path
import sqlite3
import statistics
import tempfile

import kda_profile as profile
from kda_hardware_contract import CONTRACT as BASE_CONTRACT
from kda_hardware_extra import SOURCES, EVENTS, CODING
CONTRACT = copy.deepcopy(BASE_CONTRACT)
CONTRACT["sources"].update(SOURCES)
CONTRACT["events"].update(EVENTS)
CONTRACT["coding"].update(CODING)
CONTRACT["id"] = "xsai-default-matrix-store-fix-20261026/v3"


def receipt_for(report, mode):
    block = report['sections'][mode]
    if block['status'] != 'available':
        return None
    directory = Path(block['run'])
    manifest = profile.read_json(directory / 'manifest.json')
    names = [n for n in manifest['artifacts'] if n.startswith('rtl-config.')]
    if len(names) != 1:
        return None
    path = profile.recorded_artifact(directory, manifest, names[0])
    try:
        receipt = profile.read_json(path)
    except (ValueError, UnicodeError):
        return None
    return receipt if isinstance(receipt, dict) else None


def binding(receipt):
    """Match the reviewed build receipt, never names of mutable checkout paths."""
    if receipt is None:
        return {'status': 'unavailable', 'reason': 'No recorded RTL build receipt'}
    wanted = CONTRACT['build']
    sources = receipt.get('sources', [])
    identities = {(s.get('revision'), s.get('diff_sha256')) for s in sources}
    from kda_clock import reviewed_observer
    matched = ((receipt.get('emulator', {}).get('sha256') == wanted['emulator_sha256'] or reviewed_observer(receipt)) and
               receipt.get('build_log_sha256') == wanted['build_log_sha256'] and
               receipt.get('configuration') == wanted['configuration'] and
               all((s['revision'], s['diff_sha256']) in identities for s in wanted['sources']))
    return {'status': 'matched' if matched else 'unreviewed',
            'contract_id': CONTRACT['id'],
            'reason': ('Recorded emulator, build log, configuration and reviewed source identities match.' if matched else
                       'This RTL build has no matching reviewed contract; names alone do not verify event semantics.'),
            'source_identity_scope': CONTRACT['source_identity_scope'],
            'reference_sources': copy.deepcopy(CONTRACT['sources'])}


def clock_contract(report):
    from kda_clock import anchors
    sync = anchors(report, receipt_for(report, 'trace'))
    if sync['status'] == 'validated':
        return {**sync, 'build_binding': binding(receipt_for(report, 'trace')),
                'definition_status': 'source_reviewed',
                'cpu': 'PerfCCT global_tick_acc recorded directly at each selected CUTE writer callback.',
                'rvv': 'Committed RVV instructions use the CPU lifetime clock; residence is not RVV execution occupancy.',
                'cute': 'Original local Table.log STAMP retained; direct callbacks establish the same-run integer offset.',
                'cross_engine_overlap': 'Display intervals after mapping; no exclusive engine utilization or critical path.'}
    audit = binding(receipt_for(report, 'trace'))
    return {'status': 'unproven', 'synchronization': sync, 'build_binding': audit,
            'definition_status': 'source_reviewed' if audit['status'] == 'matched' else 'reference_only',
            'cpu': 'PerfCCT global_tick_acc: C++ counter incremented by reset-gated Rob negedge DPI calls.',
            'rvv': 'RVV instructions in LifeTimeCommitTrace use the CPU lifetime counter; this is not an independent RVV engine clock.',
            'cute': 'ChiselDB Table.log STAMP: local RegInit(0) counter, positive-edge writer, TaskController clock/reset.',
            'reason': ('Distinct counter/reset/edge mechanisms; no recorded synchronization anchor establishes their offset or mapping. '
                       'The same database and similar numeric ranges are insufficient.'),
            'required_for_alignment': ['A same-run synchronization event recorded in both timestamp domains.',
                'Clock/reset/edge and multi-core behavior validated for the exact emulator build.',
                'A verified affine mapping with repeated anchors and residual checks.'],
            'cross_engine_overlap': None, 'critical_path': None}


def expression(row):
    names = row.get('rtl_event_names') or [None] * 4
    terms = [n if n is not None else 'unresolved:' + str(i)
             for n, i in zip(names, row['event_ids'])]
    a, b, c = row['operators']
    return f'(({terms[0]} {a} {terms[1]}) {c} ({terms[2]} {b} {terms[3]}))'


def event_definition(name, group):
    key = name or ''
    if key.startswith('Slice') and '_l2_cache_' in key:
        key = key[key.index('l2_cache_'):]
    return CONTRACT['events'].get(group + '/' + key)


def hpm_explanation(report, kda):
    section = report['sections']['hpm']
    if section['status'] != 'available':
        return {'status': 'unavailable', 'reason': section.get('reason'), 'counters': []}
    # Reparse the raw log and saved coding rather than trusting cached labels.
    item = profile.load_input(report['spec']['hpm'], kda, 'hpm')
    fresh = profile.hpm_section(item, kda)
    audit = binding(receipt_for(report, 'hpm'))
    measurements = item['manifest'].get('measurements', [])
    denominator = measurements[0]['cycles_per_run'] if len(measurements) == 1 else None
    rows = []
    for counter in fresh['counters']:
        definitions = []
        for event_id, name, signal in zip(counter['event_ids'], counter['rtl_event_names'], counter['rtl_event_signals']):
            definition = event_definition(name, counter['group'])
            coding = CONTRACT['coding'].get(str(counter['group']) + '/' + str(event_id))
            verified = audit['status'] == 'matched' and coding == {'name': name, 'signal': signal}
            definitions.append({'name': name, 'recorded_signal': signal,
                'status': ('source_reviewed' if verified else 'reference_only') if definition else 'unreviewed',
                'definition': copy.deepcopy(definition) if definition else None})
        resolved = counter['encoding_resolved']
        interpreted = resolved and all(d['status'] == 'source_reviewed' for d in definitions)
        issues = []
        if counter.get('upstream_label_matches_rtl') is False:
            issues.append('Printed upstream label differs from the recorded selector event.')
        for d in definitions:
            if d['status'] == 'source_reviewed' and d['definition'].get('caveat'):
                issues.append(d['definition']['caveat'])
        rows.append({**counter, 'selector_expression': expression(counter), 'event_definitions': definitions,
            'semantic_status': 'source_reviewed' if interpreted else 'partial' if resolved else 'unresolved',
            'issues': list(dict.fromkeys(issues)),
            'normalization': {'events_per_call': counter['per_run'] if resolved else None,
                'denominator_cycles_per_call': denominator,
                'denominator_source': 'same HPM run manifest.measurements[0].cycles_per_run' if denominator else None,
                'approx_events_per_instrumented_cycle': counter['per_run'] / denominator if resolved and denominator else None,
                'status': 'approximate' if resolved and denominator else 'unavailable',
                'reason': 'HPM inhibit/CSR read boundaries differ from cycle reads; both per-call values are printed with rounding. This is a diagnostic rate, never utilization or an exclusive stall percentage.'}})
    return {'status': 'available', 'build_binding': audit, 'run': fresh['run'], 'counters': rows,
            'composition': 'Four 10-bit selectors; ((event0 op0 event1) op2 (event2 op1 event3)). Operations are bitwise and/xor/or or width-limited add on RTL event increments, not logical union of elapsed stalls.',
            'scope': 'Instrumented HPM harness window, warmup outside; includes loop, synchronization and collection-boundary overhead. Separate from perf and trace runs.',
            'denominator_policy': 'Never divide HPM values by uninstrumented perf or trace cycles. No exact stall fraction is emitted.',
            'cache_miss_rate': {'status': 'unavailable', 'value': None,
                'reason': 'L1 aggregate includes a write event whose source predicate counts all stores; L2 read access/miss events use different pipeline qualifiers. A conventional cache miss ratio is not established.'}}


def cute_phases(report):
    trace = report['sections']['trace']
    if trace['status'] != 'available':
        return {'status': 'unavailable', 'reason': trace.get('reason'), 'stages': []}
    cute = trace['cute']
    if cute['status'] not in ('available', 'unscoped'):
        return {'status': cute['status'], 'reason': cute.get('reason'), 'stages': []}
    stages = []
    paths = {'CUTELoadEvent': [('allocation_to_issue', 'LoadAllocate', 'LoadIssue'),
                              ('issue_to_finish', 'LoadIssue', 'LoadFinish')],
             'CUTEComputeEvent': [('issue_to_read_a_finish', 'ComputeIssue', 'ComputeReadAFinish'),
                 ('issue_to_read_b_finish', 'ComputeIssue', 'ComputeReadBFinish'),
                 ('issue_to_write_c_finish', 'ComputeIssue', 'ComputeWriteCFinish')],
             'CUTEStoreEvent': [('issue_to_finish', 'StoreIssue', 'StoreFinish')]}
    db = Path(trace['run']) / 'chiseldb.db'
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        for stage in cute['stages']:
            table = stage['table']
            profile.require(table in paths, 'Unknown CUTE stage table')
            stamps = {}
            for seq, site, stamp in conn.execute(f'SELECT SEQID,SITE,STAMP FROM {table}'):
                profile.require((seq, site) not in stamps, 'Duplicate CUTE task site')
                stamps[seq, site] = stamp
            phases = []
            for name, begin, end in paths[table]:
                tasks = []
                for task in stage['tasks']:
                    seq = task['seq_id']
                    a, b = stamps.get((seq, begin)), stamps.get((seq, end))
                    valid = a is not None and b is not None and 0 <= a <= b
                    tasks.append({'seq_id': seq, 'begin_site': begin, 'end_site': end,
                        'begin': a, 'end': b, 'cycles': b - a if valid else None,
                        'status': 'available' if valid else 'unavailable'})
                values = [t['cycles'] for t in tasks if t['cycles'] is not None]
                phases.append({'name': name, 'tasks': tasks,
                    'status': 'available' if len(values) == len(tasks) else 'partial' if values else 'unavailable',
                    'median_cycles': statistics.median(values) if values else None,
                    'missing_tasks': len(tasks) - len(values)})
            stages.append({'table': table, 'role': stage['role'], 'phases': phases})
    return {'status': cute['status'], 'scope': cute['scope'], 'stages': stages,
        'semantics': 'Same-task site timestamp differences only. Read-A/read-B/write-C intervals start at issue and overlap; never add them or label them pure compute time. Allocation-to-issue is controller waiting, not a uniquely identified hazard. Unscoped tasks do not become ROI tasks.'}


def hardware(report, kda):
    hpm = hpm_explanation(report, kda)
    clocks = clock_contract(report)
    from kda_ame_activity import summary as ame_summary
    trace = report['sections']['trace']
    hotspots = []
    if trace['status'] == 'available':
        for f in sorted(trace['functions'], key=lambda f: f['retirement_cycles'], reverse=True)[:8]:
            pcs = sorted((p for p in trace['pcs'] if p['function'] == f['function']),
                         key=lambda p: p['retirement_cycles'], reverse=True)
            hotspots.append({**f, 'top_pcs': pcs[:6], 'pcs_total': len(pcs),
                'source_view': 'Original report source-assembly.html; archived text only when verified.'})
    return {'schema': 'xsai-prof.hardware/v1', 'kind': 'hardware', 'label': report['label'],
        'performance': copy.deepcopy(report['sections']['performance']),
        'clocks': clocks, 'hpm': hpm, 'cute_phases': cute_phases(report), 'ame_activity': ame_summary(report),
        'hotspots': {'status': trace['status'], 'scope': trace.get('window'), 'functions': hotspots,
            'semantics': profile.SEMANTICS['roi'], 'functions_max': 8, 'pcs_per_function_max': 6},
        'observability': [
            {'name': 'CPU/CUTE timestamp alignment', 'status': 'available' if clocks['status'] == 'validated' else 'unavailable', 'reason': clocks['reason']},
            {'name': 'CPU/RVV-to-CUTE critical path', 'status': 'unavailable', 'reason': 'Aligned intervals alone do not record causal dependencies or exclusive engine execution.'},
            {'name': 'DRAM bandwidth / Roofline', 'status': 'unavailable', 'reason': 'No measured memory-controller byte count; instruction counts and modeled op_bytes are insufficient.'},
            {'name': 'RVV / AME occupancy', 'status': 'unavailable', 'reason': 'Instruction residence and task elapsed time do not record execution-resource occupancy.'},
            {'name': 'Exclusive function time / causal stall partition', 'status': 'unavailable', 'reason': 'Retirement attribution and overlapping event predicates do not form a time partition.'}],
        'warnings': copy.deepcopy(report['warnings']),
        'limitations': ['No new simulation or speedup measurement. Hardware events come from separate instrumented runs.',
            'Source contracts apply only to a matching recorded build; unreviewed builds retain raw selector evidence.',
            'A source-reviewed predicate is an observation definition, not a causal bottleneck proof.']}


def markdown(data):
    lines = ['# ' + data['label'] + ' — hardware analysis', '',
        '## Uninstrumented outcome', '',
        '| Workload | Cycles/call | Independent perf repeats |', '| --- | --- | --- |']
    for row in data['performance']['measurements']:
        lines.append('| ' + str(row['op']) + ' | ' + str(row['median_cycles']) + ' | ' + str(row['cycles']) + ' |')
    lines += ['',
        '## Clock contract', '', data['clocks']['reason'], '',
        'Build binding: ' + data['clocks']['build_binding']['status'], '',
        'Definition status: ' + data['clocks']['definition_status'], '',
        data['clocks']['cpu'], '', data['clocks']['rvv'], '', data['clocks']['cute'], '',
        '## HPM semantics', '', data['hpm'].get('scope', 'HPM unavailable'), '',
        data['hpm'].get('denominator_policy', ''), '',
        '| Counter | Printed label | Actual selector expression | Semantic status | Events/call | Approx events/HPM cycle |',
        '| --- | --- | --- | --- | --- | --- |']
    issues = []
    for r in data['hpm']['counters']:
        rate = r['normalization']['approx_events_per_instrumented_cycle']
        lines.append('| ' + ' | '.join(str(v).replace('|', '&#124;') for v in [r['counter'], r['upstream_label'],
            r['selector_expression'], r['semantic_status'], r['normalization']['events_per_call'],
            'unavailable' if rate is None else f'{rate:.6f}']) + ' |')
        if r['issues']:
            issues += ['- Counter ' + str(r['counter']) + ': ' + x for x in r['issues']]
    lines += ['', *issues, '', 'Detailed predicates, source line excerpts, signal paths and normalization caveats: [hardware.json](hardware.json).', '',
        '## Event predicates', '']
    seen = set()
    for row in data['hpm']['counters']:
        for event in row['event_definitions']:
            key = (row['group'], event['name'], event['recorded_signal'])
            if key in seen or event['definition'] is None:
                continue
            seen.add(key)
            d = event['definition']
            lines += ['### ' + str(event['name']) + ' — ' + event['status'], '',
                'Signal: ' + str(event['recorded_signal']), '', 'Unit: ' + d['unit'], '',
                '```', d['predicate'], '```', '', 'Source references: ' + ', '.join(d['source_refs']), '']
    lines += [
        '## CUTE task phases', '', data['cute_phases'].get('semantics', data['cute_phases'].get('reason', 'Unavailable')), '',
        '| Stage/role | Phase | Median cycles | Missing tasks |', '| --- | --- | --- | --- |']
    for stage in data['cute_phases']['stages']:
        for p in stage['phases']:
            lines.append(f'| {stage["table"]}/{stage["role"]} | {p["name"]} | {p["median_cycles"]} | {p["missing_tasks"]} |')
    lines += ['', '## ROI hotspots → source', '', data['hotspots']['semantics'], '']
    for f in data['hotspots']['functions']:
        lines.append('- ' + f['function'] + ': ' + str(f['retirement_cycles']) + ' attributed cycles; ' +
            ', '.join(str(p['pc']) + ' ' + p['instruction'] for p in f['top_pcs']))
    lines += ['', '## Evidence gaps', '']
    lines += ['- ' + x['name'] + ': ' + x['reason'] for x in data['observability']]
    lines += ['', *['- ' + x for x in data['limitations'] + data['warnings']]]
    lines += ['', '## Reviewed source excerpts', '', 'These excerpts describe the pinned reference build. Check build binding before applying them to a run.', '']
    for key, source in CONTRACT['sources'].items():
        lines += ['### ' + key, '', source['file'] + ' (SHA256 ' + source['sha256'] + ')', '', '```']
        lines += [str(line['number']) + ': ' + line['text'] for line in source['lines']]
        lines += ['```', '']
    return '\n'.join(lines) + '\n'


def add_parser(commands):
    p = commands.add_parser('hardware', help='Explain reviewed RTL events, clock contracts, CUTE phases and evidence gaps')
    p.add_argument('report', type=Path)
    p.add_argument('--output', '-o', type=Path, required=True)


def dispatch(args, kda):
    report, directory = profile.verify_saved_report(args.report, kda)
    out = args.output.resolve()
    profile.require(not out.is_relative_to(directory), 'Hardware output must not modify the input report')
    profile.require(not out.exists(), 'Hardware output already exists')
    profile.require(not out.is_relative_to(profile.ROOT / 'dependencies'), 'Output must not modify dependencies')
    profile.require(not any((p / 'manifest.json').exists() for p in (out, *out.parents)), 'Output must not modify runs')
    # Preserve the original report. Revalidate trace/ELF and recompute sites in a
    # temporary output before publishing a derivative explanation.
    with tempfile.TemporaryDirectory(prefix='xsai-hardware-check-') as temporary:
        if report['sections']['trace']['status'] == 'available':
            item = profile.load_input(report['spec']['trace'], kda, 'trace')
            report['sections']['trace'] = profile.trace_section(item,
                {**report['options'], 'cute': report['spec'].get('cute')}, Path(temporary))
        data = hardware(report, kda)
    data['provenance'] = {'report': str(directory), 'report_sha256': profile.digest(directory / 'report.json'),
        'contract_sha256': profile.digest(Path(__file__).with_name('kda_hardware_contract.py')),
        'contract_extensions_sha256': profile.digest(Path(__file__).with_name('kda_hardware_extra.py')),
        'clock_contract_sha256': profile.digest(Path(__file__).with_name('kda_clock.py')),
        'producer_sha256': profile.digest(Path(__file__)),
        'input_manifests': copy.deepcopy(report['inputs'])}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.hardware-', dir=out.parent) as temporary:
        staging = Path(temporary) / 'result'
        staging.mkdir()
        profile.dump(staging / 'hardware.json', data)
        md = markdown(data)
        (staging / 'hardware.md').write_text(md)
        (staging / 'index.html').write_text(profile.html_document(md, data['label']))
        profile.dump(staging / 'checksums.json', {'files': {p.name: profile.digest(p) for p in staging.iterdir()}})
        staging.rename(out)
    print(json.dumps({'status': 'passed', 'hardware': str(out / 'hardware.json'), 'html': str(out / 'index.html'),
        'hpm_build_binding': data['hpm'].get('build_binding', {}).get('status', 'unavailable')}))
