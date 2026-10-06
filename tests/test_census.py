import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
spec = importlib.util.spec_from_file_location('census_cli', ROOT / 'tools/census.py')
census = importlib.util.module_from_spec(spec)
spec.loader.exec_module(census)


class CensusWorkflowTests(unittest.TestCase):
    def fixture(self, root):
        run = root / 'run01'
        (run / 'hosts').mkdir(parents=True)
        (run / 'hosts/host01.json').write_text(json.dumps({'schema_version':1,'asset_id':'host01','platform':'linux','sections':{'identity':{'status':'access_denied'}}}))
        (run / 'expected-assets.json').write_text(json.dumps({'expected_assets':['host01','missing01']}))
        census.bundle.seal(run)
        return run

    def test_finish_exports_only_allowlisted_data_and_no_symlinks(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.fixture(Path(directory))
            (run / 'private-passwords.txt').write_text('do not export')
            (run / 'products').mkdir()
            (run / 'products/not-a-product.key').write_text('do not export')
            archive = census.finish(run)
            with tarfile.open(archive) as package:
                names = package.getnames()
                self.assertIn('run01/products/dependency-map.html', names)
                self.assertIn('run01/hosts/host01.json', names)
                self.assertIn('run01/context/manual-context.json', names)
                self.assertNotIn('run01/private-passwords.txt', names)
                self.assertNotIn('run01/products/not-a-product.key', names)
                self.assertTrue(all(member.isfile() and not member.name.startswith('/') and '..' not in Path(member.name).parts for member in package.getmembers()))
                self.assertTrue(all(member.uid == 0 and member.gid == 0 and not member.uname and not member.gname for member in package.getmembers()))
                self.assertIn(hashlib.sha256(archive.read_bytes()).hexdigest(), archive.with_name(archive.name + '.sha256').read_text())
            model = json.loads((run / 'products/map.json').read_text())
            self.assertTrue(any(node['id'] == 'missing01' for node in model['nodes']))
            self.assertTrue(any(gap['status'] == 'missing host record' for gap in model['gaps']))
            checksums = (run / 'SHA256SUMS').read_bytes()
            second = census.finish(run, render=False)
            self.assertNotEqual(second, archive)
            self.assertEqual((run / 'SHA256SUMS').read_bytes(), checksums)

    def test_symlinked_host_directory_and_changed_evidence_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = self.fixture(root)
            (run / 'hosts').rename(run / 'original-hosts')
            (run / 'hosts').symlink_to(run / 'original-hosts', target_is_directory=True)
            with self.assertRaises(ValueError):
                census.finish(run, render=False)
            (run / 'hosts').unlink()
            (run / 'original-hosts').rename(run / 'hosts')
            (run / 'hosts/host01.json').write_text('{}')
            with self.assertRaises(ValueError):
                census.finish(run, render=False)

    def test_demo_is_a_one_command_offline_workflow_and_preserves_prior_run(self):
        with tempfile.TemporaryDirectory() as directory:
            command = [sys.executable, str(ROOT / 'tools/census.py'), 'demo', '--output-root', directory, '--run-id', 'demo01', '--manual', str(ROOT / 'model/manual-context.example.yml')]
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('READY FOR WINSCP', result.stdout)
            self.assertTrue((Path(directory) / 'census-demo01.tar.gz').is_file())
            self.assertNotEqual(subprocess.run(command, capture_output=True).returncode, 0)

    def test_invalid_run_ids_rejected(self):
        for value in ('../other', '.hidden', '/tmp/run', 'two words'):
            with self.assertRaises(ValueError):
                census.run_id(value)

    def test_generated_symlinks_are_rejected_before_any_outside_write(self):
        for relative in ('products', 'products/map.json', 'context', 'context/manual-context.json', 'START-HERE.md', 'TRANSFER-SHA256SUMS'):
            with self.subTest(relative=relative), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                run = self.fixture(root)
                target = run / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                outside = root / 'outside'
                if relative in ('products', 'context'):
                    outside.mkdir()
                    target.symlink_to(outside, target_is_directory=True)
                else:
                    outside.write_text('untouched')
                    target.symlink_to(outside)
                with self.assertRaises(ValueError):
                    census.finish(run)
                if outside.is_file():
                    self.assertEqual(outside.read_text(), 'untouched')
                else:
                    self.assertEqual(list(outside.iterdir()), [])

    def test_repeat_finish_retains_manual_input(self):
        with tempfile.TemporaryDirectory() as directory:
            run = self.fixture(Path(directory))
            manual = Path(directory) / 'manual.json'
            manual.write_text(json.dumps({'schema_version':1,'assets':[{'id':'hv','notes':'keep my context'}]}))
            census.finish(run, manual=manual)
            census.finish(run)
            saved = json.loads((run / 'context/manual-context.json').read_text())
            self.assertEqual(saved['assets'][0]['notes'], 'keep my context')


if __name__ == '__main__':
    unittest.main()
