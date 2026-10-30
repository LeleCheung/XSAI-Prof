"""Evidence-checked instruction residence and CUTE timelines in separate clocks."""
from collections import Counter
import csv
import html
import json
from pathlib import Path
import sqlite3
import tempfile

import kda_profile as profile

LIMITATIONS = [
    'CPU bars are fetch-to-commit residence for committed instructions, not exclusive execution or functional-unit occupancy.',
    'ROI selects instructions by dynamic SN between markers; fetch may precede the ROI begin commit timestamp.',
    'CUTE uses the explicitly recorded task scope, independently of the CPU ROI; no cross-engine clock alignment is claimed.',
    'All coordinates are recorded timestamp cycles in their own clock domain, not seconds; overlapping intervals are not additive.',
    'CPU tracks classify emitted instruction mnemonics, not hardware pipeline occupancy; display sublanes are visual layout only.',
]


def timeline(report, function=None, max_instructions=10000, cpu_range=None, cute_stage=None, cute_task_range=None):
    profile.require(type(max_instructions) is int and 0 < max_instructions <= 100000,
                    'max-instructions must be in 1..100000')
    section = report['sections']['trace']
    profile.require(section['status'] == 'available', 'Timeline needs verified trace evidence')
    if cpu_range is not None:
        profile.require(len(cpu_range) == 2 and cpu_range[0] >= 0 and cpu_range[1] >= cpu_range[0],
                        'CPU cycle range must satisfy 0 <= begin <= end')
    profile.require(cute_stage in (None, 'load', 'compute', 'store'), 'Unknown CUTE stage')
    if cute_task_range is not None:
        profile.require(len(cute_task_range) == 2 and cute_task_range[0] >= 0 and cute_task_range[1] >= cute_task_range[0],
                        'CUTE task range must satisfy 0 <= begin <= end')
    directory = Path(section['run'])
    window = section['window']
    pcmap = {int(p['pc'], 16): p for p in section['pcs']}
    allowed = {pc for pc, p in pcmap.items() if function is None or function in p['function']}
    events = []
    missing = Counter()
    total = matched = 0
    db = directory / 'chiseldb.db'
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        columns = {r[1] for r in connection.execute('PRAGMA table_info(LifeTimeCommitTrace)')}
        profile.require({'SN', 'PC', 'AtCommit'} <= columns, 'Missing CPU timeline columns')
        def optional(name):
            return f'MIN(CASE WHEN {name} > 0 THEN {name} END)' if name in columns else 'NULL'
        query = f'''SELECT SN,PC,{optional('AtFetch')},{optional('AtIssueQue')},
                    {optional('AtFU')},MAX(AtCommit),COUNT(*)
                    FROM LifeTimeCommitTrace WHERE AtCommit>0 AND SN>? AND SN<?
                    GROUP BY SN,PC ORDER BY SN,PC'''
        for sn, pc, fetched, issued, fu, committed, uops in connection.execute(query, (window['begin_sn'], window['end_sn'])):
            total += 1
            profile.require(pc in pcmap, 'Timeline PC absent from verified ROI')
            if pc not in allowed or (cpu_range and not cpu_range[0] <= committed <= cpu_range[1]):
                continue
            matched += 1
            if matched > max_instructions:
                continue
            p = pcmap[pc]
            valid = fetched is not None and 0 < fetched <= committed
            if not valid:
                missing['fetch_to_commit'] += 1
            event = {'domain': 'cpu', 'track': 'RVV instructions' if p['instruction'].startswith('v') else 'Scalar / other instructions',
                     'kind': 'residence' if valid else 'commit', 'name': p['instruction'],
                     'begin': fetched if valid else committed, 'end': committed,
                     'sn': sn, 'pc': p['pc'], 'function': p['function'], 'source': p['source'], 'uops': uops,
                     'stamps': {'fetch': fetched, 'issue_queue': issued, 'functional_unit': fu, 'commit': committed}}
            for key, value in [('issue_queue', issued), ('functional_unit', fu)]:
                if value is None or value > committed or (valid and value < fetched):
                    event['stamps'][key] = None
                    missing[key] += 1
            events.append(event)
    cpu_count = len(events)
    cute = section['cute']
    if cute['status'] in ('available', 'unscoped'):
        for stage in cute['stages']:
            if cute_stage and {'load': 'CUTELoadEvent', 'compute': 'CUTEComputeEvent', 'store': 'CUTEStoreEvent'}[cute_stage] != stage['table']:
                continue
            for task in stage['tasks']:
                if cute_task_range and not cute_task_range[0] <= task['seq_id'] <= cute_task_range[1]:
                    continue
                profile.require(task['end_stamp'] >= task['begin_stamp'], 'Negative CUTE interval')
                events.append({'domain': 'cute', 'track': stage['table'] + '/' + stage['role'],
                               'kind': 'task', 'name': stage['table'], 'begin': task['begin_stamp'],
                               'end': task['end_stamp'], 'seq_id': task['seq_id'], 'role': stage['role']})
    cpu_memory = section.get('memory', {}).get('cpu', {})
    memory_shown = memory_matched = 0
    if cpu_memory.get('status') == 'available':
        for item in [*cpu_memory['requests'], *cpu_memory['store_events'], *cpu_memory['sbuffer_events']]:
            source = item.get('source') or {}
            if function and function not in source.get('function', ''):
                continue
            stamp = item['cpu_stamp']
            if cpu_range and not cpu_range[0] <= stamp <= cpu_range[1]:
                continue
            memory_matched += 1
            if memory_shown >= max_instructions:
                continue
            memory_shown += 1
            finish = item.get('response_cpu_stamp') or stamp
            events.append({'domain': 'cpu', 'track': 'LSU memory / ' + item['kind'],
                           'kind': 'memory', 'name': item['kind'], 'begin': stamp, 'end': finish,
                           'pc': item.get('pc'), 'function': source.get('function'),
                           'source': source.get('source'), 'sn': item.get('sn'),
                           'archived_source': source.get('archived_source'),
                           'disassembly_context': source.get('disassembly_context'), 'memory_event': item})
    ame_reads_matched = ame_reads_shown = 0
    actual_memory = section.get('memory', {})
    if actual_memory.get('read_returns', {}).get('status') == 'available' and function is None:
        for tx in actual_memory.get('transactions', []):
            if tx['kind'] != 'read':
                continue
            stamp = tx['request_cpu_stamp']
            if cpu_range and not cpu_range[0] <= stamp <= cpu_range[1]:
                continue
            ame_reads_matched += 1
            if ame_reads_shown >= max_instructions:
                continue
            ame_reads_shown += 1
            events.append({'domain': 'cpu', 'track': 'AME read service', 'kind': 'ame_memory',
                'name': 'matrix_data_in read', 'begin': stamp,
                'end': tx['response_cpu_stamp'] if tx['response_cpu_stamp'] is not None else stamp,
                'memory_event': tx,
                'ownership': 'Timestamp overlap only; asynchronous source ID is not an instruction PC.'})
    source_details = {int(p['pc'], 16): p for p in section['pcs']}
    for event in events:
        if event['domain'] == 'cpu' and event['kind'] not in ('memory', 'ame_memory'):
            detail = source_details[int(event['pc'], 16)]
            event['archived_source'] = detail.get('archived_source')
            event['disassembly_context'] = detail.get('disassembly_context')
    domains = []
    for name in ('cpu', 'cute'):
        chosen = [e for e in events if e['domain'] == name]
        domains.append({'id': name, 'unit': 'recorded timestamp cycles',
                        'origin': min((e['begin'] for e in chosen), default=None),
                        'end': max((e['end'] for e in chosen), default=None),
                        'scope': window if name == 'cpu' else cute.get('scope'),
                        'status': 'available' if chosen else 'unavailable',
                        'reason': None if chosen else ('No instructions match filters' if name == 'cpu' else cute.get('reason', 'No CUTE tasks match filters'))})
    from kda_hardware import clock_contract
    clocks = clock_contract(report)
    if clocks['status'] == 'validated':
        mapping = clocks['mapping']
        for e in events:
            if e['domain'] == 'cute' and mapping['cute_min'] <= e['begin'] <= e['end'] <= mapping['cute_max']:
                e['cpu_aligned_begin'] = e['begin'] + mapping['offset']
                e['cpu_aligned_end'] = e['end'] + mapping['offset']
    return {'schema': 'xsai-prof.timeline/v1', 'kind': 'timeline', 'label': report['label'],
            'domains': domains, 'cross_domain_alignment': clocks['status'], 'events': events,
            'clock_contract': clocks,
            'cpu_selection': {'function_contains': function, 'commit_cycle_range': cpu_range,
                              'instructions_in_roi': total, 'instructions_matched': matched,
                              'instructions_shown': cpu_count, 'truncated': matched > max_instructions,
                              'memory_events_matched': memory_matched, 'memory_events_shown': memory_shown, 'memory_events_truncated': memory_matched > memory_shown,
                              'max_instructions': max_instructions, 'missing_or_invalid_stamps': dict(missing)},
            'cute_selection': {'stage': cute_stage, 'seq_id_range': cute_task_range,
                               'scope': cute.get('scope'), 'independent_of_cpu_filters': True},
            'ame_read_selection': {'matched': ame_reads_matched, 'shown': ame_reads_shown,
                'truncated': ame_reads_matched > ame_reads_shown,
                'function_filter_supported': False,
                'reason': 'AME source IDs identify requests; no instruction ownership is inferred.'},
            'limitations': [s for s in LIMITATIONS if clocks['status'] != 'validated' or not s.startswith('CUTE uses')], 'source_pcs': [p for pc, p in pcmap.items() if pc in allowed]}


