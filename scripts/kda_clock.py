"""Same-run CPU/CUTE callback anchors for a reviewed observer emulator."""
from collections import Counter
from pathlib import Path
import sqlite3

import kda_profile as p

# Exact observation-only build, reusing all original RTL model object bytes.
OBSERVER = {'emulator_sha256': 'cc6d7b5f3ad20a269bfc45144094840356cf6defc82b34909091a49e5ed96659',
            'logger_sha256': 'b00e5bfb6e245838f4f3ebf80d366726d946e53bb92b977b8a0a28cd0ea31f2c',
            'base_emulator_sha256': '189681b2f3aa6fe9f51891acd9df0bb51b250305ecd970f2d0b26a619541adfd'}
TABLES = ('CUTELoadEvent', 'CUTEComputeEvent', 'CUTEStoreEvent', 'CUTEReleaseEvent')


def reviewed_observer(receipt):
    from kda_observer import reviewed
    if reviewed(receipt):
        return True
    if not receipt:
        return False
    bridge = receipt.get('clock_bridge', {})
    return (receipt.get('emulator', {}).get('sha256') == OBSERVER['emulator_sha256'] and
            bridge.get('schema') == 'xsai-prof.clock-bridge/v1' and
            bridge.get('observer_sha256') == OBSERVER['logger_sha256'] and
            bridge.get('base_emulator_sha256') == OBSERVER['base_emulator_sha256'] and
            bridge.get('single_core_only') is True and
            receipt.get('configuration', {}).get('NUM_CORES') == '1')


def anchors(report, receipt):
    unknown = {'status': 'unproven', 'reason': 'No reviewed same-run clock observer', 'mapping': None}
    if not reviewed_observer(receipt):
        return unknown
    section = report['sections']['trace']
    if section['status'] != 'available':
        return unknown
    run = Path(section['run']).resolve()
    manifest = p.read_json(run / 'manifest.json')
    p.require(manifest['rtl']['emu_sha256'] == receipt['emulator']['sha256'], 'Clock observer manifest/receipt mismatch')
    db = p.recorded_artifact(run, manifest, 'chiseldb.db')
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        columns = {r[1] for r in conn.execute('PRAGMA table_info(XSAIClockSync)')}
        if not columns:
            return {**unknown, 'reason': 'Reviewed observer but no synchronization table in this run'}
        p.require({'TABLE_NAME', 'SEQID', 'SITE', 'CPU_STAMP', 'CUTE_STAMP'} <= columns, 'Clock synchronization schema differs')
        rows = conn.execute('SELECT TABLE_NAME,SEQID,SITE,CPU_STAMP,CUTE_STAMP FROM XSAIClockSync').fetchall()
        if not rows:
            return {**unknown, 'reason': 'No CUTE callbacks were observed; empty anchors do not prove alignment'}
        recorded = Counter()
        for table in TABLES:
            for seq, site, stamp in conn.execute(f'SELECT SEQID,SITE,STAMP FROM {table}'):
                recorded[(table, seq, site, stamp)] += 1
        observed = Counter((t, seq, site, cute) for t, seq, site, cpu, cute in rows)
        p.require(recorded == observed, 'Clock anchors do not cover the exact same CUTE events')
        p.require(all(t in TABLES and type(cpu) is int and type(cute) is int and cpu >= 0 and cute >= 0 for t, seq, site, cpu, cute in rows), 'Invalid clock anchor values')
        offsets = Counter(cpu - cute for t, seq, site, cpu, cute in rows)
        span = max(r[4] for r in rows) - min(r[4] for r in rows)
        sites = sorted({r[2] for r in rows})
        if len(rows) < 4 or span == 0 or len(offsets) != 1:
            return {'status': 'unproven', 'reason': 'Anchors do not establish a constant unit-slope mapping across this run',
                    'mapping': None, 'anchors': len(rows), 'cute_span_cycles': span,
                    'offset_histogram': dict(offsets), 'sites': sites}
        offset = next(iter(offsets))
        return {'status': 'validated', 'reason': 'Every CUTE event has a same-callback CPU stamp; all recorded anchors agree exactly with CPU = CUTE + offset.',
                'mapping': {'slope': 1, 'offset': offset, 'max_residual_cycles': 0,
                            'cute_min': min(r[4] for r in rows), 'cute_max': max(r[4] for r in rows)},
                'anchors': len(rows), 'cute_span_cycles': span, 'sites': sites,
                'scope': 'This single-core run and observed CUTE span only. Callback observation has clock-edge ordering semantics; no subcycle execution ordering is inferred.',
                'observer': receipt['clock_bridge'],
                'critical_path': None, 'note': 'Aligned residence/task intervals still do not establish causal critical paths or functional-unit occupancy.'}
