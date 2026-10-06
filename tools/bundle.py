#!/usr/bin/env python3
"""Seal and verify census evidence using only Python's standard library."""
import argparse
import datetime
import hashlib
import json
import re
from pathlib import Path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def archive_metadata(member):
    """Portable archives must not retain a staging operator's account metadata."""
    member.uid = member.gid = 0
    member.uname = member.gname = ''
    member.mtime = 0
    member.pax_headers = {}
    return member


def seal(root):
    seal_paths = [root / name for name in ('MANIFEST.json', 'COLLECTION-SUMMARY.md', 'SHA256SUMS')]
    if any(path.exists() for path in seal_paths):
        if not all(path.is_file() and not path.is_symlink() for path in seal_paths):
            raise ValueError('partial or unsafe seal exists; preserve it and collect under a new run ID')
        verify(root)
        print('already sealed; original integrity baseline preserved')
        return
    paths = sorted((root / 'hosts').glob('*.json'))
    if not paths:
        raise ValueError('no host evidence found')
    assets, gaps, hashes = [], [], []
    for path in paths:
        if path.is_symlink():
            raise ValueError('symlink evidence is unsupported')
        item = json.loads(path.read_text())
        if item.get('schema_version') != 1 or not isinstance(item.get('sections'), dict):
            raise ValueError('invalid host evidence: ' + path.name)
        asset = item.get('asset_id')
        if not isinstance(asset, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', asset) or asset != path.stem or asset in assets:
            raise ValueError('mismatched or duplicate asset: ' + path.name)
        assets.append(asset)
        hashes.append({'path': str(path.relative_to(root)), 'sha256': digest(path)})
        for name, result in item['sections'].items():
            if not isinstance(result, dict) or result.get('status') != 'ok':
                gaps.append({'asset_id': asset, 'section': name,
                             'status': result.get('status', 'invalid') if isinstance(result, dict) else 'invalid'})
    expected_path = root / 'expected-assets.json'
    expected = json.loads(expected_path.read_text()).get('expected_assets', []) if expected_path.exists() else assets
    if not isinstance(expected, list) or any(not isinstance(asset, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', asset) for asset in expected) or len(set(expected)) != len(expected):
        raise ValueError('expected_assets must be a list of unique safe inventory IDs')
    if expected_path.is_symlink():
        raise ValueError('symlink expected scope is unsupported')
    if expected_path.exists():
        hashes.append({'path': 'expected-assets.json', 'sha256': digest(expected_path)})
    missing = sorted(set(expected) - set(assets))
    unexpected = sorted(set(assets) - set(expected))
    manifest = {'schema_version': 1, 'sealed_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                'run_id': root.name, 'assets': assets, 'expected_assets': expected,
                'missing_assets': missing, 'unexpected_assets': unexpected,
                'section_gaps': gaps, 'files': hashes}
    (root / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2) + '\n')
    lines = ['# Census collection summary', '', 'Run: ' + root.name, '',
             'Host records: ' + str(len(assets)), 'Expected hosts: ' + str(len(expected)),
             'Missing hosts: ' + (', '.join(missing) or 'none'),
             'Unexpected hosts: ' + (', '.join(unexpected) or 'none'), '',
             'A section gap reports collection capability/access, not service health.', '']
    lines += ['- {asset_id}: {section}: {status}'.format(**gap) for gap in gaps]
    (root / 'COLLECTION-SUMMARY.md').write_text('\n'.join(lines) + '\n')
    files = paths + ([expected_path] if expected_path.exists() else []) + [root / 'MANIFEST.json', root / 'COLLECTION-SUMMARY.md']
    (root / 'SHA256SUMS').write_text(''.join('{}  {}\n'.format(digest(p), p.relative_to(root)) for p in files))
    print('sealed {} host records; {} section gaps; {} missing hosts'.format(len(assets), len(gaps), len(missing)))


def verify(root):
    checksum_file = root / 'SHA256SUMS'
    if not checksum_file.is_file():
        raise ValueError('SHA256SUMS missing; seal the bundle first')
    listed = set()
    for line in checksum_file.read_text().splitlines():
        checksum, rel = line.split('  ', 1)
        if not re.fullmatch(r'[0-9a-f]{64}', checksum) or rel in listed:
            raise ValueError('invalid or duplicate checksum entry')
        p = root / rel
        if p.is_symlink() or not p.resolve().is_relative_to(root.resolve()):
            raise ValueError('unsafe checksum path')
        if not p.is_file() or digest(p) != checksum:
            raise ValueError('checksum failed: ' + rel)
        listed.add(rel)
    actual_hosts = {str(p.relative_to(root)) for p in (root / 'hosts').glob('*.json')}
    if (root / 'expected-assets.json').exists() and 'expected-assets.json' not in listed:
        raise ValueError('unsealed expected scope')
    if not {'MANIFEST.json', 'COLLECTION-SUMMARY.md'}.issubset(listed) or not actual_hosts.issubset(listed):
        raise ValueError('unsealed host or missing manifest checksum')
    manifest = json.loads((root / 'MANIFEST.json').read_text())
    for item in manifest['files']:
        if item['path'] not in listed or digest(root / item['path']) != item['sha256']:
            raise ValueError('manifest mismatch: ' + item['path'])
    print('checksums verified; {} assets; {} missing; {} section gaps'.format(
        len(manifest['assets']), len(manifest['missing_assets']), len(manifest['section_gaps'])))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['seal', 'verify'])
    parser.add_argument('bundle', type=Path)
    args = parser.parse_args()
    try:
        (seal if args.action == 'seal' else verify)(args.bundle.resolve())
    except (ValueError, OSError, KeyError, json.JSONDecodeError) as error:
        parser.exit(1, 'bundle error: ' + str(error) + '\n')


if __name__ == '__main__':
    main()
