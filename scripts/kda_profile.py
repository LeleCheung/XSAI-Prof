"""Offline, evidence-bound profiling reports shared by humans and agents.

Collection stays in xsai_kda.py. This module never changes input runs or starts
an emulator. All views are rendered from the same versioned JSON document.
"""
from collections import Counter, defaultdict
import hashlib
import html
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import statistics
import subprocess
import sys
import tempfile
import zipfile

from kda_paths import ROOT, VENDOR, ADAPTER
from kda_version import __version__
SCHEMA = "xsai-kda.profile/v1"
BIND_FIELDS = ("selection", "rtl", "arch", "toolchain", "build_environment",
               "compiler", "runtime_source", "build_overrides", "rvv_enable",
               "test_harness", "backend")
SEMANTICS = {
    "performance": "Only uninstrumented RTL cycles/call establish speedup; scope is the recorded shape and configuration.",
    "hpm": "Separate instrumentation. Events may overlap; CPU counters do not cover all CUTE traffic. Missing is not zero.",
    "roi": "ROI means region of interest. Retirement gaps attribute time to the next committed instruction, not exclusive function execution time.",
    "latency": "Fetch-to-commit is overlapping pipeline residence, not an additive execution-time breakdown.",
    "cute": "CUTE stage intervals may overlap. CPU/CUTE clock offset is unproven; task scope is explicit, not inferred from CPU timestamps.",
    "instructions": "Dynamic counts describe emitted instructions, not measured DRAM bytes or arithmetic latency.",
}


def require(condition, message):
    if not condition:
        raise RuntimeError(message)


def read_json(path):
    return json.loads(Path(path).read_text())


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def dump(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + '\n')


def analyzer_module():
    name = '_kda_roi_report'
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(
            name, VENDOR / 'roi_hotspots.py')
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        spec.loader.exec_module(module)
    from kda_roi import decorate
    return decorate(sys.modules[name])


def native32(code):
    return code & 3 == 3 and code & 28 != 28


def run_path(path):
    path = Path(path).resolve()
    return path.parent if path.name == 'manifest.json' else path


def recorded_artifact(directory, manifest, name):
    require(name in manifest.get('artifacts', {}), f'Artifact not recorded: {directory / name}')
    path = (directory / name).resolve()
    require(path.is_relative_to(directory), f'Artifact escapes run: {name}')
    require(path.is_file() and digest(path) == manifest['artifacts'][name]['sha256'],
            f'Artifact changed or missing: {path}')
    return path


def load_input(entry, kda, mode):
    directory = run_path(entry['run'])
    manifest = kda.load_run(directory)
    require(manifest.get('target') == 'rtl' and manifest.get('mode') == mode,
            f'Expected RTL {mode} run: {directory}')
    check = manifest.get('correctness', {})
    require(check.get('failed') == 0 and check.get('passed', 0) > 0,
            f'Correctness gate missing: {directory}')
    require(check['passed'] == len(manifest.get('measurements', [])),
            f'Correctness/measurement case counts differ: {directory}')
    expected = 'none' if mode == 'perf' else mode
    require(manifest.get('instrumentation') == expected,
            f'Unexpected instrumentation: {directory}')
    for field in ('source', 'rtl', 'compiler', 'runtime_source'):
        require(manifest.get(field), f'Missing {field} identity: {directory}')
    if mode == 'perf':
        kda.compare_runs(manifest, manifest)
    source = None
    provenance = {'run': str(directory), 'manifest_sha256': digest(directory / 'manifest.json'),
                  'mode': mode, 'source': manifest['source']}
    if entry.get('source_receipt'):
        receipt_path = Path(entry['source_receipt']).resolve()
        receipt = read_json(receipt_path)
        require(receipt.get('identity') == manifest['source'],
                f'Source receipt identity differs: {receipt_path}')
        files = receipt['files']
        # Recompute the same whole-tree identity used by the collector.
        h = hashlib.sha256()
        for name, value in sorted(files.items()):
            h.update(name.encode() + b'\0')
            h.update(bytes.fromhex(value))
        require(h.hexdigest() == manifest['source']['sha256'],
                f'Source receipt file identity differs: {receipt_path}')
        archive = Path(entry.get('source_archive') or receipt_path.with_suffix('.zip')).resolve()
        require(archive.is_file(), f'Source archive missing: {archive}')
        with zipfile.ZipFile(archive) as zipped:
            require(len(zipped.namelist()) == len(files) and set(zipped.namelist()) == set(files),
                    f'Source archive file set differs: {archive}')
            for name, value in files.items():
                require(hashlib.sha256(zipped.read(name)).hexdigest() == value,
                        f'Source archive changed: {name}')
        source = {'files': files, 'archive': str(archive)}
        provenance.update(source_receipt=str(receipt_path),
                          source_receipt_sha256=digest(receipt_path),
                          source_archive=str(archive), source_archive_sha256=digest(archive))
    return {'path': directory, 'manifest': manifest, 'provenance': provenance, 'source': source}


def bind(reference, diagnostic):
    a, b = reference['manifest'], diagnostic['manifest']
    for field in BIND_FIELDS:
        require(a.get(field) == b.get(field), f'Diagnostic workload/build differs: {field}')
    require(a['source'] == b['source'], 'Diagnostic source identity differs')
    require([(r['op'], r['unit']) for r in a['measurements']] ==
            [(r['op'], r['unit']) for r in b['measurements']],
            'Diagnostic operator shape or unit differs')


def tools_for_trace(manifest, options):
    llvm = Path(manifest.get('build_environment', {}).get('LLVM_HOME') or '') / 'bin'
    result = {}
    for name in ('objdump', 'addr2line', 'readelf'):
        explicit = options.get(name)
        candidates = [explicit] if explicit else [str(llvm / ('llvm-' + name)),
                      shutil.which('riscv64-linux-gnu-' + name), shutil.which(name)]
        # LLVM multicall tools select behavior from argv[0]; keep symlink names
        # such as llvm-readelf -> llvm-readobj and llvm-addr2line -> llvm-symbolizer.
        found = next((str(Path(v).absolute()) for v in candidates if v and Path(v).is_file()), None)
        require(found is not None or name == 'addr2line', f'{name} unavailable; specify --{name}')
        result[name] = found
    # XSAI custom decoding is available in the ROI analyzer even for <unknown>.
    result['objdump_mattr'] = options.get('objdump_mattr') or ''
    return result


def mnemonic_class(instruction):
    mnemonic = instruction.split()[0] if instruction else 'unknown'
    if re.fullmatch(r'vl(?:e|se|uxei|oxei|seg)\w*\.v', mnemonic):
        return 'vector_load'
    if mnemonic.startswith(('vsext.', 'vzext.')):
        return 'vector_extension'
    if mnemonic.startswith(('vfwcvt.', 'vfcvt.', 'vfncvt.')):
        return 'vector_conversion'
    if mnemonic.startswith(('vfmacc.', 'vfnmacc.', 'vfmsac.', 'vfnmsac.')):
        return 'vector_fma'
    if re.fullmatch(r'(?:vs[1248]r|vl[1248]re\d+)\.v', mnemonic):
        return 'whole_register_memory'
    if mnemonic.startswith('vset'):
        return 'vector_configuration'
    return 'other'


