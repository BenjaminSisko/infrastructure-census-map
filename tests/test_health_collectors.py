import ast
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('health_linux', ROOT / 'collectors/linux_census.py')
linux = importlib.util.module_from_spec(spec)
spec.loader.exec_module(linux)


class LinuxHealthCollectorTests(unittest.TestCase):
    def test_linux_source_parses_with_python_36_grammar(self):
        ast.parse((ROOT / 'collectors/linux_census.py').read_text(), feature_version=(3, 6))

    def test_mount_sources_exclude_credentials_options_and_queries(self):
        for source in ('smb://reader:secret@files.example.test/team?token=private',
                       '//reader:secret@files.example.test/team#private'):
            safe = linux.safe_mount_source(source)
            self.assertNotIn('secret', safe)
            self.assertNotIn('reader', safe)
            self.assertNotIn('private', safe)
        for source in ('//files.example.test/team,password=private', 'smb://reader:secret/team',
                       'smb://reader%3Asecret%40files.example.test/team', 'smb://[invalid/team'):
            self.assertIn('omitted', linux.safe_mount_source(source))
        mounted = linux.safe_mounts({'filesystems': [{
            'target': '/mnt/team', 'fstype': 'cifs', 'source': '//reader:secret@files.example.test/team',
            'options': 'password=private', 'children': [{'target': '/mnt/team/nested',
                                                       'source': 'files.example.test:/nested', 'fstype': 'nfs'}]}]})
        self.assertNotIn('private', json.dumps(mounted))
        self.assertNotIn('secret', json.dumps(mounted))
        self.assertNotIn('options', mounted['filesystems'][0])
        self.assertEqual(mounted['filesystems'][0]['children'][0]['source'], 'files.example.test:/nested')

    def test_configured_and_active_mounts_remain_distinct(self):
        active = {'status': 'ok', 'data': {'filesystems': [
            {'target': '/', 'source': '/dev/vda1', 'fstype': 'ext4'},
            {'target': '/mnt/active', 'source': 'files.example.test:/active', 'fstype': 'nfs'}]}}
        declared = {'status': 'ok', 'data': {'filesystems': [
            {'target': '/mnt/inactive', 'source': 'files.example.test:/inactive', 'fstype': 'nfs'}]}}
        with patch.object(linux, 'run', return_value=declared) as query, \
                patch.object(linux, 'static_autofs', return_value=([], [])):
            result = linux.configured_mounts(active)
        query.assert_called_once_with(['findmnt', '--fstab', '--json', '--output', 'TARGET,SOURCE,FSTYPE'],
                                      parse_json=True)
        self.assertEqual(result['data']['filesystems'][0]['target'], '/mnt/inactive')
        self.assertEqual(active['data']['filesystems'][1]['target'], '/mnt/active')
        self.assertNotIn('--evaluate', query.call_args.args[0])
        self.assertNotIn('OPTIONS', ','.join(query.call_args.args[0]))

    def test_static_autofs_never_executes_or_resolves_dynamic_maps(self):
        fixtures = {
            '/etc/auto.master': '/shares /etc/auto.shares\n/- file:/etc/auto.direct\n'
                                '/program program:/etc/auto.runner\n/nss auto.network\n'
                                '+auto.master\n/ldap ldap:private\n',
            '/etc/auto.shares': 'team -fstype=cifs,user=reader,password=private ://files.example.test/team\n'
                                'archive -ro files.example.test:/archive\n'
                                '* files.example.test:/users/&\n+ldap.private\n',
            '/etc/auto.direct': '/mnt/direct -fstype=nfs4 files.example.test:/direct\n'
                                '/mnt/multi -ro / files.example.test:/one \\\n'
                                ' /nested files.example.test:/two\n',
        }
        with patch.object(linux, 'read_local_map', side_effect=lambda name, _: fixtures[name]) as reader:
            rows, gaps = linux.static_autofs([{'target': '/', 'fstype': 'ext4'}])
        self.assertEqual({row['target'] for row in rows}, {'/shares/team', '/shares/archive', '/mnt/direct'})
        self.assertEqual(next(row for row in rows if row['target'] == '/shares/team')['fstype'], 'cifs')
        self.assertNotIn('private', json.dumps(rows + gaps))
        self.assertTrue(gaps)
        self.assertEqual({call.args[0] for call in reader.call_args_list}, set(fixtures))

    def test_autofs_requires_local_paths_and_refuses_program_files(self):
        with self.assertRaisesRegex(ValueError, 'not_verified_local'), patch.object(linux.os, 'open') as opener:
            linux.open_local_map('/etc/auto.remote', [{'target': '/', 'fstype': 'ext4'},
                                                    {'target': '/etc', 'fstype': 'nfs'}])
        opener.assert_not_called()
        with self.assertRaisesRegex(ValueError, 'allowlist'), patch.object(linux.os, 'open') as opener:
            linux.open_local_map('/remote/auto.data', [{'target': '/', 'fstype': 'ext4'}])
        opener.assert_not_called()
        with patch.object(linux.os, 'open', side_effect=[10, 11]), \
                patch.object(linux.os, 'close') as closer, \
                patch.object(linux.os, 'fstat') as info:
            info.return_value.st_mode = 0o100755
            with self.assertRaisesRegex(ValueError, 'program_or_nonregular'):
                linux.open_local_map('/etc/auto.program', [{'target': '/', 'fstype': 'ext4'}])
        self.assertEqual(closer.call_count, 2)

    def test_file_reads_have_an_explicit_limit(self):
        with tempfile.TemporaryDirectory() as folder:
            fixture = Path(folder) / 'metadata'
            fixture.write_bytes(b'12345')
            self.assertEqual(linux.read_bounded_file(str(fixture), 4)['status'], 'truncated')
            self.assertEqual(linux.read_bounded_file(str(fixture), 5)['data'], '12345')

    def test_static_autofs_file_and_record_limits_preserve_explicit_gaps(self):
        master = '/one /etc/auto.one\n/two /etc/auto.two\n/three /etc/auto.three\n'
        def file_fixture(name, _):
            return master if name == '/etc/auto.master' else 'team files.example.test:/team\n'
        with patch.object(linux, 'MAP_COUNT_LIMIT', 3), \
                patch.object(linux, 'read_local_map', side_effect=file_fixture) as reader:
            rows, gaps = linux.static_autofs([{'target': '/', 'fstype': 'ext4'}])
        self.assertEqual(reader.call_count, 3)  # master and two static map files
        self.assertEqual(len(rows), 2)
        self.assertIn('static_map_file_limit_reached', {row['reason'] for row in gaps})
        with patch.object(linux, 'MAP_RECORD_LIMIT', 4), \
                patch.object(linux, 'read_local_map', side_effect=lambda name, _: (
                    '/one /etc/auto.one\n' if name == '/etc/auto.master' else
                    ''.join('team{} files.example.test:/team\n'.format(index) for index in range(10)))):
            rows, gaps = linux.static_autofs([{'target': '/', 'fstype': 'ext4'}])
        self.assertEqual(len(rows), 3)  # one master record and three mount declarations
        self.assertIn('static_map_record_limit_reached', {row['reason'] for row in gaps})

    def test_uptime_memory_and_load_are_selected_counters(self):
        fixtures = {
            '/proc/uptime': '3600.5 1800.0\n', '/proc/stat': 'cpu 1 2 3\nbtime 1700000000\n',
            '/proc/meminfo': 'MemTotal: 8192 kB\nMemAvailable: 4096 kB\nSwapTotal: 2048 kB\nSwapFree: 1024 kB\n',
            '/proc/loadavg': '1.00 0.50 0.25 1/10 12\n',
        }
        with patch.object(linux, 'read_bounded_file', side_effect=lambda name, *args: {
                'status': 'ok', 'data': fixtures[name]}):
            self.assertEqual(linux.uptime()['data']['uptime_seconds'], 3600.5)
            self.assertEqual(linux.uptime()['data']['boot_time'], '2023-11-14T22:13:20+00:00')
            self.assertEqual(linux.memory()['data'], {'total_bytes': 8388608, 'available_bytes': 4194304,
                                                     'swap_total_bytes': 2097152, 'swap_free_bytes': 1048576})
            self.assertEqual(linux.load()['data'], {'load_1': 1.0, 'load_5': .5, 'load_15': .25})
        with patch.object(linux, 'read_bounded_file', return_value={'status': 'ok', 'data': 'cpu 1 2 3'}):
            self.assertEqual(linux.uptime()['status'], 'parse_error')
            self.assertEqual(linux.memory()['status'], 'parse_error')
        for invalid in ('nan 1 1', 'inf 1 1', '-1 1 1'):
            with patch.object(linux, 'read_bounded_file', return_value={'status': 'ok', 'data': invalid}):
                self.assertEqual(linux.uptime()['status'], 'parse_error')
                self.assertEqual(linux.load()['status'], 'parse_error')

    def test_capacity_queries_only_local_allowlisted_types_without_path_operands(self):
        output = 'Mounted on Type 1B-blocks Used Avail Use% Inodes IFree\n/ ext4 1000 200 750 22% 100 90\n'
        with patch.object(linux, 'run', return_value={'status': 'ok', 'data': output}) as query:
            result = linux.storage_capacity()
        argv = query.call_args.args[0]
        self.assertIn('--local', argv)
        self.assertNotIn('/', argv)
        for fstype in ('nfs', 'nfs4', 'cifs', 'autofs', 'fuse', 'fuse.sshfs'):
            self.assertNotIn(fstype, argv)
        self.assertEqual(result['data'][0]['available_bytes'], 750)
        self.assertEqual(result['data'][0]['inodes_free'], 90)
        with patch.object(linux, 'run', return_value={'status': 'ok', 'data': output.replace('ext4', 'nfs')}):
            self.assertEqual(linux.storage_capacity()['status'], 'parse_error')

    def test_rpm_install_inventory_uses_local_query_and_never_claims_currency(self):
        output = 'kernel-core\t6.8.1-1.x86_64\t1700000000\nkernel\t6.8.1-1.x86_64\t1700000000\nexample\t1-1.x86_64\t1700100000\n'
        with patch.object(linux.shutil, 'which', return_value='/usr/bin/rpm'), \
                patch.object(linux, 'run', return_value={'status': 'ok', 'data': output}) as query:
            result = linux.patch_inventory()
        self.assertEqual(query.call_args.args[0][:2], ['rpm', '-qa'])
        self.assertIn('%{INSTALLTIME}', query.call_args.args[0][-1])
        self.assertEqual(len(result['data']['installed_kernels']), 1)
        self.assertEqual(result['data']['baseline_status'], 'unknown')
        self.assertGreater(result['data']['latest_package_install_at'],
                           result['data']['installed_kernels'][0]['installed_at'])
        with patch.object(linux.shutil, 'which', return_value=None):
            self.assertEqual(linux.patch_inventory()['status'], 'unsupported')

    def test_configured_mount_gaps_survive_partial_fstab_evidence(self):
        with patch.object(linux, 'run', return_value={'status': 'not_installed', 'reason': 'command unavailable'}), \
                patch.object(linux, 'static_autofs', return_value=([
                    {'target': '/shares/team', 'source': 'files.example.test:/team', 'fstype': 'nfs'}], [])):
            result = linux.configured_mounts({'status': 'ok', 'data': {'filesystems': []}})
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['gaps'][0]['source'], 'fstab')
        self.assertEqual(result['gaps'][0]['status'], 'not_installed')

    def test_audit_section_allows_selected_unit_state_only(self):
        with patch.object(linux, 'run', return_value={'status': 'ok', 'data':
                'ActiveState=active\nSubState=running\nUnitFileState=enabled\nExecStart=private-command\n'}) as query:
            result = linux.audit_state()
        self.assertEqual(result['data'], {'active_state': 'active', 'sub_state': 'running',
                                          'unit_file_state': 'enabled'})
        self.assertNotIn('private', json.dumps(result))
        self.assertEqual(query.call_args.args[0], ['systemctl', 'show', 'auditd', '-p', 'ActiveState',
                                                  '-p', 'SubState', '-p', 'UnitFileState'])


