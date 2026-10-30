"""Portable evidence archives: preserve raw identities, rebuild derived paths."""
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import tempfile
import zipfile

import kda_profile as p

SCHEMA = 'xsai-prof.portable/v1'
MAX_BYTES = 64 * 1024 ** 3
MAX_FILES = 100000


def export(report_path, output, kda):
    report, directory = p.verify_saved_report(report_path, kda)
    output = output.resolve()
    p.require(not output.exists(), 'Archive destination exists')
    p.require(not output.is_relative_to(directory) and not output.is_relative_to(p.ROOT / 'dependencies') and
              not any((x / 'manifest.json').exists() for x in (output, *output.parents)),
              'Archive must not modify evidence or dependencies')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.xsai-export-', dir=output.parent) as tmp:
        root = Path(tmp)
        files, entries, runs = {}, {}, {}

        def copy_file(source, name):
            p.require(not source.is_symlink() and source.is_file(), 'Archive rejects symlinks and non-files')
            target = root / name
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            files[name] = p.digest(target)
            p.require(files[name] == p.digest(source), 'Evidence changed during export')

        for i, item in enumerate(report['inputs']):
            run = Path(item['run'])
            name = 'evidence/run-' + str(i)
            manifest = kda.load_run(run)
            copy_file(run / 'manifest.json', name + '/manifest.json')
            for artifact in manifest.get('artifacts', {}):
                source = (run / artifact).resolve()
                p.require(source.is_relative_to(run.resolve()), 'Run artifact escapes evidence root')
                copy_file(source, name + '/' + artifact)
            entry = {'run': name}
            for key, suffix in [('source_receipt', '.json'), ('source_archive', '.zip')]:
                if item.get(key):
                    relative = 'sources/' + str(i) + suffix
                    copy_file(Path(item[key]), relative)
                    entry[key] = relative
            runs[str(run)] = entry
        for mode in ('perf', 'hpm', 'trace'):
            if mode in report['spec']:
                values = report['spec'][mode] if mode == 'perf' else [report['spec'][mode]]
                selected = [runs[str(Path(v['run']).resolve())] for v in values]
                entries[mode] = selected if mode == 'perf' else selected[0]
        # Keep the original report byte-for-byte, with its original paths. Only
        # the newly built imported report uses relocated evidence references.
        checksum = p.read_json(directory / 'checksums.json')
        for name in set(checksum['files']) | {'checksums.json'}:
            copy_file(directory / name, 'original-report/' + name)
        metadata = {'schema': SCHEMA, 'spec': {**report['spec'], **entries},
                    'options': report['options'], 'files': files,
                    'original_report_sha256': p.digest(directory / 'report.json'),
                    'policy': 'Raw manifests and artifacts retain exact bytes. Import revalidates and creates a new derived report; original report is archived unchanged.'}
        p.dump(root / 'portable.json', metadata)
        # Revalidate originals after copying, before committing the archive.
        p.verify_saved_report(report_path, kda)
        archive = root / 'output.zip'
        with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as z:
            for name in sorted(files):
                z.write(root / name, name)
            z.write(root / 'portable.json', 'portable.json')
        archive.rename(output)
    return {'status': 'exported', 'archive': str(output), 'sha256': p.digest(output), 'files': len(files)}


def safe_name(name):
    path = PurePosixPath(name)
    return bool(name) and not path.is_absolute() and not any(v in ('', '.', '..') for v in name.split('/')) and '\\' not in name and ':' not in name


def build_imported_report(spec, options, output, kda, original):
    """Keep separately observed diagnostics separate after relocation.

    A replay is never permission to weaken normal report/performance binding.
    Only an explicitly archived observation-only trace can take this path, with
    unchanged software identities, correctness images and a reviewed observer.
    """
    validation = original.get('validation', {})
    if validation.get('diagnostics_bound_to_perf') is not False:
        return p.build_report(spec, options, output, kda)
    p.require(validation.get('observation_replay') and spec.get('trace'),
              'Unbound diagnostics need an explicit observation-only trace receipt')
    reference = p.load_input(spec['perf'][0], kda, 'perf')
    diagnostic = p.load_input(spec['trace'], kda, 'trace')
    # Reuse every software/shape check; RTL identity is deliberately distinct
    # and remains so in the returned report and raw manifests.
    p.bind(reference, {**diagnostic, 'manifest': {
        **diagnostic['manifest'], 'rtl': reference['manifest']['rtl']}})
    for name in ('test.bin', 'test.elf'):
        left = p.recorded_artifact(reference['path'], reference['manifest'], name)
        right = p.recorded_artifact(diagnostic['path'], diagnostic['manifest'], name)
        p.require(p.digest(left) == p.digest(right), 'Observation replay correctness image differs: ' + name)
    from kda_observer import reviewed
    receipts = [name for name in diagnostic['manifest']['artifacts'] if name.startswith('rtl-config.')]
    p.require(len(receipts) == 1, 'Observation replay needs one recorded RTL receipt')
    receipt_path = p.recorded_artifact(diagnostic['path'], diagnostic['manifest'], receipts[0])
    receipt = p.read_json(receipt_path)
    p.require(reviewed(receipt) and
              diagnostic['manifest']['rtl']['emu_sha256'] == receipt['emulator']['sha256'] and
              diagnostic['manifest']['rtl']['config_sha256'] == p.digest(receipt_path),
              'Observation replay needs an exact reviewed observer identity')
    base_spec = {key: value for key, value in spec.items() if key != 'trace'}
    result = p.build_report(base_spec, options, output, kda)
    result['spec'] = spec
    trace = p.trace_section(diagnostic, {**options, 'cute': spec.get('cute')}, output)
    result['sections']['trace'] = trace
    result['inputs'].append(diagnostic['provenance'])
    result['validation'].update(diagnostics_bound_to_perf=False,
        observation_replay=validation['observation_replay'])
    result['warnings'] = list(dict.fromkeys(
        [w for w in result['warnings'] if w != 'TRACE evidence unavailable.'] +
        original.get('warnings', []) +
        ['Relocated observation-only trace: software and correctness images verified; diagnostic RTL remains independent of performance RTL. No new speedup claim.']))
    result['observations'] = original.get('observations', [])
    return result


