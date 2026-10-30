"""Sequential, failure-preserving multi-shape comparisons with verified inputs."""
import csv
import fcntl
import html
import json
from pathlib import Path
import re
import sqlite3
import tempfile
import os

from kda_collect import now

import kda_profile as profile


def config(path):
    spec = profile.read_json(path)
    profile.require(isinstance(spec, dict) and set(spec) == {'cases'} and isinstance(spec['cases'], list) and spec['cases'],
                    'Batch config must contain a nonempty cases list')
    seen = set()
    for case in spec['cases']:
        profile.require(isinstance(case, dict) and set(case) <= {'id', 'baseline', 'candidate'} and 'id' in case,
                        'Batch cases accept id, baseline and candidate')
        key = case['id']
        profile.require(isinstance(key, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_-]{0,79}', key) and key not in seen,
                        'Case ids must be unique safe names of 1..80 characters')
        seen.add(key)
        for role in ('baseline', 'candidate'):
            entry = case.get(role)
            if entry is not None:
                profile.require(isinstance(entry, dict) and len(entry) == 1 and
                                set(entry) <= {'report', 'spec', 'collect'} and
                                isinstance(next(iter(entry.values())), str),
                                'Each input is one report, spec or collect-config path')
    return spec


def obtain(entry, base, destination, kda):
    kind, path = next(iter(entry.items()))
    path = (base / path).resolve()
    if kind == 'report':
        return profile.verify_saved_report(path, kda)
    if kind == 'spec':
        if (destination / 'report.json').is_file():
            return profile.verify_saved_report(destination, kda)
        spec = profile.normalize_spec(profile.read_json(path), path.parent)
        profile.publish(destination, lambda out: profile.build_report(spec, {'window': 1}, out, kda))
        return profile.verify_saved_report(destination, kda)
    import argparse
    import kda_collect as collect
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest='command')
    collect.add_parser(commands)
    args = parser.parse_args(['collect', '--config', str(path), '--output', str(destination)])
    collect.collect(collect.settings(args), destination, (destination / 'collection.json').is_file(), kda)
    return profile.verify_saved_report(destination / 'report', kda)


def result_rows(case_id, comparison):
    rows = []
    for m in comparison['sections']['performance']['measurements']:
        repeated = m['independent_repeats_both']
        a, b = m['baseline_cycles'], m['candidate_cycles']
        if m['speedup'] == 1:
            outcome = 'unchanged'
        elif not repeated:
            outcome = 'inconclusive'
        elif max(b) < min(a):
            outcome = 'improved'
        elif min(b) > max(a):
            outcome = 'regressed'
        else:
            outcome = 'inconclusive'
        rows.append({'id': case_id, 'state': 'compared', 'outcome': outcome, 'op': m['op'], 'unit': m['unit'],
                     'baseline_cycles': a, 'candidate_cycles': b, 'speedup': m['speedup'],
                     'cycle_reduction_pct': m['cycle_reduction_pct'], 'independent_repeats_both': repeated,
                     'error': None})
    return rows


