"""Discoverable XSAI metrics and collection sections; unavailable is never zero."""
import argparse
import json
from pathlib import Path
import shutil
import sqlite3
import sys

SECTIONS = {
    'performance': {'description': 'Uninstrumented RTL cycles and independent repeats', 'modes': [], 'source': 'perf manifest'},
    'hpm': {'description': 'Configured RTL HPM selectors and resolved event names', 'modes': ['hpm'], 'source': 'perf.log and saved RTL event coding'},
    'hotspots': {'description': 'ROI retirement-gap attribution and instruction counts', 'modes': ['trace'], 'source': 'LifeTimeCommitTrace plus paired ELF'},
    'rvv': {'description': 'RVV emitted instruction categories and mnemonics', 'modes': ['trace'], 'source': 'ROI PCs and ELF disassembly'},
    'ame': {'description': 'CUTE load/compute/store task intervals with explicit scope', 'modes': ['trace'], 'source': 'CUTELoad/Compute/Store/ReleaseEvent'},
    'source': {'description': 'PC to ELF assembly and archived source mapping', 'modes': ['trace'], 'source': 'Same-build ELF; optional verified source archive'},
    'memory': {'description': 'Actual AME and ordinary CPU/RVV memory requests, masks and status; reviewed observer required', 'modes': ['trace'], 'source': 'XSAITL plus reviewed XSAICpuLoad/XSAICpuStore/XSAISbuffer events'},
}
SETS = {'basic': ['performance'], 'counters': ['performance', 'hpm'],
        'detailed': ['performance', 'hpm', 'hotspots', 'rvv', 'ame', 'source']}
METRICS = [
    ('cycles_per_call', 'performance', 'cycles/call', 'uninstrumented independent perf calls', 'performance.measurements[].median_cycles', 'Only comparable uninstrumented RTL measurements establish speedup.'),
    ('instructions_per_call', 'performance', 'instructions/call', 'same perf calls', 'performance.measurements[].instret', 'Unavailable when not recorded; not a latency model.'),
    ('elements_per_cycle', 'performance', 'elements/cycle', 'harness-defined element count', 'performance.measurements[].elements_per_cycle', 'Element definition belongs to each operator harness.'),
    ('hpm_events_per_call', 'hpm', 'counter-defined events/call', 'instrumented harness measurement', 'hpm.counters[].per_run', 'Selector meaning requires saved RTL event coding; events may overlap.'),
    ('retirement_gap_cycles', 'hotspots', 'cycles', 'selected dynamic marker window', 'trace.functions[].retirement_cycles', 'Gap attribution to next retired instruction; not exclusive function runtime.'),
    ('dynamic_instructions', 'hotspots', 'instructions', 'selected dynamic marker window', 'trace.pcs[].instructions', 'Decoded from the paired ELF, not elapsed time.'),
    ('rvv_instruction_mix', 'rvv', 'instructions', 'selected dynamic marker window', 'trace.instruction_mix', 'Emitted vector instruction counts, not DRAM bytes or bandwidth.'),
    ('cute_stage_cycles', 'ame', 'CUTE timestamp cycles/task', 'explicit warmup/measured task scope', 'trace.cute.stages[].median_cycles', 'Intervals overlap; cross-clock alignment requires validated same-run anchors.'),
    ('source_location', 'source', 'file:line', 'selected ROI PCs', 'trace.pcs[].source', 'Debug information and matching archived text required; missing source is explicit.'),
    ('cpu_read_request_enabled_bytes', 'memory', 'mask-enabled request bytes', 'ordinary LoadUnit requests initiated in selected timestamp interval, including replay/speculation', 'trace.memory.cpu.metrics.demand_read_request_enabled_bytes', 'Actual enabled lanes, not read payload, unique bytes, cacheline fills or DRAM traffic.'),
    ('rvv_read_request_enabled_bytes', 'memory', 'mask-enabled request bytes', 'ordinary vector LoadUnit requests in selected timestamp interval', 'trace.memory.cpu.metrics.rvv_read_request_enabled_bytes', 'RVV request attempts; preserves replay, tails and lane masks.'),
    ('cpu_pma_store_enabled_bytes', 'memory', 'mask-enabled store bytes', 'PMA store event timestamps in selected interval, delayed two edges', 'trace.memory.cpu.metrics.pma_store_known_enabled_bytes', 'Whole-line special events have unknown bytes; separate from merged sbuffer completion masks.'),
    ('cpu_l1_status_responses', 'memory', 'status responses', 'responses paired to requests initiated in selected timestamp interval', 'trace.memory.cpu.metrics.observed_l1_statuses', 'L1 hit/miss/replay status, not observed data payload or architectural load completion.'),
    ('ame_read_requested_bytes', 'memory', 'requested bytes', 'requests initiated in selected CPU marker interval', 'trace.memory.metrics.read_requested_bytes', 'Get request size, not observed read payload or DRAM traffic.'),
    ('ame_write_payload_bytes', 'memory', 'mask-enabled bytes', 'requests initiated in selected CPU marker interval', 'trace.memory.metrics.write_payload_bytes', 'Actual Put byte enables at the AME interface, not CPU/RVV or DRAM bytes.'),
    ('ame_read_payload_bytes', 'memory', 'observed bus payload bytes', 'returns for requests initiated in selected CPU interval; followed outside end', 'trace.memory.metrics.read_payload_bytes', 'Reviewed matrix_data_in 64-byte accepted beats; not useful element bytes or DRAM traffic.'),
    ('ame_read_service_cycles', 'memory', 'CPU cycles/request', 'matched read requests initiated in selected interval', 'trace.memory.metrics.read_completion_latency', 'Mean near_cute Get to matrix_data_in acceptance, including queueing/backpressure; not instruction latency.'),
    ('ame_read_outstanding_max', 'memory', 'requests', 'selected CPU interval including entering pending reads', 'trace.memory.metrics.read_outstanding_max', 'Source-paired observed requests; full-run boundary context required.'),
    ('ame_read_return_backpressure_cycles', 'memory', 'CPU cycles', 'valid matrix_data_in cycles in selected interval', 'trace.memory.metrics.read_return_backpressure_cycles', 'Valid without ready at this interface; not a partition of execution time.'),
]


