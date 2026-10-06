#!/usr/bin/env python3
"""Normalize census evidence and render offline maps. Collected text is data only."""
import argparse
import csv
import hashlib
import html
import ipaddress
import json
from pathlib import Path
import re
import sys

try:
    from jinja2 import Environment, FileSystemLoader, select_autoescape
except ImportError:
    sys.exit("Census map requires Jinja2 on the reporting controller. Use the prepared offline Python environment.")


def canonical_ip(value):
    try:
        return str(ipaddress.ip_address(str(value).split("%", 1)[0]))
    except ValueError:
        return None


def digest(value):
    return hashlib.sha256(value.encode()).hexdigest()[:16]


def section(host, name):
    entry = host.get("sections", {}).get(name, {})
    return entry.get("data") if entry.get("status") in ("ok", "collected", "success", "partial") else None


def addresses(data):
    """Accept Linux ip -j, Windows Get-NetIPAddress, and normalized interfaces."""
    result = set()
    for item in data if isinstance(data, list) else []:
        if not isinstance(item, dict):
            continue
        values = [item.get("IPAddress"), item.get("ip_address"), item.get("address")]
        values += [a.get("local") for a in item.get("addr_info", []) if isinstance(a, dict)]
        values += item.get("addresses", []) if isinstance(item.get("addresses"), list) else []
        for family in ("ipv4", "ipv6"):
            nested = item.get(family, [])
            values += [nested] if isinstance(nested, dict) else nested if isinstance(nested, list) else []
        for value in values:
            if isinstance(value, dict):
                value = value.get("address") or value.get("ip")
            parsed = canonical_ip(value)
            if parsed and not ipaddress.ip_address(parsed).is_loopback:
                result.add(parsed)
    return sorted(result)


def load_manual(path):
    if not path:
        return {"schema_version": 1, "assets": [], "relationships": []}
    text = Path(path).read_text(encoding="utf-8")
    if Path(path).suffix.lower() in (".yml", ".yaml"):
        try:
            import yaml
        except ImportError as exc:
            raise ValueError("Manual YAML needs PyYAML on the reporting controller; JSON is also supported") from exc
        try:
            document = yaml.safe_load(text)
        except yaml.YAMLError as exc:
            raise ValueError("Invalid manual YAML") from exc
    else:
        document = json.loads(text)
    if not isinstance(document, dict) or document.get("schema_version") != 1:
        raise ValueError("Manual context requires schema_version: 1")
    if set(document) - {"schema_version", "assets", "relationships"}:
        raise ValueError("Unknown manual context field; use assets and relationships")
    for key in ("assets", "relationships"):
        if not isinstance(document.get(key, []), list):
            raise ValueError(f"Manual {key} must be a list")
    return document


def manual_details(item, reference):
    return {"evidence": reference, "source": str(item.get("source") or item.get("source_reference") or "Needs Validation"),
            "entered_by": str(item.get("entered_by") or "Not supplied"),
            "reviewed_at": str(item.get("reviewed_at") or "Not supplied")}


def string_keys(value):
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("attributes require string mapping keys")
        if set(value) & {'__proto__', 'constructor', 'prototype'}:
            raise ValueError('attributes contain a reserved browser key')
        for child in value.values():
            string_keys(child)
    elif isinstance(value, list):
        for child in value:
            string_keys(child)


