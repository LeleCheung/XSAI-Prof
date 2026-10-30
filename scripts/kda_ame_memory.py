"""Pair the reviewed fixed-beat AME read-return bypass by source ID."""
from collections import Counter
import re
import statistics

import kda_profile as p


def with_read_returns(data, all_transactions, rows, begin, end):
    """Rows: ID,CPU_STAMP,EPOCH,SOURCE,READY,DATA_HEX; valid is implicit.

    All requests and responses remain available to reconstruct interval edges.
    Source IDs name one pending request across both reads and writes. Return
    bytes count the observed 512-bit bus beat, not requested useful elements.
    """
    errors = []
    accepted, blocked = [], []
    offsets = Counter()
    for ident, stamp, epoch, source, ready, payload in rows:
        p.require(all(type(v) is int and v >= 0 for v in (ident, stamp, epoch, source)),
                  'Invalid AME return metadata')
        p.require(source < 64 and ready in (0, 1), 'Unreviewed AME return source/ready')
        p.require(isinstance(payload, str) and re.fullmatch('[0-9a-f]{128}', payload),
                  'AME return must retain one exact 512-bit payload')
        offsets[stamp - epoch] += 1
        event = {'id': ident, 'cpu_stamp': stamp, 'epoch': epoch, 'source': source,
                 'ready': bool(ready), 'data_hex': payload,
                 'payload_bytes': 64 if ready else 0}
        (accepted if ready else blocked).append(event)
    if len(offsets) > 1:
        errors.append({'reason': 'AME pre-edge CPU stamp/epoch offset is not constant'})

    pending = {}
    events = []
    for tx in all_transactions:
        if tx['size'] != 6:
            errors.append({'request': tx['request_id'], 'reason': 'AME read observer requires reviewed 64-byte fixed transfers'})
        events.append((tx['request_cpu_stamp'], 1, tx['request_id'], 'request', tx))
        if tx['kind'] == 'write' and tx['response_cpu_stamp'] is not None:
            events.append((tx['response_cpu_stamp'], 0, tx['request_id'], 'write_ack', tx))
    for event in accepted:
        events.append((event['cpu_stamp'], 0, event['id'], 'read_return', event))
    for _, _, _, kind, item in sorted(events, key=lambda row: row[:3]):
        source = item['source']
        if kind == 'request':
            if source in pending:
                errors.append({'source': source, 'reason': 'Source reused before read/write completion'})
            pending[source] = item
        else:
            tx = pending.pop(source, None)
            expected = 'read' if kind == 'read_return' else 'write'
            if tx is None or tx['kind'] != expected:
                errors.append({'source': source, 'reason': 'Return/ack has no matching pending request of its kind'})
                continue
            if kind == 'read_return':
                latency = item['cpu_stamp'] - tx['request_cpu_stamp']
                if latency < 0:
                    errors.append({'source': source, 'reason': 'Negative read service latency'})
                tx.update(response_cpu_stamp=item['cpu_stamp'], response_stamp=None,
                          latency_cycles=latency, completion='observed_matrix_data_in',
                          read_payload_bytes=64, return_event=item,
                          denied=None, corrupt=None)
    # Validate stalled beat identity/payload against its eventual handshake.
    by_source = {}
    for event in sorted(accepted + blocked, key=lambda e: (e['cpu_stamp'], e['id'])):
        source = event['source']
        previous = by_source.get(source)
        if previous is not None and previous['cpu_stamp'] + 1 == event['cpu_stamp'] and previous['data_hex'] != event['data_hex']:
            errors.append({'source': source, 'reason': 'Read payload changed while backpressured'})
        if event['ready']:
            by_source.pop(source, None)
        else:
            by_source[source] = event

    reads_all = [t for t in all_transactions if t['kind'] == 'read']
    for tx in reads_all:
        if tx['response_cpu_stamp'] is None:
            tx['completion'] = 'pending_matrix_data_in'
            tx['read_payload_bytes'] = None
    inside = lambda stamp: begin is None or begin <= stamp < end
    selected = [t for t in all_transactions if inside(t['request_cpu_stamp'])]
    reads = [t for t in selected if t['kind'] == 'read']
    matched = [t for t in reads if t['response_cpu_stamp'] is not None]
    entering = [t for t in reads_all if begin is not None and t['request_cpu_stamp'] < begin and
                (t['response_cpu_stamp'] is None or t['response_cpu_stamp'] >= begin)]
    leaving = [t for t in reads if t['response_cpu_stamp'] is None or
               end is not None and t['response_cpu_stamp'] >= end]
    latencies = [t['latency_cycles'] for t in matched]
    first = begin if begin is not None else min((t['request_cpu_stamp'] for t in all_transactions), default=0)
    last = end if end is not None else max([first] + [t['response_cpu_stamp'] or t['request_cpu_stamp'] for t in all_transactions])
    changes = Counter()
    initial = 0
    for tx in reads_all:
        start, finish = tx['request_cpu_stamp'], tx['response_cpu_stamp']
        if start < first and (finish is None or finish >= first):
            initial += 1
        if first <= start < last:
            changes[start] += 1
        if finish is not None and first <= finish < last:
            changes[finish] -= 1
    current, maximum, area, previous_stamp = initial, initial, 0, first
    outstanding = []
    for stamp, delta in sorted(changes.items()):
        area += current * (stamp - previous_stamp)
        current += delta
        if current < 0:
            errors.append({'reason': 'Negative reconstructed outstanding read count'})
        maximum = max(maximum, current)
        outstanding.append({'cpu_stamp': stamp, 'outstanding_reads_after_edge': current})
        previous_stamp = stamp
    area += current * (last - previous_stamp)
    data['transactions'] = selected
    data['entering_transactions'] = [t for t in all_transactions if begin is not None and t['request_cpu_stamp'] < begin and
        (t['response_cpu_stamp'] is None or t['response_cpu_stamp'] >= begin)]
    data['metrics'].update({
        'read_payload_bytes': sum(t['read_payload_bytes'] for t in matched),
        'observed_read_completions': len(matched),
        'read_completion_latency': statistics.mean(latencies) if latencies else None,
        'read_completion_latency_min': min(latencies) if latencies else None,
        'read_completion_latency_max': max(latencies) if latencies else None,
        'read_outstanding_max': maximum,
        'read_outstanding_mean': area / (last - first) if last > first else None,
        'read_return_backpressure_cycles': sum(inside(e['cpu_stamp']) for e in blocked),
    })
    data['boundary'].update(entering_reads=len(entering), leaving_reads=len(leaving),
        unclosed_reads_in_full_capture=sum(t['response_cpu_stamp'] is None for t in reads_all),
        read_inflight=current, reason='Read/write source pairing includes the full observed run; interval edges retain pending reads.')
    data['read_returns'] = {'status': 'invalid' if errors else 'available',
        'accepted_in_interval': [e for e in accepted if inside(e['cpu_stamp'])],
        'backpressured_in_interval': [e for e in blocked if inside(e['cpu_stamp'])],
        'full_capture_accepted': len(accepted), 'offset_histogram': dict(offsets),
        'latency_histogram': dict(Counter(latencies)), 'outstanding': outstanding,
        'outstanding_interval': [first, last],
        'semantics': '64 observed payload bytes per accepted matrix_data_in beat. Latency is near_cute Get handshake to CUTE acceptance in CPU cycles; includes queueing/backpressure. No DRAM or architectural latency.',
        'errors': errors}
    data['scope']['policy'] = 'Request initiation in interval; read and write completions followed outside interval. Return-arrival counts are separate.'
    data['limitations'] = [s for s in data['limitations'] if not s.startswith('A Get records')]
    data['limitations'] += ['Read returns are 512-bit interface beats; useful element bytes, DRAM traffic and instruction ownership remain unknown.',
        'Read return denied/corrupt are not carried by this bypass; these flags remain unknown.',
        'Read latency is interface service time, including queueing/backpressure; it is not architectural instruction latency.']
    data['errors'] += errors
    if errors:
        data['status'] = 'invalid'
    return data
