"""Storage identity, numerical gaps, offline dashboard and product regression tests."""
import csv
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("insights_render", ROOT / "renderer/render.py")
render = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(render)


def host(asset_id="client", platform="linux", hostname=None, address="192.0.2.10", sections=None):
    return {"schema_version": 1, "asset_id": asset_id, "platform": platform, "collected_at": "2026-10-05T14:00:00Z",
            "sections": {"identity": {"status": "ok", "data": {"hostname": hostname or asset_id}},
                         "interfaces": {"status": "ok", "data": [{"address": address}]}, "tcp": {"status": "ok", "data": []}, **(sections or {})}}


def ok(data):
    return {"status": "ok", "data": data}


def mounts(*rows):
    return ok({"filesystems": list(rows)})


def nfs(source="nas.example.test:/exports/shared", target="/mnt/shared", fstype="nfs4"):
    return {"source": source, "target": target, "fstype": fstype}


class InsightsTests(unittest.TestCase):
    def setUp(self):
        self.workspace = tempfile.TemporaryDirectory()
        self.root = Path(self.workspace.name)
        (self.root / "hosts").mkdir()

    def tearDown(self):
        self.workspace.cleanup()

    def save(self, *records):
        for record in records:
            (self.root / "hosts" / (record["asset_id"] + ".json")).write_text(json.dumps(record), encoding="utf-8")

    def manual(self, assets):
        path = self.root / "context.json"
        path.write_text(json.dumps({"schema_version": 1, "assets": assets, "relationships": []}), encoding="utf-8")
        return path

    def test_nested_nfs_reconciles_configuration_with_original_pointers(self):
        row = nfs()
        self.save(host(sections={"mounts": mounts({"source": "/dev/example", "target": "/", "fstype": "xfs", "children": [row]}), "configured_mounts": mounts(row)}),
                  host("nas", hostname="nas.example.test", address="192.0.2.50"))
        model = render.normalize(self.root)
        mount = model["storage_mounts"][0]
        self.assertEqual(mount["provider_asset_id"], "nas")
        self.assertEqual(mount["mount_state"], "active")
        self.assertEqual(mount["identity_basis"], "census identity")
        self.assertIn("hosts/client.json#/sections/mounts/data/filesystems/0/children/0", mount["evidence"])
        self.assertEqual(len(mount["evidence"]), 2)
        edge = next(edge for edge in model["relationships"] if edge["kind"] == "storage_mount")
        self.assertEqual(edge["status"], "observed")
        self.assertEqual(edge["remote_name"], "nas.example.test")
        self.assertEqual(edge["id"], model["evidence_relationships"][0]["id"])
        self.assertNotIn("authorized", edge)
        ET.fromstring(render.draw_svg(model))

    def test_local_mount_bind_and_unsupported_source_do_not_create_remote_nodes(self):
        self.save(host(sections={"mounts": mounts(nfs("/dev/sda1", "/", "xfs"), nfs("/srv/local[/folder]", "/bind", "ext4"), nfs("//nas.example.test/share", "/other", "bind")), "configured_mounts": mounts()}))
        self.assertEqual(render.normalize(self.root)["storage_mounts"], [])

    def test_ipv6_nfs_and_unc_canonicalization(self):
        self.save(host(sections={"mounts": mounts(nfs("[2001:0db8::50]:/exports/shared")), "configured_mounts": mounts()}),
                  host("nas", address="2001:db8::50"),
                  host("windows", "windows", address="192.0.2.30", sections={"smb_mappings": ok([{"local_path": "Z:", "remote_path": "\\\\NAS.EXAMPLE.TEST\\share", "status": "OK"}]), "configured_mounts": mounts(nfs("//nas.example.test/share", "Z:", "cifs")), "disks": ok([{"device_id": "Z:", "provider_name": "//nas.example.test/share"}])}))
        model = render.normalize(self.root)
        self.assertEqual(model["storage_mounts"][0]["remote_path"], "[2001:db8::50]:/exports/shared")
        mapping = model["storage_mounts"][1]
        self.assertEqual(mapping["remote_path"], "//nas.example.test/share")
        self.assertEqual(len(mapping["evidence"]), 3)
        self.assertTrue(mapping["active_observed"])
        self.assertEqual(mapping["provider_asset_id"], "storage:nas.example.test")
        external = next(node for node in model["nodes"] if node["id"] == mapping["provider_asset_id"])
        self.assertEqual(external["addresses"], [])

    def test_no_dns_lookup_or_short_hostname_expansion(self):
        self.save(host(sections={"mounts": mounts(nfs("nas:/exports/shared")), "configured_mounts": mounts()}),
                  host("storage01", hostname="nas.example.test", address="192.0.2.50"))
        with patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")), patch("socket.gethostbyname", side_effect=AssertionError("DNS forbidden")):
            model = render.normalize(self.root)
        self.assertEqual(model["storage_mounts"][0]["provider_asset_id"], "storage:nas")

    def test_ambiguous_provider_names_remain_unknown(self):
        self.save(host(sections={"mounts": mounts(nfs()), "configured_mounts": mounts()}),
                  host("storage1", hostname="nas.example.test", address="192.0.2.50"), host("storage2", hostname="nas.example.test", address="192.0.2.51"))
        model = render.normalize(self.root)
        mount = model["storage_mounts"][0]
        self.assertEqual(mount["identity_basis"], "ambiguous")
        self.assertEqual(mount["provider_asset_id"], "ambiguous:nas.example.test")
        self.assertEqual(next(node for node in model["nodes"] if node["id"] == mount["provider_asset_id"])["candidates"], ["storage1", "storage2"])
        self.assertEqual(model["relationships"][0]["status"], "observed")

    def test_manual_identity_match_is_an_assertion(self):
        self.save(host(sections={"mounts": mounts(nfs()), "configured_mounts": mounts()}))
        context = self.manual([{"id": "nas", "label": "nas.example.test", "addresses": ["192.0.2.50"], "source": "Fictional worksheet", "reviewed_at": "2026-10-05"}])
        model = render.normalize(self.root, manual=context)
        self.assertEqual(model["storage_mounts"][0]["identity_basis"], "manual assertion")
        self.assertEqual(model["relationships"][0]["target_resolution_basis"], "manual assertion")

    def test_mount_states_are_evidence_states_not_outage_claims(self):
        cases = [(mounts(nfs()), mounts(nfs()), "active"),
                 (mounts(), mounts(nfs()), "configured_only"),
                 ({"status": "access_denied"}, mounts(nfs()), "unknown"),
                 (mounts(nfs()), {"status": "access_denied"}, "configuration_unknown")]
        for active, configured, expected in cases:
            with self.subTest(expected=expected):
                self.save(host(sections={"mounts": active, "configured_mounts": configured}))
                model = render.normalize(self.root)
                self.assertEqual(model["storage_mounts"][0]["mount_state"], expected)
                self.assertNotIn("disconnected", json.dumps(model["storage_mounts"]))
                self.assertNotIn("outage", model["relationships"][0]["purpose"])

    def test_partial_active_and_configured_collections_do_not_prove_absence(self):
        configured = mounts(nfs())
        self.save(host(sections={"mounts": {"status": "partial", "data": {"filesystems": []}}, "configured_mounts": configured}))
        self.assertEqual(render.normalize(self.root)["storage_mounts"][0]["mount_state"], "unknown")
        self.save(host(sections={"mounts": mounts(nfs()), "configured_mounts": {"status": "partial", "data": configured["data"], "gaps": [{"source": "/etc/auto.example", "reason": "unsupported dynamic map"}]}}))
        self.assertEqual(render.normalize(self.root)["storage_mounts"][0]["mount_state"], "configuration_unknown")

    def test_nfs_and_nfs4_reconcile_without_false_configuration_only_duplicate(self):
        self.save(host(sections={"mounts": mounts(nfs(fstype="nfs4")), "configured_mounts": mounts(nfs(fstype="nfs"))}))
        model = render.normalize(self.root)
        self.assertEqual(len(model["storage_mounts"]), 1)
        self.assertEqual(model["storage_mounts"][0]["reported_fs_types"], ["nfs", "nfs4"])
        self.assertEqual(model["storage_mounts"][0]["mount_state"], "active")

    def test_windows_unavailable_unlettered_and_disk_fallback_do_not_prove_active(self):
        self.save(host("windows", "windows", sections={"smb_mappings": ok([{"local_path": "", "remote_path": "\\\\nas.example.test\\share", "status": "Unavailable"}]),
            "configured_mounts": mounts(), "disks": ok([{"device_id": "Z:", "provider_name": "\\\\nas.example.test\\other"}])}))
        model = render.normalize(self.root)
        self.assertEqual(len(model["storage_mounts"]), 2)
        self.assertIn("(no local drive)", {row["target"] for row in model["storage_mounts"]})
        self.assertTrue(all(row["mount_state"] == "unknown" and not row["active_observed"] for row in model["storage_mounts"]))
        self.assertEqual(model["dashboards"]["summary"]["active_storage_mount_count"], 0)
        self.save(host("windows", "windows", sections={"smb_mappings": {"status": "access_denied"}, "configured_mounts": mounts(nfs("//nas.example.test/other", "Z:", "cifs")),
            "disks": ok([{"device_id": "Z:", "provider_name": "\\\\nas.example.test\\other"}])}))
        self.assertEqual(render.normalize(self.root)["storage_mounts"][0]["mount_state"], "unknown")

    def test_date_only_hotfix_preserves_day_precision_without_currency_claim(self):
        self.save(host("windows", "windows", sections={"hotfixes": ok([{"id": "KB-EXAMPLE", "installed_at": "2026-10-04"}, {"id": "KB-UNKNOWN", "installed_at": None}])}))
        asset = render.normalize(self.root)["dashboards"]["assets"][0]
        self.assertEqual(asset["latest_patch_observation"]["observed_at"], "2026-10-04")
        self.assertEqual(asset["latest_patch_observation"]["precision"], "day")
        self.assertEqual(asset["patch_evidence"]["status"], "unknown")

    def test_static_autofs_rows_and_configuration_lists_are_supported(self):
        self.save(host(sections={"mounts": mounts(), "configured_mounts": ok([nfs()]), "autofs": ok([nfs("nas2.example.test:/exports/other", "/auto/other")])}))
        model = render.normalize(self.root)
        self.assertEqual(len(model["storage_mounts"]), 2)
        self.assertTrue(all(row["mount_state"] == "configured_only" for row in model["storage_mounts"]))

    def test_storage_credentials_options_queries_are_excluded_from_derived_model(self):
        secret = "fixture-password-marker"
        row = nfs("//user:" + secret + "@nas.example.test/share?token=" + secret, "/mnt/share", "cifs")
        row["options"] = "password=" + secret
        self.save(host(sections={"mounts": mounts(row), "configured_mounts": mounts(row)}))
        model = render.normalize(self.root)
        self.assertEqual(model["storage_mounts"][0]["remote_path"], "//nas.example.test/share")
        self.assertNotIn(secret, json.dumps(model))
        self.assertIn(secret, (self.root / "hosts/client.json").read_text())

    def test_sanitized_smb_uri_is_canonical_share_not_dropped(self):
        row = nfs("smb://user:fixture-password-marker@nas.example.test/share?token=fixture-token-marker", "/mnt/share", "cifs")
        self.save(host(sections={"mounts": mounts(row), "configured_mounts": mounts(nfs("//nas.example.test/share", "/mnt/share", "cifs"))}))
        model = render.normalize(self.root)
        self.assertEqual(len(model["storage_mounts"]), 1)
        self.assertEqual(model["storage_mounts"][0]["remote_path"], "//nas.example.test/share")
        self.assertNotIn("fixture-password-marker", json.dumps(model))
        self.assertNotIn("fixture-token-marker", json.dumps(model))

    def test_malformed_multi_userinfo_and_spaced_credential_assignment_are_redacted(self):
        for source in ("smb://reader:fixture-marker-one@second:fixture-marker-two@nas.example.test/share",
                       "//nas.example.test/share,password = fixture-marker-two"):
            self.save(host(sections={"mounts": mounts(nfs(source, "/mnt/share", "cifs")), "configured_mounts": mounts()}))
            value = json.dumps(render.normalize(self.root))
            self.assertNotIn("fixture-marker-one", value)
            self.assertNotIn("fixture-marker-two", value)

    def test_dashboard_numeric_unknowns_and_patch_currency_are_explicit(self):
        self.save(host(sections={"memory": ok({"total_bytes": 100, "available_bytes": 150}), "uptime": ok({"uptime_seconds": -1, "boot_time": "invalid"}),
            "storage_capacity": ok([{"target": "/", "fstype": "xfs", "used_percent": float("nan")}, {"target": "/negative", "fstype": "ext4", "used_percent": -1}, {"target": "/missing", "fstype": "xfs"}]),
            "patch_inventory": ok({"latest_package_install_at": "2026-10-04T12:00:00Z", "baseline_status": "current"})}))
        model = render.normalize(self.root)
        dashboard = model["dashboards"]
        asset = dashboard["assets"][0]
        self.assertIsNone(asset["uptime_seconds"])
        self.assertEqual(asset["boot_time"], "Unknown")
        self.assertIsNone(asset["memory_available_percent"])
        self.assertEqual(asset["patch_evidence"]["status"], "unknown")
        self.assertEqual(asset["latest_patch_observation"]["status"], "observed")
        self.assertTrue(all(row["used_percent"] is None and row["status"] == "unknown" for row in dashboard["storage_capacity"]))
        self.assertEqual(asset["reboot_pending"]["status"], "unknown")
        json.dumps(model, allow_nan=False)

    def test_capacity_only_local_filesystems_and_threshold_configuration(self):
        self.save(host(sections={"storage_capacity": ok([{"target": "/", "fstype": "xfs", "total_bytes": 100, "used_bytes": 85}, {"target": "/remote", "fstype": "nfs4", "used_percent": 99}])}))
        normal = render.normalize(self.root)["dashboards"]
        self.assertEqual(len(normal["storage_capacity"]), 1)
        self.assertEqual(normal["storage_capacity"][0]["status"], "warning")
        adjusted = render.normalize(self.root, capacity_warning_percent=70, capacity_critical_percent=80)["dashboards"]
        self.assertEqual(adjusted["storage_capacity"][0]["status"], "critical")
        for warning, critical in ((90, 80), (-1, 90), (80, float("nan")), (80, 101)):
            with self.assertRaisesRegex(ValueError, "thresholds"):
                render.normalize(self.root, capacity_warning_percent=warning, capacity_critical_percent=critical)

    def test_invalid_zero_and_contradictory_capacity_totals_remain_unknown(self):
        records = [{"target": "/zero", "fstype": "xfs", "total_bytes": 0, "used_bytes": 0, "used_percent": 0},
                   {"target": "/negative", "fstype": "xfs", "total_bytes": -1, "used_percent": 0},
                   {"target": "/nan", "fstype": "xfs", "total_bytes": float("nan"), "used_percent": 0},
                   {"target": "/bounds", "fstype": "xfs", "total_bytes": 100, "used_bytes": 50, "available_bytes": 90, "used_percent": 50}]
        self.save(host(sections={"storage_capacity": ok(records)}))
        rows = render.normalize(self.root)["dashboards"]["storage_capacity"]
        self.assertTrue(all(row["used_percent"] is None and row["status"] == "unknown" for row in rows))

    def test_security_presence_failed_services_and_reboot_are_observations(self):
        self.save(host("windows", "windows", sections={"services": ok([{"name": "WazuhSvc", "state": "Running"}, {"name": "Example", "active": "failed"}]),
            "reboot_pending": ok({"pending": True, "indicators": ["example"]}), "tcp": ok([{"state": "Listen", "local_address": "0.0.0.0", "local_port": 5986, "process": "System"}])}))
        dashboard = render.normalize(self.root)["dashboards"]
        row = dashboard["assets"][0]
        self.assertEqual(row["failed_services"]["names"], ["Example"])
        self.assertTrue(row["reboot_pending"]["value"])
        self.assertEqual(row["security"]["agent"]["names"], ["WazuhSvc"])
        self.assertIn("received telemetry unknown", row["security"]["agent"]["value"])
        self.assertEqual(row["security"]["listeners"]["items"][0]["port"], 5986)
        self.assertTrue(all(item["evidence"] for item in dashboard["findings"]))

    def test_context_retains_sources_and_review_dates_no_attestation_score(self):
        self.save(host())
        context = self.manual([{"id": "client", "owner": "Example team", "source": "Fictional ticket", "reviewed_at": "2026-10-05", "attributes": {"backup_attestation": "Operator states daily backups", "patch_baseline": "Operator says current"}}])
        row = render.normalize(self.root, manual=context)["dashboards"]["assets"][0]
        self.assertEqual(row["backup_attestation"]["status"], "manual assertion")
        self.assertEqual(row["backup_attestation"]["entries"][0]["source"], "Fictional ticket")
        self.assertEqual(row["backup_attestation"]["entries"][0]["reviewed_at"], "2026-10-05")
        self.assertEqual(row["patch_evidence"]["status"], "unknown")

    def test_snapshot_relative_freshness_deterministic_and_missing_scope_visible(self):
        earlier = host("older", address="192.0.2.20")
        earlier["collected_at"] = "2026-10-02T14:00:00Z"
        self.save(host(), earlier)
        (self.root / "expected-assets.json").write_text(json.dumps({"expected_assets": ["client", "older", "not-returned"]}))
        model = render.normalize(self.root)
        self.assertEqual(model, render.normalize(self.root))
        dashboard = model["dashboards"]
        self.assertEqual(dashboard["summary"]["coverage"], {"returned": 2, "expected": 3, "percent": 66.67})
        self.assertEqual(next(row for row in dashboard["assets"] if row["asset_id"] == "older")["freshness"]["age_seconds"], 259200)
        missing = next(row for row in dashboard["assets"] if row["asset_id"] == "not-returned")
        self.assertEqual(missing["coverage"]["status"], "not collected")
        self.assertEqual(missing["security"]["agent"]["status"], "unknown")

    def test_dashboard_products_inline_assets_and_csv_formula_safety(self):
        self.save(host(hostname="=FICTIONAL_FORMULA", sections={"mounts": mounts(nfs(target="=FORMULA")), "configured_mounts": mounts()}))
        model = render.normalize(self.root)
        output = self.root / "output"
        render.write_products(model, output)
        self.assertEqual(json.loads((output / "dashboard-summary.json").read_text()), model["dashboards"])
        page = (output / "dashboards.html").read_text()
        self.assertIn('id="dashboard-data"', page)
        self.assertNotIn('src="http', page)
        with (output / "assets-summary.csv").open(newline="") as stream:
            self.assertEqual(next(csv.DictReader(stream))["label"], "'=FICTIONAL_FORMULA")
        with (output / "storage-mounts.csv").open(newline="") as stream:
            self.assertEqual(next(csv.DictReader(stream))["target"], "'=FORMULA")


if __name__ == "__main__":
    unittest.main()
