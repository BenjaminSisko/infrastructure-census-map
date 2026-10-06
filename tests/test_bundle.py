import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('bundle', Path(__file__).parents[1] / 'tools/bundle.py')
bundle = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bundle)


class BundleTests(unittest.TestCase):
    def test_reseal_preserves_baseline_and_rejects_changed_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_bundle(root)
            original = (root / 'SHA256SUMS').read_bytes()
            bundle.seal(root)
            self.assertEqual((root / 'SHA256SUMS').read_bytes(), original)
            (root / 'hosts/host01.json').write_text('{}')
            with self.assertRaises(ValueError):
                bundle.seal(root)
            self.assertEqual((root / 'SHA256SUMS').read_bytes(), original)

    def make_bundle(self, path):
        (path / 'hosts').mkdir()
        (path / 'hosts/host01.json').write_text(json.dumps({
            'schema_version': 1, 'asset_id': 'host01', 'platform': 'windows',
            'sections': {'collection': {'status': 'unreachable'}}
        }))
        (path / 'expected-assets.json').write_text(json.dumps({'expected_assets': ['host01', 'host02']}))
        bundle.seal(path)

    def test_gap_host_and_missing_expected_host_remain_visible(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_bundle(root)
            bundle.verify(root)
            result = json.loads((root / 'MANIFEST.json').read_text())
            self.assertEqual(result['missing_assets'], ['host02'])
            self.assertEqual(result['section_gaps'][0]['status'], 'unreachable')

    def test_changed_evidence_and_unsealed_host_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.make_bundle(root)
            path = root / 'hosts/host01.json'
            original = path.read_text()
            path.write_text(original + ' ')
            with self.assertRaises(ValueError):
                bundle.verify(root)
            path.write_text(original)
            (root / 'hosts/extra.json').write_text(original)
            with self.assertRaises(ValueError):
                bundle.verify(root)


if __name__ == '__main__':
    unittest.main()
