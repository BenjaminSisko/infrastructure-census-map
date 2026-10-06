"""Offline, evidence-bounded storage normalization and administration summaries.

No network calls or wall clock are used. All relationships are observations or
configuration evidence; ownership and operational context remain assertions.
"""
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import math
import re


GOOD = {"ok", "collected", "success", "partial"}
COMPLETE = {"ok", "collected", "success"}
UNKNOWN = "Unknown"
LIMITATIONS = [
    "A census is a point-in-time snapshot. Uptime is time since boot, not an availability SLA or outage history.",
    "Patch inventory and install dates do not establish patch currency. An approved applicable baseline and comparison are not supplied.",
    "Configured storage is not proof of an active mount, remote reachability, required business dependency, or authorization.",
    "Provider identity uses exact inventory IDs, names, or IPs in this model. No DNS lookup or hostname expansion is performed; manual matches remain assertions.",
    "Capacity is filesystem or logical-volume evidence, not SMART, RAID, SAN fabric, backup, or restore health.",
    "Security controls, agents, services and listeners are observations, not a compliance score or proof of effective enforcement or received telemetry.",
    "Missing or failed collection is an evidence gap, not proof that an asset or service is unhealthy, offline, disconnected, or retired.",
    "Freshness is relative to the latest valid collection timestamp in this snapshot, not the time this page is opened.",
]


def numeric(value, maximum=None):
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (ValueError, TypeError, OverflowError):
        return None
    if not math.isfinite(result) or result < 0 or (maximum is not None and result > maximum):
        return None
    return int(result) if result.is_integer() else result


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.astimezone(timezone.utc) if parsed.tzinfo else None
    except (ValueError, OverflowError):
        return None


def patch_date(value):
    """Sort install dates while retaining the source's day/instant precision."""
    instant = timestamp(value)
    if instant:
        return instant, "instant"
    if isinstance(value, str) and re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        try:
            # This comparison key is never displayed as a measured UTC instant.
            return datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc), "day"
        except ValueError:
            pass
    return None, "unknown"


def ip(value):
    try:
        return str(ipaddress.ip_address(str(value).strip("[]")))
    except ValueError:
        return None


def safe_text(value):
    """Remove common credential-bearing source decorations, retaining metadata."""
    text = str(value or "").strip()
    text = re.sub(r"[\x00-\x1f\x7f]", "", text)
    text = text.split("?", 1)[0].split("#", 1)[0]
    if re.search(r"(?:credentials?|password|passwd|pass|username|user|token|secret|api[_-]?key|access[_-]?key)\s*=", text, re.I):
        return "[omitted: credential-bearing source]"
    match = re.match(r"^(?P<prefix>[A-Za-z][A-Za-z0-9+.-]*://|//|\\\\)(?P<authority>[^/\\]*)(?P<path>.*)$", text)
    if match:
        authority = match.group("authority").rsplit("@", 1)[-1]
        if not re.fullmatch(r"(?:[A-Za-z0-9_.-]+|\[[A-Za-z0-9:.%_-]+\])(?::\d+)?", authority):
            return "[omitted: unsafe source]"
        return match.group("prefix") + authority + match.group("path")
    if "@" in text.split("/", 1)[0]:
        text = text.rsplit("@", 1)[-1]
    return text


def remote_source(source, fstype):
    """Return canonical provider/path for NFS/SMB only; local binds stay local."""
    source = safe_text(source)
    fstype = str(fstype or "").lower()
    if fstype in {"cifs", "smb", "smbfs"}:
        path = re.sub(r"^(?:smb|cifs)://", "//", source, flags=re.I).replace("\\", "/")
        if not path.startswith("//"):
            return None
        pieces = path[2:].split("/")
        if len(pieces) < 2 or not pieces[0] or not pieces[1]:
            return None
        provider = pieces[0].strip("[]").lower().rstrip(".")
        if not valid_provider(provider):
            return None
        provider = ip(provider) or provider
        display = "[" + provider + "]" if ":" in provider else provider
        return provider, "//" + display + "/" + "/".join(pieces[1:]).rstrip("/"), "cifs"
    if fstype in {"nfs", "nfs4"}:
        match = re.fullmatch(r"(\[[^\]]+\]|[^/]+):(/.*)", source)
        if not match:
            return None
        provider = match.group(1).strip("[]").lower().rstrip(".")
        if not valid_provider(provider):
            return None
        provider = ip(provider) or provider
        display = "[" + provider + "]" if ":" in provider else provider
        return provider, display + ":" + match.group(2), fstype
    return None


