#!/usr/bin/env python3
"""Verify the exact release wheel and keep its clean venv for live RTL acceptance."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(wheel, output, rtl_config=None):
    wheel, output = wheel.resolve(), output.resolve()
    assert not output.exists(), 'Preserve prior installation attempts'
    output.mkdir(parents=True)
    checks = []
    subprocess.run([sys.executable, '-m', 'venv', str(output/'venv')], check=True)
    python = output/'venv/bin/python'
    result = subprocess.run([str(python), '-m', 'pip', 'install', '--no-index', '--no-deps', str(wheel)], capture_output=True, text=True)
    (output/'pip.log').write_text(result.stdout+result.stderr)
    assert result.returncode == 0
    program = output/'venv/bin/xsai-prof'
    env = {k: v for k, v in os.environ.items() if k not in ['PYTHONPATH', 'XSAI_KDA_ROOT', 'NOOP_HOME']}
    with tempfile.TemporaryDirectory(prefix='xsai-prof-beta-client-') as temporary:
        work = Path(temporary)
        serial = 0
        def command(*args, expected=0):
            nonlocal serial
            serial += 1
            result = subprocess.run([str(program), *map(str,args)], cwd=work, env=env, capture_output=True, text=True)
            (output/('command-'+str(serial)+'.log')).write_text(result.stdout+result.stderr)
            assert result.returncode == expected, (args, result.returncode, result.stdout, result.stderr)
            return result.stdout
        from email.parser import Parser
        with zipfile.ZipFile(wheel) as archive:
            metadata = Parser().parsestr(archive.read(next(n for n in archive.namelist() if n.endswith('.dist-info/METADATA'))).decode())
        assert command('--version').strip() == 'xsai-prof ' + metadata['Version']
        assert json.loads(command('doctor'))['offline_ready']
        checks.append('Exact beta wheel installs offline and CLI works outside project without PYTHONPATH')
        location = subprocess.check_output([str(python), '-I', '-c', 'import xsai_prof;print(xsai_prof.__file__)'], cwd=work, env=env, text=True).strip()
        package = Path(location).parent
        members = {}
        with zipfile.ZipFile(wheel) as archive:
            for name in archive.namelist():
                if name.startswith('xsai_prof/') and not name.endswith('/'):
                    sha = hashlib.sha256(archive.read(name)).hexdigest()
                    assert digest(package/name.removeprefix('xsai_prof/')) == sha
                    members[name] = sha
        assert (package/'resources/docs/profiler-quickstart.md').is_file()
        checks.append('All installed code, analyzer, licenses and user docs match exact release wheel bytes')
        argv = ['init', '--output', work/'config.json']
        for name in ['blas', 'noop-home', 'rtl-config', 'xsai-env', 'am-home', 'llvm-home']:
            argv += ['--'+name, work/('missing-'+name)]
        assert json.loads(command(*argv))['status']=='created'
        doctor=json.loads(command('doctor','--config',work/'config.json',expected=1))
        assert doctor['rtl_collection']['next_steps']
        checks.append('Installed setup emits explicit config and doctor explains missing external paths')
        command('demo','--output',work/'demo')
        command('analyze',work/'demo/baseline','--output',work/'analysis')
        analysis=json.loads((work/'analysis/analysis.json').read_text())
        assert analysis['overview']['coverage']['memory']=='unavailable'
        assert not analysis['overview']['hypotheses']
        checks.append('Installed unified overview preserves missing memory and does not invent hypotheses')
        names={item['name'] for item in json.loads(command('query','metrics','--format','json'))['items']}
        assert {'ame_read_payload_bytes','ame_read_service_cycles','ame_read_outstanding_max'}<=names
        checks.append('Installed metric query discovers reviewed read-return capability without claiming measured availability')
        if rtl_config:
            doctor=json.loads(command('doctor','--config',rtl_config.resolve()))
            assert doctor['rtl_collection']['status']=='available'
            assert doctor['rtl_collection']['supported_target']['coverage']['ame_read_returns']
            checks.append('Installed doctor validates actual external dependencies and exact reviewed target/coverage')
    receipt={'schema':'xsai-prof.beta-install/v1','status':'passed','checks_passed':len(checks),'checks':checks,
        'wheel':str(wheel),'wheel_sha256':digest(wheel),'program':str(program),'python':str(python),
        'installed_package':str(package),'member_hashes':members,'real_collection_executed':False}
    (output/'acceptance.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k!='member_hashes'}))


if __name__=='__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--wheel',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--rtl-config',type=Path,help='Collection config to validate, without running simulation')
    args=parser.parse_args()
    verify(args.wheel,args.output,args.rtl_config)
