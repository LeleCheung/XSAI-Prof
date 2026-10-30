"""Unified offline analysis for humans and structured consumers."""
import html
import json
from pathlib import Path
import tempfile

import kda_profile as p
import kda_hardware as hardware
import kda_timeline as timeline


def analyze(report, kda, baseline=None, max_instructions=10000, directory=None):
    # Revalidate raw trace/ELF and compute range annotations rather than trusting
    # a prior tool version's cached derived fields.
    if report['sections']['trace']['status'] == 'available':
        with tempfile.TemporaryDirectory(prefix='xsai-analysis-') as tmp:
            report = json.loads(json.dumps(report))
            item = p.load_input(report['spec']['trace'], kda, 'trace')
            report['sections']['trace'] = p.trace_section(item, {**report['options'], 'cute': report['spec'].get('cute')}, Path(tmp))
    hw = hardware.hardware(report, kda)
    trace = report['sections']['trace']
    observations = []
    if trace['status'] == 'available':
        for row in sorted(trace['functions'], key=lambda r: r['retirement_cycles'], reverse=True)[:5]:
            observations.append({'kind': 'hotspot', 'function': row['function'], 'instructions': row['instructions'],
                'retirement_gap_cycles': row['retirement_cycles'], 'evidence': 'trace.functions',
                'interpretation': 'Source inspection priority; not exclusive function execution time.'})
    partial = [c['counter'] for c in hw['hpm']['counters'] if c['semantic_status'] != 'source_reviewed']
    ranges = trace.get('ranges', {'status': 'unavailable'})
    scoped = [e for e in ranges.get('events', []) if e['kind'] == 'stage'] or ranges.get('events', [])
    cpu_span = [min(e['begin_commit'] for e in scoped), max(e['end_commit'] for e in scoped)] if scoped else None
    instruction_timeline = timeline.timeline(report, max_instructions=max_instructions, cpu_range=cpu_span) if trace['status'] == 'available' else {'status': 'unavailable', 'events': []}
    instruction_timeline['focus'] = ('Named-stage commit span' if any(e['kind'] == 'stage' for e in scoped) else 'Selected invocation commit span') if scoped else 'Outer ROI'
    memory = {'status': 'unavailable', 'reason': 'No reviewed actual-interface capture', 'metrics': None}
    if trace['status'] == 'available':
        from kda_memory import memory as memory_analysis
        from kda_observer import reviewed
        if reviewed(hardware.receipt_for(report, 'trace')):
            memory = memory_analysis(report)
    result = {'schema': 'xsai-prof.analysis/v1', 'kind': 'analysis', 'label': report['label'],
        'performance': report['sections']['performance'], 'hardware': hw,
        'ranges': ranges, 'trace_status': trace['status'], 'collector': trace.get('collector'), 'memory': memory,
        'timeline': instruction_timeline,
        'source_pcs': trace.get('pcs', []),
        'comparison': p.compare_reports(baseline[0], report, (baseline[1], directory), kda) if baseline else None,
        'diagnosis': {'version': 'evidence-summary/v1', 'observations': observations,
                      'unreviewed_counters': partial, 'causal_bottleneck': None,
                      'reason': 'Trace hotspots and predicates guide experiments; causality still requires fresh performance, event predictions and ablation.'},
        'warnings': report['warnings'], 'report_inputs': report['inputs'],
        'validation': report.get('validation', {}), 'performance_identity': report.get('identity', {})}
    from kda_summary import overview
    result['overview'] = overview(result)
    from kda_version import __version__
    result['producer'] = {'version': __version__, 'analysis_sha256': p.digest(Path(__file__)),
        'overview_sha256': p.digest(Path(__file__).with_name('kda_summary.py'))}
    return result


def html_view(data):
    from kda_ui import html_view as render
    return render(data)


def add_parser(commands):
    a = commands.add_parser('analyze', help='Unified offline metrics, ranges, hardware, timeline and source navigation')
    a.add_argument('report', type=Path)
    a.add_argument('--baseline', type=Path)
    a.add_argument('--output', '-o', type=Path, required=True)
    a.add_argument('--max-instructions', type=int, default=10000)


def dispatch(args, kda):
    report, directory = p.verify_saved_report(args.report, kda)
    baseline = p.verify_saved_report(args.baseline, kda) if args.baseline else None
    out = args.output.resolve()
    p.require(not out.exists() and not out.is_relative_to(directory) and
              not out.is_relative_to(p.ROOT / 'dependencies') and
              not any((x / 'manifest.json').exists() for x in (out, *out.parents)), 'Analysis output must be a new directory outside evidence/dependencies')
    data = analyze(report, kda, baseline, args.max_instructions, directory)
    out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.xsai-analysis-', dir=out.parent) as tmp:
        root = Path(tmp) / 'analysis'
        root.mkdir()
        p.dump(root / 'analysis.json', data)
        (root / 'index.html').write_text(html_view(data))
        p.dump(root / 'checksums.json', {'files': {n: p.digest(root / n) for n in ('analysis.json', 'index.html')}})
        root.rename(out)
    print(json.dumps({'status': 'passed', 'analysis': str(out / 'analysis.json'), 'html': str(out / 'index.html')}))
