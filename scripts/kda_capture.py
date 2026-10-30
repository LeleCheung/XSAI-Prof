"""Explicit diagnostic annotations applied only to the collector's snapshot."""
import json
from pathlib import Path
import re
import sqlite3
from collections import Counter

import kda_profile as p

RECEIPT = '.xsai-prof-capture.json'
BEGIN, END = 1443, 1444


def instruction(imm):
    return (imm << 20) | 0x13


def hpm_plan(events, receipt):
    p.require(isinstance(events, list) and 0 < len(events) <= 29, 'hpm_events requires 1..29 counters')
    coding = receipt.get('hpm_event_coding', [])
    seen, result = set(), []
    for row in events:
        p.require(isinstance(row, dict) and set(row) <= {'counter', 'events', 'operators'} and {'counter', 'events'} <= set(row), 'Invalid custom HPM entry')
        c = row['counter']
        p.require(type(c) is int and 3 <= c <= 31 and c not in seen, 'Counters must be unique integers in 3..31')
        seen.add(c)
        group = next(g for lo, hi, g in ((3, 10, 'frontend'), (11, 18, 'backend'), (19, 26, 'memblock'), (27, 31, 'l2 cache')) if lo <= c <= hi)
        available = [e for e in coding if e['group'].casefold() == group]
        requested = row['events']
        p.require(isinstance(requested, list) and 1 <= len(requested) <= 4, 'Each selector needs 1..4 events')
        resolved = []
        for event in requested + [0] * (4 - len(requested)):
            found = [e for e in available if (type(event) is int and e['id'] == event) or (isinstance(event, str) and e['name'].strip() == event)]
            p.require(len(found) == 1 and 0 <= found[0]['id'] <= 1023, 'Event unavailable/ambiguous in counter group: ' + str(event))
            resolved.append(found[0])
        ops = row.get('operators', ['or'] * 3)
        p.require(isinstance(ops, list) and len(ops) == 3 and all(op in ('and', 'xor', 'add', 'or') for op in ops), 'Three explicit selector operators required')
        value = sum(e['id'] << (10 * i) for i, e in enumerate(resolved))
        value |= sum({'or': 0, 'and': 1, 'xor': 2, 'add': 4}[op] << (40 + 5 * i) for i, op in enumerate(ops))
        # Labels are generated locally; RTL names/signals remain in receipt.
        result.append({'counter': c, 'group': group, 'events': resolved, 'operators': ops,
                       'label': 'custom_' + str(c), 'selector': value})
    return sorted(result, key=lambda v: v['counter'])