def archived_source(location, source):
    if not source:
        return None
    match = re.search(r' at (.*?):(\d+)', location or '')
    if not match:
        return None
    absolute, line = match.group(1), int(match.group(2))
    matches = [p for p in source['files'] if absolute == p or absolute.endswith('/' + p)]
    if len(matches) != 1:
        return None
    cache = source.setdefault('_text_cache', {})
    if matches[0] not in cache:
        with zipfile.ZipFile(source['archive']) as zipped:
            cache[matches[0]] = zipped.read(matches[0]).decode(errors='replace').splitlines()
    lines = cache[matches[0]]
    start, end = max(1, line - 2), min(len(lines), line + 2)
    return {'file': matches[0], 'line': line,
            'sha256': source['files'][matches[0]],
            'lines': [{'number': i, 'text': lines[i - 1]} for i in range(start, end + 1)]}


def cute_summary(connection, policy):
    tables = {r[0] for r in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    wanted = {'CUTELoadEvent': ('LoadIssue', 'LoadFinish'),
              'CUTEComputeEvent': ('ComputeIssue', 'ComputeWriteCFinish'),
              'CUTEStoreEvent': ('StoreIssue', 'StoreFinish')}
    available = set(wanted) & tables
    if not available:
        return {'status': 'unavailable', 'reason': 'CUTE event tables absent', 'stages': []}
    require(available == set(wanted) and 'CUTEReleaseEvent' in tables,
            'Incomplete CUTE event table set')
    scoped = bool(policy)
    skip = policy.get('warmup_tasks', 0)
    count = policy.get('measured_tasks')
    require(isinstance(skip, int) and skip >= 0 and not isinstance(skip, bool),
            'warmup_tasks must be a non-negative integer')
    if scoped:
        require(isinstance(count, int) and not isinstance(count, bool) and count > 0,
                'measured_tasks must be a positive integer')
    stages, task_counts, absent_stages = [], [], []
    for table, (begin, end) in wanted.items():
        groups = defaultdict(list)
        for row in connection.execute(f'SELECT * FROM {table} ORDER BY STAMP'):
            groups[int(row['SEQID'])].append(dict(row))
        roles = defaultdict(list)
        for seq, rows in sorted(groups.items()):
            sites = {}
            for row in rows:
                require(row['SITE'] not in sites, f'Duplicate CUTE site: {table}/{seq}/{row["SITE"]}')
                sites[row['SITE']] = int(row['STAMP'])
            require(begin in sites and end in sites and sites[end] >= sites[begin],
                    f'Incomplete CUTE task: {table}/{seq}')
            role = str(rows[0]['NEEDMASK']) if table == 'CUTELoadEvent' else 'all'
            roles[role].append({'seq_id': seq, 'duration': sites[end] - sites[begin],
                                'begin_stamp': sites[begin], 'end_stamp': sites[end]})
        if not roles:
            require(not scoped, f'Empty CUTE table: {table}')
            absent_stages.append(table)
            continue
        for role, tasks in sorted(roles.items()):
            if scoped:
                require(len(tasks) == skip + count,
                        f'CUTE task count differs: {table}/{role}: {len(tasks)} != {skip + count}')
            chosen = tasks[skip:] if scoped else tasks
            durations = [t['duration'] for t in chosen]
            stages.append({'table': table, 'role': role, 'total_tasks': len(tasks),
                           'selected_tasks': len(chosen), 'tasks': chosen,
                           'median_cycles': statistics.median(durations),
                           'min_cycles': min(durations), 'max_cycles': max(durations)})
            task_counts.append(len(tasks))
    releases = connection.execute('SELECT COUNT(*) FROM CUTEReleaseEvent').fetchone()[0]
    if not stages:
        return {'status': 'unavailable', 'reason': 'Selected CUTE tables contain no observed complete tasks',
                'stages': [], 'absent_stages': absent_stages, 'release_events': releases}
    agreement = all(n == releases for n in task_counts)
    if scoped:
        require(agreement, 'CUTE load/compute/store/release task counts differ')
    return {'status': 'available' if scoped else 'unscoped',
            'scope': policy if scoped else 'all recorded tasks, possibly including warmup and non-ROI work',
            'release_events': releases, 'stages': stages,
            'task_release_count_agreement': agreement,
            'task_release_semantics': 'Unscoped tasks can have multiple release groups; no one-release-per-stage assumption. Explicit legacy task scope retains its count validation.',
            'absent_stages': absent_stages,
            'semantics': SEMANTICS['cute']}


def trace_section(item, options, output):
    manifest, directory = item['manifest'], item['path']
    db = recorded_artifact(directory, manifest, 'chiseldb.db')
    elf = recorded_artifact(directory, manifest, 'profile.elf')
    perf_elf = recorded_artifact(directory, manifest, 'perf.elf')
    require(digest(elf) == digest(perf_elf), 'Trace profile.elf differs from collected perf.elf')
    toolset = tools_for_trace(manifest, options)
    analyzer = analyzer_module()
    archived = directory / 'roi/hotspots.json'
    if options.get('recompute_roi') or not archived.is_file():
        roi_output = output / 'roi'
        command = [sys.executable, str(Path(__file__).with_name('kda_roi.py')),
                   '--db', str(db), '--elf', str(elf), '--output', str(roi_output),
                   '--window', str(options.get('window', 1))]
        for name, value in toolset.items():
            if value:
                command += ['--' + name.replace('_', '-'), value]
        result = subprocess.run(command, capture_output=True, text=True)
        (output / 'roi-analysis.log').write_text(result.stdout + result.stderr)
        require(result.returncode == 0, 'ROI analyzer failed: ' + result.stderr[-2000:])
        report = read_json(roi_output / 'hotspots.json')
        detail = roi_output / 'index.html'
    else:
        recorded_artifact(directory, manifest, 'roi/hotspots.json')
        report = read_json(archived)
        detail = directory / 'roi/index.html'
    encodings = analyzer.elf_instruction_encodings(elf, toolset['objdump'], toolset['objdump_mattr'])
    require(encodings, 'Cannot decode ELF instructions for full trace pairing check')
    connection = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        analyzer.require_trace_schema(connection)
        window = analyzer.select_window(connection, options.get('window', 1))
        require(all(report['window'].get(k) == v for k, v in window.items()),
                'ROI report window differs from requested database marker pair; use --recompute-roi')
        stats = {}
        # Recompute dynamic counts and gap attribution from the raw database,
        # grouping uops and using the preceding maximum commit like the analyzer.
        query = '''WITH instructions AS (
          SELECT SN, PC, MIN(DisAsm) lo, MAX(DisAsm) hi,
                 MAX(AtCommit) committed, COUNT(*) uops
          FROM LifeTimeCommitTrace WHERE AtCommit > 0 AND SN > ? AND SN < ? GROUP BY SN, PC
        ), gaps AS (
          SELECT *, MAX(committed) OVER (ORDER BY SN, PC ROWS BETWEEN UNBOUNDED PRECEDING AND 1 PRECEDING) previous
          FROM instructions
        ) SELECT PC, MIN(lo), MAX(hi), COUNT(*), SUM(uops),
                 SUM(MAX(0, committed - MAX(?, COALESCE(previous, ?))))
          FROM gaps GROUP BY PC'''
        native = skipped = 0
        for row in connection.execute(query, (window['begin_sn'], window['end_sn'],
                                               window['begin_commit_cycle'], window['begin_commit_cycle'])):
            pc, lo, hi, count, uops, gaps = tuple(row)
            require(pc in encodings, f'Trace PC absent from ELF: {pc:#x}')
            if native32(encodings[pc]):
                require(lo == hi == encodings[pc], f'Trace and ELF do not match at PC {pc:#x}')
                native += 1
            else:
                skipped += 1
            stats[pc] = {'instructions': count, 'uops': uops, 'retirement_cycles': gaps}
        require(native > 0, 'No native 32-bit PCs available to verify ELF/trace pairing')
        pcs = {int(p['pc'], 16): p for p in report['pcs']}
        require(stats.keys() == pcs.keys(), 'ROI report PC set differs from database')
        for pc, expected in stats.items():
            require(all(pcs[pc].get(k) == v for k, v in expected.items()),
                    f'ROI report counts/attribution differ at PC {pc:#x}')
        w = report['window']
        roi_cycles = window['end_commit_cycle'] - window['begin_commit_cycle']
        require(w['roi_cycles'] == roi_cycles and
                w['attributed_cycles'] + w['trailing_marker_cycles'] == roi_cycles and
                sum(p['retirement_cycles'] for p in pcs.values()) == w['attributed_cycles'] and
                sum(p['instructions'] for p in pcs.values()) == w['committed_instructions'],
                'ROI cycle/instruction conservation failed')
        try:
            symbols = analyzer.SymbolTable(elf, toolset['readelf'])
        except SystemExit as exc:
            raise RuntimeError(str(exc)) from exc
        functions = {f['function']: f for f in report['functions']}
        counts = defaultdict(Counter)
        for pc, p in pcs.items():
            name = symbols.lookup(pc)[0]
            require(p['function'] == name and name in functions, 'ROI ELF function mapping differs')
            counts[name].update({k: p[k] for k in ('instructions', 'uops', 'retirement_cycles')})
        require(counts.keys() == functions.keys() and all(
            all(functions[name][k] == v for k, v in values.items()) for name, values in counts.items()),
            'ROI function attribution does not conserve PC counts')
        cute = cute_summary(connection, options.get('cute') or {})
        from kda_roi import collector
        collection_scope = collector(connection)
    finally:
        connection.close()
    # Re-read assembly and line mappings from this ELF instead of trusting
    # archived mnemonic text. Source text comes only from a verified source zip.
    assembly = analyzer.disassembly_context(elf, toolset['objdump'], stats,
                                            objdump_mattr=toolset['objdump_mattr'])
    locations = analyzer.source_locations(elf, toolset['addr2line'], stats)
    by_function, mnemonics = defaultdict(Counter), defaultdict(Counter)
    for pc, p in pcs.items():
        p.update(assembly[pc])
        p['source'] = locations.get(pc, 'N/A')
        p['instruction_class'] = mnemonic_class(p['instruction'])
        p['archived_source'] = archived_source(p['source'], item['source'])
        by_function[p['function']][p['instruction_class']] += p['instructions']
        mnemonics[p['function']][p['instruction'].split()[0]] += p['instructions']
    ranges = {'status': 'unavailable', 'reason': 'No recorded capture metadata'}
    if 'capture.json' in manifest['artifacts']:
        import kda_capture
        capture = read_json(recorded_artifact(directory, manifest, 'capture.json'))
        ranges = kda_capture.ranges_from_db(db, capture, report['window'])
        ranges = kda_capture.range_hotspots(db, ranges, pcs.values())
    section = {'status': 'available', 'run': str(directory), 'window': report['window'],
            'ranges': ranges, 'collector': collection_scope,
            'functions': report['functions'],
            'pcs': sorted(pcs.values(), key=lambda p: p['retirement_cycles'], reverse=True),
            'instruction_mix': {k: dict(v) for k, v in sorted(by_function.items())},
            'mnemonics': {k: dict(v) for k, v in sorted(mnemonics.items())},
            'elf_validation': {'native_32bit_pcs_checked': native,
                               'compressed_or_wide_pcs_skipped': skipped,
                               'scope': 'All native 32-bit PCs in selected ROI; RVC decompression is not compared.'},
            'tools': {k: {'path': v, 'sha256': digest(v)} for k, v in toolset.items()
                      if v and k != 'objdump_mattr'},
            'objdump_mattr': toolset['objdump_mattr'],
            'detail_report': str(detail), 'cute': cute, 'semantics': SEMANTICS['roi']}
    from kda_observer import reviewed
    receipt_names = [n for n in manifest['artifacts'] if n.startswith('rtl-config.')]
    receipt = read_json(recorded_artifact(directory, manifest, receipt_names[0])) if len(receipt_names) == 1 else None
    if collection_scope['mode'] != 'full':
        require(reviewed(receipt) and manifest['rtl']['emu_sha256'] == receipt['emulator']['sha256'], 'Filtered lifetime metadata requires the reviewed observer receipt')
        require(manifest.get('trace_capture', {}).get('scope') == collection_scope['mode'], 'Collector DB mode differs from recorded trace invocation')
    section['memory'] = {'status': 'unavailable', 'reason': 'No reviewed actual-interface capture', 'metrics': None}
    if reviewed(receipt):
        from kda_memory import memory
        section['memory'] = memory({'sections': {'trace': section}})
        require(section['memory']['status'] != 'invalid', 'Actual interface protocol evidence is invalid')
    return section


def hpm_section(item, kda):
    manifest, directory = item['manifest'], item['path']
    log = recorded_artifact(directory, manifest, 'perf.log').read_text(errors='replace')
    config = next((n for n in manifest['artifacts'] if n.startswith('rtl-config.')), None)
    require(config, 'HPM run has no recorded RTL config')
    receipt_path = recorded_artifact(directory, manifest, config)
    try:
        receipt = read_json(receipt_path)
    except (ValueError, UnicodeError):
        receipt = {}
    rows = kda.hpm_measurements(log, receipt.get('hpm_event_coding'))
    require(rows, 'No HPM counters found in recorded perf.log')
    require(len({r['counter'] for r in rows}) == len(rows), 'Duplicate HPM counters')
    return {'status': 'available', 'run': str(directory), 'counters': rows,
            'encoding_resolved': all(r['encoding_resolved'] for r in rows),
            'semantics': SEMANTICS['hpm']}


def performance_section(items):
    first = items[0]['manifest']['measurements']
    measurements = []
    for row in first:
        rows = [next(r for r in i['manifest']['measurements']
                     if (r['op'], r['unit']) == (row['op'], row['unit'])) for i in items]
        cycles = [r['cycles_per_run'] for r in rows]
        measurements.append({'op': row['op'], 'unit': row['unit'], 'cycles': cycles,
                             'median_cycles': statistics.median(cycles),
                             'min_cycles': min(cycles), 'max_cycles': max(cycles),
                             'instret': [r.get('instret_per_run') for r in rows],
                             'ipc': [r.get('ipc') for r in rows],
                             'elements_per_cycle': [r.get('elements_per_cycle') for r in rows]})
    return {'status': 'available', 'repeat_count': len(items), 'measurements': measurements,
            'semantics': SEMANTICS['performance']}


def normalize_spec(spec, base):
    result = json.loads(json.dumps(spec))
    require(result.get('perf'), 'At least one perf run is required')
    def entry(value):
        value = {'run': value} if isinstance(value, str) else dict(value)
        for key in ('run', 'source_receipt', 'source_archive'):
            if value.get(key):
                value[key] = str((base / value[key]).resolve())
        require('run' in value, 'Run entry requires a run path')
        return value
    result['perf'] = [entry(v) for v in result['perf']]
    for mode in ('hpm', 'trace'):
        if result.get(mode):
            result[mode] = entry(result[mode])
    return result


def build_report(spec, options, output, kda):
    perf = [load_input(e, kda, 'perf') for e in spec['perf']]
    require(len({str(i['path']) for i in perf}) == len(perf), 'Duplicate perf runs are not independent repeats')
    for item in perf[1:]:
        kda.compare_runs(perf[0]['manifest'], item['manifest'])
        bind(perf[0], item)
        require(perf[0]['manifest']['source'] == item['manifest']['source'], 'Perf repeat source identity differs')
    warnings = []
    if any(i['manifest'].get('synthetic_fixture') for i in perf):
        warnings.append('SYNTHETIC FIXTURE: values are not measured hardware or simulator performance.')
    if len(perf) < 2:
        warnings.append('Only one uninstrumented perf run; repeated performance is not established.')
    if not perf[0]['manifest'].get('test_harness'):
        warnings.append('Legacy manifest has no test_harness hashes; harness equality is not independently substantiated.')
    sections = {'performance': performance_section(perf)}
    inputs = list(perf)
    for mode in ('hpm', 'trace'):
        if not spec.get(mode):
            sections[mode] = {'status': 'unavailable', 'reason': f'No {mode} run supplied'}
            warnings.append(f'{mode.upper()} evidence unavailable.')
            continue
        diagnostic = load_input(spec[mode], kda, mode)
        bind(perf[0], diagnostic)
        inputs.append(diagnostic)
        if mode == 'hpm':
            sections[mode] = hpm_section(diagnostic, kda)
            if not sections[mode]['encoding_resolved']:
                warnings.append('Some HPM event selectors are unresolved; their hardware meaning is not verified.')
        else:
            sections[mode] = trace_section(diagnostic, {**options, 'cute': spec.get('cute')}, output)
            if sections[mode].get('collector', {}).get('mode', 'full') != 'full':
                warnings.append('Capture-side filtered lifetime trace: hotspots cover only the selected captured range. Omitted invocation/outer-ROI instructions are unavailable, not zero.')
            if sections[mode]['cute']['status'] == 'unscoped':
                warnings.append('CUTE task scope not supplied; all-task durations include possible warmup/non-ROI work.')
    if not all(i['source'] for i in inputs):
        warnings.append('Some source archives were not supplied; binding uses recorded whole-tree source identities. Source text is shown only from verified archives.')
    observations = []
    trace = sections['trace']
    if trace['status'] == 'available':
        top = trace['functions'][0]
        observations.append({'kind': 'hotspot', 'function': top['function'],
                             'retirement_share_pct': top['retirement_cycle_percent'],
                             'evidence': 'trace.functions[0]',
                             'interpretation': 'Start source inspection here; attribution alone does not identify the cause.'})
    return {'schema': SCHEMA, 'kind': 'profile', 'label': spec.get('label') or perf[0]['path'].name,
            'spec': spec, 'options': options, 'metric_semantics': SEMANTICS,
            'identity': {k: perf[0]['manifest'].get(k) for k in (*BIND_FIELDS, 'source')},
            'inputs': [i['provenance'] for i in inputs], 'sections': sections,
            'observations': observations, 'warnings': warnings,
            'producer': {'version': __version__, 'adapter_sha256': digest(Path(__file__)),
                         'collector_sha256': digest(ADAPTER),
                         'roi_analyzer_sha256': digest(VENDOR / 'roi_hotspots.py'),
                         'roi_scope_adapter_sha256': digest(Path(__file__).with_name('kda_roi.py')),
                         'memory_analyzer_sha256': digest(Path(__file__).with_name('kda_memory.py')),
                          'cpu_memory_analyzer_sha256': digest(Path(__file__).with_name('kda_cpu_memory.py')),
                          'ame_read_analyzer_sha256': digest(Path(__file__).with_name('kda_ame_memory.py'))},
            'validation': {'status': 'passed', 'artifact_hashes': 'verified',
                           'diagnostics_bound_to_perf': True,
                           'source_archives': 'verified' if all(i['source'] for i in inputs) else 'partial_or_absent'}}


def verify_saved_report(path, kda):
    directory = Path(path).resolve()
    if directory.is_file():
        directory = directory.parent
    receipt = read_json(directory / 'checksums.json')
    require(receipt.get('schema') == 'xsai-kda.profile-files/v1', 'Unsupported report checksum schema')
    for name, expected in receipt['files'].items():
        require((directory / name).resolve().is_relative_to(directory), 'Report artifact escapes directory')
        require((directory / name).is_file() and digest(directory / name) == expected,
                f'Report artifact changed: {name}')
    require('report.json' in receipt['files'], 'Report checksum missing')
    report = read_json(directory / 'report.json')
    require(report.get('schema') == SCHEMA and report.get('kind') == 'profile', 'Expected a profile report')
    for item in report['inputs']:
        run = Path(item['run'])
        require(digest(run / 'manifest.json') == item['manifest_sha256'], 'Input manifest changed since report')
        kda.load_run(run)
        for key in ('source_receipt', 'source_archive'):
            if key in item:
                require(digest(item[key]) == item[key + '_sha256'], f'{key} changed since report')
    return report, directory


def keyed_rows(rows, fields):
    result = {tuple(row[f] for f in fields): row for row in rows}
    require(len(result) == len(rows), 'Duplicate metric keys')
    return result


def compare_reports(a, b, paths, kda):
    # Reuse existing performance comparison checks on the original manifests.
    am = kda.load_run(a['inputs'][0]['run'])
    bm = kda.load_run(b['inputs'][0]['run'])
    kda.compare_runs(am, bm)
    require(a['identity'].get('backend') == b['identity'].get('backend'), 'Comparison backend differs')
    warnings = list(dict.fromkeys(a['warnings'] + b['warnings']))
    sections = {}
    left = keyed_rows(a['sections']['performance']['measurements'], ('op', 'unit'))
    right = keyed_rows(b['sections']['performance']['measurements'], ('op', 'unit'))
    require(left.keys() == right.keys(), 'Performance shapes differ')
    rows = []
    for key, x in left.items():
        y = right[key]
        rows.append({'op': key[0], 'unit': key[1], 'baseline_cycles': x['cycles'],
                     'candidate_cycles': y['cycles'],
                     'speedup': x['median_cycles'] / y['median_cycles'],
                     'cycle_reduction_pct': (1 - y['median_cycles'] / x['median_cycles']) * 100,
                     'stable_win_in_recorded_runs': max(y['cycles']) < min(x['cycles']),
                     'independent_repeats_both': len(x['cycles']) >= 2 and len(y['cycles']) >= 2})
    sections['performance'] = {'status': 'available', 'measurements': rows}
    for mode in ('hpm', 'trace'):
        x, y = a['sections'][mode], b['sections'][mode]
        if x['status'] != 'available' or y['status'] != 'available':
            sections[mode] = {'status': 'unavailable', 'reason': f'Paired {mode} evidence not supplied'}
            continue
        if mode == 'hpm':
            old = keyed_rows(x['counters'], ('counter',))
            new = keyed_rows(y['counters'], ('counter',))
            require(old.keys() == new.keys(), 'HPM counter sets differ')
            counters = []
            for key, lhs in old.items():
                rhs = new[key]
                require(int(lhs['config'], 16) == int(rhs['config'], 16) and
                        lhs['event_ids'] == rhs['event_ids'] and lhs['operators'] == rhs['operators'] and
                        lhs['rtl_event_names'] == rhs['rtl_event_names'], 'HPM selectors/events differ')
                resolved = lhs['encoding_resolved'] and rhs['encoding_resolved']
                counters.append({'counter': lhs['counter'], 'events': lhs['rtl_event_names'],
                                 'operators': lhs['operators'], 'selector': lhs['config'],
                                 'group': lhs['group'], 'encoding_resolved': resolved,
                                 'baseline_per_call': lhs['per_run'], 'candidate_per_call': rhs['per_run'],
                                 'delta_per_call': rhs['per_run'] - lhs['per_run'] if resolved else None})
            sections[mode] = {'status': 'available', 'counters': counters}
        else:
            require(a['options'].get('window', 1) == b['options'].get('window', 1), 'ROI window selection differs')
            require(x.get('collector', {}).get('mode', 'full') == y.get('collector', {}).get('mode', 'full'), 'Trace collector scopes differ')
            old = {r['function']: r for r in x['functions']}
            new = {r['function']: r for r in y['functions']}
            functions, mix, mnemonics = [], [], []
            for name in sorted(old.keys() | new.keys()):
                lhs, rhs = old.get(name, {}), new.get(name, {})
                functions.append({'function': name,
                                  **{role + '_' + metric: value.get(metric, 0)
                                     for role, value in (('baseline', lhs), ('candidate', rhs))
                                     for metric in ('instructions', 'retirement_cycles')},
                                  'instruction_delta': rhs.get('instructions', 0) - lhs.get('instructions', 0)})
                lmix, rmix = x['instruction_mix'].get(name, {}), y['instruction_mix'].get(name, {})
                for kind in sorted(lmix.keys() | rmix.keys()):
                    mix.append({'function': name, 'class': kind, 'baseline': lmix.get(kind, 0),
                                'candidate': rmix.get(kind, 0),
                                'delta': rmix.get(kind, 0) - lmix.get(kind, 0)})
                lm, rm = x['mnemonics'].get(name, {}), y['mnemonics'].get(name, {})
                for mnemonic in sorted(lm.keys() | rm.keys()):
                    mnemonics.append({'function': name, 'mnemonic': mnemonic,
                                      'baseline': lm.get(mnemonic, 0), 'candidate': rm.get(mnemonic, 0),
                                      'delta': rm.get(mnemonic, 0) - lm.get(mnemonic, 0)})
            cute = {'status': 'unavailable', 'reason': 'Paired CUTE task scope not established'}
            if x['cute']['status'] == y['cute']['status'] == 'available':
                require(x['cute']['scope'] == y['cute']['scope'], 'CUTE task scopes differ')
                ls = keyed_rows(x['cute']['stages'], ('table', 'role'))
                rs = keyed_rows(y['cute']['stages'], ('table', 'role'))
                require(ls.keys() == rs.keys(), 'CUTE stage roles differ')
                cute = {'status': 'available', 'stages': [
                    {'table': key[0], 'role': key[1], 'baseline_median_cycles': v['median_cycles'],
                     'candidate_median_cycles': rs[key]['median_cycles'],
                     'delta_cycles': rs[key]['median_cycles'] - v['median_cycles']}
                    for key, v in ls.items()]}
            from kda_memory import compare as compare_memory
            sections[mode] = {'status': 'available', 'functions': functions, 'memory': compare_memory(x, y),
                              'instruction_mix': mix, 'mnemonics': mnemonics, 'cute': cute,
                              'windows': {'baseline': x['window'], 'candidate': y['window']}}
    return {'schema': SCHEMA, 'kind': 'comparison',
            'label': a['label'] + ' → ' + b['label'], 'sections': sections,
            'metric_semantics': SEMANTICS, 'warnings': warnings,
            'baseline_report': str(paths[0]), 'candidate_report': str(paths[1]),
            'report_inputs': {role: {'path': str(path), 'report_sha256': digest(path / 'report.json'),
                                    'checksums_sha256': digest(path / 'checksums.json')}
                              for role, path in zip(('baseline', 'candidate'), paths)},
            'producer': {'version': __version__, 'adapter_sha256': digest(Path(__file__))},
            'observations': [], 'validation': {'status': 'passed',
                'scope': 'Report integrity and original run artifacts verified; this is not a correctness/ablation selection audit.'}}


def fmt(value):
    if value is None:
        return 'unavailable'
    if isinstance(value, float):
        return f'{value:,.4f}'.rstrip('0').rstrip('.')
    return str(value)


def table(headers, rows):
    def cell(v):
        return fmt(v).replace('|', '\\|').replace('\n', '<br>')
    return ['| ' + ' | '.join(headers) + ' |', '| ' + ' | '.join(['---'] * len(headers)) + ' |',
            *['| ' + ' | '.join(cell(v) for v in row) + ' |' for row in rows], '']


def markdown(report, directory):
    compare = report['kind'] == 'comparison'
    lines = ['# XSAI profiling: ' + report['label'], '',
             'Scope: RTL simulation. ' + SEMANTICS['performance'], '',
             '## Evidence and limitations', '']
    lines += ['- ' + v for v in report['warnings']] or ['- Required input validation passed.']
    lines += ['', '## Performance', '', SEMANTICS['performance'], '']
    perf = report['sections']['performance']
    if compare:
        lines += table(['Operator', 'Baseline cycles/call', 'Candidate cycles/call', 'Speedup', 'Cycle reduction %', 'Repeated on both sides'],
                       [[r['op'], r['baseline_cycles'], r['candidate_cycles'], r['speedup'],
                         r['cycle_reduction_pct'], r['independent_repeats_both']] for r in perf['measurements']])
        for role in ('baseline', 'candidate'):
            target = os.path.relpath(Path(report[role + '_report']) / 'index.html', directory)
            lines += [f'[{role.title()} details]({target})', '']
    else:
        lines += table(['Operator', 'Compute unit label', 'Cycles/call', 'Median cycles/call', 'Instret/call'],
                       [[r['op'], r['unit'], r['cycles'], r['median_cycles'], r['instret']]
                        for r in perf['measurements']])
        ident = report['identity']
        lines += ['## Workload and build', '', '```json', json.dumps(ident, ensure_ascii=False, indent=2), '```', '']
    hpm = report['sections']['hpm']
    lines += ['## CPU execution and memory counters', '', SEMANTICS['hpm'], '']
    if hpm['status'] != 'available':
        lines += [hpm['reason'], '']
    else:
        for group in ('frontend', 'backend', 'memblock', 'l2 cache', None):
            counters = [r for r in hpm['counters'] if r.get('group') == group]
            if not counters:
                continue
            lines += ['### ' + (group or 'unclassified'), '']
            if compare:
                lines += table(['Counter', 'RTL events', 'Operators', 'Baseline/call', 'Candidate/call', 'Delta/call', 'Resolved'],
                               [[r['counter'], r['events'], r['operators'], r['baseline_per_call'],
                                 r['candidate_per_call'], r['delta_per_call'], r['encoding_resolved']] for r in counters])
            else:
                lines += table(['Counter', 'RTL events', 'Operators', 'Count/call', 'Resolved', 'Upstream label'],
                               [[r['counter'], r['rtl_event_names'], r['operators'], r['per_run'],
                                 r['encoding_resolved'], r['upstream_label']] for r in counters])
    trace = report['sections']['trace']
    lines += ['## ROI and source hotspots', '', SEMANTICS['roi'], '', SEMANTICS['latency'], '']
    if trace['status'] != 'available':
        lines += [trace['reason'], '']
    elif compare:
        lines += table(['Function', 'Baseline instructions', 'Candidate instructions', 'Delta instructions', 'Baseline attributed cycles', 'Candidate attributed cycles'],
                       [[r['function'], r['baseline_instructions'], r['candidate_instructions'], r['instruction_delta'],
                         r['baseline_retirement_cycles'], r['candidate_retirement_cycles']] for r in trace['functions']])
        lines += ['## RVV / instruction mix', '', SEMANTICS['instructions'], '']
        lines += table(['Function', 'Class', 'Baseline', 'Candidate', 'Delta'],
                       [[r['function'], r['class'], r['baseline'], r['candidate'], r['delta']]
                        for r in trace['instruction_mix'] if r['class'] != 'other'])
    else:
        w = trace['window']
        lines += ['Collector scope: ' + json.dumps(trace.get('collector', {'mode': 'full'})), '']
        lines += [f'ROI cycles: {w["roi_cycles"]}; committed instructions: {w["committed_instructions"]}; '
                  f'trailing marker cycles: {w["trailing_marker_cycles"]}.', '',
                  'ELF/trace pairing: ' + json.dumps(trace['elf_validation']), '',
                  '[Detailed ROI report](' + os.path.relpath(trace['detail_report'], directory) + ')', '',
                  '[Search all PCs, source and assembly](source-assembly.html)', '']
        lines += table(['Function', 'Dynamic instructions', 'Attributed cycles', 'Attributed share %'],
                       [[r['function'], r['instructions'], r['retirement_cycles'], r['retirement_cycle_percent']]
                        for r in trace['functions'][:30]])
        lines += ['## RVV / instruction mix', '', SEMANTICS['instructions'], '']
        lines += table(['Function', 'Class', 'Dynamic instructions'],
                       [[f, kind, n] for f, mix in trace['instruction_mix'].items()
                        for kind, n in mix.items() if kind != 'other'])
        lines += ['## Source and assembly', '', 'Top 20 PCs by retirement attribution; all PCs are in report.json.', '']
        for pc in trace['pcs'][:20]:
            lines += [f'### {pc["function"]} @ {pc["pc"]}', '',
                      f'{pc["instructions"]} dynamic instructions; {pc["retirement_cycles"]} attributed cycles.', '',
                      pc['source'], '', '```asm', pc['disassembly_context'], '```', '']
            source = pc.get('archived_source')
            if source:
                lines += ['Verified archived source: ' + source['file'], '', '```c',
                          *[f'{r["number"]}: {r["text"]}' for r in source['lines']], '```', '']
    if trace['status'] == 'available':
        cute = trace['cute']
        lines += ['## AME / CUTE stages', '', SEMANTICS['cute'], '']
        if cute['status'] in ('available', 'unscoped'):
            if compare:
                lines += table(['Stage', 'Role', 'Baseline median cycles', 'Candidate median cycles', 'Delta'],
                               [[r['table'], r['role'], r['baseline_median_cycles'], r['candidate_median_cycles'],
                                 r['delta_cycles']] for r in cute['stages']])
            else:
                lines += ['Task scope: ' + json.dumps(cute['scope']), '']
                lines += table(['Stage', 'Role', 'Selected tasks', 'Median cycles', 'Min', 'Max'],
                               [[r['table'], r['role'], r['selected_tasks'], r['median_cycles'],
                                 r['min_cycles'], r['max_cycles']] for r in cute['stages']])
        else:
            lines += [cute['reason'], '']
        if compare and trace.get('memory', {}).get('status') == 'available':
            lines += ['## Actual AME interface traffic', '', trace['memory']['semantics'], '']
            lines += table(['Metric', 'Baseline', 'Candidate', 'Delta'],
                           [[row['metric'], row['baseline'], row['candidate'], row['delta']]
                            for row in trace['memory']['metrics']])
            cpu_comparison = trace['memory'].get('cpu', {})
            if cpu_comparison.get('status') == 'available':
                lines += ['## CPU/RVV memory comparison', '', cpu_comparison['semantics'], '']
                lines += table(['Metric', 'Baseline', 'Candidate', 'Delta'], [[row['metric'], row['baseline'], row['candidate'], row['delta']] for row in cpu_comparison['metrics']])
        if not compare:
            memory = trace.get('memory', {})
            lines += ['## Actual AME interface traffic', '',
                      'AME requested/masked bytes and separately captured ordinary CPU/RVV requests and PMA stores. Read payload and DRAM traffic remain unknown.', '']
            if memory.get('status') == 'available':
                lines += ['Request timestamp scope: ' + json.dumps(memory['scope']), '']
                lines += table(['Metric', 'Value'], [[name, value] for name, value in memory['metrics'].items()])
                lines += ['Boundary state: ' + json.dumps(memory['boundary']), '',
                          'Use xsai-prof memory REPORT --output NEW_DIR for transaction details and cross-boundary task analysis.', '']
            else:
                lines += [memory.get('reason', 'No reviewed actual-interface capture'), '']
            cpu_memory = memory.get('cpu', {})
            if cpu_memory.get('status') == 'available':
                lines += ['## CPU/RVV ordinary memory interfaces', '', cpu_memory['coverage'], '']
                lines += table(['Metric', 'Value'], [[key, value] for key, value in cpu_memory['metrics'].items()])
                lines += ['Local status timing: ' + json.dumps(cpu_memory['timestamps']), '', 'Boundaries: ' + json.dumps(cpu_memory['boundary']), '']
    lines += ['## Metric interpretation', '', *['- ' + v for v in SEMANTICS.values()], '']
    if not compare:
        lines += ['## Metric catalog', '', '[Metric definitions and availability](metrics.json)', '', '[Section availability](sections.json)', '']
        if report['options'].get('collection_sections'):
            lines += ['Requested collection sections: ' + ', '.join(report['options']['collection_sections']) + '.', '',
                      'Sections select required native modes; trace-derived views may share one acquisition.', '']
    return '\n'.join(lines)


def html_document(md, title):
    # Small dependency-free renderer for the Markdown subset emitted above.
    parts, navigation, table_open, code = [], [], False, False
    def inline(value):
        escaped = html.escape(value)
        def link(match):
            target = html.unescape(match[2])
            if ':' in target or target.startswith('//'):
                return match[0]
            return '<a href="' + html.escape(target, quote=True) + '">' + match[1] + '</a>'
        return re.sub(r'\[([^\]]+)\]\(([^)]+)\)', link, escaped)
    for line in md.splitlines():
        if line.startswith('```'):
            if table_open:
                parts.append('</tbody></table>')
                table_open = False
            parts.append('</code></pre>' if code else '<pre><code>')
            code = not code
        elif code:
            parts.append(html.escape(line) + '\n')
        elif line.startswith('| '):
            cells = re.split(r'(?<!\\)\|', line)[1:-1]
            if all(c.strip() == '---' for c in cells):
                continue
            if not table_open:
                parts.append('<table><thead><tr>' + ''.join('<th>' + html.escape(c.strip()) + '</th>' for c in cells) + '</tr></thead><tbody>')
                table_open = True
            else:
                parts.append('<tr>' + ''.join('<td>' + html.escape(c.strip()) + '</td>' for c in cells) + '</tr>')
        else:
            if table_open:
                parts.append('</tbody></table>')
                table_open = False
            match = re.match(r'^(#{1,3}) (.*)', line)
            if match:
                n, content = len(match[1]), match[2]
                anchor = 'section-' + str(len(parts))
                parts.append(f'<h{n} id="{anchor}">{html.escape(content)}</h{n}>')
                if n == 2:
                    navigation.append(f'<a href="#{anchor}">{html.escape(content)}</a>')
            elif line:
                parts.append('<p>' + inline(line) + '</p>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>' + html.escape(title) + '</title><style>'
            'body{font:15px system-ui,sans-serif;color:#172033;max-width:1250px;margin:32px auto;padding:0 20px}'
            'table{display:block;overflow:auto;border-collapse:collapse;width:100%;margin:16px 0}'
            'th,td{border:1px solid #dce2ea;padding:8px;text-align:left}th{background:#edf2f8}'
            'pre{background:#f3f5f8;padding:16px;overflow:auto}h2{margin-top:36px}p{line-height:1.6}'
            'nav{display:flex;gap:12px;flex-wrap:wrap;margin:20px 0}a{color:#145ab5}'
            '</style><header><a href="report.json">JSON</a> · <a href="report.md">Markdown</a></header>' +
            '<nav>' + ''.join(navigation) + '</nav>' + ''.join(parts) + '</html>')


def source_html(trace):
    """Self-contained, searchable PC details; never read a mutable source tree."""
    escape = html.escape
    rows = []
    for pc in trace['pcs']:
        source = pc.get('archived_source')
        snippet = ''
        if source:
            snippet = '<p>Verified archive: ' + escape(source['file']) + '</p><pre>' + escape(
                '\n'.join(f'{line["number"]}: {line["text"]}' for line in source['lines'])) + '</pre>'
        rows.append('<details><summary>' + escape(
            f'{pc["pc"]} | {pc["function"]} | count {pc["instructions"]} | '
            f'attributed cycles {pc["retirement_cycles"]} | {pc["instruction"]}') +
            '</summary><p>' + escape(pc['source']) + '</p><pre>' +
            escape(pc['disassembly_context']) + '</pre>' + snippet + '</details>')
    return ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width">'
            '<title>XSAI source and assembly</title><style>body{font:15px system-ui;max-width:1400px;margin:30px auto;padding:0 20px}'
            'input{width:90%;padding:12px;margin:12px 0}details{border-bottom:1px solid #ddd;padding:10px}'
            'summary{cursor:pointer;font-family:monospace}pre{background:#f3f5f8;padding:15px;overflow:auto}</style>'
            '<a href="index.html">Report</a> · <a href="report.json">JSON</a><h1>Source and assembly</h1>'
            '<p>All PCs in the selected ROI, sorted by retirement attribution. Counts are emitted instructions; '
            'attributed cycles are not exclusive execution time. Source text appears only from verified archives.</p>'
            '<label>Filter function, instruction or source <input id="filter" type="search" placeholder="e.g. flash_attention_update_i8 or vle8.v"></label>'
            '<p id="count"></p><main>' + ''.join(rows) + '</main><script>'
            'const rows=[...document.querySelectorAll("details")], input=document.querySelector("#filter");'
            'function filter(){const q=input.value.toLowerCase();let n=0;for(const r of rows){'
            'r.hidden=!r.textContent.toLowerCase().includes(q);if(!r.hidden)n++;}'
            'document.querySelector("#count").textContent=n+" / "+rows.length+" PCs";}'
            'input.addEventListener("input",filter);filter();</script></html>')