@unittest.skipUnless(shutil.which('pwsh'), 'PowerShell runtime unavailable; live Windows still requires qualification')
class WindowsHealthCollectorTests(unittest.TestCase):
    def collect_mocked(self, denied=False, omit_smb=False, future_boot=False, empty_reboot=False):
        collector = str(ROOT / 'collectors/windows_census.ps1').replace("'", "''")
        # Every target query is mocked, even Get-Command: this invokes no host inventory.
        harness = r'''
$parseErrors = $null
$parseTokens = $null
[void][System.Management.Automation.Language.Parser]::ParseFile('__COLLECTOR__', [ref]$parseTokens, [ref]$parseErrors)
if ($parseErrors.Count -gt 0) { throw 'collector_parse_failed' }
$global:MockDenied = __DENIED__
$global:OmitSmb = __OMIT_SMB__
$global:FutureBoot = __FUTURE_BOOT__
$global:EmptyReboot = __EMPTY_REBOOT__
function Get-Command {
    param($Name, $ErrorAction)
    if ($Name -in @('Get-CimInstance', 'Get-HotFix', 'Test-Path', 'Get-ItemProperty', 'Get-ChildItem') -or
        ($Name -eq 'Get-SmbMapping' -and -not $global:OmitSmb)) { [pscustomobject]@{Name = $Name} }
}
function Get-CimInstance {
    param($ClassName, $OperationTimeoutSec)
    if ($global:MockDenied) { throw [System.UnauthorizedAccessException]::new('private error must not leave collector') }
    if ($ClassName -ne 'Win32_OperatingSystem') { throw 'fixture_class_unavailable' }
    [pscustomobject]@{
        LastBootUpTime = $(if ($global:FutureBoot) { [DateTime]::UtcNow.AddHours(1) } else { [DateTime]::UtcNow.AddHours(-1) })
        TotalVisibleMemorySize = 8192; FreePhysicalMemory = 4096
        SizeStoredInPagingFiles = 2048; FreeSpaceInPagingFiles = 1024
    }
}
function Get-HotFix {
    [pscustomobject]@{HotFixID = 'KB1234567'; InstalledOn = [DateTime]'2026-01-02'; InstalledBy = 'private-user'}
    [pscustomobject]@{HotFixID = 'KB0000000'; InstalledOn = $null}
}
function Test-Path {
    param($LiteralPath, $Path, $ErrorAction)
    if ($LiteralPath -like '*RebootRequired') { return $false }
    if ($global:EmptyReboot -and $LiteralPath -like '*RebootPending') { return $false }
    return $true
}
function Get-ItemProperty {
    param($LiteralPath, $Path, $Name, $ErrorAction)
    if ($LiteralPath -like '*Session Manager') {
        if ($global:EmptyReboot) {
            return [pscustomobject]@{PendingFileRenameOperations = @('', $null); PendingFileRenameOperations2 = @('')}
        }
        return [pscustomobject]@{PendingFileRenameOperations = @('private-file', 'private-replacement')}
    }
    [pscustomobject]@{RemotePath = '\\reader:private-password@files.example.test\persisted'; UserName = 'private-user'}
}
function Get-ChildItem {
    param($LiteralPath, $ErrorAction)
    [pscustomobject]@{PSChildName = 'Z'; PSPath = 'fixture-persisted-drive'}
    [pscustomobject]@{PSChildName = 'ignore-username'; PSPath = 'fixture-ignored'}
}
function Get-SmbMapping {
    [pscustomobject]@{LocalPath = 'Y:'; RemotePath = '\\reader:private-password@files.example.test\active'; Status = 'OK'; UserName = 'private-user'}
    [pscustomobject]@{LocalPath = 'X:'; RemotePath = 'smb://reader:private-password@files.example.test/uri'; Status = 'Unavailable'}
    [pscustomobject]@{LocalPath = 'W:'; RemotePath = '//reader:private-password@files.example.test/slash'; Status = 'OK'}
    [pscustomobject]@{LocalPath = 'V:'; RemotePath = 'smb://reader:private-password/malformed'; Status = 'Unavailable'}
}
$result = & '__COLLECTOR__' -InventoryId fixture-win
$result | ConvertTo-Json -Depth 30 -Compress
'''.replace('__COLLECTOR__', collector).replace('__DENIED__', '$true' if denied else '$false').replace(
            '__OMIT_SMB__', '$true' if omit_smb else '$false').replace(
            '__FUTURE_BOOT__', '$true' if future_boot else '$false').replace(
            '__EMPTY_REBOOT__', '$true' if empty_reboot else '$false')
        completed = subprocess.run([shutil.which('pwsh'), '-NoProfile', '-NonInteractive', '-Command', harness],
                                   capture_output=True, text=True, timeout=30)
        self.assertEqual(completed.returncode, 0, completed.stderr)
        return json.loads(completed.stdout)

    def test_mocked_windows_health_and_scoped_mappings(self):
        document = self.collect_mocked()
        sections = document['sections']
        self.assertAlmostEqual(sections['uptime']['data']['uptime_seconds'], 3600, delta=5)
        self.assertEqual(sections['memory']['data']['total_bytes'], 8388608)
        self.assertEqual(sections['memory']['data']['swap_free_bytes'], 1048576)
        self.assertEqual(sections['hotfixes']['data'][0], {'id': 'KB1234567', 'installed_at': '2026-01-02'})
        self.assertIsNone(sections['hotfixes']['data'][1]['installed_at'])
        self.assertTrue(sections['reboot_pending']['data']['pending'])
        self.assertIn('component_based_servicing', sections['reboot_pending']['data']['indicators'])
        self.assertNotIn('windows_update', sections['reboot_pending']['data']['indicators'])
        self.assertEqual(sections['smb_mappings']['data'][0]['local_path'], 'Y:')
        self.assertEqual(sections['smb_mappings']['data'][0]['remote_path'], '\\\\files.example.test\\active')
        self.assertEqual(sections['smb_mappings']['data'][1]['remote_path'], 'smb://files.example.test/uri')
        self.assertEqual(sections['smb_mappings']['data'][1]['status'], 'Unavailable')
        self.assertIn('omitted', sections['smb_mappings']['data'][3]['remote_path'])
        self.assertEqual(sections['configured_mounts']['data']['filesystems'][0]['target'], 'Z:')
        self.assertIn('current collection session', sections['smb_mappings']['scope'])
        self.assertIn('collection account only', sections['configured_mounts']['scope'])
        self.assertNotIn('private-', json.dumps(document))

    def test_mocked_windows_denial_and_missing_command_remain_gaps(self):
        sections = self.collect_mocked(denied=True, omit_smb=True)['sections']
        self.assertEqual(sections['uptime']['status'], 'access_denied')
        self.assertEqual(sections['memory']['status'], 'access_denied')
        self.assertEqual(sections['smb_mappings']['status'], 'not_installed')
        self.assertIn('scope', sections['smb_mappings'])
        self.assertNotIn('private error', json.dumps(sections))

    def test_future_windows_boot_is_gap_and_empty_reboot_values_are_not_pending(self):
        sections = self.collect_mocked(future_boot=True, empty_reboot=True)['sections']
        self.assertEqual(sections['uptime']['status'], 'error')
        self.assertNotIn('data', sections['uptime'])
        self.assertEqual(sections['reboot_pending']['status'], 'ok')
        self.assertEqual(sections['reboot_pending']['data'], {'pending': False, 'indicators': []})


if __name__ == '__main__':
    unittest.main()