def validate_ranges(ranges):
    p.require(isinstance(ranges, dict) and set(ranges) <= {'invocations', 'stages'}, 'ranges accepts invocations and stages')
    inv = ranges.get('invocations', [1, 2147483647])
    p.require(isinstance(inv, list) and len(inv) == 2 and all(type(n) is int for n in inv) and 1 <= inv[0] <= inv[1] <= 2147483647, 'invocations is a 1-based inclusive [first,last] range')
    stages = ranges.get('stages', [])
    p.require(isinstance(stages, list) and len(stages) <= 128, 'At most 128 named stages')
    names = set()
    for stage in stages:
        p.require(isinstance(stage, dict) and set(stage) == {'name', 'file', 'begin', 'end'}, 'Stage needs name, file, begin and end exact source anchors')
        p.require(isinstance(stage['name'], str) and re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', stage['name']) and stage['name'] not in names, 'Stage names must be unique safe identifiers')
        names.add(stage['name'])
        p.require(all(isinstance(stage[k], str) and stage[k] for k in ('file', 'begin', 'end')), 'Stage anchors must be nonempty strings')
    return json.loads(json.dumps({'invocations': inv, 'stages': stages}))


def apply(source, config):
    """Source anchors fail closed rather than guessing where C scopes end."""
    metadata = {'schema': 'xsai-prof.capture/v1', 'instrumentation': 'trace-only marker instructions; perf/HPM ranges compile to no-ops',
                'trace_volume': 'Full raw lifetime trace retained; invocation/stage selection is applied to recorded markers during analysis.'}
    if config.get('capture_scope', 'full') != 'full':
        metadata['capture_scope'] = config['capture_scope']
        metadata['trace_volume'] = 'Capture-side lifetime SQLite filtering in retirement order; all metadata tracked, all markers/CUTE tasks/interface events retained. Only selected lifetime instructions are available.'
    harness = source / 'test/test-ops.c'
    text = harness.read_text()
    max_runs = config.get('environment', {}).get('PERF_MAX_RUNS')
    if max_runs is not None:
        p.require(isinstance(max_runs, str) and max_runs.isdigit() and 0 < int(max_runs) <= 2147483647,
                  'PERF_MAX_RUNS must be a positive 32-bit integer')
        header_path = source / 'test/test.h'
        header = header_path.read_text()
        pattern = r'^#define PERF_MAX_RUNS[^\n]*$'
        matches = re.findall(pattern, header, re.MULTILINE)
        p.require(len(matches) == 1, 'Cannot substantiate upstream PERF_MAX_RUNS definition')
        header_path.write_text(re.sub(pattern, '#define PERF_MAX_RUNS ' + max_runs, header, flags=re.MULTILINE))
        metadata['max_runs'] = {'requested': int(max_runs), 'original_definition': matches[0],
                                'effective_definition': '#define PERF_MAX_RUNS ' + max_runs,
                                'policy': 'Explicit frozen harness definition; upstream only used the environment in its object-directory name.'}
    if config.get('ranges') is not None:
        ranges = validate_ranges(config['ranges'])
        metadata['ranges'] = ranges
        # The harness and kernel library have separate compilers/build rules.
        # Forward the trace-only switch through CMake, including cache changes
        # when the same private tree switches between perf and trace images.
        make_path = source / 'test/Makefile'
        make_text = make_path.read_text()
        anchor = '-DXSAI_BLAS_ENABLE_DEBUG_INFO=$(XSAI_BLAS_DEBUG_INFO)'
        p.require(make_text.count(anchor) == 1, 'Kernel debug/configure build hook differs')
        make_text = make_text.replace(anchor, '-DXSAI_PROF_TRACE=$(if $(filter yes,$(PERFCCT_MARKERS)),ON,OFF) \\\n\t  ' + anchor)
        make_path.write_text(make_text)
        cmake_path = source / 'CMakeLists.txt'
        cmake = cmake_path.read_text()
        cmake += '\n# xsai-prof: explicit trace-only annotations in kernel translation units.\noption(XSAI_PROF_TRACE "Enable profiler kernel range annotations" OFF)\nif(XSAI_PROF_TRACE)\n  add_compile_definitions(XSAI_BLAS_ENABLE_PERFCCT_MARKERS)\nendif()\n'
        cmake_path.write_text(cmake)
        metadata['kernel_trace_build'] = 'PERFCCT_MARKERS -> CMake XSAI_PROF_TRACE -> kernel compile definition; OFF for perf/HPM/correctness'
        first, last = ranges['invocations']
        header = ['#ifndef XSAI_PROF_RANGES_H', '#define XSAI_PROF_RANGES_H',
            '#if defined(XSAI_BLAS_ENABLE_PERFCCT_MARKERS) && defined(__riscv)',
            'extern int xsai_prof_active;',
            '#define XSAI_PROF_MARK(n) do { if (xsai_prof_active) { __asm__ volatile(".insn i 0x13, 0, x0, x0, " #n ::: "memory"); } } while (0)',
            f'#define XSAI_PROF_CALL_BEGIN(r) do {{ xsai_prof_active = ((r) + 1 >= {first} && (r) + 1 <= {last}); XSAI_PROF_MARK(1443); }} while (0)',
            '#define XSAI_PROF_CALL_END() do { XSAI_PROF_MARK(1444); xsai_prof_active = 0; } while (0)',
            '#else', '#define XSAI_PROF_MARK(n) ((void)0)', '#define XSAI_PROF_CALL_BEGIN(r) ((void)0)',
            '#define XSAI_PROF_CALL_END() ((void)0)', '#endif', '#endif', '']
        (source / 'include/xsai_prof_ranges.h').write_text('\n'.join(header))
        text = '#include "xsai_prof_ranges.h"\nint xsai_prof_active = 0;\n' + text
        loop = '    for (int r = 0; r < n_runs; r++) {\n      tc->run_opt(tc);\n    }'
        p.require(text.count(loop) == 1, 'Measured-call loop differs from supported harness')
        text = text.replace(loop, '    for (int r = 0; r < n_runs; r++) {\n      XSAI_PROF_CALL_BEGIN(r);\n      tc->run_opt(tc);\n      XSAI_PROF_CALL_END();\n    }')
        for i, stage in enumerate(ranges['stages']):
            path = (source / stage['file']).resolve()
            p.require(path.is_relative_to(source.resolve()) and path.is_file() and path != harness.resolve(), 'Stage file must be a kernel source within frozen snapshot')
            content = path.read_text()
            begin, end = stage['begin'], stage['end']
            p.require(content.count(begin) == 1 and content.count(end) == 1, 'Source anchors must each match exactly once: ' + stage['name'])
            a = content.index(begin)
            b = content.index(end) + len(end)
            p.require(a < b, 'Reversed stage anchors')
            content = content[:a] + f'\nXSAI_PROF_MARK({1536 + i * 2});\n' + content[a:b] + f'\nXSAI_PROF_MARK({1537 + i * 2});\n' + content[b:]
            if '#include "xsai_prof_ranges.h"' not in content:
                content = '#include "xsai_prof_ranges.h"\n' + content
            path.write_text(content)
            stage['begin_imm'], stage['end_imm'] = 1536 + 2 * i, 1537 + 2 * i
    if config.get('hpm_events') is not None:
        plan = hpm_plan(config['hpm_events'], p.read_json(config['rtl_config']))
        metadata['hpm_events'] = plan
        macro = '#undef XSAI_HPM_COUNTERS\n#define XSAI_HPM_COUNTERS(X) ' + ' \\\n  '.join(
            f'X({e["counter"]}, "{e["label"]}", 0x{e["selector"]:016x}ULL)' for e in plan)
        macro += '\n#undef XSAI_HPM_PROFILE_NAME\n#define XSAI_HPM_PROFILE_NAME "xsai-prof-custom"\n'
        anchor = 'typedef struct {\n  int counter;'
        p.require(text.count(anchor) == 1, 'HPM harness definition differs')
        text = text.replace(anchor, macro + '\n' + anchor)
        old = 'uint64_t total = end->value[i] - start->value[i];'
        p.require(text.count(old) == 1, 'HPM print indexing differs')
        text = text.replace(old, 'int index = xsai_hpm_descs[i].counter - 3;\n    uint64_t total = end->value[index] - start->value[index];')
    harness.write_text(text)
    p.dump(source / RECEIPT, metadata)
    return metadata


def ranges_from_db(db, metadata, window):
    ranges = metadata.get('ranges')
    if not ranges:
        return {'status': 'unavailable', 'reason': 'No invocation/stage capture metadata'}
    begin_codes = {instruction(s['begin_imm']): s['name'] for s in ranges['stages']}
    end_codes = {instruction(s['end_imm']): s['name'] for s in ranges['stages']}
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as connection:
        from kda_roi import collector
        capture_scope = collector(connection)
        if capture_scope['mode'] == 'full':
            rows = connection.execute('SELECT SN,MIN(DisAsm),MAX(AtCommit) FROM LifeTimeCommitTrace WHERE SN>? AND SN<? AND AtCommit>0 GROUP BY SN ORDER BY SN', (window['begin_sn'], window['end_sn']))
        else:
            lo = connection.execute('SELECT MAX(SN) FROM XSAIScopeMarker WHERE CODE=? AND SN<=?', (instruction(1441), window['begin_sn'])).fetchone()[0]
            hi = connection.execute('SELECT MIN(SN) FROM XSAIScopeMarker WHERE CODE=? AND SN>=?', (instruction(1442), window['end_sn'])).fetchone()[0]
            p.require(lo is not None and hi is not None, 'Collector range lacks surrounding original ROI markers')
            rows = connection.execute('SELECT SN,CODE,CPU_STAMP FROM XSAIScopeMarker WHERE SN>? AND SN<? ORDER BY SN', (lo, hi))
        events, stack, invocation, selected = [], [], None, 0
        for sn, code, stamp in rows:
            if code == instruction(BEGIN):
                p.require(invocation is None and not stack, 'Nested invocation marker')
                selected += 1
                invocation = {'kind': 'invocation', 'invocation': ranges['invocations'][0] + selected - 1, 'begin_sn': sn, 'begin_commit': stamp}
            elif code == instruction(END):
                p.require(invocation is not None and not stack, 'Unmatched invocation end or unfinished stage')
                events.append({**invocation, 'end_sn': sn, 'end_commit': stamp})
                invocation = None
            elif code in begin_codes:
                p.require(invocation is not None, 'Stage outside selected invocation')
                stack.append({'kind': 'stage', 'name': begin_codes[code], 'invocation': invocation['invocation'], 'begin_sn': sn, 'begin_commit': stamp})
            elif code in end_codes:
                p.require(stack and stack[-1]['name'] == end_codes[code], 'Mismatched stage marker nesting')
                events.append({**stack.pop(), 'end_sn': sn, 'end_commit': stamp})
        p.require(invocation is None and not stack, 'Incomplete range markers')
    missing = sorted(set(s['name'] for s in ranges['stages']) - {e['name'] for e in events if e['kind'] == 'stage'})
    for event in events:
        event['instructions_retained'] = (capture_scope['mode'] == 'full' or
            window['begin_sn'] <= event['begin_sn'] and event['end_sn'] <= window['end_sn'])
    return {'status': 'partial' if selected and missing else 'available' if selected else 'empty', 'events': events, 'selected_invocations': selected,
            'unobserved_stages': missing,
            'requested_invocations': ranges['invocations'], 'semantics': 'Marker commit intervals in diagnostic trace; includes instrumentation and overlapping work, not exclusive stage runtime or perf cycles.',
            'trace_volume': capture_scope.get('semantics', metadata['trace_volume']), 'collector': capture_scope}


def range_hotspots(db, ranges, pcs):
    """Per-range attribution checked against marker intervals and paired PCs."""
    pcmap = {int(row['pc'], 16): row for row in pcs}
    with sqlite3.connect(db.resolve().as_uri() + '?mode=ro', uri=True) as conn:
        for event in ranges.get('events', []):
            if event.get('instructions_retained') is False:
                event['metrics'] = {'status': 'unavailable', 'reason': 'Instructions outside captured range were omitted; marker duration alone is retained.'}
                continue
            query = '''WITH inst AS (
                SELECT SN,PC,MAX(AtCommit) t FROM LifeTimeCommitTrace
                WHERE SN>? AND SN<? AND AtCommit>0 GROUP BY SN,PC
              ), gaps AS (
                SELECT *,MAX(t) OVER (ORDER BY SN,PC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) previous
                FROM inst
              ) SELECT PC,COUNT(*),SUM(MAX(0,t-MAX(?,COALESCE(previous,?)))),MAX(t) FROM gaps GROUP BY PC'''
            functions, total, maximum = {}, 0, event['begin_commit']
            for pc, count, gaps, last in conn.execute(query, (event['begin_sn'], event['end_sn'], event['begin_commit'], event['begin_commit'])):
                p.require(pc in pcmap, 'Range PC absent from validated outer ROI')
                function = pcmap[pc]['function']
                values = functions.setdefault(function, Counter())
                values.update(instructions=count, retirement_gap_cycles=gaps)
                total += gaps
                maximum = max(maximum, last)
            duration = event['end_commit'] - event['begin_commit']
            trailing = max(0, event['end_commit'] - maximum)
            p.require(duration >= 0 and total + trailing == duration, 'Range attribution does not conserve marker interval')
            event['metrics'] = {'marker_interval_cycles': duration, 'attributed_retirement_gap_cycles': total,
                               'trailing_marker_cycles': trailing,
                               'instructions': sum(f['instructions'] for f in functions.values()),
                               'functions': [{'function': k, **v} for k,v in sorted(functions.items(), key=lambda kv: kv[1]['retirement_gap_cycles'], reverse=True)],
                               'semantics': 'Diagnostic marker interval and retirement-gap attribution; not uninstrumented or exclusive execution time.'}
    return ranges