def html_view(data):
    # User-controlled text is escaped; JSON is served separately, not interpolated as JS.
    parts = ['<!doctype html><html><meta charset="utf-8"><title>XSAI timeline</title>',
             '<style>body{font:15px system-ui;margin:24px}svg{border:1px solid #ccc}pre{white-space:pre-wrap}table{border-collapse:collapse}td{padding:6px;border-bottom:1px solid #ddd}.scroll{overflow:auto;max-height:600px}h2{margin-top:32px}</style>',
             '<h1>' + html.escape(data['label']) + '</h1><p><a href="timeline.json">JSON</a> · <a href="events.csv">CSV</a></p>',
             '<p>Clock mapping: ' + html.escape(data.get('clock_contract', {}).get('reason', 'Unproven')) + '</p>',
             '<ul>' + ''.join('<li>' + html.escape(s) + '</li>' for s in data['limitations']) + '</ul>',
             '<p>CPU selection: ' + html.escape(json.dumps(data['cpu_selection'])) + '</p>',
             '<p>CUTE selection: ' + html.escape(json.dumps(data['cute_selection'])) + '</p>',
             '<label>Zoom <input id="zoom" type="range" min="1" max="10" value="1"></label>']
    for domain in data['domains']:
        events = [e for e in data['events'] if e['domain'] == domain['id']]
        parts += ['<h2>' + domain['id'].upper() + ' — separate clock domain</h2>',
                  '<p>Unit: recorded timestamp cycles. Scope: ' + html.escape(json.dumps(domain['scope'])) + '</p>']
        if not events:
            parts += ['<p>' + html.escape(str(domain['reason'])) + '</p>']
            continue
        begin, end = domain['origin'], domain['end']
        tracks = list(dict.fromkeys(e['track'] for e in events))
        # Intervals can overlap on a track. Rows are compact instruction lanes,
        # with full exact timestamps in tooltips/table rather than inferred occupancy.
        height = 45 + len(tracks) * 85
        shapes = [f'<svg width="1400" height="{height}" viewBox="0 0 1400 {height}">']
        shapes += [f'<text x="190" y="18">{begin}</text><text x="1260" y="18">{end}</text>']
        for index, track in enumerate(tracks):
            shapes += [f'<text x="4" y="{42+index*85}">{html.escape(track)}</text>']
        lanes = Counter()
        for event in events:
            x = 190 + (event['begin'] - begin) / max(1, end - begin) * 1190
            width = max(1, (event['end'] - event['begin']) / max(1, end - begin) * 1190)
            lane = lanes[event['track']] % 5
            lanes[event['track']] += 1
            y = 30 + tracks.index(event['track']) * 85 + lane * 12
            title = html.escape(json.dumps(event, ensure_ascii=False))
            shapes += [f'<rect x="{x:.3f}" y="{y}" width="{width:.3f}" height="10" fill="#3478b9" opacity="0.65"><title>{title}</title></rect>']
        shapes += ['</svg>']
        parts += ['<div class="scroll">' + ''.join(shapes) + '</div>']
    parts += ['<h2>Exact events and source</h2><input id="filter" placeholder="Filter function, PC, source or instruction"><div class="scroll"><table><tr><th>Domain/track</th><th>Begin/end cycles</th><th>Instruction/task and source</th></tr>']
    for event in data['events']:
        parts.append('<tr class="event"><td>' + html.escape(event['domain'] + '/' + event['track']) + '</td><td>' +
                     html.escape(f'{event["begin"]} → {event["end"]}') + '</td><td><pre>' +
                     html.escape(json.dumps(event, ensure_ascii=False)) + '</pre></td></tr>')
    parts += ['</table></div><script>document.getElementById("zoom").oninput=e=>document.querySelectorAll("svg").forEach(s=>s.setAttribute("width",1400*e.target.value));document.getElementById("filter").oninput=e=>document.querySelectorAll(".event").forEach(r=>r.hidden=!r.textContent.toLowerCase().includes(e.target.value.toLowerCase()));</script></html>']
    return ''.join(parts)