def selection(sections=None, preset=None):
    if sections is not None and preset is not None:
        raise ValueError('Choose --sections or --set, not both')
    if preset is not None:
        if not isinstance(preset, str) or preset not in SETS:
            raise ValueError('Unknown set: ' + str(preset))
        selected = list(SETS[preset])
    else:
        if sections is not None and (not isinstance(sections, (list, tuple))):
            raise ValueError('Sections must be a list of section names')
        selected = list(sections if sections is not None else SETS['detailed'])
    if not isinstance(selected, list) or not selected or any(not isinstance(s, str) or s not in SECTIONS for s in selected) or len(set(selected)) != len(selected):
        raise ValueError('Sections must be nonempty, unique known names')
    if 'performance' not in selected:
        selected.insert(0, 'performance')
    return {'sections': selected, 'diagnostics': [m for m in ('hpm', 'trace')
            if any(m in SECTIONS[s]['modes'] for s in selected)]}


def availability(section, report):
    if report is None:
        return 'requires_evidence', 'No report supplied; capability is not a measured value'
    if section == 'performance':
        return report['sections']['performance']['status'], None
    block = report['sections']['hpm' if section == 'hpm' else 'trace']
    if block['status'] != 'available':
        return 'unavailable', block.get('reason', 'Evidence missing')
    if section == 'ame':
        cute = block['cute']
        return cute['status'], cute.get('reason') or (None if cute['status'] == 'available' else 'Task scope absent')
    if section == 'memory':
        memory = block.get('memory', {})
        status = memory.get('status', 'unavailable')
        return status, (None if status == 'available' else memory.get('reason', 'No reviewed actual-interface capture'))
    if section == 'source':
        if not any(p.get('archived_source') for p in block['pcs']):
            return 'partial', 'ELF mapping available; verified archived source text may be absent'
    if section == 'hpm' and not block['encoding_resolved']:
        return 'partial', 'Some selectors are unresolved; do not infer hardware event meaning'
    return 'available', None


