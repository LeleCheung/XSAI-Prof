"""Actual reviewed AME and ordinary CPU/RVV interfaces; never inferred DRAM bytes."""
from collections import Counter
import html
import json
from pathlib import Path
import sqlite3
import tempfile

import kda_profile as p
from kda_observer import reviewed

LIMITATIONS = [
    'Only the 64-byte AME near_cute A/D interface is observed; CPU/RVV traffic and DRAM traffic are unknown.',
    'A Get records requested bytes, not observed read payload. Matrix read returns may bypass D via matrix_data_in.',
    'Put payload counts mask-enabled byte lanes on actual A handshakes. It is interface traffic, not unique addresses or DRAM writes.',
    'Write completion latency is A handshake to matching AccessAck callback; not instruction latency or exclusive engine time.',
    'Scope uses CPU marker commit timestamps, includes boundary overlap and does not prove which instruction owns an asynchronous request.',
    'All interface events and CUTE tasks are retained to reconstruct crossing-boundary writes; CPU lifetime insertion alone is filtered.',
]


def decode(rows, begin=None, end=None):
    """Rows: ID,channel,site,cpu,stamp,opcode,param,size,source,address,mask,denied,corrupt."""
    p.require((begin is None) == (end is None) and (begin is None or 0 <= begin < end), 'Invalid memory interval')
    pending, transactions, raw, offsets, errors = {}, [], Counter(), Counter(), []
    # Existing responses free source IDs before another request on the same edge.
    ordered = sorted(rows, key=lambda r: (r[3], r[1] == 'A', r[0]))
    for row in ordered:
        ident, channel, site, cpu, stamp, opcode, param, size, source, address, mask, denied, corrupt = row
        p.require(channel in ('A', 'D') and site == ('TLA_near_cute' if channel == 'A' else 'TLD_near_cute'), 'Unreviewed interface site/channel')
        p.require(all(type(v) is int and v >= 0 for v in (ident, cpu, stamp, opcode, param, size, source, address, denied, corrupt)), 'Invalid interface event types')
        p.require(type(mask) is int, 'Mask must retain all 64 integer bits; REAL masks are invalid')
        offsets[cpu - stamp] += 1
        raw[channel + '_handshakes'] += 1
        if channel == 'D':
            if opcode == 0:
                tx = pending.pop(source, None)
                if tx is None:
                    errors.append({'event': ident, 'reason': 'AccessAck has no observed pending write'})
                else:
                    if size != tx['size']:
                        errors.append({'event': ident, 'reason': 'AccessAck size differs from request'})
                    tx.update(response_cpu_stamp=cpu, response_stamp=stamp, denied=bool(denied), corrupt=bool(corrupt),
                              latency_cycles=cpu - tx['request_cpu_stamp'], completion='observed')
            elif opcode == 1:
                raw['observed_D_AccessAckData'] += 1
            else:
                errors.append({'event': ident, 'reason': 'Unsupported D opcode'})
            continue
        if opcode not in (0, 1, 4) or param != 0 or size > 6:
            errors.append({'event': ident, 'reason': 'Unsupported A opcode/param or multibeat transfer; no bytes inferred'})
            continue
        if source in pending:
            errors.append({'event': ident, 'reason': 'Source reused before observed write completion'})
        length = 1 << size
        mask &= (1 << 64) - 1
        allowed = ((1 << length) - 1) << (address % 64)
        if address % length or allowed >= (1 << 64) or mask & ~allowed:
            errors.append({'event': ident, 'reason': 'Misaligned address or invalid mask'})
            continue
        tx = {'request_id': ident, 'source': source, 'address': hex(address), 'size': size,
              'request_cpu_stamp': cpu, 'request_stamp': stamp, 'response_cpu_stamp': None,
              'response_stamp': None, 'latency_cycles': None, 'denied': None, 'corrupt': None,
              'request_bytes': length, 'mask': hex(mask), 'opcode': opcode,
              'kind': 'read' if opcode == 4 else 'write',
              'write_payload_bytes': mask.bit_count() if opcode in (0, 1) else 0,
              'completion': 'unobserved_read_bypass' if opcode == 4 else 'pending'}
        if opcode == 0 and mask != allowed:
            errors.append({'event': ident, 'reason': 'PutFull mask does not cover full transfer'})
        transactions.append(tx)
        if opcode != 4:
            pending[source] = tx
    selected = [t for t in transactions if begin is None or begin <= t['request_cpu_stamp'] < end]
    entering = [t for t in transactions if begin is not None and t['request_cpu_stamp'] < begin and
                (t['response_cpu_stamp'] is not None and t['response_cpu_stamp'] >= begin or
                 t['kind'] == 'write' and t['response_cpu_stamp'] is None)]
    leaving = [t for t in selected if t['kind'] == 'write' and
               (t['response_cpu_stamp'] is None or end is not None and t['response_cpu_stamp'] >= end)]
    writes = [t for t in selected if t['kind'] == 'write']
    reads = [t for t in selected if t['kind'] == 'read']
    if len(offsets) > 1:
        errors.append({'reason': 'Same-run interface/CPU callback offset is not constant'})
    return {'status': 'invalid' if errors else 'available', 'errors': errors, 'raw': dict(raw),
            'scope': {'begin_cpu_stamp': begin, 'end_cpu_stamp_exclusive': end, 'policy': 'request initiation in interval; write completions followed outside interval'},
            'timestamps': {'domain': 'PerfCCT.global_tick_acc at the interface callback',
                           'offset_histogram': dict(offsets), 'constant_unit_slope': len(offsets) == 1,
                           'same_run_callback_stamps': True},
            'metrics': {'read_requests': len(reads), 'read_requested_bytes': sum(t['request_bytes'] for t in reads),
                        'write_requests': len(writes), 'write_payload_bytes': sum(t['write_payload_bytes'] for t in writes),
                        'observed_write_completions': sum(t['completion'] == 'observed' for t in writes),
                        'denied_writes': sum(t['denied'] is True for t in writes),
                        'corrupt_writes': sum(t['corrupt'] is True for t in writes),
                        'read_payload_bytes': None, 'read_completion_latency': None,
                        'cpu_rvv_memory_bytes': None, 'dram_bytes': None, 'dram_bandwidth': None},
            'boundary': {'entering_writes': len(entering), 'leaving_writes': len(leaving),
                         'unclosed_writes_in_full_capture': len(pending),
                         'read_inflight': None, 'reason': 'Read bypass is not observed, so outstanding reads are unknown.'},
            'transactions': selected, 'entering_transactions': entering,
            'limitations': LIMITATIONS}


