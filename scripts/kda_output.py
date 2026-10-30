"""Consistent human/machine tables and exclusive, evidence-safe output files."""
import csv
import io
import json
from pathlib import Path

import kda_profile as p


def scalar(value):
    if value is None:
        return 'unavailable'
    if isinstance(value, (dict, list)):
        return json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    return str(value)


def render(data, rows, columns, format):
    if format == 'json':
        return json.dumps(data, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if format == 'csv':
        stream = io.StringIO(newline='')
        writer = csv.writer(stream)
        writer.writerow(columns)
        for row in rows:
            writer.writerow([scalar(row.get(key)) if row.get(key) is not None else '' for key in columns])
        return stream.getvalue()
    lines = [' | '.join(columns)]
    lines += [' | '.join(scalar(row.get(key)).replace('\n', ' ') for key in columns) for row in rows]
    if not rows:
        lines.append('(no matching rows)')
    if data.get('warnings'):
        lines += ['Warnings:'] + ['- ' + warning for warning in data['warnings']]
    return '\n'.join(lines) + '\n'


def emit(text, output=None, protected=()):
    if output is None:
        print(text, end='')
        return
    output = Path(output).resolve()
    p.require(not output.exists(), 'Output exists; choose a new file')
    p.require(not output.is_relative_to(p.ROOT/'dependencies') and
              not any(output.is_relative_to(Path(root).resolve()) for root in protected) and
              not any((root/'manifest.json').exists() or (root/'checksums.json').exists()
                      for root in output.parents), 'Output must be outside saved reports, raw evidence and dependencies')
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open('x', newline='') as stream:
        stream.write(text)