def valid_provider(value):
    return bool(ip(value) or re.fullmatch(r"[a-z0-9_][a-z0-9_.-]*", value, re.I))


def mount_records(data, reference):
    """Flatten findmnt children and normalized list records, preserving pointers."""
    if isinstance(data, dict):
        entries = data.get("filesystems", [])
        prefix = reference + "/filesystems"
    else:
        entries, prefix = data, reference
    for index, item in enumerate(entries if isinstance(entries, list) else []):
        if not isinstance(item, dict):
            continue
        pointer = prefix + "/" + str(index)
        yield item, pointer
        if isinstance(item.get("children"), list):
            yield from mount_records(item["children"], pointer + "/children")


def sanitize_storage_host(host):
    """Whitelist derived storage metadata; raw sealed host files are untouched."""
    def finite_json(value):
        if isinstance(value, float) and not math.isfinite(value):
            return None
        if isinstance(value, dict):
            return {key: finite_json(child) for key, child in value.items()}
        if isinstance(value, list):
            return [finite_json(child) for child in value]
        return value
    clone = finite_json(host)
    def clean_mount(row):
        result = {key: safe_text(row[key]) for key in ("target", "source", "fstype") if key in row}
        if isinstance(row.get("children"), list):
            result["children"] = [clean_mount(child) if isinstance(child, dict) else {} for child in row["children"]]
        return result
    for name in ("mounts", "configured_mounts", "autofs"):
        entry = clone.get("sections", {}).get(name, {})
        data = entry.get("data") if isinstance(entry, dict) else None
        if isinstance(data, dict) and isinstance(data.get("filesystems"), list):
            entry["data"] = {"filesystems": [clean_mount(row) if isinstance(row, dict) else {} for row in data["filesystems"]]}
        elif isinstance(data, list):
            entry["data"] = [clean_mount(row) if isinstance(row, dict) else {} for row in data]
    entry = clone.get("sections", {}).get("smb_mappings", {})
    if isinstance(entry, dict) and isinstance(entry.get("data"), list):
        entry["data"] = [{key: safe_text(row.get(key)) for key in ("local_path", "remote_path", "status")} if isinstance(row, dict) else {}
                         for row in entry["data"]]
    entry = clone.get("sections", {}).get("disks", {})
    if isinstance(entry, dict) and isinstance(entry.get("data"), list):
        for row in entry["data"]:
            if isinstance(row, dict) and "provider_name" in row:
                row["provider_name"] = safe_text(row["provider_name"])
    return clone


def section(host, name):
    entry = host.get("sections", {}).get(name, {})
    if not isinstance(entry, dict):
        return None, "invalid"
    return (entry.get("data") if entry.get("status") in GOOD else None), str(entry.get("status", "not collected"))