def compare(left, right):
    """Compare reviewed same-scope interface observations, never inferred traffic."""
    lhs, rhs = left.get('memory', {}), right.get('memory', {})
    if lhs.get('status') != 'available' or rhs.get('status') != 'available':
        return {'status': 'unavailable', 'reason': 'Paired reviewed actual-interface observations required'}
    def scope(trace):
        return (trace.get('collector', {}).get('mode', 'full'),
                [(event['kind'], event.get('name'), event['invocation'])
                 for event in trace.get('ranges', {}).get('events', [])])
    if scope(left) != scope(right) or lhs.get('observer') != rhs.get('observer'):
        return {'status': 'unavailable', 'reason': 'Memory observer or selected invocation/stage scopes differ'}
    metrics = []
    for name, value in lhs['metrics'].items():
        other = rhs['metrics'].get(name)
        metrics.append({'metric': name, 'baseline': value, 'candidate': other,
                        'delta': other - value if value is not None and other is not None else None})
    cpu_left, cpu_right = lhs.get('cpu', {}), rhs.get('cpu', {})
    cpu_compare = {'status': 'unavailable', 'reason': 'Paired reviewed CPU events required'}
    if cpu_left.get('status') == cpu_right.get('status') == 'available':
        cpu_compare = {'status': 'available', 'metrics': [{'metric': key, 'baseline': value, 'candidate': cpu_right['metrics'].get(key), 'delta': cpu_right['metrics'].get(key) - value if value is not None and cpu_right['metrics'].get(key) is not None else None} for key, value in cpu_left['metrics'].items()], 'semantics': 'Same partial ordinary LSU/PMA interfaces and timestamp scope. Request attempts include replay/speculation; store-buffer completions are separate.'}
    return {'status': 'available', 'metrics': metrics, 'cpu': cpu_compare,
            'scopes': {'baseline': lhs['scope'], 'candidate': rhs['scope']},
            'boundaries': {'baseline': lhs['boundary'], 'candidate': rhs['boundary']},
            'semantics': 'Same selected marker scope and reviewed AME interface; CPU events are compared separately when captured. Missing values remain unknown.'}