def publish(output, build):
    output = Path(output).resolve()
    require(not output.exists(), f'Output already exists; choose a new directory: {output}')
    require(not output.is_relative_to(ROOT / 'dependencies'), 'Reports must not modify dependencies')
    # Reject output in an existing run so artifact directories stay immutable.
    require(not any((p / 'manifest.json').is_file() for p in (output, *output.parents)),
            'Reports must not be written inside an existing run')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.profile-', dir=output.parent) as tmp:
        staging = Path(tmp) / 'report'
        staging.mkdir()
        report = build(staging)
        # Recompute mode writes an auxiliary ROI report inside staging.
        if report['kind'] == 'profile' and report['sections']['trace'].get('detail_report', '').startswith(str(staging)):
            report['sections']['trace']['detail_report'] = str(output / 'roi/index.html')
        dump(staging / 'report.json', report)
        if report['kind'] == 'profile':
            import kda_catalog
            dump(staging / 'metrics.json', kda_catalog.catalog('metrics', report))
            dump(staging / 'sections.json', kda_catalog.catalog('sections', report))
        md = markdown(report, output)
        (staging / 'report.md').write_text(md)
        (staging / 'index.html').write_text(html_document(md, report['label']))
        if report['kind'] == 'profile' and report['sections']['trace']['status'] == 'available':
            (staging / 'source-assembly.html').write_text(source_html(report['sections']['trace']))
        dump(staging / 'checksums.json', {'schema': 'xsai-kda.profile-files/v1', 'files': {
            str(p.relative_to(staging)): digest(p) for p in sorted(staging.rglob('*')) if p.is_file()}})
        staging.rename(output)
    return {'status': 'passed', 'kind': report['kind'], 'report': str(output / 'report.json'),
            'markdown': str(output / 'report.md'), 'html': str(output / 'index.html'),
            'warnings': report['warnings']}