def storage_topology(raw_hosts, nodes):
    names, addresses = {}, {}
    for node in list(nodes.values()):
        if node.get("external"):
            continue
        for name in (node["id"], node.get("label", "")):
            names.setdefault(str(name).lower().rstrip("."), set()).add(node["id"])
        for address in node.get("addresses", []):
            addresses.setdefault(address, set()).add(node["id"])
    rows, edges = [], []
    for host, reference in raw_hosts:
        asset_id = host["asset_id"]
        platform = host["platform"]
        if platform not in ("linux", "windows"):
            continue
        active, active_status = section(host, "mounts" if platform == "linux" else "smb_mappings")
        configured, configured_status = section(host, "configured_mounts")
        seen = {}
        def collect(row, pointer, observed, mapping_observed=False):
            source = row.get("source", row.get("remote_path", row.get("provider_name")))
            target = safe_text(row.get("target", row.get("local_path", row.get("device_id")))) or ("(no local drive)" if platform == "windows" else "")
            fstype = row.get("fstype", "cifs" if platform == "windows" else "")
            remote = remote_source(source, fstype)
            if not remote or not target:
                return
            provider, remote_path, fstype = remote
            key = (target, remote_path, "nfs" if fstype.startswith("nfs") else fstype)
            record = seen.setdefault(key, {"provider": provider, "remote_path": remote_path, "target": target,
                                          "fstype": fstype, "evidence": [], "active_observed": False,
                                          "configured_observed": False, "mapping_observed": False,
                                          "reported_fs_types": [], "reported_mapping_statuses": []})
            if fstype not in record["reported_fs_types"]:
                record["reported_fs_types"].append(fstype)
            if mapping_observed:
                record["mapping_observed"] = True
                reported_status = safe_text(row.get("status")) or "Unknown"
                if reported_status not in record["reported_mapping_statuses"]:
                    record["reported_mapping_statuses"].append(reported_status)
            if observed:
                record["active_observed"] = True
                record["fstype"] = fstype
            elif not mapping_observed:
                record["configured_observed"] = True
            if pointer not in record["evidence"]:
                record["evidence"].append(pointer)
        if platform == "linux":
            for row, pointer in mount_records(active, reference + "#/sections/mounts/data"):
                collect(row, pointer, True)
        else:
            for index, row in enumerate(active if isinstance(active, list) else []):
                if isinstance(row, dict):
                    collect(row, reference + "#/sections/smb_mappings/data/" + str(index), str(row.get("status", "")).upper() == "OK", True)
            # Win32_LogicalDisk provider_name is current-account mapping evidence.
            disks, disk_status = section(host, "disks")
            for index, row in enumerate(disks if isinstance(disks, list) else []):
                if isinstance(row, dict) and row.get("provider_name"):
                    collect(row, reference + "#/sections/disks/data/" + str(index), False, True)
        for row, pointer in mount_records(configured, reference + "#/sections/configured_mounts/data"):
            collect(row, pointer, False)
        autofs, autofs_status = section(host, "autofs")
        for row, pointer in mount_records(autofs, reference + "#/sections/autofs/data"):
            collect(row, pointer, False)
        for key, row in sorted(seen.items()):
            provider = row["provider"]
            candidates = sorted(addresses.get(ip(provider), set()) if ip(provider) else names.get(provider, set()))
            if len(candidates) == 1:
                target_id = candidates[0]
                target_node = nodes[target_id]
                label_basis = target_node.get("field_provenance", {}).get("label", "")
                manual_match = target_node.get("source_kind") == "manual" or (not ip(provider) and provider != target_id.lower() and label_basis not in ("", "census", "inventory alias"))
                basis = "manual assertion" if manual_match else target_node.get("address_provenance", {}).get(provider, "census identity") if ip(provider) else "census identity"
                identity_evidence = label_basis if manual_match and label_basis else target_node.get("evidence", "")
            else:
                target_id = ("ambiguous:" if candidates else "storage:") + provider
                basis = "ambiguous" if candidates else "unresolved"
                identity_evidence = "Unknown"
                if target_id not in nodes:
                    nodes[target_id] = {"id": target_id, "label": provider, "platform": "external", "addresses": [provider] if ip(provider) else [],
                                        "os": UNKNOWN, "domain": "", "collected_at": UNKNOWN, "evidence": "", "external": True, "candidates": candidates}
            observed = row["active_observed"]
            state = ("active" if configured_status in COMPLETE else "configuration_unknown") if observed else ("configured_only" if row["configured_observed"] and active_status in COMPLETE and not row["mapping_observed"] else "unknown")
            row["reported_fs_types"].sort()
            row["reported_mapping_statuses"].sort()
            row.update(asset_id=asset_id, provider_asset_id=target_id, identity_basis=basis, provider_identity_evidence=identity_evidence,
                       mount_state=state, collection_status={"active": active_status, "configured": configured_status})
            rows.append(row)
            mapping_observed = row["mapping_observed"]
            edge = {"source": asset_id, "target": target_id, "kind": "storage_mount", "status": "observed" if observed or mapping_observed else "configured",
                    "source_origin": "mount observation" if observed else "mapping observation" if mapping_observed else "configuration evidence", "protocol": "nfs" if row["fstype"].startswith("nfs") else "smb",
                    "remote_port": None, "remote_path": row["remote_path"], "mount_target": row["target"], "fstype": row["fstype"], "mount_state": state,
                    "remote_address": provider if ip(provider) else None, "remote_name": provider,
                    "target_resolution_basis": basis, "target_identity_evidence": identity_evidence,
                    "purpose": "Remote filesystem mount observation" if observed else "Remote filesystem mapping observation; activity unconfirmed" if mapping_observed else "Remote filesystem configuration; activity unconfirmed",
                    "evidence": sorted(row["evidence"])}
            edge["id"] = hashlib.sha256(json.dumps(edge, sort_keys=True).encode()).hexdigest()[:16]
            edges.append(edge)
    return rows, edges