def add_parser(commands):
    p = commands.add_parser('timeline', help='Export CPU residence and CUTE task timelines with explicit clock contracts')
    p.add_argument('report', type=Path)
    p.add_argument('--output', '-o', type=Path, required=True)
    p.add_argument('--function', help='CPU function substring filter; CUTE scope remains independent')
    p.add_argument('--cute-stage', choices=['load', 'compute', 'store'])
    p.add_argument('--cute-task-range', type=int, nargs=2, metavar=('FIRST_SEQ', 'LAST_SEQ'))
    p.add_argument('--max-instructions', type=int, default=10000)
    p.add_argument('--cpu-cycle-range', nargs=2, type=int, metavar=('BEGIN', 'END'))


def dispatch(args, kda):
    report, directory = profile.verify_saved_report(args.report, kda)
    profile.require(report['sections']['trace']['status'] == 'available', 'Timeline needs verified trace evidence')
    out = args.output.resolve()
    profile.require(not out.exists(), 'Timeline output already exists')
    profile.require(not out.is_relative_to(profile.ROOT / 'dependencies'), 'Timeline must not modify dependencies')
    profile.require(not out.is_relative_to(directory) and not any((p / 'manifest.json').exists() for p in (out, *out.parents)), 'Timeline must not modify evidence')
    # Re-run the established all-PC DB/ELF pairing check, including archived ROI checks.
    with tempfile.TemporaryDirectory(prefix='xsai-timeline-check-') as temporary:
        item = profile.load_input(report['spec']['trace'], kda, 'trace')
        verified = profile.trace_section(item, {**report['options'], 'cute': report['spec'].get('cute')}, Path(temporary))
        report['sections']['trace'] = verified
        data = timeline(report, args.function, args.max_instructions, args.cpu_cycle_range,
                        getattr(args, 'cute_stage', None), getattr(args, 'cute_task_range', None))
    data['provenance'] = {'report': str(directory), 'report_sha256': profile.digest(directory / 'report.json'),
                          'trace_run': verified['run'], 'database_sha256': profile.digest(Path(verified['run']) / 'chiseldb.db'),
                          'elf_sha256': profile.digest(Path(verified['run']) / 'profile.elf')}
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.timeline-', dir=out.parent) as temporary:
        staging = Path(temporary) / 'result'
        staging.mkdir()
        profile.dump(staging / 'timeline.json', data)
        (staging / 'index.html').write_text(html_view(data))
        with (staging / 'events.csv').open('w', newline='') as stream:
            writer = csv.DictWriter(stream, fieldnames=['domain', 'track', 'kind', 'begin', 'end', 'name', 'sn', 'pc', 'function', 'source', 'seq_id'])
            writer.writeheader()
            for event in data['events']:
                writer.writerow({k: event.get(k) for k in writer.fieldnames})
        profile.dump(staging / 'checksums.json', {'files': {p.name: profile.digest(p) for p in staging.iterdir()}})
        staging.rename(out)
    print(json.dumps({'status': 'passed', 'timeline': str(out / 'timeline.json'), 'html': str(out / 'index.html'),
                      'cpu_selection': data['cpu_selection']}))
