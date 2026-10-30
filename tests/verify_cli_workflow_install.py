#!/usr/bin/env python3
"""Verify a specific 0.8 wheel in a persistent clean project-external client."""
import argparse
import csv
from email.parser import Parser
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import zipfile


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify(wheel, output, config=None):
    wheel, output = wheel.resolve(), output.resolve()
    assert not output.exists(), 'Preserve installation attempts'
    output.mkdir(parents=True)
    subprocess.run([sys.executable, '-m', 'venv', str(output/'venv')], check=True)
    python = output/'venv/bin/python'
    result=subprocess.run([str(python),'-m','pip','install','--no-index','--no-deps',str(wheel)],capture_output=True,text=True)
    (output/'pip.log').write_text(result.stdout+result.stderr)
    assert result.returncode==0
    program=output/'venv/bin/xsai-prof'
    env={k:v for k,v in os.environ.items() if k not in ('PYTHONPATH','XSAI_KDA_ROOT','NOOP_HOME')}
    checks=[];commands=[]
    with tempfile.TemporaryDirectory(prefix='xsai-prof08-client-') as tmp:
        work=Path(tmp)
        def run(*args,expected=0):
            argv=[str(program),*map(str,args)]
            result=subprocess.run(argv,cwd=work,env=env,capture_output=True,text=True)
            log=output/('command-'+str(len(commands)+1)+'.log')
            log.write_text(result.stdout+result.stderr)
            commands.append({'argv':argv,'cwd':tmp,'exit_code':result.returncode,'log':log.name,'log_sha256':digest(log)})
            assert result.returncode==expected,(args,result.stdout,result.stderr)
            return result.stdout
        with zipfile.ZipFile(wheel) as z:
            meta=Parser().parsestr(z.read(next(n for n in z.namelist() if n.endswith('.dist-info/METADATA'))).decode())
            assert run('--version').strip()=='xsai-prof '+meta['Version']
            package=Path(subprocess.check_output([str(python),'-I','-c','import xsai_prof;print(xsai_prof.__file__)'],cwd=work,env=env,text=True).strip()).parent
            members={n:hashlib.sha256(z.read(n)).hexdigest() for n in z.namelist() if n.startswith('xsai_prof/') and not n.endswith('/')}
            for name,sha in members.items():assert digest(package/name.removeprefix('xsai_prof/'))==sha
            assert 'xsai_prof/resources/docs/profiler-cli-workflow.md' in members
        checks.append('Exact wheel installs offline; every installed code/resource member matches; CLI runs outside project without PYTHONPATH')
        for alias,kind in [('--query-metrics','metrics'),('--list-sections','sections'),('--list-sets','sets')]:
            assert json.loads(run(alias,'--format','json'))==json.loads(run('query',kind,'--format','json'))
        queried=list(csv.DictReader(io.StringIO(run('--query-metrics','--filter','ame_read','--format','csv'))))
        assert queried and all(r['name'].startswith('ame_read') for r in queried)
        checks.append('Discovery aliases and filtered CSV catalog work after installation')
        cfg={'blas':str(work/'missing-blas'),'noop_home':str(work/'missing-rtl'),'rtl_config':str(work/'rtl.json'),
            'kernel':'softmax','diagnostics':[],'perf_repeats':2}
        (work/'rtl.json').write_text('{}');(work/'config.json').write_text(json.dumps(cfg))
        plan=json.loads(run('collect','--config',work/'config.json','--metrics','cycles_per_call','--dry-run','-o',work/'uncreated',expected=1))
        assert plan['status']=='blocked' and plan['cost']['fresh_emulator_invocations']==4
        assert not (work/'uncreated').exists()
        run('collect','--config',work/'config.json','--metrics','dram_bytes','--dry-run','-o',work/'uncreated',expected=1)
        checks.append('Blocked no-op plans preserve stage costs and unknown metrics never become fake values or bundles')
        run('demo','-o',work/'demo')
        view=json.loads(run('report',work/'demo/baseline','--metrics','cycles_per_call','--format','json'))
        assert view['evidence_verified'] and view['rows'] and all(r['metric']=='cycles_per_call' for r in view['rows'])
        run('view',work/'demo/baseline','--metrics','cycles_per_call','--format','csv','-o',work/'perf.csv')
        assert list(csv.DictReader(io.StringIO((work/'perf.csv').read_text())))
        assert json.loads(run('view',work/'demo/baseline','--metrics','ame_read_payload_bytes','--format','json'))['rows'][0]['value'] is None
        run('view',work/'demo/baseline','--format','csv','-o',work/'perf.csv',expected=1)
        checks.append('Saved report aliases, filtered views, CSV quoting, missing values and exclusive exports work')
        compared=json.loads(run('view',work/'demo/candidate','--page','comparison','--baseline',work/'demo/baseline','--format','json'))
        assert compared['rows'][0]['speedup']>1 and compared['rows'][0]['delta']<0
        checks.append('Comparison separates cycle medians, cycle delta and dimensionless speedup')
        run('analyze',work/'demo/baseline','-o',work/'analysis')
        opened=json.loads(run('open',work/'analysis','--no-browser'))
        assert opened['status']=='verified' and not opened['browser_opened']
        doc=(work/'analysis/index.html').read_text()
        assert 'AME interface traffic' in doc and 'Experiments to validate' in doc
        (work/'analysis/index.html').write_text(doc+'changed')
        run('open',work/'analysis','--no-browser',expected=1)
        checks.append('Offline UI resources and opener work; modified report bytes are rejected')
        if config:
            assert json.loads(run('doctor','--config',config.resolve()))['rtl_collection']['status']=='available'
            ready=json.loads(run('collect','--config',config.resolve(),'--metrics','ame_read_payload_bytes','--dry-run','-o',work/'real-preview'))
            assert ready['status']=='ready' and ready['target']['coverage']['ame_read_returns']
            assert not (work/'real-preview').exists()
            checks.append('Installed dry-run validates actual external reviewed target without starting RTL')
    receipt={'schema':'xsai-prof.cli-install/v1','status':'passed','checks_passed':len(checks),'checks':checks,
        'wheel':str(wheel),'wheel_sha256':digest(wheel),'version':meta['Version'],'program':str(program),
        'package':str(package),'member_hashes':members,'commands':commands,
        'real_collection_executed':False,'browser_executed':False}
    (output/'acceptance.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(json.dumps({k:v for k,v in receipt.items() if k not in ('member_hashes','commands')}))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--wheel',type=Path,required=True);parser.add_argument('--output',type=Path,required=True);parser.add_argument('--config',type=Path)
    args=parser.parse_args();verify(args.wheel,args.output,args.config)
