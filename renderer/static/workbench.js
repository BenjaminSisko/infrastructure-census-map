(function () {
  "use strict";

  const base = JSON.parse(document.getElementById("model-data").textContent);
  const $ = id => document.getElementById(id);
  const clone = value => JSON.parse(JSON.stringify(value));
  const NS = "http://www.w3.org/2000/svg";
  const platforms = ["linux", "windows", "network", "infrastructure"];
  const relationshipKinds = ["hosts", "depends_on", "uses_storage", "backs_up", "managed_by"];
  const annotationKeys = ["owner", "role", "description", "location", "criticality", "asset_type", "notes", "attributes"];
  const assetKeys = ["id", "platform", "label", "os", "domain", "addresses", "source", "entered_by", "reviewed_at", ...annotationKeys];
  const edgeKeys = ["source", "target", "kind", "purpose", "protocol", "port", "source_reference", "entered_by", "reviewed_at", "notes"];
  const measuredNodes = clone(base.census_nodes || base.nodes.filter(node => node.source_kind !== "manual"));
  const evidenceEdges = clone(base.evidence_relationships || base.relationships.filter(edge => edge.source_origin !== "manual"));
  const measuredIds = new Set(measuredNodes.map(node => node.id));
  const storageKey = "census-workbench:1:" + (base.workspace_id || "default");
  let context = clone(base.manual_context || {schema_version: 1, assets: [], relationships: []});
  let positions = {}, selected = null, activeTab = "details", focused = false;
  let nodes = [], edges = [], conflicts = [], lookup = new Map();
  let history = [], storageAvailable = true, dirtyForm = false, modal = null;
  let view = {x: 0, y: 0, scale: 1}, drag = null, initializedFit = false;
  let visibleNodes = [], visibleEdges = [], viewport = null;
  const layers = {observed: true, neighbor: true, manual: true, declared: true, storage: true};

  function element(tag, className, text) {
    const item = document.createElement(tag);
    if (className) item.className = className;
    if (text !== undefined) item.textContent = String(text);
    return item;
  }
  function svgElement(tag, attrs, text) {
    const item = document.createElementNS(NS, tag);
    Object.entries(attrs || {}).forEach(([name, value]) => item.setAttribute(name, String(value)));
    if (text !== undefined) item.textContent = String(text);
    return item;
  }
  function showNotice(message, error) {
    $("notice").textContent = message;
    $("notice").classList.toggle("error", Boolean(error));
    $("notice").hidden = !message;
  }
  function plainObject(value) {
    return value !== null && typeof value === "object" && !Array.isArray(value);
  }
  function safeValues(value) {
    if (typeof value === "number" && !Number.isFinite(value)) throw new Error("Attributes must contain finite numbers.");
    if (Array.isArray(value)) value.forEach(safeValues);
    else if (plainObject(value)) Object.entries(value).forEach(([key, item]) => {
      if (["__proto__", "constructor", "prototype"].includes(key)) throw new Error("Reserved attribute key: " + key);
      safeValues(item);
    });
    else if (value !== null && !["string", "number", "boolean"].includes(typeof value)) throw new Error("Attributes must contain JSON values.");
  }
  function canonicalIP(value) {
    if (typeof value !== "string" || !value.trim() || /[\s%/]/.test(value)) return null;
    if (/^\d+\.\d+\.\d+\.\d+$/.test(value)) {
      const parts = value.split(".");
      return parts.every(part => Number(part) <= 255 && (part === "0" || !part.startsWith("0"))) ? parts.map(Number).join(".") : null;
    }
    if (!value.includes(":")) return null;
    try { const parsed = new URL("http://[" + value + "]/"); return parsed.hostname.slice(1, -1).toLowerCase(); }
    catch (_) { return null; }
  }
  function textFields(item, fields, label) {
    fields.forEach(field => {
      if (Object.hasOwn(item, field) && typeof item[field] !== "string") throw new Error(label + ": " + field + " must be text.");
    });
  }
  function validateContext(input) {
    if (!plainObject(input) || input.schema_version !== 1) throw new Error("Context must be an object with schema_version: 1.");
    if (Object.keys(input).some(key => !["schema_version", "assets", "relationships"].includes(key))) throw new Error("Context contains an unknown top-level field.");
    safeValues(input);
    const doc = clone(input);
    if (doc.assets === undefined) doc.assets = [];
    if (doc.relationships === undefined) doc.relationships = [];
    if (!Array.isArray(doc.assets) || !Array.isArray(doc.relationships)) throw new Error("Context requires assets and relationships arrays.");
    const ids = new Set(measuredIds), manualIds = new Set();
    doc.assets.forEach((asset, index) => {
      if (!plainObject(asset) || Object.keys(asset).some(key => !assetKeys.includes(key))) throw new Error("Asset " + index + " contains an unknown field.");
      if (typeof asset.id !== "string" || !/^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$/.test(asset.id)) throw new Error("Asset " + index + " requires an ID containing only letters, numbers, dots, hyphens and underscores.");
      if (manualIds.has(asset.id)) throw new Error("Duplicate asset ID: " + asset.id);
      manualIds.add(asset.id); ids.add(asset.id);
      if (asset.platform !== undefined && !platforms.includes(asset.platform)) throw new Error("Unsupported platform for " + asset.id);
      textFields(asset, assetKeys.filter(key => !["id", "platform", "addresses", "attributes"].includes(key)), "Asset " + asset.id);
      if (asset.addresses !== undefined) {
        if (!Array.isArray(asset.addresses) || asset.addresses.some(address => !canonicalIP(address))) throw new Error("Asset " + asset.id + ": addresses must be valid IP addresses.");
        asset.addresses = [...new Set(asset.addresses.map(canonicalIP))];
      }
      if (asset.attributes !== undefined) {
        if (!plainObject(asset.attributes)) throw new Error("Attributes for " + asset.id + " must be a JSON object.");
        safeValues(asset.attributes);
      }
    });
    const hosting = new Map();
    doc.relationships.forEach((edge, index) => {
      if (!plainObject(edge) || Object.keys(edge).some(key => !edgeKeys.includes(key))) throw new Error("Relationship " + index + " contains an unknown field.");
      if (typeof edge.source !== "string" || typeof edge.target !== "string" || !ids.has(edge.source) || !ids.has(edge.target)) throw new Error("Relationship " + index + ": both endpoints must identify an asset.");
      if (!relationshipKinds.includes(edge.kind)) throw new Error("Unsupported relationship kind: " + edge.kind);
      textFields(edge, edgeKeys.filter(key => key !== "port"), "Relationship " + index);
      if (!edge.purpose || !edge.purpose.trim()) throw new Error("A relationship needs a purpose in your own words.");
      if (edge.port !== undefined && (!Number.isInteger(edge.port) || edge.port < 1 || edge.port > 65535)) throw new Error("Port must be an integer from 1 to 65535.");
      if (edge.kind === "hosts") {
        if (Object.hasOwn(edge, "port") || Object.hasOwn(edge, "protocol")) throw new Error("Hosting is placement. Put ports and protocols on a separate dependency.");
        if (edge.source === edge.target) throw new Error("An asset cannot host itself.");
        if (!hosting.has(edge.source)) hosting.set(edge.source, []);
        hosting.get(edge.source).push(edge.target);
      }
    });
    const visited = new Set(), active = new Set();
    function visit(id) {
      if (active.has(id)) throw new Error("Hosting relationships contain a cycle.");
      if (visited.has(id)) return;
      active.add(id); (hosting.get(id) || []).forEach(visit); active.delete(id); visited.add(id);
    }
    hosting.forEach((_, id) => visit(id));
    return doc;
  }

  function canonicalNodeAddresses(node) { return (node.addresses || []).map(canonicalIP).filter(Boolean); }
  function derive() {
    const map = new Map(measuredNodes.map(node => [node.id, clone(node)]));
    conflicts = [];
    context.assets.forEach((asset, index) => {
      const measured = map.get(asset.id);
      const node = measured || {id: asset.id, label: asset.label || asset.id, platform: asset.platform || "infrastructure", os: asset.os || "Unknown", addresses: asset.addresses || [], address_provenance: Object.fromEntries((asset.addresses || []).map(address => [canonicalIP(address), "manual assertion"])), source_kind: "manual", external: false, collected_at: "Not collected", evidence: "manual-context.json#/assets/" + index};
      const reference = "manual-context.json#/assets/" + index;
      node.field_provenance = node.field_provenance || {};
      if (measured) {
        ["label", "os", "domain", "platform"].forEach(field => {
          if (asset[field] !== undefined && asset[field] !== measured[field]) {
            const unknown = [undefined, null, "", "Unknown"].includes(measured[field]) || (field === "label" && measured.label === asset.id && node.field_provenance.label !== "census");
            if (unknown) { node[field] = asset[field]; node.field_provenance[field] = reference; }
            else conflicts.push({asset_id: asset.id, field, collected_value: measured[field], manual_value: asset[field], status: "Needs Validation"});
          }
        });
        const unobserved = (asset.addresses || []).filter(address => !canonicalNodeAddresses(measured).includes(canonicalIP(address)));
        if (unobserved.length) conflicts.push({asset_id: asset.id, field: "addresses", collected_value: measured.addresses, manual_value: unobserved, status: "Needs Validation"});
      }
      annotationKeys.forEach(field => { if (asset[field] !== undefined) { node[field] = clone(asset[field]); node.field_provenance[field] = reference; } });
      node.manual_information = [{fields: clone(asset), source: asset.source || "Needs Validation", entered_by: asset.entered_by || "Unknown", reviewed_at: asset.reviewed_at || "Not supplied", evidence: "manual-context.json#/assets/" + index}];
      map.set(asset.id, node);
    });
    const addressIndex = new Map();
    const nameIndex = new Map();
    map.forEach(node => {
      if (node.external || node.source_kind === "external") return;
      canonicalNodeAddresses(node).forEach(address => {
        if (!addressIndex.has(address)) addressIndex.set(address, []);
        addressIndex.get(address).push(node.id);
      });
      [node.id, node.label].filter(Boolean).forEach(name => {
        const normalized = String(name).replace(/\.$/, "").toLowerCase();
        if (!nameIndex.has(normalized)) nameIndex.set(normalized, []);
        if (!nameIndex.get(normalized).includes(node.id)) nameIndex.get(normalized).push(node.id);
      });
    });
    function endpoint(address, name, original) {
      const addressMatches = addressIndex.get(canonicalIP(address)) || [];
      const nameMatches = nameIndex.get(String(name || "").replace(/\.$/, "").toLowerCase()) || [];
      const matches = addressMatches.length ? addressMatches : nameMatches;
      if (matches.length === 1) {
        const chosen = map.get(matches[0]);
        const manualLabel = !addressMatches.length && String(chosen.field_provenance?.label || "").startsWith("manual-context.json");
        return {id: chosen.id, resolution: addressMatches.length ? (chosen.address_provenance || {})[canonicalIP(address)] || (chosen.source_kind === "manual" ? "manual assertion" : "interface observation") : chosen.source_kind === "manual" || manualLabel ? "manual name assertion" : "collected identity", identity: manualLabel ? chosen.field_provenance.label : chosen.evidence || ""};
      }
      if (!address && !name && map.has(original)) return {id: original, resolution: "recorded endpoint", identity: map.get(original).evidence || ""};
      const token = address || name || original || "unknown";
      const id = "endpoint-" + [...String(token)].map(character => character.codePointAt(0).toString(16)).join("-");
      if (!map.has(id)) map.set(id, {id, label: matches.length > 1 ? "Ambiguous: " + token : token, platform: "external", os: "Unknown", addresses: address ? [address] : [], source_kind: "external", external: true, collected_at: "Observation only", evidence: "Connection endpoint", candidates: matches, manual_information: []});
      return {id, resolution: matches.length > 1 ? "ambiguous identity; needs validation" : "unresolved endpoint; needs validation", identity: ""};
    }
    edges = evidenceEdges.map((original, index) => {
      const edge = clone(original);
      if (edge.remote_address || edge.remote_name) {
        const remote = canonicalIP(edge.remote_address);
        const loopback = remote === "::1" || (remote && remote.startsWith("127."));
        const resolved = loopback ? {id: edge.source, resolution: "loopback observation", identity: map.get(edge.source)?.evidence || ""} : endpoint(edge.remote_address, edge.remote_name, edge.target);
        edge.target = resolved.id; edge.target_resolution_basis = resolved.resolution; edge.target_identity_evidence = resolved.identity;
      } else if (!map.has(edge.target)) {
        edge.target = endpoint(null, null, edge.target).id;
        edge.target_resolution_basis = "missing declared endpoint; needs validation";
      }
      if (!map.has(edge.source)) edge.source = endpoint(null, null, edge.source).id;
      edge.id = edge.id || "evidence-" + index;
      return edge;
    });
    context.relationships.forEach((edge, index) => edges.push({...clone(edge), id: "manual-" + index, kind: "manual_relationship", relationship_type: edge.kind, remote_port: edge.port, manual_index: index, status: "manual_declared", source_origin: "manual", evidence: ["manual-context.json#/relationships/" + index], manual_information: {source: edge.source_reference || "Needs Validation", entered_by: edge.entered_by || "Unknown", reviewed_at: edge.reviewed_at || "Not supplied"}}));
    // Pre-manual endpoint snapshots no longer used by a current edge are hidden.
    const endpoints = new Set(edges.flatMap(edge => [edge.source, edge.target]));
    nodes = [...map.values()].filter(node => !node.external || endpoints.has(node.id)).sort((a, b) => a.id.localeCompare(b.id));
    lookup = new Map(nodes.map(node => [node.id, node]));
    if (selected && !lookup.has(selected)) selected = null;
    assignPositions();
  }

  function assignPositions() {
    const hosting = new Map(), children = new Set();
    context.relationships.filter(edge => edge.kind === "hosts").forEach(edge => {
      if (!hosting.has(edge.source)) hosting.set(edge.source, []);
      hosting.get(edge.source).push(edge.target); children.add(edge.target);
    });
    const roots = nodes.filter(node => !children.has(node.id));
    roots.sort((a, b) => (hosting.has(b.id) - hosting.has(a.id)) || (a.external - b.external) || a.id.localeCompare(b.id));
    const gap = 65, cache = new Map();
    // Measure each complete hosting group before positioning neighboring groups.
    // Wide guest lists wrap into rows instead of overlapping another hypervisor.
    function measure(id) {
      if (cache.has(id)) return cache.get(id);
      const children = (hosting.get(id) || []).filter(child => lookup.has(child)), rows = [];
      for (let index = 0; index < children.length; index += 3) {
        const ids = children.slice(index, index + 3), blocks = ids.map(measure);
        rows.push({ids, width: blocks.reduce((sum, block) => sum + block.width, 0) + gap * (ids.length - 1), height: Math.max(...blocks.map(block => block.height))});
      }
      const block = {width: Math.max(215, ...rows.map(row => row.width)), height: 105 + rows.reduce((sum, row) => sum + gap + row.height, 0), rows};
      cache.set(id, block); return block;
    }
    const placed = new Set();
    function place(id, left, top) {
      if (placed.has(id)) return;
      placed.add(id);
      const block = measure(id), candidate = {x:left + (block.width - 215) / 2, y:top};
      if (!positions[id] || !Number.isFinite(positions[id].x) || !Number.isFinite(positions[id].y)) {
        while (Object.entries(positions).some(([other, point]) => other !== id && lookup.has(other) && candidate.x < point.x + 230 && candidate.x + 230 > point.x && candidate.y < point.y + 120 && candidate.y + 120 > point.y)) candidate.y += 170;
        positions[id] = candidate;
      }
      let y = top + 105 + gap;
      block.rows.forEach(row => {
        let x = left + (block.width - row.width) / 2;
        row.ids.forEach(child => {place(child, x, y); x += measure(child).width + gap;});
        y += row.height + gap;
      });
    }
    let top = 80;
    for (let index = 0; index < roots.length; index += 2) {
      const row = roots.slice(index, index + 2); let left = 80;
      row.forEach(node => {place(node.id, left, top); left += measure(node.id).width + gap;});
      top += Math.max(...row.map(node => measure(node.id).height)) + gap;
    }
  }
  function saveDraft() {
    try {
      localStorage.setItem(storageKey, JSON.stringify({manual_context: context, positions, saved_at: new Date().toISOString()}));
      storageAvailable = true;
      $("save-state").textContent = "Browser draft saved · export to keep a file";
    } catch (_) {
      storageAvailable = false;
      $("save-state").textContent = "Browser storage unavailable · export to keep edits";
      showNotice("Browser storage is unavailable. Export context before closing this page; your entered changes are currently in memory.", true);
    }
  }
  function commit(next, message) {
    const validated = validateContext(next);
    history.push({context: clone(context), positions: clone(positions)});
    if (history.length > 30) history.shift();
    context = validated; dirtyForm = false; derive(); render(); saveDraft();
    if (message && storageAvailable) showNotice(message);
    return clone(context);
  }
  function saveAsset(id, changes) {
    if (!lookup.has(id)) throw new Error("Unknown asset: " + id);
    if (lookup.get(id).external) throw new Error("Create a stable entered asset for this unresolved endpoint before adding notes or details.");
    if (!plainObject(changes) || Object.keys(changes).some(key => !assetKeys.includes(key) || key === "id")) throw new Error("Changes contain a field that cannot be edited.");
    safeValues(changes);
    const next = clone(context), index = next.assets.findIndex(asset => asset.id === id);
    const item = { ...(index >= 0 ? next.assets[index] : {id}), ...clone(changes), id };
    if (index >= 0) next.assets[index] = item; else next.assets.push(item);
    return commit(next, "Details and notes saved to this browser. Export context to update your local agent or repository.");
  }
  function addAsset(asset) {
    if (!plainObject(asset) || lookup.has(asset.id)) throw new Error("Choose a new, unique asset ID.");
    safeValues(asset);
    const next = clone(context); next.assets.push(clone(asset));
    commit(next, "Asset added. Add its notes and connections in the inspector.");
    selectHost(asset.id); fitMap(); return clone(lookup.get(asset.id));
  }
  function addRelationship(edge) {
    safeValues(edge);
    const next = clone(context); next.relationships.push(clone(edge));
    commit(next, "Entered relationship saved. Its purpose and source remain visible.");
    return next.relationships.length - 1;
  }
  function editRelationship(index, edge) {
    if (!Number.isInteger(index) || index < 0 || index >= context.relationships.length) throw new Error("Unknown relationship.");
    safeValues(edge);
    const next = clone(context); next.relationships[index] = clone(edge); commit(next, "Relationship updated.");
  }
  function deleteRelationship(index) {
    if (!Number.isInteger(index) || index < 0 || index >= context.relationships.length) throw new Error("Unknown relationship.");
    const next = clone(context); next.relationships.splice(index, 1); commit(next, "Relationship removed. Undo restores it.");
  }
  function removeAsset(id) {
    const next = clone(context), index = next.assets.findIndex(asset => asset.id === id);
    if (index < 0) throw new Error("This asset has no entered context to remove.");
    next.assets.splice(index, 1);
    if (!measuredIds.has(id)) next.relationships = next.relationships.filter(edge => edge.source !== id && edge.target !== id);
    commit(next, measuredIds.has(id) ? "Entered context removed. Collected evidence remains available. Undo restores your changes." : "Entered asset and its manual links removed. Undo restores them.");
  }
  function undo() {
    if (!history.length) return false;
    const previous = history.pop(); context = previous.context; positions = previous.positions; dirtyForm = false;
    derive(); render(); saveDraft(); showNotice("Previous context restored."); return true;
  }
  function exportContext() { return JSON.stringify(context, null, 2) + "\n"; }
  function importContext(input) {
    const parsed = typeof input === "string" ? JSON.parse(input) : input;
    return commit(parsed, "Context imported and applied. Measured census evidence is preserved.");
  }
  function download(name, contents, type) {
    const blob = new Blob([contents], {type}), url = URL.createObjectURL(blob), link = element("a");
    link.href = url; link.download = name; document.body.appendChild(link); link.click(); link.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }
  function savePending() {
    if (!dirtyForm || !selected) return true;
    try { submitAssetForm(); return true; }
    catch (error) { $("form-error").textContent = error.message; $("form-error").hidden = false; return false; }
  }
  function selectHost(id) {
    if (id && !lookup.has(id)) throw new Error("Unknown asset: " + id);
    if (!savePending()) return false;
    selected = id; renderNavigator(); renderGraph(); renderInspector();
    $("focus-host").disabled = !selected;
    return true;
  }
  function short(value, limit) { const text = String(value || ""); return text.length > limit ? text.slice(0, limit - 1) + "…" : text; }
  function layerOf(edge) {
    if (edge.kind === "storage_mount") return "storage";
    if (edge.kind === "manual_relationship" || edge.source_origin === "manual") return "manual";
    if (/neighbor/.test(edge.kind)) return "neighbor";
    if (/declared/.test(edge.kind)) return "declared";
    return "observed";
  }
  function connectedIds(id) { return new Set([id, ...edges.filter(edge => edge.source === id || edge.target === id).flatMap(edge => [edge.source, edge.target])]); }
  function filteredNodes() {
    const query = $("search").value.trim().toLowerCase(), platform = $("platform").value;
    return nodes.filter(node => (platform === "all" || node.platform === platform) && (!query || JSON.stringify(node).toLowerCase().includes(query)));
  }
  function renderNavigator() {
    const list = $("host-list"); list.replaceChildren();
    const matches = filteredNodes(); $("asset-count").textContent = matches.length;
    matches.forEach(node => {
      const button = element("button", "host-item" + (selected === node.id ? " active" : ""));
      button.type = "button"; button.dataset.hostId = node.id; button.setAttribute("aria-pressed", String(selected === node.id));
      const icons = {linux: "LX", windows: "WN", network: "NW", infrastructure: "HV", external: "?"};
      button.appendChild(element("span", "host-icon", node.collected_at === "Not returned" ? "AS" : icons[node.platform] || "AS"));
      const info = element("span", "host-text"); info.appendChild(element("span", "host-name", node.label || node.id));
      info.appendChild(element("span", "host-meta", (node.addresses || [])[0] || node.id));
      if (node.owner) info.appendChild(element("span", "host-meta", node.owner));
      if (node.notes) info.appendChild(element("span", "host-note", "● Notes recorded"));
      button.appendChild(info); button.addEventListener("click", () => selectHost(node.id)); list.appendChild(button);
    });
    if (!matches.length) list.appendChild(element("p", "empty-list", "No assets match. Clear the search, import context, or add an asset."));
  }
  function renderCounts() {
    const box = $("counts"); box.replaceChildren();
    const entries = [[nodes.length, "assets"], [edges.length, "relationships"], [context.assets.length, "entered records"], base.collection_mode === "manual_only" ? ["Not collected", "census"] : [(base.gaps || []).length, "collection gaps"]];
    entries.forEach(([number, label]) => { const item = element("span"); item.append(element("strong", "", number), document.createTextNode(" " + label)); box.appendChild(item); });
    $("gap-count").textContent = "(" + (base.gaps || []).length + ")";
    $("open-gaps").hidden = base.collection_mode === "manual_only";
    $("undo").disabled = !history.length;
    $("focus-host").disabled = !selected;
  }
  function dimensions() { const rect = $("graph-container").getBoundingClientRect(); return {width: Math.max(rect.width, 1), height: Math.max(rect.height, 1)}; }
  function updateView() {
    if (viewport) viewport.setAttribute("transform", "translate(" + view.x + " " + view.y + ") scale(" + view.scale + ")");
    $("zoom-level").textContent = Math.round(view.scale * 100) + "%";
  }
  function fitMap() {
    if (!visibleNodes.length) { view = {x: 0, y: 0, scale: 1}; updateView(); return; }
    const {width, height} = dimensions();
    const minX = Math.min(...visibleNodes.map(node => positions[node.id].x));
    const minY = Math.min(...visibleNodes.map(node => positions[node.id].y));
    const maxX = Math.max(...visibleNodes.map(node => positions[node.id].x + 215));
    const maxY = Math.max(...visibleNodes.map(node => positions[node.id].y + 105));
    const scale = Math.max(.15, Math.min(1.35, (width - 90) / Math.max(maxX - minX, 1), (height - 115) / Math.max(maxY - minY, 1)));
    view = {x: (width - (maxX - minX) * scale) / 2 - minX * scale, y: (height - (maxY - minY) * scale) / 2 - minY * scale - 12, scale};
    updateView();
  }
  function zoom(factor, x, y) {
    const size = dimensions(); x = x === undefined ? size.width / 2 : x; y = y === undefined ? size.height / 2 : y;
    const next = Math.max(.15, Math.min(3.5, view.scale * factor));
    view.x = x - (x - view.x) / view.scale * next; view.y = y - (y - view.y) / view.scale * next; view.scale = next; updateView();
  }
  function renderGraph() {
    const graph = $("graph"), size = dimensions(); graph.replaceChildren(); graph.setAttribute("viewBox", "0 0 " + size.width + " " + size.height);
    const defs = svgElement("defs");
    const pattern = svgElement("pattern", {id: "grid", width: 22, height: 22, patternUnits: "userSpaceOnUse"}); pattern.appendChild(svgElement("circle", {cx: 1, cy: 1, r: .65, fill: "#cad0c2"})); defs.appendChild(pattern);
    const shadow = svgElement("filter", {id: "node-shadow", x: "-20%", y: "-20%", width: "150%", height: "160%"}); shadow.appendChild(svgElement("feDropShadow", {dx: 0, dy: 2, stdDeviation: 2, "flood-color": "#244236", "flood-opacity": ".08"})); defs.appendChild(shadow);
    const colors = {manual: "#17675f", observed: "#a36536", neighbor: "#477383", declared: "#6c7a50", storage: "#3b6c9f"};
    ["manual", "declared", "storage"].forEach(kind => { const marker = svgElement("marker", {id: "arrow-" + kind, viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 5, markerHeight: 5, orient: "auto-start-reverse"}); marker.appendChild(svgElement("path", {d: "M 0 0 L 10 5 L 0 10 z", fill: colors[kind]})); defs.appendChild(marker); });
    graph.appendChild(defs); graph.appendChild(svgElement("rect", {width: "100%", height: "100%", fill: "url(#grid)", "data-background": "true"}));
    viewport = svgElement("g", {id: "viewport"}); graph.appendChild(viewport);
    const connected = selected ? connectedIds(selected) : null;
    visibleNodes = nodes.filter(node => !focused || !selected || connected.has(node.id));
    const visible = new Set(visibleNodes.map(node => node.id)), matches = new Set(filteredNodes().map(node => node.id));
    visibleEdges = edges.filter(edge => layers[layerOf(edge)] && visible.has(edge.source) && visible.has(edge.target) && (!focused || !selected || edge.source === selected || edge.target === selected));
    $("graph-empty").hidden = nodes.length > 0;
    $("map-title").textContent = focused && selected ? "Connections · " + short(lookup.get(selected).label, 28) : "Environment overview";
    const bundlePairs = new Map();
    visibleEdges.forEach(edge => {
      const pair = [edge.source, edge.target].sort().join("\0"); if (!bundlePairs.has(pair)) bundlePairs.set(pair, []); bundlePairs.get(pair).push(edge);
    });
    visibleEdges.forEach(edge => {
      const a = positions[edge.source], b = positions[edge.target], layer = layerOf(edge);
      if (!a || !b) return;
      const sourceCenter = {x: a.x + 107.5, y: a.y + 52.5}, targetCenter = {x: b.x + 107.5, y: b.y + 52.5};
      const dx = targetCenter.x - sourceCenter.x, dy = targetCenter.y - sourceCenter.y;
      const horizontal = Math.abs(dx) > Math.abs(dy);
      const start = {x: sourceCenter.x + (horizontal ? Math.sign(dx) * 107.5 : 0), y: sourceCenter.y + (!horizontal ? Math.sign(dy) * 52.5 : 0)};
      const end = {x: targetCenter.x - (horizontal ? Math.sign(dx) * 107.5 : 0), y: targetCenter.y - (!horizontal ? Math.sign(dy) * 52.5 : 0)};
      const siblings = bundlePairs.get([edge.source, edge.target].sort().join("\0"));
      const offset = (siblings.indexOf(edge) - (siblings.length - 1) / 2) * 25;
      const mx = (start.x + end.x) / 2 + (horizontal ? 0 : offset), my = (start.y + end.y) / 2 + (horizontal ? offset : 0);
      let pathData = "M " + start.x + " " + start.y + " Q " + mx + " " + my + " " + end.x + " " + end.y;
      if (edge.source === edge.target) pathData = "M " + (a.x + 215) + " " + (a.y + 25) + " C " + (a.x + 295) + " " + (a.y - 55) + " " + (a.x + 300) + " " + (a.y + 145) + " " + (a.x + 215) + " " + (a.y + 80);
      const group = svgElement("g", {class: "graph-edge" + (selected && edge.source !== selected && edge.target !== selected ? " dimmed" : ""), "data-edge": edge.id});
      const attrs = {class: "edge-path", d: pathData, stroke: colors[layer]};
      if (layer === "observed") attrs["stroke-dasharray"] = "5 4";
      if (layer === "storage" && edge.status !== "observed") attrs["stroke-dasharray"] = "2 4";
      if (layer === "manual" || layer === "declared" || layer === "storage") attrs["marker-end"] = "url(#arrow-" + layer + ")";
      group.appendChild(svgElement("path", attrs));
      const label = edge.relationship_type ? edge.relationship_type.replace(/_/g, " ") : layer === "storage" ? "storage · " + (edge.mount_state || edge.status || "unknown").replace(/_/g, " ") : layer === "neighbor" ? "physical neighbor" : edge.remote_port ? (edge.protocol || "tcp") + " / " + edge.remote_port : "observed";
      group.appendChild(svgElement("text", {class: "edge-label", x: mx, y: my - 6, "text-anchor": "middle"}, label));
      group.appendChild(svgElement("title", {}, (lookup.get(edge.source).label || edge.source) + (layer === "observed" || layer === "neighbor" ? " ↔ " : " → ") + (lookup.get(edge.target).label || edge.target) + "\n" + (edge.purpose || label)));
      viewport.appendChild(group);
    });
    visibleNodes.forEach(node => {
      const position = positions[node.id];
      const dim = !matches.has(node.id) || (selected && !connected.has(node.id));
      const group = svgElement("g", {class: "graph-node" + (node.id === selected ? " selected" : "") + (dim ? " dimmed" : ""), transform: "translate(" + position.x + " " + position.y + ")", "data-node": node.id, role: "button", tabindex: 0, "aria-label": "Inspect " + (node.label || node.id), "aria-pressed": String(selected === node.id)});
      group.appendChild(svgElement("rect", {class: "node-outline", width: 215, height: 105, rx: 3}));
      group.appendChild(svgElement("rect", {x: 0, y: 0, width: 4, height: 105, rx: 1, fill: node.source_kind === "manual" ? "#a36536" : node.external ? "#9b9e8b" : "#729985"}));
      group.appendChild(svgElement("text", {class: "node-platform", x: 15, y: 20}, (node.asset_type || node.platform || "asset").toUpperCase()));
      group.appendChild(svgElement("text", {class: "node-label", x: 15, y: 40}, short(node.label || node.id, 29)));
      group.appendChild(svgElement("text", {class: "node-address", x: 15, y: 57}, short((node.addresses || []).join(", ") || "Address unknown", 29)));
      group.appendChild(svgElement("text", {class: "node-role", x: 15, y: 77}, short(node.role || node.os || "Needs validation", 33)));
      const gap = (base.gaps || []).some(item => item.asset_id === node.id);
      const status = node.external ? "UNRESOLVED" : node.source_kind === "manual" ? "ENTERED CONTEXT" : "CENSUS EVIDENCE";
      group.appendChild(svgElement("text", {class: "node-status" + (node.source_kind === "manual" ? " manual" : ""), x: 15, y: 95}, status + (gap ? " · GAP" : "") + (node.notes ? " · NOTES" : "")));
      group.appendChild(svgElement("title", {}, (node.label || node.id) + "\n" + (node.owner || "Owner not recorded") + "\nClick to inspect; drag to arrange."));
      group.addEventListener("click", () => { if (!group.dataset.suppressClick) selectHost(node.id); delete group.dataset.suppressClick; });
      group.addEventListener("keydown", event => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); selectHost(node.id); } });
      viewport.appendChild(group);
    });
    updateView();
    if (!initializedFit && visibleNodes.length) { initializedFit = true; requestAnimationFrame(fitMap); }
  }

  function fact(container, label, value) {
    const row = element("div", "fact-row"); row.append(element("span", "fact-key", label), element("span", "fact-value", value || "Not recorded")); container.appendChild(row);
  }
  function field(container, label, name, value, type) {
    const wrapper = element("label", "", label), input = element(type === "textarea" ? "textarea" : "input");
    input.name = name; input.value = value || ""; if (type && type !== "textarea") input.type = type;
    wrapper.appendChild(input); container.appendChild(wrapper); return input;
  }
  function platformField(container, name, value) {
    const wrapper = element("label", "", "Platform"), select = element("select"); select.name = name;
    platforms.forEach(platform => { const option = element("option", "", platform === "infrastructure" ? "Infrastructure / hypervisor" : platform); option.value = platform; select.appendChild(option); });
    select.value = value || "infrastructure"; wrapper.appendChild(select); container.appendChild(wrapper); return select;
  }
  function renderInspector() {
    const node = lookup.get(selected), form = $("asset-form");
    form.hidden = !node; $("inspector-empty").hidden = Boolean(node);
    $("form-error").hidden = true;
    if (!node) { $("detail-title").textContent = "Choose an asset"; $("detail-subtitle").textContent = "Inspect evidence, add notes, and map relationships."; return; }
    const entry = context.assets.find(asset => asset.id === selected) || {};
    $("inspector-kind").textContent = node.external ? "UNRESOLVED ENDPOINT" : node.collected_at === "Not returned" ? "INVENTORY ONLY · NO RECORD RETURNED" : node.source_kind === "manual" ? "MANUALLY ENTERED ASSET" : "COLLECTED ASSET";
    $("detail-title").textContent = node.label || node.id;
    $("detail-subtitle").textContent = node.id + " / " + (node.platform || "asset");
    const facts = $("measured-facts"); facts.replaceChildren();
    const measured = measuredNodes.find(item => item.id === node.id) || node;
    const factsNode = node.source_kind === "manual" ? node : measured;
    fact(facts, node.source_kind === "manual" ? "Record" : "Census identity / inventory alias", factsNode.label);
    fact(facts, "OS / platform", factsNode.os);
    fact(facts, "IP addresses", (factsNode.addresses || []).join(", "));
    fact(facts, "Collected", factsNode.collected_at);
    if (node.source_kind !== "manual" && (node.label !== measured.label || node.os !== measured.os)) facts.appendChild(element("p", "small", "Display identity includes entered context. The census facts above remain unchanged; review the optional assertions below."));
    const identity = $("identity-fields"); identity.replaceChildren();
    if (node.external) {
      identity.appendChild(element("p", "small", "This is an unresolved observation. Create a stable asset with a name and ID to add notes and resolve its address."));
      const resolve = element("button", "small-button", "Create asset for this endpoint"); resolve.type = "button";
      resolve.addEventListener("click", () => addAssetModal(node)); identity.appendChild(resolve);
    } else if (node.source_kind === "manual") {
      field(identity, "Display name", "label", entry.label || node.label);
      field(identity, "Operating system", "os", entry.os || node.os);
      field(identity, "Addresses (one per line)", "addresses", (entry.addresses || []).join("\n"), "textarea");
      platformField(identity, "platform", entry.platform || node.platform);
    } else {
      const assertions = element("details", "assertion-fields"); assertions.appendChild(element("summary", "", "Optional identity assertions"));
      assertions.appendChild(element("p", "small", "Collected identity stays measured. Enter conflicting information here as an assertion for review."));
      field(assertions, "Asserted hostname / label", "label", entry.label);
      field(assertions, "Asserted operating system", "os", entry.os);
      field(assertions, "Asserted addresses (one per line)", "addresses", (entry.addresses || []).join("\n"), "textarea");
      identity.appendChild(assertions);
    }
    annotationKeys.filter(key => key !== "attributes").forEach(key => {
      const input = form.elements.namedItem(key);
      if (key === "criticality" && entry[key] && ![...input.options].some(option => option.value === entry[key])) { const option = element("option", "", entry[key]); option.value = entry[key]; input.appendChild(option); }
      input.value = entry[key] || "";
    });
    form.elements.namedItem("attributes").value = JSON.stringify(entry.attributes || {}, null, 2);
    ["source", "entered_by", "reviewed_at"].forEach(key => form.elements.namedItem(key).value = entry[key] || "");
    if (!entry.reviewed_at) form.elements.namedItem("reviewed_at").value = new Date().toISOString().slice(0, 10);
    $("remove-asset").textContent = node.source_kind === "manual" ? "Remove asset" : "Remove context";
    $("remove-asset").disabled = node.external || !context.assets.some(asset => asset.id === selected);
    form.querySelectorAll("input, select, textarea").forEach(input => input.disabled = Boolean(node.external));
    $("save-asset").disabled = Boolean(node.external);
    $("add-relationship").disabled = Boolean(node.external);
    const conflictBox = $("asset-conflicts"); conflictBox.replaceChildren();
    conflicts.filter(item => item.asset_id === selected).forEach(item => conflictBox.appendChild(element("div", "conflict-item", "Needs Validation · " + item.field + ": collected " + JSON.stringify(item.collected_value) + "; asserted " + JSON.stringify(item.manual_value))));
    renderRelationships(); renderEvidence(); switchTab(activeTab); dirtyForm = false;
  }
  function renderRelationships() {
    const box = $("relationships"); box.replaceChildren();
    const related = edges.filter(edge => edge.source === selected || edge.target === selected);
    related.forEach(edge => {
      const layer = layerOf(edge), card = element("div", "relationship-card " + layer);
      const type = edge.relationship_type || (layer === "storage" ? "Storage mount · " + edge.status : layer === "neighbor" ? "Physical neighbor" : layer === "observed" ? "Observed association" : "Declared dependency");
      const symbol = layer === "observed" || layer === "neighbor" ? " ↔ " : " → ";
      card.appendChild(element("div", "relationship-type", type.replace(/_/g, " ")));
      const heading = element("h4");
      [edge.source, edge.target].forEach((id, index) => {
        if (index) heading.appendChild(document.createTextNode(symbol));
        const button = element("button", "text-button", lookup.get(id)?.label || id); button.type = "button"; button.addEventListener("click", () => selectHost(id)); heading.appendChild(button);
      });
      card.appendChild(heading);
      if (edge.purpose) card.appendChild(element("p", "", edge.purpose));
      if (layer === "storage") card.appendChild(element("p", "small", "Mount-table evidence only: configured is not necessarily active, reachable, healthy, required or approved."));
      if (edge.remote_port) card.appendChild(element("p", "mono", (edge.protocol || "protocol unspecified") + " / " + edge.remote_port));
      if (edge.target_resolution_basis) card.appendChild(element("p", "small", "Identity: " + edge.target_resolution_basis));
      const details = edge.manual_information;
      if (details) card.appendChild(element("p", "small", "Source: " + details.source + " · " + details.entered_by + " · " + details.reviewed_at));
      else card.appendChild(element("p", "small", (edge.evidence || []).join(" · ")));
      if (edge.notes) card.appendChild(element("p", "", edge.notes));
      if (layer === "manual") {
        const actions = element("div", "relationship-actions"), edit = element("button", "text-button", "Edit"), remove = element("button", "text-button danger", "Remove");
        edit.type = remove.type = "button"; edit.addEventListener("click", () => relationshipModal(edge.manual_index)); remove.addEventListener("click", () => { if (savePending()) deleteRelationship(edge.manual_index); }); actions.append(edit, remove); card.appendChild(actions);
      } else card.appendChild(element("p", "small", layer === "declared" ? "Declared dependency · view only" : "Collected evidence · view only"));
      box.appendChild(card);
    });
    if (!related.length) box.appendChild(element("p", "small", "No relationships recorded. Add a hosting, dependency, storage, backup, or management link."));
  }
  function renderEvidence() {
    const node = lookup.get(selected), summary = $("evidence-summary"); summary.replaceChildren();
    fact(summary, "Record type", node.source_kind);
    fact(summary, "Evidence file", node.evidence);
    fact(summary, "Collection time", node.collected_at);
    const contextEntry = context.assets.find(asset => asset.id === selected);
    if (contextEntry) { fact(summary, "Entered source", contextEntry.source); fact(summary, "Entered by", contextEntry.entered_by); fact(summary, "Reviewed on", contextEntry.reviewed_at); }
    const gaps = $("gaps"); gaps.replaceChildren();
    const records = (base.gaps || []).filter(gap => gap.asset_id === selected);
    records.forEach(gap => gaps.appendChild(element("li", "", gap.section + " — " + gap.status + (gap.message ? ": " + gap.message : ""))));
    if (!records.length) gaps.appendChild(element("li", "", node.source_kind === "manual" ? "Census was not collected for this entered asset." : "No reported collection gaps for this asset."));
    $("raw-evidence").textContent = JSON.stringify({asset: node, collected_sections: (base.census_details || {})[selected] || {}, entered_context: contextEntry || null}, null, 2);
  }
  function switchTab(tab) {
    activeTab = tab;
    document.querySelectorAll(".tab").forEach(button => { const active = button.dataset.tab === tab; button.classList.toggle("active", active); button.setAttribute("aria-selected", String(active)); button.tabIndex = active ? 0 : -1; });
    ["details", "notes", "relationships", "evidence"].forEach(name => $("pane-" + name).hidden = name !== tab);
  }
  function submitAssetForm() {
    if (!selected) return;
    const form = $("asset-form"), existing = context.assets.find(asset => asset.id === selected) || {}, changes = {};
    [...annotationKeys.filter(key => key !== "attributes"), "source", "entered_by", "reviewed_at", "label", "os", "platform"].forEach(key => {
      const input = form.elements.namedItem(key);
      if (input && (input.value.trim() || Object.hasOwn(existing, key))) changes[key] = input.value;
    });
    const addressInput = form.elements.namedItem("addresses");
    if (addressInput && (addressInput.value.trim() || Object.hasOwn(existing, "addresses"))) changes.addresses = addressInput.value.split(/[\s,]+/).filter(Boolean);
    try { changes.attributes = JSON.parse(form.elements.namedItem("attributes").value || "{}"); }
    catch (_) { throw new Error("Additional attributes must be valid JSON, for example {\"cluster\": \"Compute A\"}."); }
    if (!plainObject(changes.attributes)) throw new Error("Additional attributes must be a JSON object.");
    saveAsset(selected, changes);
  }
  function render() { renderCounts(); renderNavigator(); renderGraph(); renderInspector(); }

  function openModal(title, lead) {
    closeModal();
    const previousFocus = document.activeElement, backdrop = element("div", "modal-backdrop"), dialog = element("div", "modal-dialog");
    dialog.setAttribute("role", "dialog"); dialog.setAttribute("aria-modal", "true"); dialog.setAttribute("aria-labelledby", "modal-title");
    const header = element("div", "modal-header"), heading = element("h2", "", title); heading.id = "modal-title";
    const close = element("button", "close-button", "×"); close.type = "button"; close.setAttribute("aria-label", "Close dialog"); close.addEventListener("click", closeModal); header.append(heading, close); dialog.appendChild(header);
    if (lead) dialog.appendChild(element("p", "modal-lead", lead));
    backdrop.appendChild(dialog); $("modal-root").appendChild(backdrop);
    modal = {backdrop, dialog, previousFocus};
    backdrop.addEventListener("click", event => { if (event.target === backdrop) closeModal(); });
    backdrop.addEventListener("keydown", event => {
      if (event.key === "Escape") { event.preventDefault(); closeModal(); }
      if (event.key === "Tab") {
        const focusables = [...dialog.querySelectorAll("button, input, select, textarea, [tabindex]")].filter(item => !item.disabled && item.getClientRects().length);
        if (!focusables.length) return;
        if (event.shiftKey && document.activeElement === focusables[0]) { event.preventDefault(); focusables.at(-1).focus(); }
        else if (!event.shiftKey && document.activeElement === focusables.at(-1)) { event.preventDefault(); focusables[0].focus(); }
      }
    });
    document.querySelector(".workbench").inert = true;
    close.focus();
    requestAnimationFrame(() => { if (modal && modal.dialog === dialog) (dialog.querySelector("input, textarea, select") || close).focus(); });
    return dialog;
  }
  function closeModal() {
    if (!modal) return;
    const previous = modal.previousFocus; modal.backdrop.remove(); modal = null; document.querySelector(".workbench").inert = false;
    if (previous && previous.isConnected) previous.focus();
  }
  function modalError(form, error) { const box = form.querySelector(".modal-error"); box.textContent = error.message; box.hidden = false; }
  function modalActions(form, saveText) {
    const error = element("div", "modal-error"); error.setAttribute("role", "alert"); error.hidden = true; form.appendChild(error);
    const actions = element("div", "modal-actions"), cancel = element("button", "", "Cancel"), save = element("button", "primary", saveText);
    cancel.type = "button"; cancel.addEventListener("click", closeModal); save.type = "submit"; actions.append(cancel, save); form.appendChild(actions);
  }
  function addAssetModal(seed) {
    if (!savePending()) return;
    const dialog = openModal("Add an asset", "Describe a hypervisor, server, appliance, application or storage system. You can add notes now and complete the details later."), form = element("form");
    field(form, "Stable asset ID", "id", ""); field(form, "Display name", "label", ""); platformField(form, "platform", "infrastructure");
    field(form, "Addresses (one per line, optional)", "addresses", seed && seed.external ? (seed.addresses || []).join("\n") : "", "textarea");
    field(form, "Owner / team", "owner", ""); field(form, "Your notes", "notes", "", "textarea"); field(form, "Source / reference", "source", "Operator notes");
    modalActions(form, "Add asset"); dialog.appendChild(form);
    form.addEventListener("submit", event => {
      event.preventDefault();
      try {
        const asset = {id: form.elements.id.value.trim(), label: form.elements.label.value.trim() || form.elements.id.value.trim(), platform: form.elements.platform.value, addresses: form.elements.addresses.value.split(/[\s,]+/).filter(Boolean), owner: form.elements.owner.value, notes: form.elements.notes.value, source: form.elements.source.value, reviewed_at: new Date().toISOString().slice(0, 10)};
        addAsset(asset); switchTab("notes"); closeModal();
      } catch (error) { modalError(form, error); }
    });
  }
  function relationshipModal(index) {
    if (!savePending()) return;
    const entry = index === undefined ? {source: selected || nodes[0]?.id, target: nodes.find(node => node.id !== selected)?.id, kind: "depends_on", reviewed_at: new Date().toISOString().slice(0, 10)} : clone(context.relationships[index]);
    const dialog = openModal(index === undefined ? "Add a relationship" : "Edit relationship", "Explain the connection in your own words. The arrow runs from the source asset to the target asset."), form = element("form");
    ["source", "target"].forEach(name => {
      const label = element("label", "", name === "source" ? "Source asset" : "Target asset"), select = element("select"); select.name = name;
      nodes.filter(node => !node.external).forEach(node => { const option = element("option", "", (node.label || node.id) + " [" + node.id + "]"); option.value = node.id; select.appendChild(option); });
      select.value = entry[name] || ""; label.appendChild(select); form.appendChild(label);
    });
    const kindLabel = element("label", "", "Relationship"), kindSelect = element("select"); kindSelect.name = "kind";
    const kinds = {hosts: "Hosts — hypervisor → guest", depends_on: "Depends on — consumer → required service", uses_storage: "Uses storage — consumer → storage", backs_up: "Backs up — backup system → protected asset", managed_by: "Managed by — asset → management platform"};
    relationshipKinds.forEach(kind => { const option = element("option", "", kinds[kind]); option.value = kind; kindSelect.appendChild(option); }); kindSelect.value = entry.kind; kindLabel.appendChild(kindSelect); form.appendChild(kindLabel);
    field(form, "Purpose (required)", "purpose", entry.purpose, "textarea").required = true;
    const ports = element("div", "form-pair"); field(ports, "Protocol (optional)", "protocol", entry.protocol); field(ports, "Port (optional)", "port", entry.port, "number"); form.appendChild(ports);
    const updatePorts = () => { ports.hidden = kindSelect.value === "hosts"; }; kindSelect.addEventListener("change", updatePorts); updatePorts();
    field(form, "Source / reference", "source_reference", entry.source_reference); field(form, "Notes", "notes", entry.notes, "textarea");
    const reviewer = element("div", "form-pair"); field(reviewer, "Entered by", "entered_by", entry.entered_by); field(reviewer, "Reviewed on", "reviewed_at", entry.reviewed_at, "date"); form.appendChild(reviewer);
    modalActions(form, "Save relationship"); dialog.appendChild(form);
    form.addEventListener("submit", event => {
      event.preventDefault();
      try {
        const edge = {}; ["source", "target", "kind", "purpose", "source_reference", "entered_by", "reviewed_at", "notes"].forEach(key => edge[key] = form.elements.namedItem(key).value);
        if (edge.kind !== "hosts") { if (form.elements.protocol.value.trim()) edge.protocol = form.elements.protocol.value.trim(); if (form.elements.port.value.trim()) edge.port = Number(form.elements.port.value); }
        if (index === undefined) addRelationship(edge); else editRelationship(index, edge);
        closeModal(); switchTab("relationships");
      } catch (error) { modalError(form, error); }
    });
  }
  function confirmRemoval() {
    if (!savePending() || !selected) return;
    const id = selected, measured = measuredIds.has(id);
    const dialog = openModal(measured ? "Remove entered context?" : "Remove entered asset?", measured ? "The measured census record stays available. Its entered notes and metadata will be removed. Undo can restore them." : "The entered asset and its manual relationships will be removed. Collected observations remain visible as unresolved endpoints. Undo can restore your context.");
    const form = element("form"); modalActions(form, "Remove"); dialog.appendChild(form);
    form.addEventListener("submit", event => { event.preventDefault(); try { removeAsset(id); closeModal(); } catch (error) { modalError(form, error); } });
  }
  function showGaps() {
    const dialog = openModal("Collection gaps", "Unreachable or unavailable collection is evidence of a gap, not proof that an asset was retired."); dialog.classList.add("wide");
    if (!(base.gaps || []).length) dialog.appendChild(element("p", "small", "No collection gaps were reported in this bundle."));
    (base.gaps || []).forEach(gap => { const row = element("div", "gap-row"); row.append(element("strong", "", gap.asset_id), element("span", "", gap.section + " — " + gap.status + (gap.message ? ": " + gap.message : ""))); dialog.appendChild(row); });
  }
  function exportSVG() {
    const {width, height} = dimensions(), svg = $("graph").cloneNode(true); svg.setAttribute("width", width); svg.setAttribute("height", height);
    const style = svgElement("style", {}, ".node-outline{fill:#fffefa;stroke:#c5ccc0;stroke-width:1.2}.graph-node.selected .node-outline{stroke:#17675f;stroke-width:2.5}.node-label{font:bold 12px sans-serif;fill:#273332}.node-address{font:10px monospace;fill:#717c73}.node-role{font:10px sans-serif;fill:#5e6f61}.node-status{font:8px monospace;fill:#536c61}.node-status.manual{fill:#9a6035}.node-platform{font:bold 9px monospace;fill:#48715f}.edge-label{font:9px monospace;fill:#6e786c;paint-order:stroke;stroke:#f0f1e9;stroke-width:4px}.edge-path{fill:none;stroke-width:1.8}.dimmed{opacity:.22}");
    svg.insertBefore(style, svg.firstChild); download("dependency-workspace.svg", new XMLSerializer().serializeToString(svg), "image/svg+xml");
  }
  function pointerPosition(event) { const rect = $("graph").getBoundingClientRect(); return {x: event.clientX - rect.left, y: event.clientY - rect.top}; }
  $("graph").addEventListener("pointerdown", event => {
    if (event.button !== 0) return;
    const group = event.target.closest("[data-node]"), pointer = pointerPosition(event);
    drag = group ? {kind: "node", id: group.dataset.node, start: pointer, position: {...positions[group.dataset.node]}, moved: false} : {kind: "pan", start: pointer, view: {...view}, moved: false};
    $("graph").setPointerCapture(event.pointerId); $("graph").classList.add("grabbing");
  });
  $("graph").addEventListener("pointermove", event => {
    if (!drag) return;
    const pointer = pointerPosition(event), dx = pointer.x - drag.start.x, dy = pointer.y - drag.start.y;
    if (Math.abs(dx) + Math.abs(dy) > 4) drag.moved = true;
    if (drag.kind === "pan") { view.x = drag.view.x + dx; view.y = drag.view.y + dy; updateView(); }
    else if (drag.moved) { positions[drag.id] = {x: drag.position.x + dx / view.scale, y: drag.position.y + dy / view.scale}; renderGraph(); }
  });
  function endPointer() {
    if (!drag) return;
    const previous = drag; drag = null; $("graph").classList.remove("grabbing");
    if (previous.kind === "node") {
      if (previous.moved) { const node = [...$("graph").querySelectorAll("[data-node]")].find(group => group.dataset.node === previous.id); if (node) node.dataset.suppressClick = "true"; saveDraft(); }
      else selectHost(previous.id);
    }
  }
  $("graph").addEventListener("pointerup", endPointer); $("graph").addEventListener("pointercancel", endPointer);
  $("graph").addEventListener("wheel", event => { event.preventDefault(); const pointer = pointerPosition(event); zoom(event.deltaY > 0 ? .9 : 1.1, pointer.x, pointer.y); }, {passive: false});
  $("zoom-in").addEventListener("click", () => zoom(1.2)); $("zoom-out").addEventListener("click", () => zoom(1 / 1.2)); $("fit-map").addEventListener("click", fitMap);
  $("focus-host").addEventListener("click", () => { focused = true; renderGraph(); fitMap(); });
  $("show-all").addEventListener("click", () => { focused = false; $("search").value = ""; $("platform").value = "all"; renderNavigator(); renderGraph(); fitMap(); });
  $("search").addEventListener("input", () => { renderNavigator(); renderGraph(); }); $("platform").addEventListener("change", () => { renderNavigator(); renderGraph(); });
  ["observed", "neighbor", "manual", "declared", "storage"].forEach(layer => $("layer-" + layer).addEventListener("change", event => { layers[layer] = event.target.checked; renderGraph(); }));
  document.querySelectorAll(".tab").forEach(button => {
    button.addEventListener("click", () => switchTab(button.dataset.tab));
    button.addEventListener("keydown", event => {
      if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
      event.preventDefault(); const tabs = [...document.querySelectorAll(".tab")], current = tabs.indexOf(button);
      const index = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (current + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
      switchTab(tabs[index].dataset.tab); tabs[index].focus();
    });
  });
  $("asset-form").addEventListener("input", () => { dirtyForm = true; $("save-state").textContent = "Unsaved form edits · use Save details & notes"; });
  $("asset-form").addEventListener("change", () => { dirtyForm = true; });
  $("asset-form").addEventListener("submit", event => { event.preventDefault(); try { submitAssetForm(); } catch (error) { $("form-error").textContent = error.message; $("form-error").hidden = false; } });
  $("add-host").addEventListener("click", addAssetModal); $("empty-add-host").addEventListener("click", addAssetModal);
  $("add-relationship").addEventListener("click", () => relationshipModal()); $("remove-asset").addEventListener("click", confirmRemoval);
  $("open-gaps").addEventListener("click", showGaps); $("undo").addEventListener("click", undo); $("export-svg").addEventListener("click", exportSVG);
  $("export-context").addEventListener("click", () => { if (savePending()) { download("manual-context.json", exportContext(), "application/json"); showNotice("Context exported. Feed this JSON to your local agent or use it with the renderer’s manual-context input."); } });
  $("import-context").addEventListener("click", () => { if (savePending()) { $("context-file").value = ""; $("context-file").click(); } });
  $("context-file").addEventListener("change", async event => {
    const file = event.target.files[0]; if (!file) return;
    try {
      if (file.size > 5 * 1024 * 1024) throw new Error("Context import is limited to 5 MB.");
      const document = validateContext(JSON.parse(await file.text()));
      const dialog = openModal("Import context?", "This replaces the current entered context with " + document.assets.length + " asset records and " + document.relationships.length + " relationships. Measured evidence remains. Undo restores your previous context.");
      const form = element("form"); modalActions(form, "Import context"); dialog.appendChild(form); form.addEventListener("submit", submitEvent => { submitEvent.preventDefault(); try { importContext(document); closeModal(); fitMap(); } catch (error) { modalError(form, error); } });
    } catch (error) { showNotice("Import failed: " + error.message, true); }
  });
  window.addEventListener("beforeunload", event => { if (dirtyForm || !storageAvailable) { event.preventDefault(); event.returnValue = ""; } });
  new ResizeObserver(() => { renderGraph(); }).observe($("graph-container"));

  try {
    const saved = localStorage.getItem(storageKey);
    if (saved) {
      const draft = JSON.parse(saved); context = validateContext(draft.manual_context);
      if (plainObject(draft.positions)) Object.entries(draft.positions).forEach(([id, position]) => { if (!['__proto__', 'constructor', 'prototype'].includes(id) && plainObject(position) && Number.isFinite(position.x) && Number.isFinite(position.y)) positions[id] = {x: position.x, y: position.y}; });
      showNotice("Restored your browser draft for this census workspace. Export context to keep a portable copy.");
      $("save-state").textContent = "Browser draft restored";
    } else $("save-state").textContent = "Embedded context · edits saved in this browser";
  } catch (error) {
    storageAvailable = false;
    showNotice("Browser draft unavailable: " + error.message + ". Export context to keep entered changes.", true);
    $("save-state").textContent = "Export context to keep edits";
  }
  context = validateContext(context); derive(); render();
  function selectFromHash() {
    const match = location.hash.match(/^#asset=(.*)$/);
    if (!match) return;
    try { const id = decodeURIComponent(match[1]); if (lookup.has(id)) selectHost(id); } catch (_) { /* Invalid fragment is data, not a command. */ }
  }
  selectFromHash();
  window.addEventListener("hashchange", selectFromHash);
  window.CensusWorkbench = Object.freeze({
    getState: () => clone({manual_context: context, nodes, relationships: edges, conflicts, selected, positions}),
    selectHost, saveAsset, addAsset, addRelationship, editRelationship, deleteRelationship, removeAsset, undo, exportContext, importContext,
    fitMap, showTab: switchTab, validateContext
  });
})();
