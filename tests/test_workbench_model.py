import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('workbench_render', ROOT / 'renderer/render.py')
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


class WorkbenchModelTests(unittest.TestCase):
    def test_reserved_attribute_keys_and_scoped_manual_addresses_fail_early(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'manual.json'
            for asset in ({'id':'hv','attributes':{'nested':{'constructor':'unsafe'}}}, {'id':'hv','addresses':['fe80::1%eth0']}):
                path.write_text(json.dumps({'schema_version':1,'assets':[asset]}))
                with self.assertRaises(ValueError):
                    render.normalize(manual=path)

    def test_workbench_keeps_measured_base_and_manual_edit_layer(self):
        model = render.normalize(ROOT / 'examples/synthetic', manual=ROOT / 'model/manual-context.example.yml')
        measured_ids = {node['id'] for node in model['census_nodes']}
        self.assertNotIn('hv01', measured_ids)
        self.assertIn('app01', measured_ids)
        measured = next(node for node in model['census_nodes'] if node['id'] == 'app01')
        self.assertNotIn('owner', measured)
        enriched = next(node for node in model['nodes'] if node['id'] == 'app01')
        self.assertIn('owner', enriched)
        self.assertTrue(model['census_details']['app01']['sections'])
        self.assertEqual(model['manual_context']['schema_version'], 1)
        self.assertTrue(all(edge['kind'] != 'manual_relationship' for edge in model['evidence_relationships']))

    def test_draft_scope_is_stable_for_same_inputs_and_changes_for_new_context(self):
        base = render.normalize(ROOT / 'examples/synthetic')
        again = render.normalize(ROOT / 'examples/synthetic')
        mixed = render.normalize(ROOT / 'examples/synthetic', manual=ROOT / 'model/manual-context.example.yml')
        self.assertEqual(base['workspace_id'], again['workspace_id'])
        self.assertNotEqual(base['workspace_id'], mixed['workspace_id'])

    def test_unresolved_observed_endpoint_remains_in_browser_base(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'hosts').mkdir()
            (root / 'hosts/app.json').write_text(json.dumps({
                'schema_version': 1, 'asset_id': 'app', 'platform': 'linux',
                'sections': {'tcp': {'status': 'ok', 'data': [{'state': 'Established', 'remote_address': '192.0.2.200'}]}}
            }))
            model = render.normalize(root)
            self.assertIn('address:192.0.2.200', {node['id'] for node in model['census_nodes']})
            self.assertEqual(model['evidence_relationships'][0]['remote_address'], '192.0.2.200')


if __name__ == '__main__':
    unittest.main()
