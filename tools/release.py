#!/usr/bin/env python3
"""Package only reviewed, tracked generic source and fictional examples."""
import argparse
import ipaddress
from pathlib import Path
import re
import subprocess
import tarfile

import bundle

ROOT = Path(__file__).resolve().parents[1]
FAMILIES = {'collectors', 'docs', 'inventories', 'model', 'schema', 'playbooks', 'renderer', 'tests', 'tools', 'examples', '.github'}
PRIVATE = {'output', 'evidence', 'dist', '.venv', 'node_modules', 'wheelhouse', 'collections', '__pycache__'}
ROOT_FILES = {'.gitignore', 'AGENTS.md', 'CLAUDE.md', 'CONTEXT.md', 'CHANGELOG.md', 'README.md', 'LICENSE', 'VERSION', 'SECURITY.md', 'THIRD-PARTY-NOTICES.md', 'ansible.cfg.example', 'requirements-controller.in', 'requirements-reporting.txt', 'requirements.yml', 'requirements-junos.yml', 'package.json', 'package-lock.json'}
EXAMPLES = {'synthetic', 'synthetic-products', 'synthetic-with-manual-products', 'manual-only', 'manual-only-products'}
EXTENSIONS = {'.md', '.py', '.ps1', '.js', '.cjs', '.css', '.j2', '.yml', '.yaml', '.json', '.html', '.svg', '.txt', '.png', '.csv'}


def public_paths():
    result = subprocess.run(['git', 'ls-files', '-z'], cwd=ROOT, text=True, capture_output=True, check=True)
    files = []
    for name in filter(None, result.stdout.split('\0')):
        relative = Path(name)
        if any(part in PRIVATE for part in relative.parts) or (relative.parts[0] == 'inventories' and relative.parts[1] != 'example'):
            raise ValueError('private data is tracked; refuse release: ' + name)
        if len(relative.parts) > 1 and relative.parts[0] not in FAMILIES:
            raise ValueError('unreviewed source family: ' + name)
        if len(relative.parts) == 1 and name not in ROOT_FILES:
            raise ValueError('unreviewed root file: ' + name)
        if len(relative.parts) > 1 and relative.suffix.lower() not in EXTENSIONS and relative.name not in {'SHA256SUMS'}:
            raise ValueError('unreviewed source extension: ' + name)
        if relative.parts[0] == 'examples' and (len(relative.parts) < 3 or relative.parts[1] not in EXAMPLES):
            raise ValueError('only named fictional examples may ship: ' + name)
        source = ROOT / relative
        ancestor = source
        while ancestor != ROOT:
            if ancestor.is_symlink():
                raise ValueError('symlink release source: ' + name)
            ancestor = ancestor.parent
        if not source.is_file():
            raise ValueError('missing tracked source: ' + name)
        if source.suffix.lower() != '.png':
            text = source.read_text(encoding='utf-8')
            if re.search(r'/(?:Users)/[^/\s]+/|/(?:home)/(?!your-user/|<[^>]+>/|USER/)[^/\s]+/|BEGIN (?:OPENSSH |RSA |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{30,}', text):
                raise ValueError('private path/key/token marker in public source: ' + name)
            for address in re.findall(r'(?<![\w.])(?:\d{1,3}\.){3}\d{1,3}(?![\w.])', text):
                try:
                    value = ipaddress.ip_address(address)
                except ValueError:
                    continue
                if value.is_private and value not in ipaddress.ip_network('192.0.2.0/24') and not value.is_loopback and not value.is_unspecified:
                    raise ValueError('non-documentation private IP in public source: ' + name)
        files.append((relative, source))
    return files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, default=ROOT / 'dist')
    parser.add_argument('--check-only', action='store_true')
    args = parser.parse_args()
    try:
        files = public_paths()
        if not files:
            raise ValueError('no tracked release files; stage the reviewed source first')
        print('Public source/privacy gate passed: {} files.'.format(len(files)))
        if args.check_only:
            return
        version = (ROOT / 'VERSION').read_text().strip()
        if not re.fullmatch(r'\d+\.\d+\.\d+', version):
            raise ValueError('invalid VERSION')
        destination = args.destination.absolute()
        for target in (destination, destination / ('infrastructure-census-map-' + version + '.tar.gz'), destination / 'SHA256SUMS'):
            if any(ancestor.is_symlink() for ancestor in [target] + list(target.parents)):
                raise ValueError('symlink release output destination')
        destination.mkdir(parents=True, exist_ok=True)
        archive = destination / ('infrastructure-census-map-' + version + '.tar.gz')
        if archive.exists() or archive.is_symlink():
            raise ValueError('release archive exists; preserve it and choose a new destination')
        prefix = 'infrastructure-census-map-' + version
        with tarfile.open(archive, 'w:gz') as output:
            for relative, source in files:
                output.add(source, arcname=prefix + '/' + relative.as_posix(), recursive=False, filter=bundle.archive_metadata)
        (destination / 'SHA256SUMS').write_text(bundle.digest(archive) + '  ' + archive.name + '\n', encoding='utf-8')
        print('Release archive: ' + str(archive))
    except (ValueError, OSError, subprocess.CalledProcessError) as error:
        parser.exit(1, 'release error: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
