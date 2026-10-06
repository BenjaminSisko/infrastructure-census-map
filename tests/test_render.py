"""Regression tests for evidence interpretation and offline rendering."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("census_render", ROOT / "renderer/render.py")
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


def host(asset_id, address, hostname=None):
    return {"schema_version": 1, "asset_id": asset_id, "platform": "linux",
            "sections": {"identity": {"status": "ok", "data": {"hostname": hostname or asset_id}},
                         "interfaces": {"status": "ok", "data": [{"address": address}]},
                         "tcp": {"status": "ok", "data": []}}}


class RenderTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.root = Path(self.workspace.name)
        (self.root / "hosts").mkdir()

    def tearDown(self):
        self.workspace.cleanup()

    def save(self, record):
        (self.root / "hosts" / (record["asset_id"] + ".json")).write_text(json.dumps(record))

    def test_empty_and_invalid_evidence_fail(self):
        with self.assertRaisesRegex(ValueError, "No host evidence"):
            render.normalize(self.root)
        (self.root / "hosts/missing.json").write_text('{"schema_version":1,"platform":"linux"}')
        with self.assertRaisesRegex(ValueError, "asset_id"):
            render.normalize(self.root)

    def test_established_endpoint_is_not_initiator_or_approved(self):
        record = host("server", "2001:db8::10")
        record["sections"]["tcp"]["data"] = [{"local_address": "2001:db8::10", "local_port": 443,
            "remote_address": "2001:db8::20", "remote_port": 52000, "state": "ESTABLISHED"}]
        self.save(record)
        model = render.normalize(self.root)
        edge = model["relationships"][0]
        self.assertEqual(edge["source_origin"], "unknown")
        self.assertEqual(edge["status"], "observed")
        self.assertEqual(edge["target"], "address:2001:db8::20")
        self.assertIn("hosts/server.json", edge["evidence"][0])

    def test_duplicate_ip_stays_ambiguous(self):
        record = host("client", "192.0.2.10")
        record["sections"]["tcp"]["data"] = [{"remote_address": "192.0.2.20", "remote_port": 443, "state": "Established"}]
        for value in [record, host("server1", "192.0.2.20"), host("server2", "192.0.2.20")]:
            self.save(value)
        model = render.normalize(self.root)
        edge = model["relationships"][0]
        self.assertEqual(edge["target"], "ambiguous:192.0.2.20")
        self.assertEqual(edge["status"], "Needs Validation")
        ambiguous = next(n for n in model["nodes"] if n["id"] == edge["target"])
        self.assertEqual(ambiguous["candidates"], ["server1", "server2"])

    def test_html_and_svg_escape_untrusted_evidence(self):
        payload = '</script><script>alert("unsafe")</script><svg onload="evil()">'
        self.save(host("server", "192.0.2.10", payload))
        output = self.root / "output"
        render.write_products(render.normalize(self.root), output)
        document = (output / "dependency-map.html").read_text()
        self.assertNotIn(payload, document)
        self.assertIn("\\u003c/script\\u003e", document)
        self.assertNotIn("innerHTML", document)
        self.assertNotIn("https://", document)
        ET.fromstring((output / "dependency-map.svg").read_text())

    def test_declared_does_not_promote_to_verified(self):
        self.save(host("client", "192.0.2.10"))
        self.save(host("server", "192.0.2.20"))
        declared = self.root / "declared.json"
        declared.write_text(json.dumps({"dependencies": [{"source": "client", "target": "server",
            "status": "verified", "purpose": "Application API", "port": 443}]}))
        model = render.normalize(self.root, declared)
        self.assertEqual(model["relationships"][0]["status"], "declared")
        self.assertEqual(model["relationships"][0]["source_origin"], "declared")

    def test_platform_capabilities_and_address_provenance(self):
        record = host("switch", "192.0.2.2")
        record["platform"] = "network"
        record["sections"].pop("tcp")
        record["sections"]["identity"]["data"]["management_address"] = "192.0.2.3"
        record["sections"]["interfaces"]["data"] = [{"ipv4": [{"address": "192.0.2.2"}], "ipv6": [{"address": "2001:db8::2"}]}]
        record["sections"]["neighbors"] = {"status": "ok", "data": {}}
        self.save(record)
        model = render.normalize(self.root)
        self.assertEqual(model["gaps"], [])
        self.assertEqual(model["nodes"][0]["addresses"], ["192.0.2.2", "192.0.2.3", "2001:db8::2"])
        self.assertEqual(model["nodes"][0]["address_provenance"]["192.0.2.3"], "inventory management address")

    def test_windows_and_network_fixtures_render_deterministically(self):
        model = render.normalize(ROOT / "examples/synthetic", ROOT / "model/declared-dependencies.example.json")
        self.assertEqual(len(model["nodes"]), 5)
        ad = next(n for n in model["nodes"] if n["id"] == "ad01")
        self.assertEqual(ad["addresses"], ["192.0.2.30"])
        self.assertEqual(len([e for e in model["relationships"] if e["kind"] == "physical_neighbor"]), 2)
        self.assertEqual(render.draw_svg(model), render.draw_svg(model))
        self.assertTrue(model["gaps"])


if __name__ == "__main__":
    unittest.main()
