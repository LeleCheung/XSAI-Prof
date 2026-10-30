"""Installable CLI; flat script imports remain backwards compatible."""
import argparse
import json
from pathlib import Path
import sys

def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    aliases = {'--query-metrics': 'metrics', '--list-sections': 'sections', '--list-sets': 'sets'}
    if argv and argv[0] in aliases:
        argv = ['query', aliases[argv[0]], *argv[1:]]
    core = str(Path(__file__).resolve().parent)
    if core not in sys.path:
        sys.path.insert(0, core)
    import kda_profile as profile
    import xsai_kda as adapter
    parser = argparse.ArgumentParser(prog='xsai-prof', description='XSAI operator profiling: collect, explain and compare verified evidence',
        epilog='Discovery aliases: --query-metrics, --list-sections, --list-sets. Use collect --dry-run before RTL acquisition. Views: view REPORT --page details|source|memory --format text|json|csv.')
    from kda_version import __version__
    parser.add_argument('--version', action='version', version='xsai-prof ' + __version__)
    profile.add_commands(parser)
    args = parser.parse_args(argv)
    try:
        return profile.dispatch(args, adapter) or 0
    except (RuntimeError, OSError, ValueError, KeyError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}), file=sys.stderr)
        return 1

if __name__ == '__main__':
    sys.exit(main())
