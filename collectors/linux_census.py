#!/usr/bin/env python3
"""Read selected infrastructure metadata. Python 3.6+; no installs or config edits."""
import csv
import datetime
import io
import json
import math
import os
import platform
import re
import selectors
import shutil
import signal
import shlex
import stat
import subprocess
import sys
import time

VERSION = '0.4.0'
LIMIT = 2 * 1024 * 1024
START = time.monotonic()
BUDGET = 120
LOCAL_CAPACITY_TYPES = ('ext2', 'ext3', 'ext4', 'xfs', 'btrfs', 'zfs', 'f2fs',
                        'jfs', 'reiserfs', 'vfat', 'exfat', 'ntfs', 'ntfs3')
LOCAL_CONFIG_TYPES = LOCAL_CAPACITY_TYPES + ('tmpfs', 'ramfs', 'overlay', 'rootfs')
MAP_FILE_LIMIT = 64 * 1024
MAP_COUNT_LIMIT = 32
MAP_RECORD_LIMIT = 1024


def safe_mount_source(value):
    """Keep mount identity, never credentials, URL userinfo, queries or fragments."""
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > 4096 or re.search(r'[\x00-\x1f\x7f]', value):
        return '[omitted: unsafe source]'
    if re.search(r'(?i)(?:password|passwd|pass|credentials?|token|secret|api[_-]?key|access[_-]?key|username|user)\s*=', value):
        return '[omitted: credential-bearing source]'
    source = value.split('?', 1)[0].split('#', 1)[0]
    scheme = re.match(r'^[A-Za-z][A-Za-z0-9+.-]*://', source)
    prefix = scheme.group(0) if scheme else ('//' if source.startswith('//') else '')
    if prefix:
        authority, separator, path = source[len(prefix):].partition('/')
        if '@' in authority:
            authority = authority.rsplit('@', 1)[1]
        # Reject malformed authorities rather than retain unparseable userinfo.
        if not re.fullmatch(r'(?:[A-Za-z0-9_.-]+|\[[A-Za-z0-9:.%_-]+\])(?::\d+)?', authority):
            return '[omitted: unsafe source]'
        return prefix + authority + (separator + path if separator else '')
    # Some helpers render NFS-like userinfo without a URI scheme.
    authority = source.split('/', 1)[0]
    if '@' in authority:
        source = source.split('@', 1)[1]
        if '@' in source.split('/', 1)[0]:
            return '[omitted: unsafe source]'
    return source


def safe_mounts(data):
    def rows(values, depth=0):
        if not isinstance(values, list) or depth > 32:
            raise ValueError('invalid mount tree')
        result = []
        for value in values:
            if not isinstance(value, dict):
                raise ValueError('invalid mount record')
            row = {key: value.get(key) for key in ('target', 'fstype')}
            row['source'] = safe_mount_source(value.get('source'))
            if 'children' in value:
                row['children'] = rows(value['children'], depth + 1)
            result.append(row)
        return result
    return {'filesystems': rows(data['filesystems'])}


def mount_rows(data):
    pending = list(data.get('filesystems', []))
    result = []
    while pending:
        row = pending.pop()
        result.append(row)
        pending.extend(row.get('children', []))
    return result


def read_bounded_file(path, limit=MAP_FILE_LIMIT):
    if time.monotonic() - START > BUDGET:
        return {'status': 'budget_exceeded', 'reason': 'collection budget reached'}
    try:
        with open(path, 'rb') as handle:
            raw = handle.read(limit + 1)
        if len(raw) > limit:
            return {'status': 'truncated', 'reason': 'local metadata exceeded read limit; omitted'}
        return {'status': 'ok', 'data': raw.decode('utf-8', 'replace')}
    except PermissionError:
        return {'status': 'access_denied', 'reason': 'local metadata unavailable'}
    except OSError:
        return {'status': 'error', 'reason': 'local metadata unavailable'}


