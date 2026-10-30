"""Observable subprocess groups and read-only collection/batch status."""
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import kda_profile as profile


def run_stage(command, *, stdout, stderr, cwd, env, pass_fds, timeout=None, heartbeat=None):
    """Kill the whole owned process group on timeout/interruption, then reap it.

    The adapter's simulator and compiler children stay in this group. The
    inherited collection lock remains held until every child has exited.
    """
    started = time.monotonic()
    child = subprocess.Popen(command, stdout=stdout, stderr=stderr, cwd=cwd,
                             env=env, pass_fds=pass_fds, start_new_session=True)
    try:
        while True:
            elapsed = time.monotonic() - started
            if heartbeat:
                heartbeat({'pid': child.pid, 'elapsed_seconds': round(elapsed, 1),
                           'log_bytes': os.fstat(stdout.fileno()).st_size})
            if timeout is not None and elapsed >= timeout:
                raise TimeoutError(f'Collection stage exceeded {timeout} seconds')
            try:
                child.wait(timeout=min(5, max(0.01, timeout - elapsed)) if timeout is not None else 5)
                return child
            except subprocess.TimeoutExpired:
                continue
    finally:
        # Also clean descendants if an adapter exits unexpectedly leaving a
        # simulator behind. Never release the parent lock with that child alive.
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        try:
            child.wait(timeout=3)
        except subprocess.TimeoutExpired:
            os.killpg(child.pid, signal.SIGKILL)
            child.wait()
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass


def status(path):
    path = Path(path).resolve()
    if path.is_dir():
        files = [p for p in (path / 'collection.json', path / 'batch.json') if p.is_file()]
        profile.require(len(files) == 1, 'Expected one collection.json or batch.json')
        path = files[0]
    data = profile.read_json(path)
    profile.require(data.get('schema') in ('xsai-kda.collection/v1', 'xsai-prof.batch/v1'), 'Unsupported job schema')
    if 'stages' in data:
        units = data['stages']
        passed = sum(any(a['status'] == 'passed' for a in u['attempts']) for u in units)
        attempts = sum(len(u['attempts']) for u in units)
    else:
        units = data['cases']
        passed = sum(u['state'] == 'compared' for u in units)
        attempts = sum(len(u.get('attempts', [])) for u in units)
    return {'schema': 'xsai-prof.job-status/v1', 'path': str(path), 'status': data['status'],
            'recorded_completed_units': passed, 'total_units': data.get('planned_cases', len(units)), 'attempts': attempts,
            'active_stage': data.get('active_stage'), 'heartbeat': data.get('heartbeat'),
            'error': data.get('error'), 'evidence_verified': False,
            'note': 'Progress snapshot; completion counts are recorded job state, not an evidence revalidation.'}


def add_parser(commands):
    p = commands.add_parser('status', help='Read collection or batch progress without acquiring its execution lock')
    p.add_argument('job', type=Path)


def dispatch(args, kda):
    print(json.dumps(status(args.job), ensure_ascii=False, indent=2))
