"""Task-event activity in the CUTE clock; never matrix-unit occupancy."""
from collections import Counter
from pathlib import Path
import sqlite3

import kda_profile as p


def activity(intervals):
    """Half-open interval sweep; simultaneous end/start has no fake overlap."""
    edges = Counter()
    for begin, end in intervals:
        p.require(0 <= begin <= end, 'Invalid task interval')
        if begin != end:
            edges[begin] += 1
            edges[end] -= 1
    outstanding = peak = union = total = 0
    previous = None
    for stamp, delta in sorted(edges.items()):
        if previous is not None:
            width = stamp - previous
            if outstanding:
                union += width
            total += outstanding * width
        outstanding += delta
        peak = max(peak, outstanding)
        previous = stamp
    p.require(outstanding == 0, 'Unbalanced task intervals')
    return {'task_interval_union_cycles': union, 'sum_task_interval_cycles': total,
            'peak_outstanding_task_intervals': peak}


def summary(report):
    trace = report['sections']['trace']
    cute = trace.get('cute', {})
    if trace['status'] != 'available' or cute.get('status') not in ('available', 'unscoped'):
        return {'status': 'unavailable', 'reason': 'No complete CUTE task evidence', 'stages': []}
    stages = []
    all_intervals = []
    db = Path(trace['run']) / 'chiseldb.db'
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        conn.row_factory = sqlite3.Row
        for stage in cute['stages']:
            table = stage['table']
            p.require(table in ('CUTELoadEvent', 'CUTEComputeEvent', 'CUTEStoreEvent'), 'Unexpected task table')
            issue = {'CUTELoadEvent': 'LoadIssue', 'CUTEComputeEvent': 'ComputeIssue', 'CUTEStoreEvent': 'StoreIssue'}[table]
            snapshots = {r['SEQID']: dict(r) for r in conn.execute(f'SELECT * FROM {table} WHERE SITE=?', (issue,))}
            intervals = [(t['begin_stamp'], t['end_stamp']) for t in stage['tasks']]
            all_intervals.extend(intervals)
            stages.append({'table': table, 'role': stage['role'], 'task_count': len(stage['tasks']),
                **activity(intervals),
                'issue_snapshots': [snapshots[t['seq_id']] for t in stage['tasks']]})
    return {'status': cute['status'], 'scope': cute['scope'], 'clock': 'CUTE Table.log STAMP',
            'stages': stages, 'all_selected_task_intervals': activity(all_intervals),
            'semantics': 'Half-open task-event intervals in the explicitly selected CUTE scope. Outstanding intervals include controller waiting and transfers. Raw tile/flag snapshots retain encoded fields without inferring executed MACs or bus bytes.',
            'ame_occupancy': None, 'measured_memory_bytes': None,
            'limitations': ['Overlapping task intervals are not proof of simultaneous arithmetic execution.',
                'Intervals across stages are not additive. All-stage peak counts tasks across distinct roles/resources.',
                'No cache, DRAM, register-bank utilization or task stall reason follows from event duration alone.']}
