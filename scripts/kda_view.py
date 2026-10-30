"""Read-only selected views of verified reports for terminals and agents."""
from pathlib import Path
import statistics
import webbrowser

import kda_catalog as catalog
import kda_output as output
import kda_profile as p
from kda_plan import names


def report_path(path):
    path = Path(path).resolve()
    if path.is_dir() and (path/'collection.json').is_file():
        return path/'report'
    return path


def extract(value, parts, context=None):
    context = dict(context or {})
    if isinstance(value, dict):
        context.update({key: value[key] for key in ('op', 'function', 'pc', 'instruction') if key in value})
    if not parts:
        yield value, context
        return
    part, *rest = parts
    if part.endswith('[]'):
        for item in value.get(part[:-2], []) if isinstance(value, dict) else []:
            yield from extract(item, rest, context)
    elif isinstance(value, dict) and part in value:
        yield from extract(value[part], rest, context)


def view(report, directory, args, kda):
    sections = names(args.sections)
    metrics = names(args.metrics)
    p.require(not (set(sections) - catalog.SECTIONS.keys()), 'Unknown section; use query sections')
    registry = catalog.catalog('metrics', report)['items']
    known = {row['name'] for row in registry}
    p.require(not (set(metrics) - known), 'Unsupported report metrics: ' + ', '.join(sorted(set(metrics)-known)))
    page_section = {'source': ['source'], 'hotspots': ['hotspots', 'rvv'], 'memory': ['memory']}
    if args.page in page_section:
        p.require(not sections or set(sections) <= set(page_section[args.page]), 'Page and section filters conflict')
        sections = sections or page_section[args.page]
    selected = [row for row in registry if (not sections or row['section'] in sections) and
                (not metrics or row['name'] in metrics)]
    rows = []
    if args.page == 'comparison':
        p.require(args.baseline, 'Comparison page requires --baseline REPORT')
        baseline, base_dir = p.verify_saved_report(report_path(args.baseline), kda)
        comparison = p.compare_reports(baseline, report, (base_dir, directory), kda)
        for row in comparison['sections']['performance']['measurements']:
            rows.append({'metric': 'cycles_per_call', 'section': 'performance', 'unit': 'cycles/call',
                'op': row['op'], 'baseline': statistics.median(row['baseline_cycles']),
                'candidate': statistics.median(row['candidate_cycles']),
                'value': statistics.median(row['candidate_cycles']), 'speedup': row['speedup'],
                'delta': statistics.median(row['candidate_cycles'])-statistics.median(row['baseline_cycles']),
                'status': 'available', 'reason': 'Medians of independent perf; speedup is baseline/candidate median.',
                'evidence': '/comparison/sections/performance'})
        for name, key in [('instructions_per_call', 'instret'), ('elements_per_cycle', 'elements_per_cycle')]:
            left = {m['op']: m for m in baseline['sections']['performance']['measurements']}
            for measurement in report['sections']['performance']['measurements']:
                lhs, rhs = left[measurement['op']].get(key, []), measurement.get(key, [])
                valid = bool(lhs and rhs) and all(type(v) in (int,float) for v in [*lhs,*rhs])
                a, b = (statistics.median(lhs),statistics.median(rhs)) if valid else (None,None)
                metric = next(r for r in registry if r['name']==name)
                rows.append({'metric':name,'section':'performance','unit':metric['unit'],'op':measurement['op'],
                    'baseline':a,'candidate':b,'value':b,'delta':b-a if valid else None,
                    'status':'available' if valid else 'unavailable','reason':metric['limitations'],
                    'evidence':'/comparison/sections/performance'})
        for counter in comparison['sections'].get('hpm',{}).get('counters',[]):
            resolved=counter['encoding_resolved']
            entry={'metric':'hpm_events_per_call','section':'hpm','unit':'selector-defined events/call',
                'context':'counter '+str(counter['counter']),
                'baseline':counter['baseline_per_call'] if resolved else None,
                'candidate':counter['candidate_per_call'] if resolved else None,
                'value':counter['candidate_per_call'] if resolved else None,'delta':counter['delta_per_call'],
                'status':'available' if resolved else 'unresolved','reason':'Only identical resolved RTL selectors are compared.',
                'evidence':'/comparison/sections/hpm'}
            rows.append(entry)
            dynamic='hpm.counter.'+str(counter['counter'])
            if dynamic in metrics:rows.append({**entry,'metric':dynamic})
        for function in comparison['sections'].get('trace',{}).get('functions',[]):
            a,b=function['baseline_retirement_cycles'],function['candidate_retirement_cycles']
            rows.append({'metric':'retirement_gap_cycles','section':'hotspots','unit':'cycles',
                'function':function['function'],'baseline':a,'candidate':b,'value':b,'delta':b-a,
                'status':'available','reason':'ROI retirement-gap attribution, not exclusive function time.',
                'evidence':'/comparison/sections/trace/functions'})
        mem = comparison['sections'].get('trace', {}).get('memory', {})
        for boundary, values in [('ame', mem.get('metrics', [])), ('cpu_rvv', mem.get('cpu', {}).get('metrics', []))]:
            for row in values:
                match = next((r for r in registry if r.get('json_path', '').endswith('.'+row['metric']) and r['section'] == 'memory' and
                    (('memory.cpu.' in r['json_path']) == (boundary == 'cpu_rvv'))), None)
                if match:
                    rows.append({'metric': match['name'], 'section': 'memory', 'unit': match['unit'],
                        'baseline': row['baseline'], 'candidate': row['candidate'], 'delta': row['delta'],
                        'value': row['candidate'], 'status': 'available' if row['delta'] is not None else 'unavailable',
                        'reason': match['limitations'], 'evidence': '/comparison/sections/trace/memory'})
        represented={row['metric'] for row in rows}
        for metric in selected:
            if metric['name'] not in represented:
                rows.append({'metric':metric['name'],'section':metric['section'],'unit':metric['unit'],
                    'value':None,'baseline':None,'candidate':None,'delta':None,'status':'unavailable',
                    'reason':'No comparable scalar evidence for this metric; inspect its details/source page.'})
        rows = [row for row in rows if (not sections or row['section'] in sections) and
                (not metrics or row['metric'] in metrics)]
    else:
        p.require(not args.baseline, '--baseline is used with --page comparison')
        for metric in selected:
            path = metric.get('json_path')
            found = list(extract(report['sections'], path.split('.'))) if path else [(metric.get('value_per_call'), {})]
            if not found:
                found = [(None, {})]
            for value, context in found:
                status = metric['status']
                if status in ('unavailable', 'unresolved'):
                    value = None
                if value is None:
                    status = 'unavailable'
                rows.append({'metric': metric['name'], 'section': metric['section'], 'unit': metric['unit'],
                    **context, 'value': value, 'status': status,
                    'reason': metric.get('reason') or metric.get('limitations'), 'evidence': path})
    if args.function:
        rows = [row for row in rows if args.function.lower() in str(row.get('function', '')).lower()]
    if args.op:
        rows = [row for row in rows if args.op.lower() in str(row.get('op', '')).lower()]
    matched = len(rows)
    rows = rows[:args.top] if args.top else rows
    return {'schema': 'xsai-prof.view/v1', 'label': report['label'], 'page': args.page,
        'report': str(directory), 'evidence_verified': True, 'rows': rows,
        'selection': {'sections': sections, 'metrics': metrics, 'function': args.function, 'op': args.op,
                      'matched_rows': matched, 'shown_rows': len(rows), 'truncated': len(rows) < matched},
        'warnings': report.get('warnings', []) + (['Function/operator filters omit global rows; global totals are never attributed to a function.'] if args.function or args.op else [])}


