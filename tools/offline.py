#!/usr/bin/env python3
"""Stage or install offline controller/reporting dependencies on matching systems."""
import argparse
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import zipfile
from email.parser import Parser

import bundle

ROOT = Path(__file__).resolve().parents[1]


def distribution():
    if platform.system() != 'Linux':
        return {}
    try:
        release = platform.freedesktop_os_release()
        return {key: release.get(key, 'unknown') for key in ('ID', 'VERSION_ID')}
    except OSError:
        return {'ID':'unknown', 'VERSION_ID':'unknown'}


def checksum_files(path):
    return sorted(item for item in path.rglob('*') if item.is_file() and item.name != 'SHA256SUMS')


def verify(path):
    listed = set()
    for line in (path / 'SHA256SUMS').read_text().splitlines():
        digest, relative = line.split('  ', 1)
        item = path / relative
        if Path(relative).is_absolute() or '..' in Path(relative).parts or item.is_symlink() or not item.resolve().is_relative_to(path.resolve()):
            raise ValueError('unsafe dependency path')
        if not item.is_file() or bundle.digest(item) != digest:
            raise ValueError('dependency checksum failed: ' + relative)
        listed.add(relative)
    actual = {item.relative_to(path).as_posix() for item in checksum_files(path)}
    if listed != actual:
        raise ValueError('unlisted or missing dependency files')


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='action', required=True)
    stage = sub.add_parser('stage')
    stage.add_argument('--destination', required=True, type=Path)
    stage.add_argument('--profile', choices=['reporting', 'controller'], default='controller')
    stage.add_argument('--include-junos', action='store_true')
    stage.add_argument('--confirm-matching-controller', action='store_true', help='affirm staging OS/architecture/Python match the destination; no cross-platform wheels are guessed')
    stage.add_argument('--dry-run', action='store_true')
    install = sub.add_parser('install')
    install.add_argument('--bundle', required=True, type=Path)
    install.add_argument('--venv', required=True, type=Path)
    install.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'stage':
            if not args.confirm_matching_controller:
                raise ValueError('stage only on a system matching the offline destination; add --confirm-matching-controller after checking OS, architecture and Python')
            if args.include_junos and args.profile != 'controller':
                raise ValueError('--include-junos requires --profile controller')
            destination = args.destination.expanduser().absolute()
            if destination.exists():
                raise ValueError('staging destination exists; use a new empty destination to preserve prior bundles')
            requirement = ROOT / ('requirements-reporting.txt' if args.profile == 'reporting' else 'requirements-controller.in')
            command = [sys.executable, '-m', 'pip', 'download', '--only-binary=:all:', '--requirement', str(requirement), '--dest', str(destination / 'wheelhouse')]
            if args.include_junos:
                command.append('ncclient')
            commands = [command]
            if args.profile == 'controller':
                executable = shutil.which('ansible-galaxy')
                if not executable:
                    raise ValueError('connected staging requires an approved installed ansible-galaxy')
                for name in ['requirements.yml'] + (['requirements-junos.yml'] if args.include_junos else []):
                    target = destination / ('collections' if name == 'requirements.yml' else 'collections-junos')
                    commands.append([executable, 'collection', 'download', '-r', str(ROOT / name), '-p', str(target)])
            for command in commands:
                print('Stage command: ' + json.dumps(command))
            if args.dry_run:
                print('Dry run: no directory created and nothing downloaded.')
                return
            destination.mkdir(mode=0o700, parents=True)
            for command in commands:
                subprocess.run(command, check=True)
            versions = {}
            for wheel in sorted((destination / 'wheelhouse').glob('*.whl')):
                with zipfile.ZipFile(wheel) as package:
                    metadata_path = next(name for name in package.namelist() if name.endswith('.dist-info/METADATA'))
                    metadata = Parser().parsestr(package.read(metadata_path).decode('utf-8'))
                    name, version = metadata['Name'], metadata['Version']
                    if name in versions and versions[name] != version:
                        raise ValueError('conflicting wheel versions for ' + name)
                    versions[name] = version
            if not versions:
                raise ValueError('no wheels downloaded')
            (destination / 'requirements.lock').write_text(''.join('{}=={}\n'.format(name, versions[name]) for name in sorted(versions)), encoding='utf-8')
            metadata = {'schema_version':1, 'profile':args.profile, 'os':platform.system(), 'distribution':distribution(), 'architecture':platform.machine(), 'python':platform.python_version(), 'include_junos':args.include_junos, 'claim':'dependency staging only; target runtime/platform qualification is separate'}
            (destination / 'ENVIRONMENT.json').write_text(json.dumps(metadata, indent=2) + '\n', encoding='utf-8')
            (destination / 'SHA256SUMS').write_text(''.join('{}  {}\n'.format(bundle.digest(item), item.relative_to(destination).as_posix()) for item in checksum_files(destination)), encoding='utf-8')
            print('Staged dependencies: ' + str(destination) + '\nTransfer the whole directory through the approved media process.')
        else:
            source = args.bundle.expanduser().resolve()
            verify(source)
            metadata = json.loads((source / 'ENVIRONMENT.json').read_text())
            if metadata['os'] != platform.system() or metadata.get('distribution', {}) != distribution() or metadata['architecture'] != platform.machine() or metadata['python'].split('.')[:2] != platform.python_version().split('.')[:2]:
                raise ValueError('OS/architecture/Python mismatch; prepare a new matching dependency bundle')
            target = args.venv.expanduser().absolute()
            if target.exists():
                raise ValueError('venv destination exists; select a new path rather than modifying a managed environment')
            python = target / 'bin/python'
            commands = [[sys.executable, '-m', 'venv', str(target)], [str(python), '-m', 'pip', 'install', '--no-index', '--find-links', str(source / 'wheelhouse'), '-r', str(source / 'requirements.lock')]]
            if metadata['profile'] == 'controller':
                for name in ['collections'] + (['collections-junos'] if metadata['include_junos'] else []):
                    commands.append([str(target / 'bin/ansible-galaxy'), 'collection', 'install', '--offline', '-r', str(source / name / 'requirements.yml'), '-p', str(target / 'collections')])
            for command in commands:
                print('Install command: ' + json.dumps(command))
            if args.dry_run:
                print('Dry run: no runtime or collection installation performed.')
                return
            for command in commands:
                cwd = Path(command[command.index('-r') + 1]).parent if command[1:3] == ['collection', 'install'] else source
                subprocess.run(command, cwd=cwd, check=True, env=dict(os.environ, ANSIBLE_COLLECTIONS_PATH=str(target / 'collections')))
            print('Offline environment: ' + str(target) + '\nUse its Python/Ansible executables and ANSIBLE_COLLECTIONS_PATH=' + str(target / 'collections'))
    except (ValueError, OSError, KeyError, StopIteration, subprocess.CalledProcessError) as error:
        parser.exit(1, 'offline dependency error: ' + str(error) + '\nPartial staging/runtime files are preserved. If a binary wheel is unavailable, build it on approved matching staging infrastructure; no source build is attempted on production.\n')


if __name__ == '__main__':
    main()