def observation(host, reference, name, value=None):
    data, status = section(host, name)
    return {"status": "observed" if status in GOOD and data is not None else "unknown", "value": data if value is None else value,
            "collection_status": status, "evidence": [reference + "#/sections/" + name]}


def dashboard_model(model, raw_hosts, warning_percent=80, critical_percent=90):
    warning = numeric(warning_percent, 100)
    critical = numeric(critical_percent, 100)
    if warning is None or critical is None or warning >= critical:
        raise ValueError("Capacity thresholds require 0 <= warning < critical <= 100")
    host_index = {host["asset_id"]: (host, reference) for host, reference in raw_hosts}
    valid_times = [timestamp(host.get("collected_at")) for host, _ in raw_hosts]
    valid_times = [value for value in valid_times if value]
    snapshot = max(valid_times) if valid_times else None
    assets, capacity, findings = [], [], []
    def finding(asset_id, severity, category, title, detail, evidence):
        item = {"asset_id": asset_id, "severity": severity, "category": category, "title": title, "detail": detail, "evidence": evidence}
        item["id"] = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()[:16]
        findings.append(item)
    for node in model["nodes"]:
        if node.get("external"):
            continue
        asset_id = node["id"]
        host, reference = host_index.get(asset_id, ({"sections": {}}, node.get("evidence", "Unknown")))
        identity, _ = section(host, "identity")
        identity = identity if isinstance(identity, dict) else {}
        uptime, _ = section(host, "uptime")
        uptime = uptime if isinstance(uptime, dict) else {}
        memory, _ = section(host, "memory")
        memory = memory if isinstance(memory, dict) else {}
        total, available = numeric(memory.get("total_bytes")), numeric(memory.get("available_bytes"))
        percent = round(available / total * 100, 2) if total and available is not None and available <= total else None
        services, service_status = section(host, "services")
        services = [row for row in services if isinstance(row, dict)] if isinstance(services, list) else []
        failed = sorted({str(row.get("name") or UNKNOWN) for row in services if str(row.get("active", row.get("state", ""))).lower() == "failed" or str(row.get("sub", "")).lower() == "failed"})
        failed_data, failed_status = section(host, "failed_services")
        if isinstance(failed_data, list):
            failed.extend(str(row.get("name") or UNKNOWN) for row in failed_data if isinstance(row, dict))
        failed = sorted(set(failed))
        reboot, reboot_status = section(host, "reboot_pending")
        reboot_value = reboot.get("pending") if isinstance(reboot, dict) else None
        reboot_value = reboot_value if isinstance(reboot_value, bool) else None
        patch, patch_status = section(host, "patch_inventory")
        hotfixes, hotfix_status = section(host, "hotfixes")
        latest_date, patch_precision, patch_description, patch_refs = None, "unknown", UNKNOWN, []
        candidates = []
        if isinstance(patch, dict):
            if patch_date(patch.get("latest_package_install_at"))[0]:
                candidates.append((patch_date(patch["latest_package_install_at"])[0], patch["latest_package_install_at"], "Latest observed package installation", patch_date(patch["latest_package_install_at"])[1]))
            for row in patch.get("installed_kernels", []) if isinstance(patch.get("installed_kernels"), list) else []:
                if isinstance(row, dict) and patch_date(row.get("installed_at"))[0]:
                    candidates.append((patch_date(row["installed_at"])[0], row["installed_at"], "Installed kernel " + str(row.get("version") or UNKNOWN), patch_date(row["installed_at"])[1]))
            patch_refs.append(reference + "#/sections/patch_inventory")
        for row in hotfixes if isinstance(hotfixes, list) else []:
            if isinstance(row, dict) and patch_date(row.get("installed_at"))[0]:
                candidates.append((patch_date(row["installed_at"])[0], row["installed_at"], "Installed hotfix " + str(row.get("id") or UNKNOWN), patch_date(row["installed_at"])[1]))
        if isinstance(hotfixes, list):
            patch_refs.append(reference + "#/sections/hotfixes")
        if candidates:
            _, latest_date, patch_description, patch_precision = max(candidates)
        controls = {}
        for name in ("selinux", "firewall", "time_sync", "audit"):
            data, status = section(host, name)
            # Bound display to metadata; collector text is never interpreted as commands.
            controls[name] = observation(host, reference, name, data if isinstance(data, (str, bool, list, dict)) else UNKNOWN)
            if controls[name]["status"] == "unknown":
                controls[name]["value"] = UNKNOWN
        presence = sorted({str(row.get("name") or UNKNOWN) for row in services})
        agents = [name for name in presence if re.search(r"wazuh|ossec|auditbeat|filebeat|winlogbeat|sysmon|splunk|elastic-agent|zabbix", name, re.I)]
        controls["service_presence"] = {"status": "observed" if service_status in GOOD else "unknown", "names": presence, "evidence": [reference + "#/sections/services"]}
        controls["agent"] = {"status": "observed" if service_status in GOOD else "unknown", "names": agents, "value": "Presence only; enrollment and received telemetry unknown" if agents else "No matching service observed" if service_status in GOOD else UNKNOWN, "evidence": [reference + "#/sections/services"]}
        listeners = []
        for name in ("tcp", "udp"):
            data, status = section(host, name)
            for index, row in enumerate(data if isinstance(data, list) else []):
                if not isinstance(row, dict) or (name == "tcp" and str(row.get("state", "")).upper() not in {"LISTEN", "LISTENING"}):
                    continue
                port = numeric(row.get("local_port"), 65535)
                if port is None or not port or not ip(str(row.get("local_address", "")).split("%", 1)[0]):
                    continue
                listeners.append({"protocol": name, "address": str(row["local_address"]), "port": port,
                                  "process": str(row.get("process") or UNKNOWN), "evidence": [reference + "#/sections/" + name + "/data/" + str(index)]})
        controls["listeners"] = {"status": "observed" if any(section(host, name)[1] in GOOD for name in ("tcp", "udp")) else "unknown", "items": listeners, "evidence": [reference + "#/sections/tcp", reference + "#/sections/udp"]}
        context = []
        for entry in node.get("manual_information", []):
            fields = entry.get("fields", {})
            for field in ("owner", "criticality", "role", "notes"):
                if field in fields:
                    context.append({"field": field, "value": fields[field], **{key: entry.get(key, "Not supplied") for key in ("source", "reviewed_at", "evidence")}})
            for field, value in sorted(fields.get("attributes", {}).items()):
                context.append({"field": field, "value": value, **{key: entry.get(key, "Not supplied") for key in ("source", "reviewed_at", "evidence")}})
        backup_context = [entry for entry in context if "backup" in entry["field"].lower() or "restore" in entry["field"].lower()]
        collected = timestamp(node.get("collected_at"))
        age = int((snapshot - collected).total_seconds()) if snapshot and collected else None
        gap_sections = sorted({gap["section"] for gap in model["gaps"] if gap["asset_id"] == asset_id})
        successful = sorted(name for name, entry in host["sections"].items() if isinstance(entry, dict) and entry.get("status") in GOOD)
        row = {key: node.get(key, UNKNOWN) for key in ("label", "platform", "collected_at", "os", "source_kind", "role", "evidence")}
        row.update(asset_id=asset_id, addresses=node.get("addresses", []), owner=node.get("owner") or UNKNOWN, criticality=node.get("criticality") or UNKNOWN,
                   uptime_seconds=numeric(uptime.get("uptime_seconds")), boot_time=uptime.get("boot_time") if timestamp(uptime.get("boot_time")) else identity.get("last_boot_utc") if timestamp(identity.get("last_boot_utc")) else UNKNOWN,
                   memory_available_percent=percent, kernel=identity.get("kernel") or identity.get("os_build") or UNKNOWN,
                   patch_evidence={"status": "unknown", "reason": "No approved applicable baseline and comparison supplied; install evidence is not currency", "evidence": patch_refs},
                   latest_patch_observation={"status": "observed" if candidates else "unknown", "observed_at": latest_date, "precision": patch_precision, "description": patch_description, "evidence": patch_refs},
                   reboot_pending={"status": "observed" if reboot_status in GOOD and reboot_value is not None else "unknown", "value": reboot_value, "evidence": [reference + "#/sections/reboot_pending"]},
                   failed_services={"status": "observed" if service_status in GOOD or failed_status in GOOD else "unknown", "names": failed, "evidence": [reference + "#/sections/services", reference + "#/sections/failed_services"]},
                   security=controls, freshness={"age_seconds": age, "status": "unknown" if age is None else "older_snapshot" if age > 86400 else "within_snapshot_day"},
                   coverage={"status": "not collected" if asset_id not in host_index else "partial" if gap_sections else "collected", "collected_sections": successful, "gap_sections": gap_sections},
                   context=context, backup_attestation={"status": "manual assertion" if backup_context else "unknown", "entries": backup_context, "value": "Attributed context supplied; restoration not measured" if backup_context else UNKNOWN},
                   storage_consumer_count=len({mount["asset_id"] for mount in model.get("storage_mounts", []) if mount["provider_asset_id"] == asset_id and mount["active_observed"]}))
        assets.append(row)
        if failed:
            finding(asset_id, "warning", "services", "Failed service state observed", ", ".join(failed) + "; the snapshot does not establish business impact.", row["failed_services"]["evidence"])
        if reboot_value:
            finding(asset_id, "warning", "reboot", "Reboot pending indication", "Local reboot indicators were observed; review the approved maintenance process.", row["reboot_pending"]["evidence"])
        if gap_sections:
            finding(asset_id, "info", "coverage", "Collection evidence gaps", ", ".join(gap_sections) + "; asset/service health is unknown for these gaps.", [reference])
        if age is not None and age > 86400:
            finding(asset_id, "info", "freshness", "Older collection within snapshot", str(age) + " seconds before latest collection; no live freshness assertion.", [reference])
        cap_data, cap_status = section(host, "storage_capacity" if node.get("platform") == "linux" else "disks")
        for index, item in enumerate(cap_data if isinstance(cap_data, list) else []):
            if not isinstance(item, dict):
                continue
            if node.get("platform") == "linux" and str(item.get("fstype", "")).lower() not in {"ext2", "ext3", "ext4", "xfs", "btrfs", "zfs", "f2fs", "jfs", "reiserfs", "vfat", "exfat", "ntfs", "ntfs3", "ufs"}:
                continue
            if node.get("platform") == "windows" and (numeric(item.get("drive_type")) != 3 or item.get("provider_name")):
                continue
            total = numeric(item.get("total_bytes", item.get("size_bytes")))
            available = numeric(item.get("available_bytes", item.get("free_bytes")))
            used = numeric(item.get("used_bytes"))
            if used is None and total is not None and available is not None and available <= total:
                used = total - available
            used_percent = numeric(item.get("used_percent"), 100)
            if used_percent is None and total and used is not None and used <= total:
                used_percent = round(used / total * 100, 2)
            invalid_bytes = any(field in item and numeric(item[field]) is None for field in ("total_bytes", "size_bytes", "used_bytes", "available_bytes", "free_bytes"))
            if invalid_bytes or not total or (available is not None and available > total) or (used is not None and used > total) or (available is not None and used is not None and available + used > total):
                used_percent = None
            status = "unknown" if used_percent is None else "critical" if used_percent >= critical else "warning" if used_percent >= warning else "ok"
            cap = {"asset_id": asset_id, "target": safe_text(item.get("target", item.get("device_id"))) or UNKNOWN,
                   "fstype": str(item.get("fstype", item.get("filesystem")) or UNKNOWN), "total_bytes": total, "used_bytes": used, "available_bytes": available,
                   "used_percent": used_percent, "inodes_total": numeric(item.get("inodes_total")), "inodes_free": numeric(item.get("inodes_free")),
                   "scope": "local filesystem" if node.get("platform") == "linux" else "local logical volume", "status": status,
                   "evidence": [reference + "#/sections/" + ("storage_capacity" if node.get("platform") == "linux" else "disks") + "/data/" + str(index)]}
            capacity.append(cap)
            if status in {"warning", "critical"}:
                finding(asset_id, status, "capacity", "Filesystem capacity " + status, cap["target"] + " is " + str(used_percent) + "% used; threshold " + str(critical if status == "critical" else warning) + "%. No device health inference.", cap["evidence"])
    mounts = model.get("storage_mounts", [])
    for mount in mounts:
        if mount["identity_basis"] in {"unresolved", "ambiguous", "manual assertion"}:
            finding(mount["asset_id"], "info", "storage_identity", "Storage provider identity needs review", mount["provider"] + ": " + mount["identity_basis"] + ".", mount["evidence"])
        if mount["mount_state"] != "active":
            finding(mount["asset_id"], "info", "storage_evidence", "Storage mount " + mount["mount_state"].replace("_", " "), mount["target"] + "; absence from active evidence does not prove an outage or disconnected storage.", mount["evidence"])
    assets.sort(key=lambda row: row["asset_id"])
    capacity.sort(key=lambda row: (row["asset_id"], row["target"], row["fstype"]))
    findings.sort(key=lambda row: ({"critical": 0, "warning": 1, "info": 2}[row["severity"]], row["asset_id"], row["id"]))
    expected = len([row for row in assets if row["source_kind"] == "census"])
    returned = len(host_index)
    summary = {"snapshot_at": snapshot.isoformat() if snapshot else UNKNOWN, "asset_count": len(assets), "collected_asset_count": returned,
               "expected_asset_count": expected, "collection_gap_count": len(model["gaps"]), "assets_with_gaps": len({gap["asset_id"] for gap in model["gaps"]}),
               "unknown_owner_count": sum(row["owner"] == UNKNOWN for row in assets), "unknown_criticality_count": sum(row["criticality"] == UNKNOWN for row in assets),
               "active_storage_mount_count": sum(row["active_observed"] for row in mounts), "configured_only_storage_mount_count": sum(row["mount_state"] == "configured_only" for row in mounts),
               "storage_provider_count": len({row["provider_asset_id"] for row in mounts}), "capacity_warning_count": sum(row["status"] == "warning" for row in capacity),
               "capacity_critical_count": sum(row["status"] == "critical" for row in capacity), "finding_count": len(findings),
               "coverage": {"returned": returned, "expected": expected, "percent": round(returned / expected * 100, 2) if expected else None},
               "capacity_thresholds": {"warning_percent": warning, "critical_percent": critical}, "freshness_basis": "relative to latest collection timestamp"}
    return {"schema_version": 1, "summary": summary, "assets": assets, "storage_mounts": mounts, "storage_capacity": capacity,
            "findings": findings, "limitations": list(LIMITATIONS)}
