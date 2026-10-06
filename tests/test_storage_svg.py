import importlib.util
from pathlib import Path
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location('storage_svg_renderer', ROOT / 'renderer/render.py')
RENDER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(RENDER)


class StorageSvgTests(unittest.TestCase):
    def test_storage_arrows_and_configured_dashes_retain_direction_and_paths(self):
        model = RENDER.normalize(ROOT / 'examples/admin-snapshot', manual=ROOT / 'examples/admin-snapshot/context.json')
        document = ET.fromstring(RENDER.draw_svg(model))
        paths = {element.get('data-edge'): element for element in document.iter() if element.get('data-edge')}
        mounts = [edge for edge in model['relationships'] if edge['kind'] == 'storage_mount']
        self.assertTrue(mounts)
        for edge in mounts:
            element = paths[edge['id']]
            self.assertEqual(element.get('marker-end'), 'url(#storage-arrow)')
            self.assertEqual(element.get('stroke-dasharray'), 'none' if edge['status'] == 'observed' else '2 4')
            title = ''.join(element.itertext())
            self.assertIn(edge['mount_target'], title)
            self.assertIn(edge['remote_path'], title)
            self.assertIn(edge['mount_state'], title)
