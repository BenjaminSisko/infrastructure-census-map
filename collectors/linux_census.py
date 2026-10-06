#!/usr/bin/env python3
"""Read selected infrastructure metadata. Python 3.6+; no installs or config edits."""
import csv
import datetime
import io
import json
import os
import platform
import re
import selectors
import shutil
import signal
import subprocess
import sys
import time

VERSION = '0.1.0'
LIMIT = 2 * 1024 * 1024
START = time.monotonic()
BUDGET = 120


def run(argv, timeout=8, parse_json=False):
    if time.monotonic() - START > BUDGET:
        return {'status': 'budget_exceeded', 'reason': 'collection budget reached'}
    if not shutil.which(argv[0]):
        return {'status': 'not_installed', 'reason': 'command unavailable'}
    child = None
    try:
        child = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                                 env=dict(os.environ, LC_ALL='C', LANG='C'),
                                 start_new_session=True)
        deadline = time.monotonic() + min(timeout, max(0, BUDGET - (time.monotonic() - START)))
        raw = bytearray()
        with selectors.DefaultSelector() as selector:
            selector.register(child.stdout, selectors.EVENT_READ)
            while True:
                remaining = deadline - time.monotonic()
                if remaining <= 0 or not selector.select(remaining):
                    return {'status': 'timeout', 'reason': 'read timed out'}
                chunk = child.stdout.read1(min(65536, LIMIT + 1 - len(raw)))
                if not chunk:
                    break
                raw.extend(chunk)
                if len(raw) > LIMIT:
                    return {'status': 'truncated', 'reason': 'output exceeded 2 MiB; omitted'}
        try:
            child.wait(timeout=max(.001, deadline - time.monotonic()))
        except subprocess.TimeoutExpired:
            return {'status': 'timeout', 'reason': 'read timed out'}
        if child.returncode:
            return {'status': 'error', 'rc': child.returncode,
                    'reason': 'command failed or access restricted'}
        text = raw.decode('utf-8', 'replace').strip()
        if parse_json:
            try:
                text = json.loads(text)
            except ValueError:
                return {'status': 'parse_error', 'reason': 'unexpected command format'}
        return {'status': 'ok', 'data': text}
    except OSError:
        return {'status': 'error', 'reason': 'command execution failed'}
    finally:
        if child is not None:
            # Kill only this collector's process group, including lingering helpers.
            try:
                os.killpg(child.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
            child.wait()
            child.stdout.close()


def transform(result, parser):
    if result['status'] != 'ok':
        return result
    try:
        return dict(result, data=parser(result['data']))
    except (ValueError, TypeError, KeyError, IndexError):
        return {'status': 'parse_error', 'reason': 'unexpected command format'}


def endpoint(value):
    address, sep, port = value.rpartition(':')
    if not sep:
        return value, None
    return address.strip('[]'), int(port) if port.isdigit() else None


def parse_sockets(text):
    items = []
    for line in text.splitlines():
        cols = line.split(None, 5)
        if len(cols) < 5:
            continue
        local, lport = endpoint(cols[3])
        remote, rport = endpoint(cols[4])
        proc = cols[5] if len(cols) > 5 else ''
        match = re.search(r'\("([^"\n]+)",pid=(\d+)', proc)
        items.append({'state': 'Established' if cols[0] == 'ESTAB' else cols[0],
                      'local_address': local, 'local_port': lport,
                      'remote_address': remote, 'remote_port': rport,
                      'process': match.group(1) if match else None,
                      'pid': int(match.group(2)) if match else None,
                      'initiator': 'unknown'})
    return items


def os_identity():
    facts = {'hostname': platform.node(), 'kernel': platform.release(),
             'architecture': platform.machine(), 'effective_uid': os.geteuid()}
    try:
        with open('/etc/os-release') as handle:
            for line in handle:
                name, sep, val = line.strip().partition('=')
                if sep and name in ('NAME', 'PRETTY_NAME', 'ID', 'VERSION_ID'):
                    facts[name.lower()] = val.strip('"')
    except OSError:
        pass
    facts['os'] = facts.get('pretty_name', platform.system())
    return {'status': 'ok', 'data': facts}


def safe_services(text):
    records = []
    for line in text.splitlines():
        cols = line.lstrip('● ').split()
        if len(cols) >= 4:
            records.append(dict(zip(('name', 'load', 'active', 'sub'), cols[:4])))
    return records


def safe_repos():
    import configparser
    import glob
    from urllib.parse import urlsplit, urlunsplit
    records = []
    for filename in glob.glob('/etc/yum.repos.d/*.repo'):
        cfg = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            cfg.read(filename)
            for name in cfg.sections():
                row = {'id': name, 'file': filename}
                for key in ('enabled', 'gpgcheck', 'repo_gpgcheck'):
                    if cfg.has_option(name, key):
                        row[key] = cfg.get(name, key)
                # Retain network origins only: paths/query/userinfo may contain tokens.
                origins = []
                for key in ('baseurl', 'metalink', 'mirrorlist'):
                    for value in cfg.get(name, key, fallback='').split():
                        parsed = urlsplit(value)
                        if parsed.scheme in ('http', 'https') and parsed.hostname:
                            origins.append(urlunsplit((parsed.scheme, parsed.hostname, '', '', '')))
                row['network_origins'] = sorted(set(origins))
                records.append(row)
        except (OSError, ValueError, configparser.Error):
            records.append({'file': filename, 'status': 'parse_error'})
    return {'status': 'ok', 'data': records}


def collect(asset):
    sections = {'identity': os_identity()}
    commands = {
        'hardware': (['lscpu', '-J'], True),
        'interfaces': (['ip', '-j', 'address', 'show'], True),
        'routes': (['ip', '-j', 'route', 'show', 'table', 'all'], True),
        'routing_rules': (['ip', '-j', 'rule', 'show'], True),
        'neighbor_cache': (['ip', '-j', 'neigh', 'show'], True),
        'block_devices': (['lsblk', '--json', '--bytes', '-o', 'NAME,TYPE,SIZE,FSTYPE,MOUNTPOINT'], True),
        # Omit mount options: SMB credentials can occur there.
        'mounts': (['findmnt', '--json', '--output', 'TARGET,SOURCE,FSTYPE'], True),
        'firewall': (['firewall-cmd', '--list-all-zones'], False),
        'selinux': (['getenforce'], False),
        'timers': (['systemctl', 'list-timers', '--all', '--no-pager', '--no-legend'], False),
        'time_sync': (['timedatectl', 'show', '-p', 'NTPSynchronized', '-p', 'Timezone'], False),
        'virtualization_role': (['systemd-detect-virt'], False),
        'virtual_machines': (['virsh', '-c', 'qemu:///system', 'list', '--all', '--name'], False),
        'docker': (['docker', 'ps', '--format', '{{json .}}'], False),
        'podman': (['podman', 'ps', '--format', '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'], False),
    }
    # docker ps JSON includes Commands (may contain secrets); use selected fields.
    commands['docker'] = (['docker', 'ps', '--format', '{{.Names}}\t{{.Image}}\t{{.Ports}}\t{{.Status}}'], False)
    for name, (argv, parsed) in commands.items():
        sections[name] = run(argv, parse_json=parsed)
    sections['tcp'] = transform(run(['ss', '-H', '-n', '-t', '-p', '-a']), parse_sockets)
    sections['udp'] = transform(run(['ss', '-H', '-n', '-u', '-p', '-a']), parse_sockets)
    sections['services'] = transform(run(['systemctl', 'list-units', '--type=service', '--all',
                                         '--no-pager', '--plain', '--no-legend']), safe_services)
    sections['installed_service_units'] = run(['systemctl', 'list-unit-files', '--type=service',
                                              '--no-pager', '--no-legend'])
    if shutil.which('rpm'):
        sections['packages'] = transform(run(['rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}\t%{ARCH}\n']),
                                        lambda t: [dict(zip(('name', 'version', 'arch'), row.split('\t')))
                                                   for row in t.splitlines()])
    elif shutil.which('dpkg-query'):
        sections['packages'] = run(['dpkg-query', '-W', '-f=${binary:Package}\t${Version}\n'])
    else:
        sections['packages'] = {'status': 'not_installed', 'reason': 'package query tool unavailable'}
    sections['repositories'] = safe_repos()
    try:
        with open('/etc/resolv.conf') as handle:
            resolver = [line.strip() for line in handle if line.startswith(('nameserver ', 'search ', 'domain '))]
        sections['dns'] = {'status': 'ok', 'data': resolver}
    except OSError:
        sections['dns'] = {'status': 'access_denied', 'reason': 'resolver config unavailable'}
    if shutil.which('nvidia-smi'):
        sections['gpu'] = transform(run(['nvidia-smi', '--query-gpu=index,name,driver_version,pci.bus_id',
                                         '--format=csv,noheader,nounits']),
                                    lambda text: [dict(zip(('index', 'name', 'driver_version', 'pci_bus_id'),
                                                          [x.strip() for x in row]))
                                                  for row in csv.reader(io.StringIO(text))])
    else:
        sections['gpu'] = {'status': 'not_installed', 'reason': 'nvidia-smi unavailable'}
    sections['capabilities'] = {'status': 'ok', 'data': {
        'rootless_container_scope': 'current account only',
        'process_visibility': 'permissions dependent',
        'socket_initiator': 'unknown',
        'application_configuration': 'excluded',
        'ad_membership': 'not collected by baseline profile',
        'raw_packet_collection': 'excluded',
        'cron_commands': 'excluded',
    }}
    return {'schema_version': 1, 'asset_id': asset, 'platform': 'linux',
            'collected_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
            'collector': {'name': 'linux-census', 'version': VERSION},
            'duration_seconds': round(time.monotonic() - START, 2), 'sections': sections}


if __name__ == '__main__':
    asset = sys.argv[1] if len(sys.argv) > 1 else platform.node()
    if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', asset):
        sys.exit('invalid inventory asset identifier')
    print(json.dumps(collect(asset), sort_keys=True))