def intersect_tasks(trace, interval, mapping):
    """Map recorded task intervals, without inferring request ownership."""
    tasks = []
    for stage in trace.get('cute', {}).get('stages', []):
        for task in stage['tasks']:
            start, finish = task['begin_stamp'] + mapping['offset'], task['end_stamp'] + mapping['offset']
            if start < interval[1] and finish >= interval[0]:
                tasks.append({'table': stage['table'], 'role': stage['role'], 'seq_id': task['seq_id'],
                              'begin_cpu_stamp': start, 'end_cpu_stamp': finish,
                              'began_before_scope': start < interval[0], 'finishes_at_or_after_scope_end': finish >= interval[1]})
    return {'status': 'available', 'tasks': tasks, 'clock_mapping': mapping,
            'scope': trace.get('cute', {}).get('scope'),
            'semantics': 'Recorded task intervals intersect the timestamp scope; full event capture retains entering/leaving tasks. Overlap is not critical path, exclusive time or request ownership.'}


def memory(report, interval=None):
    trace = report['sections']['trace']
    p.require(trace['status'] == 'available', 'Memory analysis requires verified trace')
    run = Path(trace['run'])
    manifest = p.read_json(run / 'manifest.json')
    names = [n for n in manifest['artifacts'] if n.startswith('rtl-config.')]
    p.require(len(names) == 1, 'Memory analysis needs one recorded RTL receipt')
    receipt = p.read_json(p.recorded_artifact(run, manifest, names[0]))
    p.require(reviewed(receipt) and manifest['rtl']['emu_sha256'] == receipt['emulator']['sha256'], 'Unreviewed memory observer or mismatched receipt')
    capture = manifest.get('trace_capture', {})
    if capture.get('memory') is not True or not {'TLAEvent', 'TLDEvent'} <= set(manifest.get('trace_table_selection', [])):
        return {'status': 'unavailable', 'reason': 'Actual interface tables were not selected; missing evidence is not zero.', 'metrics': None, 'limitations': LIMITATIONS}
    db = p.recorded_artifact(run, manifest, 'chiseldb.db')
    if interval is None:
        w = trace['window']
        interval = [w['begin_commit_cycle'], w['end_commit_cycle']]
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as c:
        from kda_roi import collector
        scope = collector(c)
        rows = c.execute('SELECT ID,CHANNEL,SITE,CPU_STAMP,STAMP,OPCODE,PARAM,SIZE,SOURCE,ADDRESS,MASK,DENIED,CORRUPT FROM XSAITL').fetchall()
        from kda_observer import cpu_reviewed
        from kda_cpu_memory import from_connection
        cpu = from_connection(c, interval, trace) if cpu_reviewed(receipt) else {'status': 'unavailable', 'reason': 'CPU observer not present in this reviewed build', 'metrics': None}
        from kda_observer import ame_read_reviewed
        read_rows = c.execute('SELECT ID,CPU_STAMP,EPOCH,SOURCE,READY,DATA_HEX FROM XSAIAMERead').fetchall() if ame_read_reviewed(receipt) else None
    data = decode(rows, *interval)
    if read_rows is not None:
        from kda_ame_memory import with_read_returns
        full = decode(rows)
        data = with_read_returns(data, full['transactions'], read_rows, *interval)
    data['cpu'] = cpu
    if cpu['status'] == 'invalid':
        data['status'] = 'invalid'
        data['errors'] += [{'cpu': error} for error in cpu['errors']]
    if cpu['status'] == 'available':
        data['limitations'] = [item for item in data['limitations'] if not item.startswith('Only the 64-byte')] + cpu['limitations']
    data['collector'] = scope
    data['observer'] = receipt['memory_observer']
    from kda_clock import anchors
    synchronization = anchors(report, receipt)
    data['ame_tasks'] = {'status': 'unavailable', 'reason': 'No validated same-run CPU/CUTE anchors or recorded tasks', 'tasks': []}
    if synchronization['status'] == 'validated':
        data['ame_tasks'] = intersect_tasks(trace, interval, synchronization['mapping'])
    data['provenance'] = {'run': str(run), 'database_sha256': p.digest(db),
                          'elf_sha256': p.digest(p.recorded_artifact(run, manifest, 'profile.elf')),
                          'rtl_receipt_sha256': p.digest(p.recorded_artifact(run, manifest, names[0]))}
    return data