def uptime():
    result = transform(read_bounded_file('/proc/uptime', 1024),
                       lambda text: float(text.split()[0]))
    if result['status'] != 'ok':
        return result
    if not math.isfinite(result['data']) or result['data'] < 0:
        return {'status': 'parse_error', 'reason': 'invalid uptime'}
    boot = transform(read_bounded_file('/proc/stat'),
                     lambda text: next(int(line.split()[1]) for line in text.splitlines()
                                       if line.startswith('btime ')))
    if boot['status'] != 'ok':
        return boot
    try:
        boot_time = datetime.datetime.fromtimestamp(boot['data'], datetime.timezone.utc).isoformat()
    except (ValueError, OverflowError, OSError):
        return {'status': 'parse_error', 'reason': 'invalid boot time'}
    return {'status': 'ok', 'data': {'uptime_seconds': result['data'], 'boot_time': boot_time}}


def memory():
    def parse(text):
        values = {}
        wanted = {'MemTotal': 'total_bytes', 'MemAvailable': 'available_bytes',
                  'SwapTotal': 'swap_total_bytes', 'SwapFree': 'swap_free_bytes'}
        for line in text.splitlines():
            name, separator, value = line.partition(':')
            if separator and name in wanted:
                amount, unit = value.split()
                if unit != 'kB' or int(amount) < 0:
                    raise ValueError('invalid memory measurement')
                values[wanted[name]] = int(amount) * 1024
        if len(values) != len(wanted):
            raise ValueError('memory counters unavailable')
        return values
    return transform(read_bounded_file('/proc/meminfo'), parse)


def load():
    def parse(text):
        values = [float(value) for value in text.split()[:3]]
        if len(values) != 3 or any(not math.isfinite(value) or value < 0 for value in values):
            raise ValueError('invalid load counters')
        return dict(zip(('load_1', 'load_5', 'load_15'), values))
    return transform(read_bounded_file('/proc/loadavg', 1024), parse)


def storage_capacity():
    # No target operands: GNU df filters remote/unsupported types before statfs.
    argv = ['df', '--local', '--block-size=1',
            '--output=target,fstype,size,used,avail,pcent,itotal,ifree']
    for fstype in LOCAL_CAPACITY_TYPES:
        argv.extend(['--type', fstype])
    def parse(text):
        records = []
        for line in text.splitlines()[1:]:
            cols = line.rsplit(None, 7)
            if len(cols) != 8 or cols[1] not in LOCAL_CAPACITY_TYPES:
                raise ValueError('invalid local filesystem record')
            target, fstype, total, used, available, percent, itotal, ifree = cols
            records.append({'target': target, 'fstype': fstype,
                            'total_bytes': int(total), 'used_bytes': int(used),
                            'available_bytes': int(available),
                            'used_percent': float(percent.rstrip('%')) if percent != '-' else None,
                            'inodes_total': int(itotal) if itotal != '-' else None,
                            'inodes_free': int(ifree) if ifree != '-' else None})
        return records
    return transform(run(argv), parse)


def patch_inventory():
    if not shutil.which('rpm'):
        return {'status': 'unsupported', 'reason': 'install-time baseline requires local RPM metadata'}
    def parse(text):
        kernels = []
        latest = None
        for line in text.splitlines():
            name, version, epoch = line.split('\t')
            installed = datetime.datetime.fromtimestamp(int(epoch), datetime.timezone.utc).isoformat()
            if latest is None or installed > latest:
                latest = installed
            if name in ('kernel', 'kernel-core', 'kernel-rt', 'kernel-rt-core', 'kernel-uek'):
                kernels.append({'version': version, 'installed_at': installed})
        # kernel and kernel-core may describe the same installed kernel.
        kernels = [dict(version=version, installed_at=installed)
                   for version, installed in sorted(set((row['version'], row['installed_at']) for row in kernels))]
        return {'installed_kernels': kernels, 'latest_package_install_at': latest,
                'source': 'local RPM install metadata', 'baseline_status': 'unknown'}
    return transform(run(['rpm', '-qa', '--qf', '%{NAME}\t%{VERSION}-%{RELEASE}.%{ARCH}\t%{INSTALLTIME}\n']), parse)


def local_map_path(path):
    return isinstance(path, str) and bool(re.fullmatch(
        r'/etc/(?:auto\.[A-Za-z0-9_.-]+|auto\.master\.d/[A-Za-z0-9_.-]+\.autofs)', path))