def apply_manual_assets(nodes, document, filename, conflicts):
    seen = set()
    keys = ("owner", "role", "description", "location", "criticality", "asset_type", "notes", "attributes")
    for number, item in enumerate(document.get("assets", [])):
        if not isinstance(item, dict):
            raise ValueError(f"Manual asset {number} must be an object")
        if set(item) - ({"id", "platform", "label", "os", "domain", "addresses", "source", "entered_by", "reviewed_at"} | set(keys)):
            raise ValueError(f"Manual asset {number}: unknown field")
        asset_id = item.get("id")
        if not isinstance(asset_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", asset_id):
            raise ValueError(f"Manual asset {number} requires a safe id")
        if asset_id in seen:
            raise ValueError(f"Duplicate manual asset id {asset_id}")
        seen.add(asset_id)
        platform = item.get("platform")
        if platform is not None and platform not in ("linux", "windows", "network", "infrastructure"):
            raise ValueError(f"Manual asset {asset_id}: unsupported platform")
        for field in ("label", "os", "domain", "source", "entered_by", "reviewed_at") + tuple(k for k in keys if k != "attributes"):
            if field in item and not isinstance(item[field], str):
                raise ValueError(f"Manual asset {asset_id}: {field} must be text")
        if "attributes" in item:
            if not isinstance(item["attributes"], dict):
                raise ValueError(f"Manual asset {asset_id}: attributes must be a mapping")
            try:
                json.dumps(item["attributes"], allow_nan=False)
                string_keys(item["attributes"])
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Manual asset {asset_id}: attributes must contain JSON-compatible values") from exc
        supplied_addresses = item.get("addresses", [])
        if not isinstance(supplied_addresses, list) or any(not isinstance(a, str) or re.search(r'[\s%/]', a) or not canonical_ip(a) for a in supplied_addresses):
            raise ValueError(f"Manual asset {asset_id}: addresses must be a list of IP addresses")
        supplied_addresses = sorted({canonical_ip(a) for a in supplied_addresses})
        reference = f"{filename}#/assets/{number}"
        details = manual_details(item, reference)
        context = {key: item[key] for key in keys if key in item}
        context.update({key: item[key] for key in ("label", "os", "domain", "platform") if key in item})
        context["addresses"] = supplied_addresses
        if asset_id not in nodes:
            nodes[asset_id] = {
                "id": asset_id, "label": item.get("label") or asset_id,
                "platform": platform or "infrastructure", "os": item.get("os") or "Unknown",
                "domain": item.get("domain") or "", "addresses": supplied_addresses,
                "address_provenance": {address: "manual assertion" for address in supplied_addresses},
                "collected_at": "Not collected", "evidence": reference, "external": False,
                "source_kind": "manual", "field_provenance": {}, "manual_information": []}
        node = nodes[asset_id]
        node["manual_information"].append({**details, "fields": context})
        # Entered context enriches measured facts. Conflicting measured values stay intact.
        for field in ("label", "os", "domain", "platform"):
            if field not in item:
                continue
            actual = node.get(field)
            unknown = actual in (None, "", "Unknown") or (field == "label" and actual == asset_id and node.get("field_provenance", {}).get(field) != "census")
            if unknown:
                node[field] = item[field]
                node["field_provenance"][field] = reference
            elif actual != item[field]:
                conflicts.append({"asset_id": asset_id, "field": field, "collected_value": actual,
                                  "manual_value": item[field], "evidence": reference,
                                  "status": "Needs Validation"})
        for field, value in context.items():
            if field in keys:
                node[field] = value
                node["field_provenance"][field] = reference
        if node["source_kind"] == "census":
            unobserved = sorted(set(supplied_addresses) - set(node["addresses"]))
            if unobserved:
                conflicts.append({"asset_id": asset_id, "field": "addresses",
                                  "collected_value": node["addresses"], "manual_value": unobserved,
                                  "evidence": reference, "status": "Needs Validation",
                                  "reason": "manual addresses not observed; retained as assertions only"})


def validate_hosting(edges):
    graph = {}
    for edge in edges:
        if edge.get("relationship_type") == "hosts":
            graph.setdefault(edge["source"], []).append(edge["target"])
    visited, active = set(), set()
    def visit(node):
        if node in active:
            raise ValueError("Manual hosts relationships contain a cycle")
        if node in visited:
            return
        active.add(node)
        for target in graph.get(node, []):
            visit(target)
        active.remove(node)
        visited.add(node)
    for node in graph:
        visit(node)


def normalize(evidence=None, declared=None, manual=None):
    document = load_manual(manual)
    if evidence and not (Path(evidence) / "hosts").is_dir():
        raise ValueError("Evidence directory must contain a hosts folder; omit --evidence for manual-only maps")
    paths = sorted((Path(evidence) / "hosts").glob("*.json")) if evidence else []
    expected_path = Path(evidence) / 'expected-assets.json' if evidence else None
    expected_scope = []
    if expected_path and expected_path.is_file():
        expected_scope = json.loads(expected_path.read_text(encoding='utf-8')).get('expected_assets', [])
        if not isinstance(expected_scope, list) or any(not isinstance(asset, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,127}', asset) for asset in expected_scope):
            raise ValueError('Invalid expected asset scope')
    if not paths and not document.get("assets") and not expected_scope:
        raise ValueError("No host evidence found: expected <evidence>/hosts/*.json")
    nodes, relationships, gaps, raw_hosts, conflicts = {}, {}, [], [], []
    for path in paths:
        try:
            host = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"Invalid host JSON {path.name}: {exc}") from exc
        if not isinstance(host, dict) or host.get("schema_version") != 1:
            raise ValueError(f"{path.name}: expected schema_version 1")
        asset_id, platform = host.get("asset_id"), host.get("platform")
        if not isinstance(asset_id, str) or not asset_id.strip():
            raise ValueError(f"{path.name}: asset_id is required")
        if asset_id != path.stem:
            raise ValueError(f"{path.name}: filename must match asset_id {asset_id!r}")
        if asset_id in nodes:
            raise ValueError(f"Duplicate asset_id {asset_id!r}")
        if platform not in ("linux", "windows", "network"):
            raise ValueError(f"{path.name}: platform must be linux, windows, or network")
        if not isinstance(host.get("sections"), dict):
            raise ValueError(f"{path.name}: sections must be an object")
        identity = section(host, "identity") or {}
        if not isinstance(identity, dict):
            identity = {}
        host_addresses = addresses(section(host, "interfaces"))
        provenance = {address: "interface observation" for address in host_addresses}
        management_address = canonical_ip(identity.get("management_address"))
        if management_address and management_address not in provenance:
            host_addresses.append(management_address)
            provenance[management_address] = "inventory management address"
        nodes[asset_id] = {
            "id": asset_id, "label": str(identity.get("hostname") or asset_id),
            "platform": platform, "addresses": sorted(host_addresses), "address_provenance": provenance,
            "os": str(identity.get("os") or identity.get("os_name") or "Unknown"),
            "domain": str(identity.get("domain") or ""),
            "collected_at": str(host.get("collected_at") or "Unknown"),
            "evidence": f"hosts/{path.name}", "external": False,
            "source_kind": "census", "manual_information": [],
            "field_provenance": {"label": "census" if identity.get("hostname") else "inventory alias",
                                 "os": "census" if identity.get("os") or identity.get("os_name") else "unknown"},
        }
        for name, value in host["sections"].items():
            if not isinstance(value, dict) or value.get("status") not in ("ok", "collected", "success"):
                status = value.get("status", "missing") if isinstance(value, dict) else "invalid"
                gaps.append({"asset_id": asset_id, "section": name, "status": str(status),
                             "evidence": f"hosts/{path.name}"})
        expected = ("identity", "interfaces", "neighbors" if platform == "network" else "tcp")
        for name in expected:
            if name not in host["sections"]:
                gaps.append({"asset_id": asset_id, "section": name, "status": "not collected",
                             "evidence": f"hosts/{path.name}"})
        raw_hosts.append((host, f"hosts/{path.name}"))

    for asset_id in sorted(set(expected_scope) - set(nodes)):
        nodes[asset_id] = {'id': asset_id, 'label': asset_id, 'platform': 'infrastructure',
                          'asset_type': 'Uncollected inventory asset', 'role': 'No host record returned',
                          'addresses': [], 'address_provenance': {}, 'os': 'Unknown', 'domain': '',
                          'collected_at': 'Not returned', 'evidence': 'expected-assets.json',
                          'external': False, 'source_kind': 'census', 'manual_information': [],
                          'field_provenance': {'label': 'inventory alias', 'os': 'unknown', 'platform': 'unknown'}}
        gaps.append({'asset_id': asset_id, 'section': 'collection', 'status': 'missing host record', 'evidence': 'expected-assets.json'})

    census_nodes = json.loads(json.dumps(list(nodes.values())))
    census_details = {host['asset_id']: {'evidence': reference, 'collector': host.get('collector', {}),
                                       'collected_at': host.get('collected_at'), 'sections': host['sections']}
                      for host, reference in raw_hosts}
    apply_manual_assets(nodes, document, Path(manual).name if manual else "manual-context", conflicts)
    ip_index, name_index = {}, {}
    for node in nodes.values():
        for address in node["addresses"]:
            ip_index.setdefault(address, []).append(node["id"])
        for name in (node["id"], node["label"]):
            name_index.setdefault(name.lower().rstrip("."), set()).add(node["id"])

    def external(label, kind="address", candidates=None):
        node_id = f"{kind}:{label}"
        if node_id not in nodes:
            nodes[node_id] = {"id": node_id, "label": label, "platform": "external",
                              "addresses": [label] if canonical_ip(label) else [],
                              "os": "Unknown", "domain": "", "collected_at": "Unknown",
                              "evidence": "", "external": True, "candidates": candidates or []}
        return node_id

    def add_edge(source, target, kind, evidence, **details):
        key = json.dumps([source, target, kind, details], sort_keys=True)
        edge_id = digest(key)
        if edge_id not in relationships:
            relationships[edge_id] = {"id": edge_id, "source": source, "target": target,
                                      "kind": kind, "status": "observed", "evidence": [], **details}
        if evidence not in relationships[edge_id]["evidence"]:
            relationships[edge_id]["evidence"].append(evidence)

    for host, evidence in raw_hosts:
        asset_id = host["asset_id"]
        tcp = section(host, "tcp")
        for number, connection in enumerate(tcp if isinstance(tcp, list) else []):
            if not isinstance(connection, dict):
                continue
            state = str(connection.get("state", "")).upper()
            if state not in ("ESTAB", "ESTABLISHED"):
                continue
            remote = canonical_ip(connection.get("remote_address"))
            local = canonical_ip(connection.get("local_address"))
            if not remote:
                gaps.append({"asset_id": asset_id, "section": "tcp", "status": "invalid remote address",
                             "evidence": f"{evidence}#/sections/tcp/data/{number}"})
                continue
            candidates = sorted(ip_index.get(remote, []))
            if ipaddress.ip_address(remote).is_loopback:
                target = asset_id
            elif len(candidates) == 1:
                target = candidates[0]
            else:
                target = external(remote, "ambiguous" if candidates else "address", candidates)
            status = "Needs Validation" if len(candidates) > 1 else "observed"
            basis = nodes[target].get("address_provenance", {}).get(remote, "unknown") if len(candidates) == 1 else "ambiguous" if candidates else "unresolved"
            add_edge(asset_id, target, "observed_connection",
                     f"{evidence}#/sections/tcp/data/{number}",
                     local_address=local, local_port=connection.get("local_port"),
                     remote_address=remote, remote_port=connection.get("remote_port"),
                     protocol="tcp", process=str(connection.get("process") or "Unknown"),
                     source_origin="unknown", status=status,
                     target_resolution_basis=basis,
                     target_identity_evidence=nodes[target].get("evidence", ""),
                     purpose="Unconfirmed application relationship")
        neighbors = section(host, "neighbors")
        if isinstance(neighbors, dict):
            neighbors = neighbors.get("ansible_net_neighbors", neighbors)
            for interface, entries in sorted(neighbors.items()):
                for number, neighbor in enumerate(entries if isinstance(entries, list) else []):
                    if not isinstance(neighbor, dict):
                        continue
                    name = str(neighbor.get("host") or neighbor.get("hostname") or neighbor.get("system_name") or neighbor.get("neighbor") or "Unknown neighbor")
                    candidates = sorted(name_index.get(name.lower().rstrip("."), []))
                    target = candidates[0] if len(candidates) == 1 else external(name, "neighbor", candidates)
                    target_node = nodes[target]
                    matched_manual_label = target_node.get("field_provenance", {}).get("label", "") not in ("", "census", "inventory alias")
                    basis = ("manual assertion" if target_node.get("source_kind") == "manual" or matched_manual_label
                             else "census identity" if len(candidates) == 1 else "ambiguous" if candidates else "unresolved")
                    identity_reference = target_node.get("field_provenance", {}).get("label") if matched_manual_label else target_node.get("evidence", "")
                    pointer = str(interface).replace("~", "~0").replace("/", "~1")
                    add_edge(asset_id, target, "physical_neighbor",
                             f"{evidence}#/sections/neighbors/data/{pointer}/{number}",
                             local_interface=str(interface), remote_interface=str(neighbor.get("port") or neighbor.get("neighbor_interface") or neighbor.get("remote_port") or "Unknown"),
                             target_resolution_basis=basis, target_identity_evidence=identity_reference,
                             remote_name=name,
                             purpose="LLDP/CDP neighbor observation", source_origin="unknown")

    if declared:
        declared_document = json.loads(Path(declared).read_text(encoding="utf-8"))
        entries = declared_document.get("dependencies", []) if isinstance(declared_document, dict) else declared_document
        if not isinstance(entries, list):
            raise ValueError("Declared file must contain a dependencies list")
        for number, edge in enumerate(entries):
            if not isinstance(edge, dict):
                raise ValueError(f"Declared dependency {number} must be an object")
            source, target = edge.get("source"), edge.get("target")
            if source not in nodes or target not in nodes:
                raise ValueError(f"Declared dependency {number}: source/target must identify collected assets")
            add_edge(source, target, "declared_dependency", f"{Path(declared).name}#/dependencies/{number}",
                     status="declared", protocol=str(edge.get("protocol") or "unknown"),
                     remote_port=edge.get("port"), purpose=str(edge.get("purpose") or "Declared dependency"),
                     source_origin="declared", authority=str(edge.get("authority") or "Needs Validation"))

    census_nodes.extend(json.loads(json.dumps([node for node in nodes.values() if node.get('external')])))
    evidence_relationships = json.loads(json.dumps(list(relationships.values())))
    for number, edge in enumerate(document.get("relationships", [])):
        if not isinstance(edge, dict):
            raise ValueError(f"Manual relationship {number} must be an object")
        if set(edge) - {"source", "target", "kind", "purpose", "protocol", "port", "source_reference", "entered_by", "reviewed_at", "notes"}:
            raise ValueError(f"Manual relationship {number}: unknown field")
        source, target, kind = edge.get("source"), edge.get("target"), edge.get("kind")
        if not isinstance(source, str) or not isinstance(target, str) or source not in nodes or target not in nodes:
            raise ValueError(f"Manual relationship {number}: source/target must identify a census or manual asset")
        if kind not in ("hosts", "depends_on", "uses_storage", "backs_up", "managed_by"):
            raise ValueError(f"Manual relationship {number}: unsupported kind")
        if kind == "hosts" and source == target:
            raise ValueError("An asset cannot host itself")
        for field in ("purpose", "protocol", "source_reference", "entered_by", "reviewed_at", "notes"):
            if field in edge and not isinstance(edge[field], str):
                raise ValueError(f"Manual relationship {number}: {field} must be text")
        if not edge.get("purpose", "").strip():
            raise ValueError(f"Manual relationship {number}: purpose is required")
        port = edge.get("port")
        if 'port' in edge and (isinstance(port, bool) or not isinstance(port, int) or not 1 <= port <= 65535):
            raise ValueError(f"Manual relationship {number}: invalid port")
        if kind == "hosts" and ("port" in edge or "protocol" in edge):
            raise ValueError("Hosting is placement; put network ports on a separate dependency relationship")
        reference = f"{Path(manual).name}#/relationships/{number}"
        add_edge(source, target, "manual_relationship", reference, relationship_type=kind,
                 status="manual_declared", source_origin="manual", protocol=edge.get("protocol"), remote_port=port,
                 purpose=str(edge.get("purpose") or kind.replace("_", " ")),
                 notes=str(edge.get("notes") or ""), manual_information=manual_details(edge, reference))
    validate_hosting(relationships.values())

    context = {'schema_version': 1, 'assets': document.get('assets', []), 'relationships': document.get('relationships', [])}
    workspace_data = {'census': census_details, 'manual_context': context, 'evidence_relationships': evidence_relationships}
    return {"schema_version": 1, "renderer_version": "0.3.1", "nodes": sorted(nodes.values(), key=lambda node: node["id"]),
            "census_nodes": census_nodes, "census_details": census_details,
            "evidence_relationships": evidence_relationships, "manual_context": context,
            "workspace_id": hashlib.sha256(json.dumps(workspace_data, sort_keys=True).encode()).hexdigest()[:24],
            "relationships": sorted(relationships.values(), key=lambda edge: edge["id"]),
            "gaps": sorted(gaps, key=lambda gap: (gap["asset_id"], gap["section"], gap["status"])),
            "conflicts": conflicts, "collection_mode": "mixed" if evidence and manual else "census" if evidence else "manual_only",
            "manual_source": {"path": str(manual), "sha256": hashlib.sha256(Path(manual).read_bytes()).hexdigest()} if manual else None,
            "interpretation": "Observed endpoints do not establish TCP initiator, purpose, authorization, or criticality."}


def draw_svg(model):
    platforms = [p for p in ("infrastructure", "linux", "windows", "network", "external")
                 if any(node["platform"] == p for node in model["nodes"])]
    rows = {p: [n for n in model["nodes"] if n["platform"] == p] for p in platforms}
    width, height = max(900, len(platforms) * 300 + 60), max(len(v) for v in rows.values()) * 110 + 200
    positions = {node["id"]: (30 + column * 300, 125 + row * 110)
                 for column, platform in enumerate(platforms) for row, node in enumerate(rows[platform])}
    esc = lambda text: html.escape(str(text), quote=True)
    svg = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" role="img" aria-label="Infrastructure evidence map">',
           '<style>text{font-family:Arial,sans-serif} .node{cursor:pointer} .edge{fill:none;stroke-width:2} .edge.selected{stroke-width:5} .dim{opacity:.12}</style>',
           f'<rect width="{width}" height="{height}" fill="#f4f7fb"/>',
           '<text x="30" y="30" font-size="24" font-weight="bold" fill="#233753">Infrastructure census map</text>',
           '<defs><marker id="manual-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10 z" fill="#7c3aed"/></marker></defs>',
           f'<text x="30" y="54" font-size="12" fill="#526981">{esc("Manual information only; census not collected." if model.get("collection_mode") == "manual_only" else "Observed relationships retain evidence; manual context retains source and review date.")}</text>']
    for column, platform in enumerate(platforms):
        svg.append(f'<text x="{45 + column * 300}" y="90" font-size="18" fill="#233753">{esc(platform.upper())}</text>')
    colors = {"observed_connection": "#b46b14", "physical_neighbor": "#3974b7", "declared_dependency": "#487c56", "manual_relationship": "#7c3aed"}
    for edge in model["relationships"]:
        x1, y1 = positions[edge["source"]]
        x2, y2 = positions[edge["target"]]
        if x1 == x2:
            d = f"M{x1+265},{y1+38} C{x1+290},{y1+38} {x2+290},{y2+38} {x2+265},{y2+38}"
        else:
            a, b = (x1 + 265, x2) if x2 > x1 else (x1, x2 + 265)
            mid = (a + b) / 2
            d = f"M{a},{y1+38} C{mid},{y1+38} {mid},{y2+38} {b},{y2+38}"
        marker = ' marker-end="url(#manual-arrow)"' if edge['kind'] == 'manual_relationship' else ''
        svg.append(f'<path class="edge" data-edge="{esc(edge["id"])}" d="{d}" stroke="{colors[edge["kind"]]}" stroke-dasharray="{("6 4" if edge["kind"] == "observed_connection" else "none")}"{marker}><title>{esc(edge.get("relationship_type", edge["kind"]))}: {esc(edge["purpose"])}</title></path>')
    for node in model["nodes"]:
        x, y = positions[node["id"]]
        svg.append(f'<g class="node" data-node="{esc(node["id"])}" tabindex="0" role="button" aria-label="{esc(node["label"])}"><title>{esc(node["id"])}</title><rect x="{x}" y="{y}" width="265" height="80" rx="10" fill="white" stroke="#899bb4"/>')
        caption = (node.get("asset_type", "") + " · " + node["os"]) if node.get("asset_type") else node["os"]
        for offset, text, size in [(25, node["label"][:35], 14), (47, ", ".join(node["addresses"])[:37] or "Address unknown", 11), (66, caption[:40], 10)]:
            svg.append(f'<text x="{x+12}" y="{y+offset}" font-size="{size}" fill="#233753">{esc(text)}</text>')
        svg.append('</g>')
    svg.append(f'<text x="30" y="{height-24}" font-size="12" fill="#b46b14">Amber dashed: observed TCP</text>')
    svg.append(f'<text x="300" y="{height-24}" font-size="12" fill="#3974b7">Blue: physical neighbor</text>')
    svg.append(f'<text x="560" y="{height-24}" font-size="12" fill="#487c56">Green: declared dependency</text>')
    svg.append(f'<text x="30" y="{height-6}" font-size="12" fill="#7c3aed">Purple: manual relationship; arrow direction follows its declared meaning</text>')
    svg.append('</svg>')
    return "".join(svg)


