import importlib.util
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('release_tools', ROOT / 'tools/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_private_or_unreviewed_tracked_files_fail_closed(self):
        for name in ('.env', 'private.pem', 'examples/real-network/private.png', 'output/private.json', 'inventories/production/hosts.yml'):
            with self.subTest(name=name), patch.object(release.subprocess, 'run') as command:
                command.return_value.stdout = name + '\0'
                with self.assertRaises(ValueError):
                    release.public_paths()


if __name__ == '__main__':
    unittest.main()