def open_local_map(path, mounts, directory=False):
    """Open only allowlisted local /etc paths, without following any symlink."""
    if time.monotonic() - START > BUDGET:
        raise ValueError('collection_budget_reached')
    if not local_map_path(path):
        raise ValueError('map_path_outside_static_allowlist')
    ancestors = [row for row in mounts if isinstance(row.get('target'), str) and
                 (path == row['target'] or path.startswith(row['target'].rstrip('/') + '/'))]
    if not ancestors or any(row.get('fstype') not in LOCAL_CONFIG_TYPES for row in ancestors):
        raise ValueError('map_path_not_verified_local')
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    fd = os.open('/etc', flags | os.O_DIRECTORY)
    try:
        parts = path[len('/etc/'):].split('/')
        for index, part in enumerate(parts):
            is_directory = index < len(parts) - 1 or directory
            next_fd = os.open(part, flags | (os.O_DIRECTORY if is_directory else 0), dir_fd=fd)
            os.close(fd)
            fd = next_fd
        info = os.fstat(fd)
        if directory:
            if not stat.S_ISDIR(info.st_mode):
                raise ValueError('map_directory_not_regular')
        elif not stat.S_ISREG(info.st_mode) or info.st_mode & 0o111:
            raise ValueError('program_or_nonregular_map_not_collected')
        return fd
    except BaseException:
        os.close(fd)
        raise


def read_local_map(path, mounts):
    fd = open_local_map(path, mounts)
    try:
        raw = os.read(fd, MAP_FILE_LIMIT + 1)
        if len(raw) > MAP_FILE_LIMIT:
            raise ValueError('map_read_limit_exceeded')
        return raw.decode('utf-8', 'replace')
    finally:
        os.close(fd)


def static_autofs(mounts):
    """Parse declarations only; never call automount, NSS or a map program."""
    rows, gaps = [], []
    master_files = ['/etc/auto.master']
    files_read = 0
    records_seen = [0]
    def gap(path, reason, line=None):
        row = {'source': path, 'reason': reason}
        if line is not None:
            row['line'] = line
        gaps.append(row)
    def tokens(text, path):
        continuation = False
        for number, line in enumerate(text.splitlines(), 1):
            if not line.strip() or line.lstrip().startswith('#'):
                continue
            records_seen[0] += 1
            if records_seen[0] > MAP_RECORD_LIMIT:
                if records_seen[0] == MAP_RECORD_LIMIT + 1:
                    gap(path, 'static_map_record_limit_reached', number)
                return
            continued = line.rstrip().endswith('\\')
            if continuation or continued:
                gap(path, 'continued_map_entry_not_collected', number)
                continuation = continued
                continue
            try:
                yield number, shlex.split(line, comments=True)
            except ValueError:
                gap(path, 'map_entry_parse_error', number)
    def map_type(options, fallback='nfs'):
        matches = re.findall(r'(?:^|[,-])fstype=([A-Za-z0-9_.+-]+)(?:,|$)', ','.join(options))
        return matches[-1] if matches else fallback
    for master in master_files:
        if files_read >= MAP_COUNT_LIMIT:
            gap(master, 'static_map_file_limit_reached')
            continue
        files_read += 1
        try:
            text = read_local_map(master, mounts)
        except FileNotFoundError:
            if master != '/etc/auto.master' or any(row.get('fstype') == 'autofs' for row in mounts):
                gap(master, 'static_master_map_unavailable')
            continue
        except (OSError, ValueError) as error:
            gap(master, str(error) if isinstance(error, ValueError) else 'static_map_access_unavailable')
            continue
        for number, fields in tokens(text, master):
            if not fields:
                continue
            if fields[0] == '+dir:/etc/auto.master.d':
                try:
                    fd = open_local_map('/etc/auto.master.d', mounts, directory=True)
                    try:
                        with os.scandir('/proc/self/fd/' + str(fd)) as entries:
                            for index, entry in enumerate(entries):
                                if index >= MAP_COUNT_LIMIT:
                                    gap(master, 'master_map_directory_entry_limit_reached', number)
                                    break
                                if entry.name.startswith('.') or not re.fullmatch(r'[A-Za-z0-9_.-]+\.autofs', entry.name):
                                    continue
                                candidate = '/etc/auto.master.d/' + entry.name
                                if candidate not in master_files:
                                    if len(master_files) >= MAP_COUNT_LIMIT:
                                        gap(master, 'master_map_file_limit_reached', number)
                                        break
                                    master_files.append(candidate)
                    finally:
                        os.close(fd)
                except (OSError, ValueError):
                    gap(master, 'master_map_directory_unavailable', number)
                continue
            if fields[0].startswith('+') or len(fields) < 2:
                gap(master, 'external_or_unsupported_master_entry', number)
                continue
            target, map_path = fields[:2]
            if map_path == '-null':
                gap(master, 'null_map_override_requires_review', number)
                continue
            if map_path.startswith(('file:', 'file,sun:')):
                map_path = map_path.split(':', 1)[1]
            if not target.startswith('/') or not local_map_path(map_path):
                gap(master, 'dynamic_external_or_unsupported_map', number)
                continue
            if files_read >= MAP_COUNT_LIMIT:
                gap(master, 'static_map_file_limit_reached', number)
                continue
            files_read += 1
            try:
                map_text = read_local_map(map_path, mounts)
            except (OSError, ValueError) as error:
                gap(map_path, str(error) if isinstance(error, ValueError) else 'static_map_access_unavailable')
                continue
            for line, values in tokens(map_text, map_path):
                if not values:
                    continue
                key, remaining = values[0], values[1:]
                options = []
                while remaining and remaining[0].startswith('-'):
                    options.append(remaining.pop(0))
                if (len(remaining) != 1 or key.startswith('+') or
                        any(character in key + ''.join(remaining) for character in '*$&`|') or
                        ',' in remaining[0] or (target == '/-' and not key.startswith('/')) or
                        (target != '/-' and ('/' in key or key in ('.', '..')))):
                    gap(map_path, 'dynamic_replica_or_multimount_entry_not_collected', line)
                    continue
                source = remaining[0]
                if source.startswith(':'):
                    source = source[1:]
                rows.append({'target': key if target == '/-' else target.rstrip('/') + '/' + key,
                             'source': safe_mount_source(source),
                             'fstype': map_type(options, map_type(fields[2:])),
                             'configured_via': 'autofs_static', 'configuration_file': map_path})
    return rows, gaps