def write_products(model, output):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    (output / "map.json").write_text(json.dumps(model, indent=2) + "\n", encoding="utf-8")
    svg = draw_svg(model)
    (output / "dependency-map.svg").write_text(svg, encoding="utf-8")
    environment = Environment(loader=FileSystemLoader(Path(__file__).parent / "templates"),
                              autoescape=select_autoescape(default=True))
    static = Path(__file__).parent / 'static'
    workbench_js = (static / 'workbench.js').read_text(encoding='utf-8')
    workbench_css = (static / 'workbench.css').read_text(encoding='utf-8')
    document = environment.get_template("map.html.j2").render(model=model, svg=svg,
                                                             workbench_js=workbench_js, workbench_css=workbench_css)
    (output / "dependency-map.html").write_text(document, encoding="utf-8")
    columns = ["source", "target", "kind", "relationship_type", "status", "protocol", "local_port", "remote_port", "source_origin", "target_resolution_basis", "target_identity_evidence", "purpose", "evidence"]
    with (output / "dependency-matrix.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns, extrasaction="ignore", lineterminator="\n")
        writer.writeheader()
        for edge in model["relationships"]:
            row = {key: edge.get(key, "") for key in columns}
            row["evidence"] = "; ".join(edge["evidence"])
            # Prevent a workbook from evaluating a collected value as a formula.
            writer.writerow({key: ("'" + value if isinstance(value, str) and re.match(r"^[\s\x00]*[=+\-@]", value) else value) for key, value in row.items()})
    lines = ["# Infrastructure evidence report", "", f"Assets: {len(model['nodes'])}; relationships: {len(model['relationships'])}; collection gaps: {len(model['gaps'])}; manual conflicts: {len(model.get('conflicts', []))}.", "", "Mode: " + model.get("collection_mode", "census"), "", model["interpretation"], "", "## Collection gaps", ""]
    lines.extend(html.escape(f"- {gap['asset_id']}: {gap['section']} — {gap['status']} ({gap['evidence']})".replace("\n", " ")) for gap in model["gaps"])
    lines += ["", "## Manual information conflicts", ""]
    lines.extend(html.escape(f"- {item['asset_id']}: {item['field']} — collected={item['collected_value']}; manual={item['manual_value']} ({item['evidence']})".replace("\n", " ")) for item in model.get("conflicts", []))
    if model.get("manual_source"):
        lines += ["", "## Manual source", "", html.escape(json.dumps(model["manual_source"]))]
    (output / "collection-report.md").write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence")
    parser.add_argument("--output", required=True)
    parser.add_argument("--declared")
    parser.add_argument("--manual", help="Manual YAML/JSON assets, context and relationships")
    args = parser.parse_args()
    try:
        model = normalize(args.evidence, args.declared, args.manual)
        write_products(model, args.output)
    except (ValueError, OSError, KeyError, TypeError) as exc:
        parser.exit(2, f"Census map error: {exc}\n")
    print(f"Rendered {len(model['nodes'])} assets and {len(model['relationships'])} relationships to {args.output}")


if __name__ == "__main__":
    main()
