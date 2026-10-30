#!/usr/bin/env python3
"""Build and test a wheel outside the source tree, with an unshared venv."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile

ROOT = Path(__file__).resolve().parents[1]


def verify():
    checks = []
    with tempfile.TemporaryDirectory(prefix='xsai-prof-install-') as temporary:
        root = Path(temporary)
        clean = root / 'source'
        clean.mkdir()
        # Test source distribution completeness as well as wheel installation.
        source = subprocess.run([sys.executable, 'setup.py', 'sdist', '--dist-dir', str(root / 'sdist')], cwd=ROOT,
                                capture_output=True, text=True)
        if source.returncode:
            raise RuntimeError(source.stdout + source.stderr)
        import tarfile
        archive = next((root / 'sdist').glob('*.tar.gz'))
        with tarfile.open(archive) as tf:
            for member in tf.getmembers():
                assert (clean / member.name).resolve().is_relative_to(clean) and not member.issym() and not member.islnk()
            if hasattr(tarfile, 'data_filter'):
                tf.extractall(clean, filter='data')
            else:
                tf.extractall(clean)
        package_source = next(clean.iterdir())
        result = subprocess.run([sys.executable, '-m', 'pip', 'wheel', '.', '--no-deps', '--no-build-isolation', '--no-index', '-w', str(root / 'wheel')],
                                cwd=package_source, capture_output=True, text=True)
        if result.returncode:
            raise RuntimeError(result.stdout + result.stderr)
        checks.append('Wheel builds from source distribution without local dependencies')
        wheel = next((root / 'wheel').glob('*.whl'))
        with zipfile.ZipFile(wheel) as zipped:
            names = zipped.namelist()
            assert 'xsai_prof/vendor/roi_hotspots.py' in names
            assert 'xsai_prof/vendor/LICENSE' in names
            assert 'xsai_prof/vendor/RTL-SOURCE-LICENSE' in names
            assert 'xsai_prof/vendor/RTL-SOURCE-NOTICE' in names
            assert not any(n.endswith(('/kda_model.py', '/bootstrap.py', '/verify_profile_examples.py')) for n in names)
            assert not any('dependencies/' in n or n.endswith('/key.md') for n in names)
        checks.append('Wheel contains pinned analyzer/license and excludes agent/model/local configuration')
        subprocess.run([sys.executable, '-m', 'venv', str(root / 'venv')], check=True)
        python = root / 'venv/bin/python'
        subprocess.run([str(python), '-m', 'pip', 'install', '--no-deps', str(wheel)], check=True, capture_output=True)
        program = root / 'venv/bin/xsai-prof'
        work = root / 'work'
        work.mkdir()
        env = {k: v for k, v in os.environ.items() if k not in ('PYTHONPATH', 'XSAI_KDA_ROOT')}

        def command(*args, expected=0):
            result = subprocess.run([str(program), *map(str, args)], cwd=work, env=env, capture_output=True, text=True)
            if result.returncode != expected:
                raise RuntimeError(f'{args}: code={result.returncode}\n{result.stdout}\n{result.stderr}')
            return result

        assert command('--version').stdout.startswith('xsai-prof ')
        assert json.loads(command('doctor').stdout)['offline_ready']
        checks.append('Installed entry point and offline doctor work outside project without PYTHONPATH')
        for kind in ('metrics', 'sections', 'sets'):
            assert json.loads(command('query', kind, '--format', 'json').stdout)['items']
        checks.append('Installed metric, section and set queries work')
        demo = work / 'demo'
        command('demo', '--output', demo)
        assert (demo / 'comparison/index.html').is_file()
        assert (demo / 'baseline/metrics.json').is_file()
        assert any('SYNTHETIC' in w for w in json.loads((demo / 'baseline/report.json').read_text())['warnings'])
        checks.append('Installed demo creates evidence-bound reports and comparison with fixture warning')
        command('report', '--spec', demo / 'baseline-spec.json', '--output', work / 'offline-report')
        command('compare', demo / 'baseline', demo / 'candidate', '--output', work / 'offline-compare')
        command('diagnose', demo / 'baseline', '--output', work / 'diagnose')
        command('query', 'metrics', '--report', demo / 'baseline', '--format', 'json')
        command('batch', '--config', demo / 'batch-config.json', '--output', work / 'batch')
        checks.append('Installed report/compare/diagnose/query/batch validate original evidence')
        command('hardware', demo / 'baseline', '--output', work / 'hardware')
        explanation = json.loads((work / 'hardware/hardware.json').read_text())
        assert explanation['hpm']['build_binding']['status'] == 'unreviewed'
        assert explanation['hpm']['counters'][0]['normalization']['events_per_call'] is None
        assert explanation['clocks']['cross_engine_overlap'] is None
        checks.append('Installed hardware explanation bundles reviewed contracts, preserves unknown builds and missing telemetry')
        command('timeline', demo / 'baseline', '--output', work / 'no-trace', expected=1)
        assert not (work / 'no-trace').exists()
        checks.append('Missing trace fails explicitly without output')
        # Target-ISA fixture uses a real ELF and synthetic DB, no RTL runtime needed.
        if __import__('shutil').which('riscv64-linux-gnu-gcc'):
            with (work / 'trace-fixture.py').open('w') as stream:
                stream.write("import sys\nfrom pathlib import Path\nsys.path.insert(0,str(Path(sys.argv[1]).parent))\nimport kda_profile as p, kda_demo, xsai_kda as k\nimport sqlite3,subprocess\nroot=Path(sys.argv[2])\nr=root/'trace'\nkda_demo.fixture_run(r,'trace',0,'synthetic-baseline',k)\nsubprocess.run(['riscv64-linux-gnu-gcc','-nostdlib','-static','-march=rv64gc','-g','-Wl,-Ttext=0x80000000','-Wl,--build-id=none',sys.argv[3],'-o',str(r/'perf.elf')],check=True)\n(r/'profile.elf').write_bytes((r/'perf.elf').read_bytes())\nwith sqlite3.connect(r/'chiseldb.db') as db:\n db.execute('CREATE TABLE LifeTimeCommitTrace(SN INTEGER,PC INTEGER,DisAsm INTEGER,AtFetch INTEGER,AtIssueQue INTEGER,AtFU INTEGER,AtCommit INTEGER)')\n for sn,code,t in [(1,0x5a100013,101),(2,0x00150513,104),(3,0x00250513,108),(4,0x5a200013,113)]:\n  db.execute('INSERT INTO LifeTimeCommitTrace VALUES(?,?,?,?,?,?,?)',(sn,0x80000000+4*(sn-1),code,t-4,t-3,t-1,t))\nm=p.read_json(r/'manifest.json')\nfor name in ('perf.elf','profile.elf','chiseldb.db'):m['artifacts'][name]={'sha256':p.digest(r/name)}\np.dump(r/'manifest.json',m)\ns=p.read_json(root/'demo/baseline-spec.json')\ns['perf']=[str(root/'demo'/v) for v in s['perf']]\ns['hpm']=str(root/'demo'/s['hpm'])\ns['trace']=str(r)\np.dump(root/'trace-spec.json',s)\n")
            location = subprocess.run([str(python), '-c', 'import xsai_prof; print(xsai_prof.__file__)'], capture_output=True, text=True, check=True).stdout.strip()
            subprocess.run([str(python), str(work / 'trace-fixture.py'), location, str(work), str(ROOT / 'tests/roi_fixture.S')], cwd=work, env=env, check=True, capture_output=True)
            command('report', '--spec', work / 'trace-spec.json', '--output', work / 'trace-report', '--recompute-roi')
            command('timeline', work / 'trace-report', '--output', work / 'timeline')
            assert len(json.loads((work / 'timeline/timeline.json').read_text())['events']) == 2
            checks.append('Installed pinned analyzer, ELF validation and timeline work on distributable synthetic trace fixture')
        command('batch', '--config', demo / 'batch-config.json', '--output', work / 'batch', '--resume')
        state = json.loads(command('status', work / 'batch').stdout)
        assert state['status'] == 'completed' and state['total_units'] == 3
        checks.append('Installed batch resume verifies completed inputs; status exposes progress without rerunning')
        coding = work / 'event-coding.json'
        coding.write_text(json.dumps({'hpm_event_coding': [{'group': 'Backend', 'id': 0, 'name': 'noEvent', 'signal': 'zero'}]}))
        queried = json.loads(command('query', 'events', '--rtl-config', coding, '--format', 'json').stdout)
        assert queried['items'][0]['semantic_status'] == 'reference_only'
        checks.append('Installed custom-event discovery preserves unreviewed build semantics')
        command('export', demo / 'baseline', '--output', work / 'portable.zip')
        # No original source/report paths may be consulted after relocation.
        demo.rename(work / 'unavailable-original-demo')
        command('import', work / 'portable.zip', '--output', work / 'imported')
        command('analyze', work / 'imported/report', '--output', work / 'analysis')
        analyzed = json.loads((work / 'analysis/analysis.json').read_text())
        assert analyzed['performance']['status'] == 'available'
        assert analyzed['timeline']['status'] == 'unavailable'
        command('model', '--help')
        command('memory', '--help')
        command('memory', work / 'imported/report', '--output', work / 'missing-memory', expected=1)
        assert not (work / 'missing-memory').exists()
        checks.append('Installed export/import/analyze works after original evidence paths disappear; new model CLI imports independently')
        return {'schema': 'xsai-prof.install-acceptance/v1', 'status': 'passed', 'checks': checks,
                'checks_passed': len(checks), 'wheel_sha256': hashlib.sha256(wheel.read_bytes()).hexdigest(),
                'limits': ['Fixture numbers are synthetic, not RTL measurements.', 'External target ISA tools are host dependencies.']}

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--output', type=Path)
    args = p.parse_args()
    result = verify()
    if args.output:
        args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(result, ensure_ascii=False, indent=2))