def add_parser(sub):
    import kda_collect
    import kda_diagnose
    parser = sub.add_parser('profile', help='Offline sectioned profiling reports and baseline comparisons')
    add_commands(parser)
    return parser


def add_commands(parser):
    import kda_setup
    import kda_collect
    import kda_diagnose
    import kda_catalog
    commands = parser.add_subparsers(dest='profile_command', required=True)
    import kda_view
    kda_view.add_parser(commands)
    kda_setup.add_parser(commands)
    import kda_memory
    kda_memory.add_parser(commands)
    kda_catalog.add_parser(commands)
    import kda_jobs
    kda_jobs.add_parser(commands)
    import kda_portable
    kda_portable.add_parser(commands)
    import kda_analyze
    kda_analyze.add_parser(commands)
    import kda_reference_model
    kda_reference_model.add_parser(commands)
    import kda_timeline
    kda_timeline.add_parser(commands)
    import kda_batch
    kda_batch.add_parser(commands)
    import kda_demo
    kda_demo.add_parser(commands)
    import kda_hardware
    kda_hardware.add_parser(commands)
    kda_collect.add_parser(commands)
    kda_diagnose.add_parser(commands)
    report = commands.add_parser('report', help='Report verified perf runs with optional bound HPM and trace')
    report.add_argument('saved_report', type=Path, nargs='?', help='Read-only view of an existing report; no recollection')
    kda_view.add_view_arguments(report)
    report.add_argument('--spec', type=Path, help='JSON bundle spec; paths relative to its directory')
    report.add_argument('--perf', type=Path, action='append', help='Perf run directory; repeat for independent measurements')
    report.add_argument('--hpm', type=Path)
    report.add_argument('--trace', type=Path)
    report.add_argument('--label')
    report.add_argument('--output', '-o', type=Path, help='New report directory when building; new export file when viewing')
    report.add_argument('--window', type=int, default=1)
    report.add_argument('--recompute-roi', action='store_true', help='Reanalyze raw DB/ELF into the new report directory')
    report.add_argument('--cute-warmup-tasks', type=int)
    report.add_argument('--cute-measured-tasks', type=int)
    for name in ('objdump', 'addr2line', 'readelf', 'objdump-mattr'):
        report.add_argument('--' + name)
    compare = commands.add_parser('compare', help='Compare two saved reports and revalidate original evidence')
    compare.add_argument('baseline', type=Path)
    compare.add_argument('candidate', type=Path)
    compare.add_argument('--output', '-o', type=Path, required=True)


