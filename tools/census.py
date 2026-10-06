#!/usr/bin/env python3
"""Operator entry point: collect, render and package private census output."""
import argparse
import datetime
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile

import bundle

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.4.0'


def run_id(value=None):
    value = value or datetime.datetime.now(datetime.timezone.utc).strftime('census-%Y%m%dT%H%M%S%fZ')
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', value):
        raise ValueError('run ID may contain letters, numbers, dots, underscores and hyphens; it cannot start with punctuation')
    return value


def default_output():
    return Path.home() / 'census-output'


def private_directory(path):
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    if path.is_symlink() or not path.is_dir():
        raise ValueError('output must be a real directory: ' + str(path))


def safe_output(root, target):
    if not target.is_relative_to(root):
        raise ValueError('output escapes its run directory')
    ancestor = target
    while True:
        if ancestor.is_symlink():
            raise ValueError('symlink output path: ' + str(target.relative_to(root)))
        if ancestor == root:
            break
        ancestor = ancestor.parent


def finish(path, manual=None, declared=None, render=True):
    path = Path(path).absolute()
    run_id(path.name)
    if path.is_symlink() or path in (Path('/'), Path.home()):
        raise ValueError('refusing a broad or symlink bundle path')
    bundle.verify(path)
    product_names = ('dependency-map.html', 'dependency-map.svg', 'map.json', 'dependency-matrix.csv', 'collection-report.md',
                     'dashboards.html', 'dashboard-summary.json', 'storage-mounts.csv', 'assets-summary.csv')
    for target in [path / 'products', path / 'context', path / 'START-HERE.md', path / 'TRANSFER-SHA256SUMS', path / 'context/manual-context.json', path / 'context/declared-dependencies.json'] + [path / 'products' / name for name in product_names]:
        safe_output(path, target)
    saved_manual = path / 'context/manual-context.json'
    saved_declared = path / 'context/declared-dependencies.json'
    if render and not manual and saved_manual.is_file():
        saved = json.loads(saved_manual.read_text(encoding='utf-8'))
        if saved.get('assets') or saved.get('relationships'):
            manual = saved_manual
    if render and not declared and saved_declared.is_file():
        declared = saved_declared
    if render:
        command = [sys.executable, str(ROOT / 'renderer/render.py'), '--evidence', str(path), '--output', str(path / 'products')]
        for flag, input_path in (('--manual', manual), ('--declared', declared)):
            if input_path:
                command.extend([flag, str(Path(input_path).resolve())])
        subprocess.run(command, check=True)
        model = json.loads((path / 'products/map.json').read_text(encoding='utf-8'))
        private_directory(path / 'context')
        (path / 'context/manual-context.json').write_text(json.dumps(model['manual_context'], indent=2) + '\n', encoding='utf-8')
        if declared:
            (path / 'context/declared-dependencies.json').write_bytes(Path(declared).read_bytes())
    elif manual or declared:
        raise ValueError('--no-render cannot be combined with manual/declared input; render those inputs on the reporting host')
    (path / 'START-HERE.md').write_text(
        '# Census output\n\nRun: ' + path.name + '\n\n'
        'Read COLLECTION-SUMMARY.md first. Gaps are missing evidence, not proof of failed services.\n\n'
        'If products were generated, open products/dashboards.html for administrator/security/leadership views '
        'or products/dependency-map.html for the interactive dependency map. These are dated snapshots, not live monitoring. '
        'Manual context exports belong in approved private storage. Browser drafts are not the durable record.\n\n'
        'For a local agent: verify this evidence with tools/bundle.py from the census source kit; '
        'read its AGENTS.md and docs/agent-workflow.md; inspect hosts/, the collection summary, '
        'products/map.json and context/manual-context.json. Keep raw evidence unchanged, preserve '
        'sources/unknowns, and do not treat observed sockets as approved dependencies.\n\n'
        'This output contains private infrastructure information. Do not upload it to the public code repository.\n', encoding='utf-8')
    # Build an allowlisted, regular-file-only transfer tree. Raw execution logs and
    # unrelated files accidentally placed in the bundle are never included.
    names = {line.split('  ', 1)[1] for line in (path / 'SHA256SUMS').read_text().splitlines()}
    names.update({'SHA256SUMS', 'START-HERE.md'})
    if render:
        names.update({'products/' + name for name in product_names})
        names.add('context/manual-context.json')
        if declared:
            names.add('context/declared-dependencies.json')
    files = []
    for relative in sorted(names):
        candidate = path / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or '\n' in relative or '\r' in relative:
            raise ValueError('unsafe transfer filename')
        if not candidate.is_file():
            raise ValueError('missing transfer member: ' + relative)
        ancestor = candidate
        while ancestor != path:
            if ancestor.is_symlink():
                raise ValueError('symlink transfer member: ' + relative)
            ancestor = ancestor.parent
        files.append(candidate)
    checksums = path / 'TRANSFER-SHA256SUMS'
    checksums.write_text(''.join('{}  {}\n'.format(bundle.digest(item), item.relative_to(path).as_posix()) for item in files), encoding='utf-8')
    files.append(checksums)
    archive = path.parent / ('census-' + path.name + '.tar.gz')
    if archive.exists() or archive.is_symlink():
        timestamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        archive = path.parent / ('census-' + path.name + '-export-' + timestamp + '.tar.gz')
    descriptor, temporary = tempfile.mkstemp(prefix='.census-export-', dir=str(path.parent))
    os.close(descriptor)
    try:
        with tarfile.open(temporary, 'w:gz') as output:
            for item in files:
                output.add(item, arcname=path.name + '/' + item.relative_to(path).as_posix(), recursive=False, filter=bundle.archive_metadata)
        os.chmod(temporary, 0o600)
        os.replace(temporary, archive)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    checksum = archive.with_name(archive.name + '.sha256')
    if checksum.exists() or checksum.is_symlink():
        raise ValueError('checksum destination exists; export again to obtain a new archive name')
    checksum.write_text(bundle.digest(archive) + '  ' + archive.name + '\n', encoding='utf-8')
    os.chmod(checksum, 0o600)
    print('\nREADY FOR WINSCP\nController folder: ' + str(path.parent))
    print('Download archive: ' + str(archive) + '\nDownload checksum: ' + str(checksum))
    print('Readable run folder: ' + str(path))
    return archive


