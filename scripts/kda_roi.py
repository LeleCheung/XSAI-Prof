"""Scope-aware adapter around the unchanged pinned upstream ROI analyzer."""
import sqlite3


def collector(connection):
    exists = connection.execute("SELECT 1 FROM sqlite_master WHERE name='XSAICollector'").fetchone()
    if not exists:
        return {'mode': 'full', 'status': 'legacy_full'}
    rows = connection.execute('SELECT * FROM XSAICollector').fetchall()
    if len(rows) != 1:
        raise RuntimeError('Collector requires one final summary row')
    row = rows[0]
    mode, seen, kept, seen_rows, kept_rows, opens, closes, active, last, schema = tuple(row)
    if schema != 'xsai-prof.observer/v1' or active or opens != closes:
        raise RuntimeError('Incomplete collector range or schema')
    if mode != 'full' and (not opens or kept > seen):
        raise RuntimeError('Collector selected no complete ranges or invalid counts')
    actual = connection.execute('SELECT COUNT(*) FROM LifeTimeCommitTrace').fetchone()[0]
    if actual != kept_rows:
        raise RuntimeError('Collector row accounting mismatch')
    return {'mode': mode, 'status': 'complete', 'seen_instructions': seen,
            'kept_instructions': kept, 'seen_rows': seen_rows, 'kept_rows': kept_rows,
            'opens': opens, 'closes': closes, 'last_cpu_stamp': last,
            'semantics': 'All instruction metadata tracked; SQLite insertion filtered in retirement SN order. All markers retained. CUTE and interface events retain full capture for boundary reconstruction.'}


def decorate(module):
    if getattr(module, '_xsai_scope_adapter', False):
        return module
    original = module.select_window

    def select(connection, number):
        metadata = collector(connection)
        if metadata['mode'] == 'full':
            return original(connection, number)
        mode = metadata['mode']
        if mode == 'invocation':
            begin = 1443
        elif mode.startswith('stage:') and mode[6:].isdigit() and 0 <= int(mode[6:]) <= 127:
            begin = 1536 + 2 * int(mode[6:])
        else:
            raise RuntimeError('Unknown collector mode')
        codes = ((begin << 20) | 0x13, ((begin + 1) << 20) | 0x13)
        rows = connection.execute('SELECT SN,PC,DisAsm,MAX(AtCommit) FROM LifeTimeCommitTrace WHERE DisAsm IN (?,?) AND AtCommit>0 GROUP BY SN,PC,DisAsm ORDER BY SN', codes).fetchall()
        pairs, pending = [], None
        for sn, pc, code, stamp in rows:
            if code == codes[0]:
                if pending is not None:
                    raise RuntimeError('Nested collector marker')
                pending = (sn, pc, stamp)
            else:
                if pending is None:
                    raise RuntimeError('Unmatched collector marker')
                pairs.append((pending, (sn, pc, stamp)))
                pending = None
        if pending is not None or not 1 <= number <= len(pairs):
            raise RuntimeError('Requested complete collector range is unavailable')
        begin_row, end_row = pairs[number - 1]
        return {'window': number, 'begin_sn': begin_row[0], 'begin_pc': begin_row[1],
                'begin_commit_cycle': begin_row[2], 'end_sn': end_row[0],
                'end_pc': end_row[1], 'end_commit_cycle': end_row[2],
                'collector_mode': mode, 'scope': 'Selected captured range; not the complete original outer ROI.'}
    module.select_window = select
    module._xsai_scope_adapter = True
    return module


if __name__ == '__main__':
    import kda_profile
    decorate(kda_profile.analyzer_module()).main()
