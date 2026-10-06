import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
ENABLED = os.environ.get('CENSUS_RUN_INTEGRATION_TESTS') == '1' and shutil.which('ansible-playbook') and shutil.which('ansible-inventory')


@unittest.skipUnless(ENABLED, 'opt-in fictional integration test needs qualified Ansible/collections')
class ParentIntegrationTests(unittest.TestCase):
    def fixture(self, parent):
        kit = parent / 'vendor/infrastructure-census-map'
        for name in ('playbooks', 'collectors', 'renderer', 'tools'):
            shutil.copytree(ROOT / name, kit / name, ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
        (parent / 'playbooks').mkdir()
        shutil.copyfile(ROOT / 'model/integration/collect-infrastructure-census.yml', parent / 'playbooks/collect-infrastructure-census.yml')
        (parent / 'playbooks/existing-maintenance.yml').write_text('---\n- hosts: all\n  gather_facts: false\n  tasks: []\n')
        (parent / 'ansible.cfg').write_text('[defaults]\nhost_key_checking = True\n')
        inventory = parent / 'inventories/current'
        (inventory / 'group_vars').mkdir(parents=True)
        (inventory / 'hosts.yml').write_text('''---
all:
  hosts:
    localhost:
      ansible_connection: ssh
      ansible_python_interpreter: /nonexistent-controller-python
      ansible_shell_type: powershell
  children:
    existing_linux:
      hosts:
        fixture01:
          ansible_connection: local
          census_python: /nonexistent-census-fixture-python
''')
        (inventory / 'group_vars/existing_linux.yml').write_text('ansible_user: fixture-reader\nparent_marker: keep-existing-inventory-vars\n')
        (parent / 'private/census').mkdir(parents=True)
        shutil.copyfile(ROOT / 'model/integration/census-groups.example.yml', parent / 'private/census/census-groups.yml')
        return kit

    def environment(self, parent):
        return dict(os.environ, ANSIBLE_CONFIG=str(parent / 'ansible.cfg'))

    def test_overlay_preserves_existing_aliases_and_inventory_variables(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            self.fixture(parent)
            result = subprocess.run(['ansible-inventory', '-i', 'inventories/current/hosts.yml', '-i', 'private/census/census-groups.yml', '--list'], cwd=parent, env=self.environment(parent), capture_output=True, text=True, timeout=60)
            self.assertEqual(result.returncode, 0, result.stderr)
            document = json.loads(result.stdout)
            values = document['_meta']['hostvars']
            self.assertEqual(set(values), {'fixture01', 'localhost'})
            self.assertEqual(values['fixture01']['ansible_user'], 'fixture-reader')
            self.assertEqual(values['fixture01']['parent_marker'], 'keep-existing-inventory-vars')
            self.assertEqual(values['localhost']['ansible_connection'], 'local')
            self.assertEqual(values['localhost']['ansible_shell_type'], 'sh')
            self.assertIn('existing_linux', document['census_linux']['children'])

    def test_nested_wrapper_completes_gap_export_without_touching_parent_playbooks(self):
        with tempfile.TemporaryDirectory() as directory:
            parent = Path(directory)
            self.fixture(parent)
            existing = {path: path.read_bytes() for path in (parent / 'ansible.cfg', parent / 'playbooks/existing-maintenance.yml')}
            settings = {'census_run_id':'integration-fixture','census_output_root':str(parent / 'private/results')}
            command = ['ansible-playbook', '-i', 'inventories/current/hosts.yml', '-i', 'private/census/census-groups.yml', 'playbooks/collect-infrastructure-census.yml', '-e', json.dumps(settings), '--limit', 'fixture01,localhost']
            result = subprocess.run(command, cwd=parent, env=self.environment(parent), capture_output=True, text=True, timeout=120)
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            self.assertIn('READY FOR WINSCP', result.stdout)
            run = parent / 'private/results/integration-fixture'
            self.assertTrue((parent / 'private/results/census-integration-fixture.tar.gz').is_file())
            self.assertTrue((run / 'products/dependency-map.html').is_file())
            manifest = json.loads((run / 'MANIFEST.json').read_text())
            self.assertEqual(manifest['expected_assets'], ['fixture01'])
            self.assertEqual(manifest['assets'], ['fixture01'])
            self.assertEqual(json.loads((run / 'hosts/fixture01.json').read_text())['sections']['collection']['status'], 'error')
            for path, content in existing.items():
                self.assertEqual(path.read_bytes(), content)


if __name__ == '__main__':
    unittest.main()
