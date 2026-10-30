"""Separate installed code/resources from external, writable workspaces."""
import os
from pathlib import Path

CODE = Path(__file__).resolve().parent
SOURCE_TREE = CODE.name == 'scripts' and (CODE.parent / 'vendor/xsai-blas-profiling').is_dir()
ROOT = Path(os.environ.get('XSAI_KDA_ROOT', str(CODE.parent if SOURCE_TREE else Path.cwd()))).resolve()
VENDOR = CODE.parent / 'vendor/xsai-blas-profiling' if SOURCE_TREE else CODE / 'vendor'
ADAPTER = CODE / 'xsai_kda.py'

def runtime_locks():
    return Path(os.environ.get('XSAI_PROF_STATE_HOME', str(Path.home() / '.cache/xsai-prof'))) / 'locks'
