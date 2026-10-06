import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('release_tools', ROOT / 'tools/release.py')
release = importlib.util.module_from_spec(spec)
spec.loader.exec_module(release)


class ReleaseTests(unittest.TestCase):
    def test_documentation_ranges_allowed_but_private_networks_rejected(self):
        allowed = ('192.0.2.1', '198.51.100.40', '203.0.113.20')
        rejected = tuple('.'.join(map(str, octets)) for octets in ((10, 1, 2, 3), (172, 16, 1, 2), (192, 168, 1, 5)))
        for address in allowed + rejected:
            with self.subTest(address=address), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                (root / 'docs').mkdir()
                (root / 'docs/address.md').write_text('Example address: ' + address, encoding='utf-8')
                with patch.object(release, 'ROOT', root), patch.object(release.subprocess, 'run') as command:
                    command.return_value.stdout = 'docs/address.md\0'
                    if address in allowed:
                        self.assertEqual(len(release.public_paths()), 1)
                    else:
                        with self.assertRaisesRegex(ValueError, 'non-documentation private IP'):
                            release.public_paths()

    def test_private_or_unreviewed_tracked_files_fail_closed(self):
        for name in ('.env', 'private.pem', 'examples/real-network/private.png', 'output/private.json', 'inventories/production/hosts.yml'):
            with self.subTest(name=name), patch.object(release.subprocess, 'run') as command:
                command.return_value.stdout = name + '\0'
                with self.assertRaises(ValueError):
                    release.public_paths()


if __name__ == '__main__':
    unittest.main()