def add_parser(commands):
    parser = commands.add_parser('memory', help='Reviewed AME and ordinary CPU/RVV memory requests, masks and status responses')
    parser.add_argument('report', type=Path)
    parser.add_argument('--output', '-o', type=Path, required=True)
    parser.add_argument('--cpu-cycle-range', type=int, nargs=2)


def html_view(data):
    encoded = json.dumps(data, ensure_ascii=False).replace('<', '\u003c')
    return '''<!doctype html><meta charset="utf-8"><title>XSAI memory interfaces</title>
<style>body{font:15px system-ui;max-width:1400px;margin:24px auto;padding:16px}table{border-collapse:collapse;width:100%}td,th{padding:8px;border-bottom:1px solid #ddd;text-align:left}pre{white-space:pre-wrap;overflow-wrap:anywhere;background:#f3f5f8;padding:12px}input{font:inherit;padding:8px;min-width:500px}button{padding:8px;margin:8px}.scroll{max-height:600px;overflow:auto}</style>
<h1>Actual memory interface traffic</h1><p><a href="memory.json">JSON evidence</a> · <a href="README.md">Definitions</a></p>
<p>Reviewed near_cute requests and mask-enabled writes. AME read payload and service latency appear when the reviewed matrix_data_in observer is captured. CPU/RVV observations have separate coverage; DRAM traffic remains unknown.</p>
<h2>Metrics and boundaries</h2><div id="summary"></div><h2>Transactions</h2>
<input id="filter" placeholder="Source, address, opcode, completion or timestamp"><button id="csv">Export filtered CSV</button><p id="count"></p><div class="scroll"><table id="transactions"></table></div>
<h2>CPU/RVV observations</h2><pre id="cpu-summary"></pre><input id="cpu-filter" placeholder="CPU function, PC, address, kind or mask"><p id="cpu-count"></p><div class="scroll"><table id="cpu-events"></table></div><h2>Selected transaction</h2><pre id="detail"></pre><details><summary>All evidence, limits and provenance</summary><pre id="raw"></pre></details>
<script id="data" type="application/json">''' + encoded + '''</script><script>
const d=JSON.parse(document.getElementById('data').textContent),cols=['kind','source','address','request_cpu_stamp','response_cpu_stamp','request_bytes','write_payload_bytes','latency_cycles','completion'];
const el=(t,s)=>{const e=document.createElement(t);if(s!==undefined)e.textContent=s;return e};
const pre=el('pre',JSON.stringify({status:d.status,scope:d.scope,metrics:d.metrics,boundary:d.boundary,timestamps:d.timestamps,ame_tasks:d.ame_tasks},null,2));document.getElementById('summary').append(pre);
const cpu=d.cpu||{status:'unavailable'};
document.getElementById('cpu-summary').textContent=JSON.stringify({status:cpu.status,coverage:cpu.coverage,metrics:cpu.metrics,boundary:cpu.boundary,timestamps:cpu.timestamps,functions:cpu.functions},null,2);
function drawCpu(){const q=document.getElementById('cpu-filter').value.toLowerCase();const all=[...(cpu.requests||[]),...(cpu.store_events||[]),...(cpu.sbuffer_events||[])];const rows=all.filter(r=>JSON.stringify(r).toLowerCase().includes(q));const table=document.getElementById('cpu-events');table.replaceChildren();const columns=['kind','cpu_stamp','pc','virtual_address','address','mask','enabled_bytes','ownership'];const h=el('tr');columns.forEach(c=>h.append(el('th',c)));h.append(el('th','function'));table.append(h);rows.slice(0,10000).forEach(r=>{const tr=el('tr');columns.forEach(c=>tr.append(el('td',r[c]===undefined||r[c]===null?'unavailable':String(r[c]))));tr.append(el('td',(r.source||{}).function||'unattributed'));tr.onclick=()=>document.getElementById('detail').textContent=JSON.stringify(r,null,2);table.append(tr)});document.getElementById('cpu-count').textContent=rows.length+' matches; at most 10000 rows displayed';}
document.getElementById('cpu-filter').oninput=drawCpu;drawCpu();
document.getElementById('raw').textContent=JSON.stringify(d,null,2);let shown=[];
function draw(){const q=document.getElementById('filter').value.toLowerCase();shown=(d.transactions||[]).filter(r=>JSON.stringify(r).toLowerCase().includes(q));const t=document.getElementById('transactions');t.replaceChildren();const h=el('tr');cols.forEach(c=>h.append(el('th',c)));t.append(h);shown.slice(0,10000).forEach(r=>{const tr=el('tr');cols.forEach(c=>tr.append(el('td',r[c]===null?'unavailable':String(r[c]))));tr.onclick=()=>document.getElementById('detail').textContent=JSON.stringify(r,null,2);t.append(tr)});document.getElementById('count').textContent=shown.length+' matches; at most 10000 rows displayed';}
document.getElementById('filter').oninput=draw;document.getElementById('csv').onclick=()=>{const quote=v=>JSON.stringify(v===null?'':String(v));const body=[cols.join(','),...shown.map(r=>cols.map(c=>quote(r[c])).join(','))].join(String.fromCharCode(10));const a=el('a');a.href=URL.createObjectURL(new Blob([body],{type:'text/csv'}));a.download='ame-interface.csv';a.click();URL.revokeObjectURL(a.href);};draw();
</script>'''