def add_view_arguments(parser):
    parser.add_argument('--page', choices=['details', 'raw', 'source', 'hotspots', 'memory', 'comparison'], default='details')
    parser.add_argument('--format', choices=['text', 'json', 'csv'], default='text')
    parser.add_argument('--metrics', nargs='+', action='extend')
    parser.add_argument('--section', '--sections', dest='sections', nargs='+', action='extend')
    parser.add_argument('--function', help='Substring filter on function-scoped rows only')
    parser.add_argument('--op', help='Substring filter on operator-scoped rows only')
    parser.add_argument('--top', type=int, help='Explicit row limit; truncation recorded in JSON/text')
    parser.add_argument('--baseline', type=Path)


def add_parser(commands):
    v = commands.add_parser('view', help='Read-only report view: filtered terminal, JSON or CSV without recollection')
    v.add_argument('report', type=Path)
    v.add_argument('--output', '-o', type=Path, help='New export file; stdout by default')
    add_view_arguments(v)
    op = commands.add_parser('open', help='Open an existing verified report/analysis in a browser')
    op.add_argument('report', type=Path)
    op.add_argument('--no-browser', action='store_true', help='Print the verified local HTML location only')


def dispatch(args, kda):
    if args.profile_command == 'open':
        path = report_path(args.report)
        directory = path.parent if path.is_file() else path
        if (directory/'analysis.json').is_file():
            receipt = p.read_json(directory/'checksums.json')
            for name in ('analysis.json', 'index.html'):
                p.require(receipt['files'].get(name) == p.digest(directory/name), 'Analysis artifact changed: ' + name)
            analysis = p.read_json(directory/'analysis.json')
            p.require(analysis.get('schema') == 'xsai-prof.analysis/v1', 'Unsupported analysis schema')
            for item in analysis.get('report_inputs', []):
                run = Path(item['run'])
                p.require(p.digest(run/'manifest.json') == item['manifest_sha256'], 'Analysis input manifest changed')
                kda.load_run(run)
                for key in ('source_receipt', 'source_archive'):
                    if key in item:
                        p.require(p.digest(item[key]) == item[key+'_sha256'], 'Analysis source evidence changed')
        else:
            _, directory = p.verify_saved_report(path, kda)
        url = (directory/'index.html').as_uri()
        opened = False if args.no_browser else webbrowser.open(url)
        import json
        print(json.dumps({'status': 'verified', 'html': str(directory/'index.html'), 'url': url,
                          'browser_opened': opened, 'next_step': 'Open this HTML file locally; on a remote host copy/import the evidence or report.'}))
        return
    p.require(args.top is None or args.top > 0, '--top must be positive')
    report, directory = p.verify_saved_report(report_path(args.report), kda)
    data = view(report, directory, args, kda)
    columns = ['section', 'metric', 'op', 'function', 'pc', 'value', 'unit', 'status', 'reason']
    if args.page == 'comparison':
        columns = ['section', 'metric', 'op', 'function', 'context', 'baseline', 'candidate', 'delta', 'speedup', 'value', 'unit', 'status', 'reason']
    text = output.render(data, data['rows'], columns, args.format)
    if args.format == 'text' and data['selection']['truncated']:
        text += 'Showing ' + str(len(data['rows'])) + ' of ' + str(data['selection']['matched_rows']) + ' matching rows.\n'
    protected = [directory, *(item['run'] for item in report['inputs'])]
    if args.baseline:
        protected.append(report_path(args.baseline))
    output.emit(text, args.output, protected)