def dispatch(args, kda):
    try:
        return dispatch_impl(args, kda)
    except (sqlite3.Error, zipfile.BadZipFile, subprocess.CalledProcessError) as exc:
        raise RuntimeError(f'Profiling input or analysis failed: {exc}') from exc


def dispatch_impl(args, kda):
    if args.profile_command in ('view', 'open'):
        import kda_view
        return kda_view.dispatch(args, kda)
    if args.profile_command == 'init':
        import kda_setup
        return kda_setup.dispatch(args, kda)
    if args.profile_command == 'memory':
        import kda_memory
        return kda_memory.dispatch(args, kda)
    if args.profile_command == 'model':
        import kda_reference_model
        return kda_reference_model.dispatch(args, kda)
    if args.profile_command == 'analyze':
        import kda_analyze
        return kda_analyze.dispatch(args, kda)
    if args.profile_command in ('export', 'import'):
        import kda_portable
        return kda_portable.dispatch(args, kda)
    if args.profile_command == 'status':
        import kda_jobs
        return kda_jobs.dispatch(args, kda)
    if args.profile_command == 'hardware':
        import kda_hardware
        return kda_hardware.dispatch(args, kda)
    if args.profile_command == 'demo':
        import kda_demo
        return kda_demo.dispatch(args, kda)
    if args.profile_command == 'batch':
        import kda_batch
        return kda_batch.dispatch(args, kda)
    if args.profile_command == 'timeline':
        import kda_timeline
        return kda_timeline.dispatch(args, kda)
    if args.profile_command in ('doctor', 'query'):
        import kda_catalog
        return kda_catalog.dispatch(args, kda)
    if args.profile_command == 'diagnose':
        import kda_diagnose
        return kda_diagnose.dispatch(args, kda)
    if args.profile_command == 'collect':
        import kda_collect
        return kda_collect.dispatch(args, kda)
    elif args.profile_command == 'report':
        if args.saved_report:
            require(not any((args.spec, args.perf, args.hpm, args.trace, args.label,
                args.cute_warmup_tasks is not None, args.cute_measured_tasks is not None, args.recompute_roi,
                args.window != 1, args.objdump, args.addr2line, args.readelf, args.objdump_mattr)),
                'Saved report viewing cannot be mixed with report-building options')
            import kda_view
            args.report = args.saved_report
            return kda_view.dispatch(args, kda)
        require(args.output is not None, 'Building a report requires --output NEW_DIRECTORY')
        require(args.page == 'details' and args.format == 'text' and not any((args.metrics, args.sections,
            args.function, args.op, args.top, args.baseline)), 'View options require an existing saved report')
        require(args.window > 0, 'window must be positive')
        if args.spec:
            require(not any((args.perf, args.hpm, args.trace, args.label,
                             args.cute_warmup_tasks is not None, args.cute_measured_tasks is not None)),
                    '--spec cannot be mixed with direct run/label/CUTE options')
            spec = normalize_spec(read_json(args.spec), args.spec.resolve().parent)
        else:
            spec = {'label': args.label, 'perf': [str(v) for v in args.perf or []]}
            for mode in ('hpm', 'trace'):
                if getattr(args, mode):
                    spec[mode] = str(getattr(args, mode))
            if args.cute_warmup_tasks is not None or args.cute_measured_tasks is not None:
                require(args.cute_warmup_tasks is not None and args.cute_measured_tasks is not None,
                        'Supply both CUTE warmup and measured task counts')
                spec['cute'] = {'warmup_tasks': args.cute_warmup_tasks,
                                'measured_tasks': args.cute_measured_tasks}
            spec = normalize_spec(spec, Path.cwd())
        options = {k: getattr(args, k) for k in ('window', 'recompute_roi', 'objdump',
                   'addr2line', 'readelf', 'objdump_mattr')}
        result = publish(args.output, lambda out: build_report(spec, options, out, kda))
    else:
        a, ap = verify_saved_report(args.baseline, kda)
        b, bp = verify_saved_report(args.candidate, kda)
        result = publish(args.output, lambda _: compare_reports(a, b, (ap, bp), kda))
    print(json.dumps(result, ensure_ascii=False, indent=2))
