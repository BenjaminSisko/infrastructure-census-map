import importlib.util
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('offline_tools', ROOT / 'tools/offline.py')
offline = importlib.util.module_from_spec(spec)
spec.loader.exec_module(offline)


class OfflineTests(unittest.TestCase):
    def test_staging_dry_run_does_not_create_output(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'dependencies'
            result = subprocess.run([sys.executable, str(ROOT / 'tools/offline.py'), 'stage', '--destination', str(path), '--profile', 'reporting', '--confirm-matching-controller', '--dry-run'], text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(path.exists())
            self.assertIn('--only-binary=:all:', result.stdout)

    def fixture(self, path):
        (path / 'collections').mkdir()
        (path / 'collections/requirements.yml').write_text('collections: []\n')
        (path / 'requirements.lock').write_text('Jinja2==3.1.6\n')
        (path / 'ENVIRONMENT.json').write_text(json.dumps({'profile':'controller','os':platform.system(),'distribution':offline.distribution(),'architecture':platform.machine(),'python':platform.python_version(),'include_junos':False}))
        (path / 'SHA256SUMS').write_text(''.join('{}  {}\n'.format(offline.bundle.digest(item), item.relative_to(path).as_posix()) for item in offline.checksum_files(path)))

    def test_offline_install_uses_collection_folder_and_offline_flag(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / 'dependency-bundle'
            source.mkdir()
            self.fixture(source)
            arguments = ['offline.py', 'install', '--bundle', str(source), '--venv', str(Path(directory) / 'new-venv')]
            with patch.object(sys, 'argv', arguments), patch.object(offline.subprocess, 'run') as execute:
                offline.main()
            collection = execute.call_args_list[-1]
            self.assertIn('--offline', collection.args[0])
            self.assertEqual(collection.kwargs['cwd'], source.resolve() / 'collections')

    def test_changed_or_unlisted_dependencies_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory)
            self.fixture(source)
            offline.verify(source)
            (source / 'unlisted.whl').write_text('unlisted')
            with self.assertRaises(ValueError):
                offline.verify(source)
