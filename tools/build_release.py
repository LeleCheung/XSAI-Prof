#!/usr/bin/env python3
"""Build sdist -> wheel offline and record artifacts; never publish or push."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def build(output):
    output = output.resolve()
    if output.exists():
        raise RuntimeError('Release output must be a new directory')
    output.mkdir(parents=True)
    log_path = output / 'build.log'
    commands = []
    with log_path.open('w') as log, tempfile.TemporaryDirectory(prefix='xsai-prof-release-') as tmp:
        temp = Path(tmp)

        def run(command, cwd):
            commands.append({'argv': command, 'cwd': str(cwd)})
            subprocess.run(command, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, check=True)

        run([sys.executable, 'setup.py', 'sdist', '--dist-dir', str(output)], ROOT)
        sdist = next(output.glob('*.tar.gz'))
        unpacked = temp / 'source'
        unpacked.mkdir()
        with tarfile.open(sdist) as archive:
            for member in archive.getmembers():
                target = (unpacked / member.name).resolve()
                if not target.is_relative_to(unpacked) or member.issym() or member.islnk():
                    raise RuntimeError('Unsafe source distribution member')
            if hasattr(tarfile, 'data_filter'):
                archive.extractall(unpacked, filter='data')
            else:
                archive.extractall(unpacked)
        source = next(unpacked.iterdir())
        run([sys.executable, '-m', 'pip', 'wheel', '.', '--no-deps', '--no-build-isolation',
             '--no-index', '-w', str(output)], source)
    wheel = next(output.glob('*.whl'))
    with zipfile.ZipFile(wheel) as archive:
        members = {name: hashlib.sha256(archive.read(name)).hexdigest()
                   for name in archive.namelist() if not name.endswith('/')}
        required = ['xsai_prof/cli.py', 'xsai_prof/kda_setup.py', 'xsai_prof/kda_ame_memory.py',
                    'xsai_prof/vendor/roi_hotspots.py', 'xsai_prof/resources/docs/profiler-quickstart.md']
        if not all(name in members for name in required):
            raise RuntimeError('Release resources missing from wheel')
    result = {'schema': 'xsai-prof.release/v1', 'status': 'built',
        'publication': 'not_published', 'python': sys.version.split()[0], 'commands': commands,
        'artifacts': {path.name: digest(path) for path in (sdist, wheel, log_path)},
        'wheel_members': members,
        'validation': 'Build integrity only. See the independent software/install/RTL acceptance records.'}
    (output / 'release.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps({'status': 'built', 'output': str(output), 'artifacts': result['artifacts']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.output)