def render(output, state):
    with tempfile.NamedTemporaryFile(mode='w', dir=output, delete=False) as stream:
        json.dump(state, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write('\n')
        temporary = stream.name
    os.replace(temporary, output / 'batch.json')
    keys = ['id', 'state', 'outcome', 'op', 'unit', 'baseline_cycles', 'candidate_cycles', 'speedup',
            'cycle_reduction_pct', 'independent_repeats_both', 'error']
    with (output / 'batch.csv').open('w', newline='') as stream:
        writer = csv.DictWriter(stream, fieldnames=keys)
        writer.writeheader()
        for row in state['rows']:
            writer.writerow({k: row.get(k) for k in keys})
    text = ['<!doctype html><html><meta charset="utf-8"><title>XSAI batch comparison</title>',
            '<style>body{font:15px system-ui;margin:24px}table{border-collapse:collapse}td,th{padding:9px;border:1px solid #ddd}.regressed,.failed{background:#ffe8e8}.improved{background:#e7f5e7}</style>',
            '<h1>Multi-shape comparison</h1><p><a href="batch.json">JSON</a> · <a href="batch.csv">CSV</a></p>',
            '<p>Each row verifies its own baseline/candidate configuration. Shapes are not pooled into one speedup. Improvement/regression labels require independent repeats and non-overlapping recorded ranges; they are not statistical significance claims.</p>',
            '<table><tr>' + ''.join('<th>' + html.escape(k) + '</th>' for k in keys) + '</tr>']
    for row in state['rows']:
        text.append('<tr class="' + html.escape(row.get('outcome') or row['state']) + '">' +
                    ''.join('<td>' + html.escape(str(row.get(k, ''))) + '</td>' for k in keys) + '</tr>')
    text.append('</table><h2>Per-case evidence</h2><ul>')
    for case in state['cases']:
        if case.get('comparison'):
            text.append('<li><a href="' + html.escape(case['comparison']) + '/index.html">' + html.escape(case['id']) + '</a></li>')
        else:
            text.append('<li>' + html.escape(case['id'] + ': ' + case['state']) + '</li>')
    text.append('</ul></html>')
    (output / 'index.html').write_text(''.join(text))


def input_fingerprints(spec, base):
    result = {}
    for case in spec['cases']:
        for role in ('baseline', 'candidate'):
            entry = case.get(role)
            if not entry:
                continue
            kind, value = next(iter(entry.items()))
            path = (base / value).resolve()
            if kind == 'report' and path.is_dir():
                path /= 'report.json'
            result[case['id'] + '/' + role] = {'path': str(path),
                'sha256': profile.digest(path) if path.is_file() else None}
    return result


def check_comparison(directory):
    receipt = profile.read_json(directory / 'checksums.json')
    profile.require('report.json' in receipt['files'], 'Comparison receipt incomplete')
    for name, sha in receipt['files'].items():
        path = (directory / name).resolve()
        profile.require(path.is_relative_to(directory.resolve()) and profile.digest(path) == sha,
                        'Completed comparison changed')


def batch(config_path, output, kda, resume=False, retries=0):
    profile.require(type(retries) is int and 0 <= retries <= 20, 'retries must be in 0..20')
    config_path = config_path.resolve()
    spec = config(config_path)
    output = output.resolve()
    profile.require(not output.is_relative_to(profile.ROOT / 'dependencies') and
                    not any((p / 'manifest.json').exists() for p in (output, *output.parents)),
                    'Batch output must not modify dependencies or existing runs')
    for case in spec['cases']:
        for role in ('baseline', 'candidate'):
            entry = case.get(role)
            if entry:
                kind, value = next(iter(entry.items()))
                p = (config_path.parent / value).resolve()
                if kind == 'report':
                    parent = p if p.is_dir() else p.parent
                    profile.require(not output.is_relative_to(parent), 'Batch output must not be inside an input report')
    if output.exists():
        profile.require(resume and (output / 'batch.json').is_file(), 'Batch output exists; use --resume with its original config')
    else:
        profile.require(not resume, '--resume requires an existing batch')
        output.mkdir(parents=True)
    with (output / '.batch.lock').open('a') as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Batch is already running') from exc
        fingerprints = input_fingerprints(spec, config_path.parent)
        if resume:
            state = profile.read_json(output / 'batch.json')
            profile.require(state.get('schema') == 'xsai-prof.batch/v1' and
                            state['config_sha256'] == profile.digest(config_path) and
                            profile.read_json(output / 'config.json') == spec and
                            state.get('input_fingerprints') == fingerprints,
                            'Batch configuration or input changed; use a new output')
            # Verify completed sides before changing any batch state. Raw
            # manifest/artifact checks run as part of verify_saved_report.
            for entry in state['cases']:
                for saved in entry.get('inputs', {}).values():
                    profile.verify_saved_report(saved, kda)
                if entry['state'] == 'compared':
                    check_comparison(output / entry['comparison'])
        else:
            profile.dump(output / 'config.json', spec)
            state = {'schema': 'xsai-prof.batch/v1', 'status': 'running', 'config_path': str(config_path),
                     'config_sha256': profile.digest(config_path), 'input_fingerprints': fingerprints,
                     'execution': 'sequential; collection retains runtime/emulator locks',
                     'created_utc': now(), 'planned_cases': len(spec['cases']), 'cases': [], 'rows': [], 'limitations': [
                         'Unmeasured is not zero; failed/incompatible pairs have no speedup.',
                         'Per-shape recorded ranges are not confidence intervals; no aggregate speedup is inferred.']}
        state['status'] = 'running'
        render(output, state)
        for case in spec['cases']:
            entry = next((e for e in state['cases'] if e['id'] == case['id']), None)
            if entry is None:
                entry = {'id': case['id'], 'state': 'pending', 'attempts': [], 'inputs': {}}
                state['cases'].append(entry)
            if entry['state'] in ('compared', 'unmeasured'):
                continue
            if case.get('baseline') is None or case.get('candidate') is None:
                entry['state'] = 'unmeasured'
                state['rows'].append({'id': case['id'], 'state': 'unmeasured', 'outcome': None, 'speedup': None,
                                      'error': 'Both baseline and candidate are required'})
                render(output, state)
                continue
            case_dir = output / 'cases' / case['id']
            case_dir.mkdir(parents=True, exist_ok=True)
            for attempt in entry['attempts']:
                if attempt['state'] == 'running':
                    attempt.update(state='interrupted', finished_utc=now())
            for retry in range(retries + 1):
                attempt = {'number': len(entry['attempts']) + 1, 'state': 'running', 'started_utc': now()}
                entry['attempts'].append(attempt)
                entry['state'] = 'running'
                state.update(active_stage=case['id'], updated_utc=now())
                state['rows'] = [r for r in state['rows'] if r['id'] != case['id']]
                render(output, state)
                try:
                    inputs = []
                    for role in ('baseline', 'candidate'):
                        if role in entry['inputs']:
                            loaded = profile.verify_saved_report(entry['inputs'][role], kda)
                        else:
                            loaded = obtain(case[role], config_path.parent, case_dir / role, kda)
                            entry['inputs'][role] = str(loaded[1])
                            render(output, state)
                        inputs.append(loaded)
                    (a, ap), (b, bp) = inputs
                    comparison = profile.compare_reports(a, b, (ap, bp), kda)
                    comparison_dir = case_dir / ('comparison-' + str(attempt['number']))
                    profile.publish(comparison_dir, lambda _: comparison)
                    state['rows'] += result_rows(case['id'], comparison)
                    entry.update(state='compared', comparison=str(comparison_dir.relative_to(output)))
                    entry.pop('error', None)
                    attempt.update(state='passed', finished_utc=now())
                    break
                except BaseException as exc:
                    attempt.update(state='failed', error=str(exc), finished_utc=now())
                    entry.update(state='failed', error=str(exc))
                    profile.dump(case_dir / ('failure-' + str(attempt['number']) + '.json'), attempt)
                    profile.dump(case_dir / 'failure.json', attempt)
                    state['rows'].append({'id': case['id'], 'state': 'failed', 'outcome': None, 'speedup': None, 'error': str(exc)})
                    if not isinstance(exc, (RuntimeError, OSError, ValueError, KeyError, sqlite3.Error)):
                        state['status'] = 'interrupted' if isinstance(exc, (KeyboardInterrupt, SystemExit)) else 'failed'
                        render(output, state)
                        raise
                    render(output, state)
            render(output, state)
        failed = any(c['state'] == 'failed' for c in state['cases'])
        state.update(status='completed_with_failures' if failed else 'completed', active_stage=None, updated_utc=now())
        render(output, state)
        profile.dump(output / 'checksums.json', {'files': {name: profile.digest(output / name)
                     for name in ('config.json', 'batch.json', 'batch.csv', 'index.html')}})
        return state


def add_parser(commands):
    p = commands.add_parser('batch', help='Collect or import multiple baseline/candidate pairs and export a shape matrix')
    p.add_argument('--config', type=Path, required=True)
    p.add_argument('--output', '-o', type=Path, required=True)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--retries', type=int, default=0, help='Additional attempts per failed case; retain all failures')


def dispatch(args, kda):
    state = batch(args.config, args.output, kda, args.resume, args.retries)
    print(json.dumps({'status': state['status'], 'report': str(args.output / 'batch.json'), 'cases': state['cases']}))
    return 1 if state['status'] == 'completed_with_failures' else 0