def metric_availability(name, section, report):
    status, reason = availability(section, report)
    if report is None or status == 'unavailable':
        return status, reason
    memory_metrics = {
        'ame_read_payload_bytes': 'read_payload_bytes', 'ame_read_service_cycles': 'read_completion_latency',
        'ame_read_outstanding_max': 'read_outstanding_max',
        'ame_read_return_backpressure_cycles': 'read_return_backpressure_cycles'}
    cpu_metrics = {'cpu_read_request_enabled_bytes': 'demand_read_request_enabled_bytes',
        'rvv_read_request_enabled_bytes': 'rvv_read_request_enabled_bytes',
        'cpu_pma_store_enabled_bytes': 'pma_store_known_enabled_bytes',
        'cpu_l1_status_responses': 'observed_l1_statuses'}
    if name in memory_metrics or name in cpu_metrics:
        block = report['sections']['trace'].get('memory', {})
        if name in cpu_metrics:
            block = block.get('cpu', {})
        key = (memory_metrics if name in memory_metrics else cpu_metrics)[name]
        if block.get('status') != 'available' or block.get('metrics', {}).get(key) is None:
            return 'unavailable', 'Required reviewed interface metric was not observed; missing is not zero'
    if name in ('instructions_per_call', 'elements_per_cycle'):
        key = 'instret' if name == 'instructions_per_call' else 'elements_per_cycle'
        values = [v for m in report['sections']['performance']['measurements'] for v in m.get(key, [])]
        if not values or all(v is None for v in values):
            return 'unavailable', 'Metric was not recorded by the performance harness'
        if any(v is None for v in values):
            return 'partial', 'Some performance repeats lack this metric'
    if name == 'source_location':
        mapped = [p.get('source') not in (None, '', 'N/A', '??:0', '??:?') for p in report['sections']['trace']['pcs']]
        if not any(mapped):
            return 'unavailable', 'No source line mapping in the recorded ELF'
        if not all(mapped):
            return 'partial', 'Some ROI PCs lack source line mapping'
    return status, reason


def catalog(kind, report=None):
    if kind == 'sets':
        rows = [{'name': name, 'sections': parts, 'diagnostics': selection(preset=name)['diagnostics']}
                for name, parts in SETS.items()]
    elif kind == 'sections':
        rows = [{'name': name, **data, 'status': availability(name, report)[0],
                 'reason': availability(name, report)[1]} for name, data in SECTIONS.items()]
    else:
        rows = [{'name': name, 'section': section, 'source': SECTIONS[section]['source'],
                 'unit': unit, 'scope': scope, 'json_path': path, 'limitations': limitation,
                 'required_modes': ['perf', *SECTIONS[section]['modes']],
                 'status': metric_availability(name, section, report)[0], 'reason': metric_availability(name, section, report)[1]}
                for name, section, unit, scope, path, limitation in METRICS]
        if report and report['sections']['hpm']['status'] == 'available':
            for c in report['sections']['hpm']['counters']:
                resolved = c['encoding_resolved']
                rows.append({'name': 'hpm.counter.' + str(c['counter']), 'section': 'hpm',
                             'source': 'Recorded RTL HPM coding', 'unit': 'selector-defined events/call',
                             'scope': 'instrumented measured harness', 'selector': c['config'],
                             'events': c['rtl_event_names'], 'operators': c['operators'],
                             'printed_label': c['upstream_label'],
                             'printed_label_matches_rtl': c.get('upstream_label_matches_rtl'),
                             'explanation_command': 'xsai-prof hardware REPORT --output NEW_DIR',
                             'status': 'available' if resolved else 'unresolved',
                             'reason': None if resolved else 'RTL event selector not decoded',
                             'value_per_call': c['per_run'] if resolved else None})
    return {'schema': 'xsai-prof.catalog/v1', 'kind': kind, 'evidence_verified': report is not None, 'items': rows}


def doctor(config_path, kda):
    from kda_paths import VENDOR
    checks = [{'name': 'python', 'status': 'available' if sys.version_info >= (3, 10) else 'unavailable',
               'detail': sys.version.split()[0]},
              {'name': 'sqlite', 'status': 'available', 'detail': sqlite3.sqlite_version},
              {'name': 'roi_analyzer', 'status': 'available' if (VENDOR / 'roi_hotspots.py').is_file() else 'unavailable',
               'detail': str(VENDOR / 'roi_hotspots.py')}]
    tools = {name: shutil.which(name) for name in ('readelf', 'addr2line', 'objdump', 'riscv64-linux-gnu-objdump')}
    ready = all(c['status'] == 'available' for c in checks)
    result = {'schema': 'xsai-prof.doctor/v1', 'offline_ready': ready, 'checks': checks,
              'elf_tools': tools, 'rtl_collection': {'status': 'not_checked', 'reason': 'Supply --config to validate external RTL, runtime and compiler dependencies'},
              'limitations': ['ELF analysis additionally needs tools that decode the target ISA.',
                              'Functional simulators do not establish RTL performance.']}
    if config_path:
        import kda_collect as collect
        parser = argparse.ArgumentParser()
        commands = parser.add_subparsers(dest='command')
        collect.add_parser(commands)
        args = parser.parse_args(['collect', '--config', str(config_path), '--output', '.doctor-unused'])
        try:
            config = collect.settings(args)
            identity = collect.preflight(config, kda)
            from kda_setup import target_support
            import kda_profile as profile
            result['rtl_collection'] = {'status': 'available', 'identity': identity,
                'supported_target': target_support(profile.read_json(config['rtl_config']))}
        except (RuntimeError, OSError, ValueError, KeyError) as exc:
            result['rtl_collection'] = {'status': 'unavailable', 'reason': str(exc)}
            result['rtl_collection']['next_steps'] = [
                'Check explicit BLAS, emulator/config, xsai-env, AM_HOME and LLVM_HOME paths.',
                'Use xsai-prof init --help to create a minimal collection config.',
                'Use a reviewed observer receipt for memory_trace or scoped capture; match the actual emulator hash.']
    return result