def doctor():
    failures = []
    print('Census kit ' + VERSION + '\nReporting/controller Python: ' + sys.version.split()[0])
    if sys.version_info < (3, 10):
        failures.append('controller/reporting tools require Python 3.10+; Linux target collector still supports Python 3.6+')
    for package in ('jinja2', 'yaml'):
        available = importlib.util.find_spec(package) is not None
        print(package + ': ' + ('available' if available else 'missing'))
        if not available:
            failures.append('install reporting dependencies from requirements-reporting.txt in the approved controller environment')
    for executable in ('ansible-playbook', 'ansible-inventory', 'ansible-galaxy'):
        print(executable + ': ' + ('available' if shutil.which(executable) else 'not found'))
    if failures:
        raise ValueError('; '.join(dict.fromkeys(failures)))
    print('Reporting prerequisites passed. Collection accounts, transports, collections and target permissions still need qualification.')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    sub.add_parser('doctor', help='check local prerequisites without contacting targets')
    for action in ('collect', 'demo'):
        command = sub.add_parser(action)
        command.add_argument('--output-root', type=Path, default=default_output())
        command.add_argument('--run-id')
        command.add_argument('--manual', type=Path)
        command.add_argument('--declared', type=Path)
        if action == 'collect':
            command.add_argument('-i', '--inventory', required=True, type=Path)
            command.add_argument('--limit', help='localhost is included automatically for initialization and export')
            command.add_argument('--no-render', action='store_true')
            command.add_argument('--ansible-arg', action='append', default=[], help='extra trusted Ansible argument; use --ansible-arg=--ask-vault-pass')
    command = sub.add_parser('finish', help='verify, render and archive an existing run without contacting targets')
    command.add_argument('--bundle', required=True, type=Path)
    command.add_argument('--manual', type=Path)
    command.add_argument('--declared', type=Path)
    command.add_argument('--no-render', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'doctor':
            doctor()
        elif args.action == 'finish':
            finish(args.bundle, args.manual, args.declared, not args.no_render)
        else:
            identity = run_id(args.run_id)
            root = args.output_root.expanduser().absolute()
            private_directory(root)
            destination = root / identity
            if destination.exists():
                raise ValueError('run already exists; choose a new --run-id to preserve evidence')
            if args.action == 'demo':
                private_directory(destination / 'hosts')
                for source in sorted((ROOT / 'examples/synthetic/hosts').glob('*.json')):
                    shutil.copyfile(source, destination / 'hosts' / source.name)
                bundle.seal(destination)
                finish(destination, args.manual, args.declared)
            else:
                if args.no_render and (args.manual or args.declared):
                    raise ValueError('--no-render cannot include manual/declared input; supply context later with finish on the reporting machine')
                executable = shutil.which('ansible-playbook')
                if not executable:
                    raise ValueError('ansible-playbook not found; use your approved controller environment')
                if not args.inventory.is_file():
                    raise ValueError('inventory file not found')
                variables = {'census_run_id':identity, 'census_output_root':str(root), 'census_render_products':not args.no_render}
                if args.manual:
                    variables['census_manual_context'] = str(args.manual.resolve())
                if args.declared:
                    variables['census_declared_dependencies'] = str(args.declared.resolve())
                command = [executable, '-i', str(args.inventory.resolve()), str(ROOT / 'playbooks/collect-census.yml'), '-e', json.dumps(variables)]
                if args.limit:
                    command.extend(['--limit', args.limit + ',localhost'])
                command.extend(args.ansible_arg)
                subprocess.run(command, cwd=ROOT, check=True)
    except (ValueError, OSError, subprocess.CalledProcessError, json.JSONDecodeError) as error:
        message = 'a local workflow command failed with exit status ' + str(error.returncode) if isinstance(error, subprocess.CalledProcessError) else str(error)
        parser.exit(1, 'census error: ' + message + '\nEvidence already written is preserved; inspect the run folder before retrying.\n')


if __name__ == '__main__':
    main()
