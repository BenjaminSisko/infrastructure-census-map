import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('manual_render', ROOT / 'renderer/render.py')
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


class ManualTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.root = Path(self.workspace.name)

    def tearDown(self):
        self.workspace.cleanup()

    def manual(self, assets, relationships=None):
        path = self.root / 'manual.json'
        path.write_text(json.dumps({'schema_version': 1, 'assets': assets, 'relationships': relationships or []}))
        return path

    def test_manual_hypervisor_storage_and_collected_guests(self):
        model = render.normalize(ROOT / 'examples/synthetic', manual=ROOT / 'model/manual-context.example.yml')
        self.assertEqual(len(model['nodes']), 8)
        hosting = [e for e in model['relationships'] if e.get('relationship_type') == 'hosts']
        self.assertEqual({e['target'] for e in hosting}, {'app01', 'db01'})
        self.assertTrue(all(e['source'] == 'hv01' and e['remote_port'] is None and e['status'] == 'manual_declared' for e in hosting))
        app = next(n for n in model['nodes'] if n['id'] == 'app01')
        self.assertEqual(app['owner'], 'Example application team')
        self.assertEqual(app['source_kind'], 'census')
        self.assertEqual(model['collection_mode'], 'mixed')
        self.assertEqual(len(model['manual_source']['sha256']), 64)

    def test_conflicting_measured_identity_and_addresses_survive(self):
        path = self.manual([{'id': 'app01', 'label': 'Wrong hostname', 'os': 'Wrong OS',
                             'addresses': ['192.0.2.99'], 'owner': 'Operator-supplied owner'}])
        model = render.normalize(ROOT / 'examples/synthetic', manual=path)
        app = next(n for n in model['nodes'] if n['id'] == 'app01')
        self.assertNotEqual(app['label'], 'Wrong hostname')
        self.assertNotEqual(app['os'], 'Wrong OS')
        self.assertNotIn('192.0.2.99', app['addresses'])
        self.assertEqual({c['field'] for c in model['conflicts']}, {'label', 'os', 'addresses'})
        self.assertEqual(app['owner'], 'Operator-supplied owner')

    def test_manual_only_map_and_untrusted_context(self):
        payload = '</script><script>evil()</script>'
        path = self.manual([{'id': 'hv01', 'label': payload, 'asset_type': 'hypervisor', 'owner': payload}])
        model = render.normalize(manual=path)
        self.assertEqual(model['collection_mode'], 'manual_only')
        self.assertEqual(model['nodes'][0]['collected_at'], 'Not collected')
        out = self.root / 'output'
        render.write_products(model, out)
        page = (out / 'dependency-map.html').read_text()
        self.assertIn('Census was not collected', page)
        self.assertNotIn(payload, page)
        ET.fromstring((out / 'dependency-map.svg').read_text())

    def test_peer_can_resolve_to_manual_asset_without_verified_status(self):
        evidence = self.root / 'evidence'
        (evidence / 'hosts').mkdir(parents=True)
        (evidence / 'hosts/client.json').write_text(json.dumps({
            'schema_version': 1, 'asset_id': 'client', 'platform': 'linux',
            'sections': {'tcp': {'status': 'ok', 'data': [{'state': 'Established', 'remote_address': '192.0.2.40'}]}}
        }))
        path = self.manual([{'id': 'hv01', 'addresses': ['192.0.2.40']}])
        model = render.normalize(evidence, manual=path)
        edge = model['relationships'][0]
        self.assertEqual(edge['target'], 'hv01')
        self.assertEqual(edge['target_resolution_basis'], 'manual assertion')
        self.assertEqual(edge['status'], 'observed')
        self.assertEqual(edge['source_origin'], 'unknown')
        # A manual address cannot hide measured duplicate ownership.
        path = self.manual([{'id': 'extra', 'addresses': ['192.0.2.10']}])
        mixed = render.normalize(ROOT / 'examples/synthetic', manual=path)
        self.assertTrue(any(e['target'] == 'ambiguous:192.0.2.10' for e in mixed['relationships']))

    def test_invalid_context_and_hosting_cycles(self):
        for assets, relationships, message in [
            ([{'id': '../bad'}], [], 'safe id'),
            ([{'id': 'hv'}, {'id': 'hv'}], [], 'Duplicate'),
            ([{'id': 'hv', 'addresses': ['bad-address']}], [], 'addresses'),
            ([{'id': 'hv', 'owner': {'bad': 'type'}}], [], 'text'),
            ([{'id': 'hv', 'attributes': {'memory': float('nan')}}], [], 'JSON-compatible'),
            ([{'id': 'hv'}], [{'source': 'hv', 'target': 'missing', 'kind': 'hosts', 'purpose': 'placement'}], 'source/target'),
            ([{'id': 'hv'}], [{'source': 'hv', 'target': 'hv', 'kind': 'hosts', 'purpose': 'placement'}], 'itself'),
            ([{'id': 'hv'}, {'id': 'vm'}], [{'source': 'hv', 'target': 'vm', 'kind': 'hosts', 'purpose': 'placement', 'port': 443}], 'placement'),
        ]:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    render.normalize(manual=self.manual(assets, relationships))
        edges = [{'source': 'a', 'target': 'b', 'kind': 'hosts', 'purpose': 'placement'},
                 {'source': 'b', 'target': 'a', 'kind': 'hosts', 'purpose': 'placement'}]
        with self.assertRaisesRegex(ValueError, 'cycle'):
            render.normalize(manual=self.manual([{'id': 'a'}, {'id': 'b'}], edges))
        for edge in edges:
            edge['kind'] = 'depends_on'
        model = render.normalize(manual=self.manual([{'id': 'a'}, {'id': 'b'}], edges))
        self.assertEqual(len(model['relationships']), 2)
        yaml_path = self.root / 'bad-keys.yml'
        yaml_path.write_text('schema_version: 1\nassets:\n  - id: hv\n    attributes:\n      1: value\n')
        with self.assertRaisesRegex(ValueError, 'JSON-compatible'):
            render.normalize(manual=yaml_path)

    def test_manual_and_legacy_declared_inputs_coexist(self):
        path = self.manual([{'id': 'hv01'}], [{'source': 'hv01', 'target': 'app01', 'kind': 'hosts', 'purpose': 'guest placement'}])
        declared = self.root / 'declared.json'
        record = {'source': 'app01', 'target': 'db01', 'purpose': 'database', 'port': 5432}
        for document in ({'dependencies': [record]}, [record]):
            declared.write_text(json.dumps(document))
            model = render.normalize(ROOT / 'examples/synthetic', declared=declared, manual=path)
            self.assertEqual(len([e for e in model['relationships'] if e['kind'] == 'manual_relationship']), 1)
            self.assertEqual(len([e for e in model['relationships'] if e['kind'] == 'declared_dependency']), 1)

    def test_neighbor_identity_match_retains_manual_basis(self):
        # Explicit peer-name match against a manual identity without observed addresses.
        evidence = self.root / 'evidence'
        (evidence / 'hosts').mkdir(parents=True)
        (evidence / 'hosts/switch.json').write_text(json.dumps({
            'schema_version': 1, 'asset_id': 'switch', 'platform': 'network',
            'sections': {'neighbors': {'status': 'ok', 'data': {'Gi0/1': [{'host': 'new-hv'}]}}}
        }))
        path = self.manual([{'id': 'hv01', 'label': 'new-hv'}])
        model = render.normalize(evidence, manual=path)
        edge = model['relationships'][0]
        self.assertEqual(edge['target_resolution_basis'], 'manual assertion')
        self.assertEqual(edge['target_identity_evidence'], 'manual.json#/assets/0')
        self.assertEqual(edge['status'], 'observed')


if __name__ == '__main__':
    unittest.main()