def add_parser(commands):
    query = commands.add_parser('query', help='List metrics, sections and sets, with evidence-backed availability')
    query.add_argument('kind', choices=['metrics', 'sections', 'sets', 'events'])
    query.add_argument('--rtl-config', type=Path, help='Recorded RTL event coding for query events')
    query.add_argument('--report', type=Path, help='Optional saved report; original evidence is verified')
    query.add_argument('--format', choices=['json', 'text', 'csv'], default='text')
    query.add_argument('--filter', help='Case-insensitive name/description substring')
    query.add_argument('--section', choices=list(SECTIONS), help='Filter metric/section catalog')
    query.add_argument('--output', '-o', type=Path, help='New export file; stdout by default')
    d = commands.add_parser('doctor', help='Check offline resources; optionally preflight an RTL collection config')
    d.add_argument('--config', type=Path)
    d.add_argument('--output', '-o', type=Path)


def emit_catalog(result, args, protected=()):
    import kda_output
    rows = result['items']
    if args.section:
        import kda_profile
        kda_profile.require(args.kind in ('metrics', 'sections'), '--section filters metrics or sections catalogs')
        rows = [row for row in rows if row.get('section', row.get('name') if args.kind == 'sections' else None) == args.section]
    if args.filter:
        rows = [row for row in rows if args.filter.lower() in json.dumps(row, ensure_ascii=False).lower()]
    result = {**result, 'items': rows}
    columns = ['name', 'section', 'unit', 'status', 'reason'] if args.kind == 'metrics' else (
        ['name', 'event_name', 'group', 'event_id', 'semantic_status'] if args.kind == 'events' else
        ['name', 'description', 'modes', 'status', 'reason'] if args.kind == 'sections' else ['name', 'sections', 'diagnostics'])
    kda_output.emit(kda_output.render(result, rows, columns, args.format), args.output, protected)


def dispatch(args, kda):
    import kda_profile as profile
    if args.profile_command == 'query':
        if args.kind == 'events':
            profile.require(args.rtl_config is not None and args.report is None, 'query events requires --rtl-config and no --report')
            receipt = profile.read_json(args.rtl_config)
            from kda_hardware import binding, event_definition, CONTRACT
            audit = binding(receipt)
            rows = []
            for event in receipt.get('hpm_event_coding', []):
                group = event['group'].casefold()
                name = event['name'].strip()
                definition = event_definition(name, group)
                verified = (definition and audit['status'] == 'matched' and
                            CONTRACT['coding'].get(group + '/' + str(event['id'])) ==
                            {'name': name, 'signal': event.get('signal')})
                rows.append({'name': group + '/' + str(event['id']), 'event_name': name,
                             'group': group, 'event_id': event['id'], 'signal': event.get('signal'),
                             'definition': definition,
                             'semantic_status': 'source_reviewed' if verified else 'reference_only' if definition else 'unreviewed'})
            profile.require(rows, 'RTL receipt contains no event coding')
            result = {'schema': 'xsai-prof.catalog/v1', 'kind': 'events', 'build_binding': audit,
                      'evidence_verified': False, 'scope': 'Recorded event coding; no live collection executed', 'items': rows}
            return emit_catalog(result, args, [args.rtl_config])
        profile.require(args.rtl_config is None, '--rtl-config applies only to query events')
        from kda_view import report_path
        report = profile.verify_saved_report(report_path(args.report), kda)[0] if args.report else None
        result = catalog(args.kind, report)
        return emit_catalog(result, args, [report_path(args.report)] if args.report else [])
    else:
        result = doctor(args.config, kda)
        if args.output:
            profile.require(not args.output.exists(), 'Doctor output already exists')
            profile.dump(args.output, result)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.profile_command == 'doctor' and (not result['offline_ready'] or result['rtl_collection']['status'] == 'unavailable'):
        return 1