def configured_mounts(active):
    result = transform(run(['findmnt', '--fstab', '--json', '--output', 'TARGET,SOURCE,FSTYPE'],
                           parse_json=True), safe_mounts)
    if active['status'] != 'ok':
        rows, gaps = [], [{'source': 'autofs', 'reason': 'active_mount_table_required_for_safe_map_read'}]
    else:
        rows, gaps = static_autofs(mount_rows(active['data']))
    if result['status'] != 'ok':
        gaps.insert(0, {'source': 'fstab', 'reason': result.get('reason', result['status']),
                        'status': result['status']})
        if not rows:
            return dict(result, gaps=gaps)
        result = {'status': 'ok', 'data': {'filesystems': []}}
    result['data']['filesystems'].extend(rows)
    if gaps:
        result['gaps'] = gaps
        result['status'] = 'partial'
    result['scope'] = 'fstab and bounded local static autofs maps; declarations only'
    return result


def audit_state():
    def parse(text):
        names = {'ActiveState': 'active_state', 'SubState': 'sub_state',
                 'UnitFileState': 'unit_file_state'}
        values = {}
        for line in text.splitlines():
            name, separator, value = line.partition('=')
            if separator and name in names:
                values[names[name]] = value
        if len(values) != len(names):
            raise ValueError('audit unit properties unavailable')
        return values
    return transform(run(['systemctl', 'show', 'auditd', '-p', 'ActiveState',
                          '-p', 'SubState', '-p', 'UnitFileState']), parse)


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
    except (ValueError, TypeError, KeyError, IndexError, StopIteration, OverflowError, OSError):
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
    sections = {'identity': os_identity(), 'uptime': uptime(), 'memory': memory(), 'load': load()}
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
    sections['mounts'] = transform(sections['mounts'], safe_mounts)
    sections['configured_mounts'] = configured_mounts(sections['mounts'])
    sections['storage_capacity'] = storage_capacity()
    sections['patch_inventory'] = patch_inventory()
    sections['audit'] = audit_state()
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
        'configured_mount_scope': 'fstab and bounded local static autofs maps; declarations only',
        'autofs_exclusions': 'program/NSS/LDAP maps, symlinks, remote map files, dynamic/replica/multimount entries',
        'capacity_scope': 'local filesystem allowlist only; no remote target probes',
        'patch_baseline_status': 'unknown; install times do not establish patch currency',
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