def dispatch(args, kda):
    report, directory = p.verify_saved_report(args.report, kda)
    out = args.output.resolve()
    p.require(not out.exists() and not out.is_relative_to(directory), 'New output outside input report required')
    p.require(not out.is_relative_to(p.ROOT / 'dependencies') and not any((a / 'manifest.json').exists() for a in (out, *out.parents)), 'Output must not modify evidence/dependencies')
    with tempfile.TemporaryDirectory(prefix='xsai-memory-check-') as temp:
        item = p.load_input(report['spec']['trace'], kda, 'trace')
        report['sections']['trace'] = p.trace_section(item, {**report['options'], 'cute': report['spec'].get('cute')}, Path(temp))
        data = memory(report, args.cpu_cycle_range)
    out.mkdir(parents=True)
    p.dump(out / 'memory.json', data)
    (out / 'index.html').write_text(html_view(data))
    lines = ['# Actual memory interface traffic', '', 'Status: ' + data['status'], '',
             '## Observed scope and metrics', '', json.dumps({key: data.get(key) for key in ('scope', 'metrics', 'boundary', 'timestamps')}, indent=2), '',
             '## CPU/RVV ordinary LSU and PMA stores', '', json.dumps({key: data.get('cpu', {}).get(key) for key in ('status', 'coverage', 'metrics', 'boundary', 'timestamps', 'functions')}, indent=2), '', '## CUTE tasks crossing or intersecting the scope', '', json.dumps(data.get('ame_tasks'), indent=2), '',
             '## Evidence boundaries', '', *('- ' + item for item in data.get('limitations', LIMITATIONS)), '',
             '## Artifact identity', '', json.dumps(data.get('provenance'), indent=2), '']
    (out / 'README.md').write_text(chr(10).join(lines))
    p.dump(out / 'checksums.json', {'files': {f.name: p.digest(f) for f in out.iterdir()}})
    print(json.dumps({'status': data['status'], 'memory': str(out / 'memory.json'), 'metrics': data.get('metrics')}))
    return 1 if data['status'] == 'invalid' else 0