def import_archive(archive, output, kda, tools=None):
    archive, output = archive.resolve(), output.resolve()
    p.require(not output.exists(), 'Import destination exists')
    p.require(not output.is_relative_to(p.ROOT / 'dependencies') and
              not any((x / 'manifest.json').exists() for x in (output, *output.parents)), 'Import must not modify evidence or dependencies')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='.xsai-import-', dir=output.parent) as tmp:
        staging = Path(tmp) / 'bundle'
        staging.mkdir()
        with zipfile.ZipFile(archive) as z:
            entries = z.infolist()
            names = [i.filename for i in entries]
            p.require(len(entries) <= MAX_FILES and sum(i.file_size for i in entries) <= MAX_BYTES, 'Archive exceeds size/file limits')
            p.require(len(names) == len(set(names)) and all(safe_name(n) for n in names), 'Unsafe or duplicate archive path')
            p.require(all(not i.is_dir() and stat.S_IFMT(i.external_attr >> 16) in (0, stat.S_IFREG) for i in entries), 'Archive rejects symlinks and special files')
            p.require('portable.json' in names and z.getinfo('portable.json').file_size <= 32 * 1024 ** 2, 'Missing/oversized portable receipt')
            metadata = json.loads(z.read('portable.json'))
            p.require(metadata.get('schema') == SCHEMA and isinstance(metadata.get('files'), dict), 'Unsupported portable schema')
            p.require(set(names) == set(metadata['files']) | {'portable.json'}, 'Archive file inventory differs')
            for info in entries:
                target = staging / info.filename
                target.parent.mkdir(parents=True, exist_ok=True)
                with z.open(info) as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
            for name, sha in metadata['files'].items():
                p.require(p.digest(staging / name) == sha, 'Portable artifact changed: ' + name)
        spec = metadata['spec']
        # All executable evidence references must refer to inventoried files.
        for mode in ('perf', 'hpm', 'trace'):
            values = spec.get(mode, []) if mode == 'perf' else [spec[mode]] if mode in spec else []
            for entry in values:
                for key, value in entry.items():
                    p.require(key in ('run', 'source_receipt', 'source_archive') and isinstance(value, str) and safe_name(value), 'Unsafe evidence reference')
                    wanted = value + '/manifest.json' if key == 'run' else value
                    p.require(wanted in metadata['files'], 'Uninventoried evidence reference')
                    if key == 'run':
                        manifest = p.read_json(staging / wanted)
                        for artifact in manifest.get('artifacts', {}):
                            p.require(safe_name(artifact) and value + '/' + artifact in metadata['files'],
                                      'Unsafe or uninventoried manifest artifact')
        p.require(p.digest(staging / 'original-report/report.json') == metadata['original_report_sha256'], 'Original report identity differs')
        original = p.read_json(staging / 'original-report/report.json')
        # Stage raw evidence first. On any validation failure move it to no
        # public destination; callers never see a partially valid imported job.
        # Build with final absolute references by temporarily resolving them to
        # staging; after validation rebuild after rename, retaining a failure
        # receipt if an external tool disappears between those operations.
        options = {**metadata.get('options', {}), **(tools or {})}
        options['recompute_roi'] = True
        validation = staging / 'validation'
        validation.mkdir()
        build_imported_report(p.normalize_spec(spec, staging), options, validation, kda, original)
        shutil.rmtree(validation)
        staging.rename(output)
    try:
        p.publish(output / 'report', lambda out: build_imported_report(p.normalize_spec(spec, output), options, out, kda, original))
        p.dump(output / 'import.json', {'schema': SCHEMA, 'status': 'passed', 'archive_sha256': p.digest(archive),
              'original_report_sha256': metadata['original_report_sha256'],
              'relocation': 'New derived report; archived raw manifest bytes and hashes preserved.'})
    except BaseException as exc:
        p.dump(output / 'import.json', {'schema': SCHEMA, 'status': 'failed', 'error': str(exc)})
        raise
    return {'status': 'imported', 'report': str(output / 'report/report.json')}


def add_parser(commands):
    e = commands.add_parser('export', help='Archive a verified report and its complete recorded raw evidence')
    e.add_argument('report', type=Path)
    e.add_argument('--output', '-o', type=Path, required=True)
    i = commands.add_parser('import', help='Validate portable raw evidence and rebuild a report in a new directory')
    i.add_argument('archive', type=Path)
    i.add_argument('--output', '-o', type=Path, required=True)
    for key in ('objdump', 'addr2line', 'readelf', 'objdump-mattr'):
        i.add_argument('--' + key)


def dispatch(args, kda):
    result = export(args.report, args.output, kda) if args.profile_command == 'export' else import_archive(
        args.archive, args.output, kda, {k: getattr(args, k) for k in ('objdump', 'addr2line', 'readelf', 'objdump_mattr') if getattr(args, k)})
    print(json.dumps(result, ensure_ascii=False, indent=2))
