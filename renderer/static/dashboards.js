/* Portable generated dashboards. Evidence is data: use text nodes, never HTML. */
(() => {
  'use strict';
  let model = {};
  try { model = JSON.parse(document.getElementById('dashboard-data').textContent); }
  catch { /* The empty state also works when a model cannot be read. */ }
  const dashboards = model.dashboards || {};
  const summary = dashboards.summary || {};
  const warningPercent = typeof (summary.capacity_thresholds || {}).warning_percent === 'number' ? summary.capacity_thresholds.warning_percent : 80;
  const criticalPercent = typeof (summary.capacity_thresholds || {}).critical_percent === 'number' ? summary.capacity_thresholds.critical_percent : 90;
  const nodes = new Map((model.nodes || []).filter(n => !n.external).map(n => [n.id, n]));
  const rawAssets = Array.isArray(dashboards.assets) ? dashboards.assets : [...nodes.values()].map(n => ({asset_id:n.id}));
  const assets = rawAssets.map(a => ({...(nodes.get(a.asset_id || a.id) || {}), ...a, asset_id:a.asset_id || a.id}));
  const byId = new Map(assets.map(a => [a.asset_id, a]));
  const details = model.census_details || {};
  const $ = id => document.getElementById(id);
  const text = value => {
    if (value === null || value === undefined || value === '') return 'Unknown';
    if (Array.isArray(value)) return value.length ? value.map(text).join(', ') : 'None recorded';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  };
  const known = value => value !== null && value !== undefined && value !== '' && !/^(unknown|not supplied|not collected|not returned|needs validation)$/i.test(String(value));
  const list = value => Array.isArray(value) ? value : [];
  function el(tag, className, value) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (value !== undefined) node.textContent = text(value);
    return node;
  }
  function join(parent, ...children) { children.filter(Boolean).forEach(child => parent.append(child)); return parent; }
  function refs(value) {
    if (!value) return [];
    if (Array.isArray(value)) return value.flatMap(refs);
    if (typeof value === 'object') return refs(value.evidence || value.reference || value.path);
    return [String(value)];
  }
  function unique(values) { return [...new Set(values)]; }
  function section(asset, name) { return ((details[asset.asset_id] || {}).sections || {})[name] || {}; }
  function sectionData(asset, name) {
    const value = section(asset, name);
    return /^(ok|collected|success|partial)$/.test(value.status || '') ? value.data : null;
  }
  function evidenceFor(asset, names) {
    const source = (details[asset.asset_id] || {}).evidence || asset.evidence;
    return names.map(name => source ? source + '#/sections/' + name : 'Unknown source / ' + name);
  }
  function number(value) { return typeof value === 'number' && Number.isFinite(value) ? value : null; }
  function numeric(value, suffix = '', digits = 0) {
    return number(value) === null ? 'Unknown' : value.toLocaleString('en-US', {maximumFractionDigits:digits}) + suffix;
  }
  function bytes(value) {
    if (number(value) === null) return 'Unknown';
    const units = ['B', 'KiB', 'MiB', 'GiB', 'TiB', 'PiB'];
    let i = 0, amount = value;
    while (amount >= 1024 && i < units.length - 1) { amount /= 1024; i++; }
    return numeric(amount, ' ' + units[i], i ? 1 : 0);
  }
  function duration(value) {
    if (number(value) === null) return 'Unknown';
    const days = Math.floor(value / 86400), hours = Math.floor(value % 86400 / 3600), minutes = Math.floor(value % 3600 / 60);
    return (days ? days + 'd ' : '') + hours + 'h ' + minutes + 'm';
  }
  function pill(value, tone) {
    const label = text(value);
    return el('span', 'pill ' + (tone || (!known(value) ? 'unknown' : '')), label);
  }
  function cell(value, sub, mono = false) {
    const box = el('div', mono ? 'mono' : '');
    box.append(el('span', !known(value) ? 'unknown-text' : '', value));
    if (sub) box.append(el('span', 'cell-sub', sub));
    return box;
  }
  function evidenceList(evidence, label = 'Source references') {
    const values = unique(refs(evidence));
    const box = el('details', 'evidence-details');
    box.append(el('summary', '', values.length ? label + ' (' + values.length + ')' : 'Source: Unknown'));
    const items = el('ul');
    (values.length ? values : ['Unknown — source evidence is needed']).forEach(value => items.append(el('li', '', value)));
    box.append(items);
    return box;
  }
  function evidenceCell(evidence, observedAt) {
    return join(el('div'), cell(observedAt || 'Unknown', 'Collection / observation time', true), evidenceList(evidence));
  }
  function assetCell(id) {
    const asset = byId.get(id) || {asset_id:id};
    const box = el('div');
    if (byId.has(id)) {
      const button = el('button', 'asset-button', asset.label || id);
      button.type = 'button'; button.dataset.assetId = id;
      button.addEventListener('click', () => selectAsset(id));
      box.append(button);
    } else box.append(el('span', '', asset.label || id || 'Unknown'));
    box.append(el('span', 'cell-sub', asset.platform || 'Unknown platform'));
    if (asset.label && asset.label !== id) box.append(el('span', 'cell-sub', id));
    return box;
  }
  function factValue(value) {
    if (!value || typeof value !== 'object') return {value:text(value), status:known(value) ? 'observed' : 'unknown', evidence:[]};
    const raw = value.status === 'unknown' ? 'Unknown' : value.value ?? value.state ?? value.mode ?? value.description ?? value.names ?? value.data;
    const display = typeof raw === 'boolean' ? (raw ? 'Yes' : 'No') : text(raw);
    return {value:display, status:value.status || (!known(raw) ? 'unknown' : 'observed'), reason:value.reason, evidence:refs(value.evidence)};
  }
  function factCell(value) {
    const fact = factValue(value);
    const preview = str => str.length > 250 ? str.slice(0,247) + '…' : str;
    const truncated = fact.value.length > 250;
    const box = join(el('div'), pill(preview(fact.value), /unknown|unsupported|denied|missing|unavailable|not_collected/.test(fact.status) ? 'unknown' : ''));
    box.append(el('span', 'cell-sub', preview(text(fact.reason || 'Evidence state: ' + fact.status + (value && value.collection_status ? ' · Collection: ' + value.collection_status : '')))));
    if (value && value.names && value.value && value.names.length) box.append(el('span', 'cell-sub', preview(text(value.names))));
    if (truncated) box.append(el('span','cell-sub','Display shortened; inspect source facts (JSON) in asset details for the full record.'));
    if (fact.evidence.length) box.append(evidenceList(fact.evidence));
    return box;
  }
  const views = {
    overview:{title:'The infrastructure picture.', audience:'LEADERSHIP / OPERATIONS', description:'Assets, capacity pressure and the evidence still needed to make decisions. Counts follow the current asset filters.'},
    storage:{title:'Capacity, consumers, context.', audience:'STORAGE / SYSTEM ADMINISTRATION', description:'Filesystem capacity and storage mounts from the snapshot, with provider identity and mount state kept explicit.'},
    resources:{title:'A point in system time.', audience:'SYSTEM ADMINISTRATION / OPERATIONS', description:'Boot uptime, kernel and resource observations. These are host facts from a collection, not service availability or SLA measurements.'},
    patch:{title:'What maintenance evidence says.', audience:'PATCH / REBOOT / CHANGE REVIEW', description:'Historical patch observations and reboot indicators. Patch currentness remains Unknown without an approved baseline and assessment.'},
    services:{title:'Services and agent presence.', audience:'PLATFORM OPERATIONS', description:'Recorded service states, failed units and security agent presence. A listed or running agent does not prove source-attributed telemetry coverage.'},
    security:{title:'Evidence for security review.', audience:'ISSO / SECURITY OPERATIONS', description:'Collected configuration facts, agent evidence and attested context. This view does not calculate compliance or authorize flows.'},
    dependencies:{title:'Relationships and exposure.', audience:'ISSE / ARCHITECTURE REVIEW', description:'Keep observed endpoints, physical neighbors and declared requirements distinct. Local listeners do not prove remote reachability or approval.'},
    coverage:{title:'Know the evidence boundary.', audience:'COLLECTION / FOLLOW-UP', description:'Returned sections, missing records and collection gaps. Failure to collect a section is not evidence of a failed service.'}
  };
  let currentView = 'overview', lastFocus = null;
  const sorting = new Map();
  let currentExports = [];
  function filteredAssets() {
    const query = $('asset-search').value.trim().toLowerCase();
    const platform = $('platform-filter').value, criticality = $('criticality-filter').value;
    return assets.filter(a => (platform === 'all' || text(a.platform) === platform) &&
      (criticality === 'all' || text(a.criticality) === criticality) &&
      (!query || [a.asset_id, a.label, a.owner, a.role, a.os, ...list(a.addresses)].map(text).join(' ').toLowerCase().includes(query)));
  }
  function times(rows) {
    const values = unique(rows.map(a => a.collected_at).filter(known)).sort();
    return values.length ? (values.length === 1 ? values[0] : values[0] + ' to ' + values[values.length - 1]) : 'Unknown / no returned collection time';
  }
  function panel(title, kicker, note, rows, source, gapNote) {
    const box = el('section', 'panel');
    const heading = join(el('div'), el('p', 'panel-kicker', kicker), el('h2', '', title));
    const header = join(el('header', 'panel-header'), heading);
    if (rows !== undefined) header.append(el('span', 'panel-count', rows + ' records'));
    box.append(header);
    if (note) box.append(el('p', 'panel-note', note));
    box._footer = el('p', 'panel-evidence');
    join(box._footer, el('strong', '', 'Evidence basis: '), document.createTextNode(source || 'Unknown'), document.createTextNode(' · Collection time: ' + times(filteredAssets()) + ' · ' + (gapNote || 'Unknown values and collection gaps remain explicit.')));
    return box;
  }
  function finishPanel(box) { box.append(box._footer); return box; }
  function empty(message, detail) {
    return join(el('div', 'empty-state'), el('strong', '', message), el('p', '', detail || 'Unknown. No corresponding records were returned for the selected assets. Check collection scope, section status and source evidence.'));
  }
  function tablePanel(id, title, kicker, note, columns, rows, source, gapNote, emptyDetail) {
    const box = panel(title, kicker, note, rows.length, source, gapNote);
    if (!rows.length) { box.append(empty('No records in this view.', emptyDetail)); return finishPanel(box); }
    const scroll = el('div', 'table-scroll');
    scroll.tabIndex = 0; scroll.setAttribute('aria-label', title + ' table; scroll horizontally if needed');
    const table = el('table');
    const caption = el('caption', 'sr-only', title); table.append(caption);
    const head = el('thead'), headRow = el('tr');
    const selected = sorting.get(id);
    columns.forEach(column => {
      const th = el('th'); th.scope = 'col';
      if (selected && selected.key === column.key) th.setAttribute('aria-sort', selected.desc ? 'descending' : 'ascending');
      const button = el('button'); button.type = 'button'; button.dataset.sort = column.key;
      join(button, el('span', '', column.label), el('span', 'sort-icon', selected && selected.key === column.key ? (selected.desc ? '↓' : '↑') : '↕'));
      button.setAttribute('aria-label', 'Sort ' + title + ' by ' + column.label + (selected && selected.key === column.key ? ', currently ' + (selected.desc ? 'descending' : 'ascending') : ''));
      button.addEventListener('click', () => {
        sorting.set(id, {key:column.key, desc:!!(selected && selected.key === column.key && !selected.desc)});
        render();
        const target = $('dashboard-view').querySelector('[data-table="' + id + '"] [data-sort="' + column.key + '"]');
        if (target) target.focus();
      });
      th.append(button); headRow.append(th);
    });
    head.append(headRow); table.append(head); table.dataset.table = id;
    const body = el('tbody');
    const sorted = rows.slice();
    if (selected) {
      const column = columns.find(c => c.key === selected.key);
      sorted.sort((a, b) => {
        const x = column.value ? column.value(a) : a[column.key], y = column.value ? column.value(b) : b[column.key];
        const comparison = number(x) !== null && number(y) !== null ? x - y : text(x).localeCompare(text(y), 'en', {numeric:true});
        return selected.desc ? -comparison : comparison;
      });
    }
    sorted.forEach(row => {
      const tr = el('tr');
      columns.forEach(column => {
        const td = el('td');
        const value = column.render ? column.render(row) : cell(column.value ? column.value(row) : row[column.key]);
        td.append(value); tr.append(td);
      });
      body.append(tr);
    });
    table.append(body); scroll.append(table); box.append(scroll);
    return finishPanel(box);
  }
  const assetColumn = {key:'asset_id', label:'Asset', render:r => assetCell(r.asset_id)};
  function metric(label, value, detail, warning = false) {
    const box = el('article', 'metric' + (warning ? ' warning' : ''));
    return join(box, el('span', 'metric-label', label), el('strong', !known(value) ? 'unknown' : '', value), el('p', '', detail));
  }
  function capacities(ids) { return list(dashboards.storage_capacity).filter(r => ids.has(r.asset_id)); }
  function mounts(ids) { return list(dashboards.storage_mounts).filter(r => ids.has(r.asset_id)); }
  function findings(ids) { return list(dashboards.findings).filter(r => !r.asset_id || ids.has(r.asset_id)); }
  function gapRows(asset) {
    return list(model.gaps).filter(g => g.asset_id === asset.asset_id);
  }
  function coverage(asset) {
    const entries = Object.entries((details[asset.asset_id] || {}).sections || {});
    const supplied = asset.coverage || {};
    const collected = list(supplied.collected_sections).length ? supplied.collected_sections : entries.filter(([,v]) => /^(ok|collected|success)$/.test(v.status || '')).map(([key]) => key);
    const gaps = list(supplied.gap_sections).length ? supplied.gap_sections : gapRows(asset).map(g => ({section:g.section, status:g.status, evidence:g.evidence}));
    return {collected, gaps, status:supplied.status || (entries.length ? (gaps.length ? 'gaps present' : 'returned sections') : 'not collected')};
  }
  function coverageCell(asset, which) {
    const value = coverage(asset)[which];
    if (!value.length) return cell(which === 'gaps' && details[asset.asset_id] ? 'None recorded' : 'Unknown', which === 'gaps' ? 'See section scope and limitations' : 'No returned sections');
    const box = el('div', 'section-list');
    value.forEach(item => {
      const name = typeof item === 'string' ? item : item.section || item.name;
      const gap = gapRows(asset).find(g => g.section === name);
      const label = which === 'gaps' ? text(name) + ': ' + text(typeof item === 'object' ? item.status : gap && gap.status || section(asset, name).status || 'Unknown') : text(name);
      box.append(el('span', 'section-chip' + (which === 'gaps' ? ' gap' : ''), label));
    });
    return box;
  }
  function capacityCell(row) {
    const amount = number(row.used_percent), box = el('div', 'capacity-cell');
    const tone = row.status === 'critical' ? 'critical' : row.status === 'warning' ? 'warning' : '';
    const line = join(el('div', 'capacity-line'), el('span', 'mono', numeric(amount, '%', 1)));
    if (amount !== null) {
      const meter = el('span', 'capacity-meter ' + tone), fill = el('span');
      fill.style.width = Math.max(0, Math.min(100, amount)) + '%'; meter.append(fill); line.append(meter);
    }
    box.append(line); box.append(el('span', 'cell-sub', amount === null ? 'Capacity evidence: Unknown' : (tone ? tone + ' threshold' : 'Below warning threshold')));
    return box;
  }
  function makeFindingList(rows) {
    const body = el('div', 'finding-list');
    if (!rows.length) return empty('No derived findings for this selection.', 'This is not a health or compliance assessment. Missing evidence and known limitations still need review.');
    rows.slice().sort((a,b) => ({critical:0,warning:1,info:2}[a.severity] ?? 3) - ({critical:0,warning:1,info:2}[b.severity] ?? 3)).forEach(row => {
      const item = el('article', 'finding');
      join(item, join(el('div', 'finding-top'), pill(row.severity || 'info', row.severity), el('h3', '', row.title)), el('p', '', row.detail));
      if (row.asset_id) item.append(assetCell(row.asset_id));
      item.append(evidenceList(row.evidence)); body.append(item);
    });
    return body;
  }
  function callout(title, message) { return join(el('aside', 'callout'), el('h2', '', title), el('p', '', message)); }
  function overview(rows, ids, root) {
    const caps = capacities(ids), relevant = findings(ids), gaps = rows.filter(a => coverage(a).gaps.length || !details[a.asset_id]);
    const returned = rows.filter(a => details[a.asset_id]).length;
    const grid = el('div', 'metric-grid');
    join(grid, metric('ASSETS IN VIEW', rows.length, returned + ' have returned census records; ' + (rows.length - returned) + ' have no returned census record.'),
      metric('ASSETS WITH EVIDENCE GAPS', gaps.length, 'Includes missing records and non-successful sections.', true),
      metric('FILESYSTEMS AT ≥' + warningPercent + '% USED', caps.filter(c => number(c.used_percent) !== null && c.used_percent >= warningPercent).length, caps.length + ' capacity records; unknown capacity is kept separate.', true),
      metric('PATCH CURRENTNESS', 'Unknown', 'An approved patch baseline and assessment are not included.', true));
    root.append(grid);
    const split = el('div', 'split-panels');
    const attention = panel('Attention queue', 'DERIVED FROM SNAPSHOT', 'Findings point to evidence to inspect. They do not establish an outage, compliance failure or approved change.', relevant.length, 'Dashboard findings retain source references.');
    attention.append(makeFindingList(relevant.slice(0,4)));
    if(relevant.length > 4) {
      const more=el('button','quiet-button','Review collection coverage & limits →');
      more.addEventListener('click',()=>selectView('coverage'));
      const wrap=el('div','finding-list'); wrap.append(join(el('div','finding'),el('p','', 'Showing the first 4 of ' + relevant.length + ' findings. Full source and gap details are available in each asset record.'),more)); attention.append(wrap);
    }
    split.append(finishPanel(attention));
    const context = panel('What the snapshot can support', 'READ THE BOUNDARY', '', undefined, 'Census, declarations and manual context retain separate provenance.');
    const basis = el('div', 'evidence-basis');
    [['Observed','A host fact at one collection time. Boot uptime is not an SLA. Capacity is not SMART or RAID health.'], ['Attested','Ownership, criticality, backups and risk statements are entered context with their named sources and review dates.'], ['Unknown','A missing section, unreturned record or absent approval stays visible. Zero findings does not mean verified health.']].forEach(([title,description]) => basis.append(join(el('div'),el('strong','',title),el('p','',description))));
    context.append(basis); split.append(finishPanel(context)); root.append(split);
    const cols = [assetColumn, {key:'addresses',label:'Addresses',render:a => cell(list(a.addresses).length ? text(a.addresses) : 'Unknown', 'Identity source: ' + text(a.source_kind),true)},
      {key:'owner',label:'Owner · attested',render:a => cell(a.owner,'Manual source in asset details')}, {key:'criticality',label:'Criticality · attested',render:a => pill(a.criticality, known(a.criticality) ? 'attested' : 'unknown')},
      {key:'coverage',label:'Evidence coverage',value:a => coverage(a).gaps.length,render:a => join(el('div'),pill(coverage(a).status,coverage(a).gaps.length || !details[a.asset_id] ? 'warning' : ''),el('span','cell-sub',coverage(a).collected.length + ' returned sections · ' + coverage(a).gaps.length + ' gaps'))},
      {key:'collected_at',label:'Collection time',render:a => evidenceCell(a.evidence,a.collected_at)}];
    root.append(tablePanel('overview-assets','Asset register','FILTERED INVENTORY','Select an asset for measured facts, context sources and its collection record.',cols,rows,'Asset identity, census section status and attributed context.'));
    currentExports = rows.map(a => ({asset_id:a.asset_id,label:a.label,platform:a.platform,addresses:text(list(a.addresses)),owner_attested:a.owner,criticality_attested:a.criticality,collected_at:a.collected_at,evidence:a.evidence}));
  }
  function storage(rows, ids, root) {
    const caps = capacities(ids), allMounts = mounts(ids);
    const providers = unique(allMounts.map(m => m.provider_asset_id || m.provider).filter(known));
    const validCapacity = row => number(row.used_percent) !== null && row.used_percent >= 0 && row.used_percent <= 100;
    const invalidCapacityCount = caps.filter(c => !validCapacity(c)).length;
    const grid = el('div', 'metric-grid');
    join(grid,metric('CAPACITY RECORDS',caps.length,'Local filesystem and logical-volume records can overlap; totals are not summed.'),
      metric('ACTIVE REMOTE MOUNTS',allMounts.filter(m => m.active_observed || /^(active|mounted|active mount)$/i.test(m.mount_state || '')).length,'A configured mount alone does not prove that it is active.'),
      metric('STORAGE PROVIDERS',providers.length,'Unresolved provider names remain explicit; identity basis is retained.'),
      metric('CAPACITY NOT KNOWN',rows.filter(a => !caps.some(c => c.asset_id === a.asset_id && validCapacity(c))).length,'Assets without a valid used-capacity percentage. ' + invalidCapacityCount + ' returned record' + (invalidCapacityCount === 1 ? ' has' : 's have') + ' invalid or unknown capacity.',true));
    root.append(grid);
    const capCols = [assetColumn,{key:'target',label:'Filesystem / volume',render:r=>cell(r.target,text(r.fstype),true)},
      {key:'used_percent',label:'Used capacity',render:capacityCell}, {key:'total_bytes',label:'Total',render:r=>cell(bytes(r.total_bytes),text(r.scope),true)},
      {key:'available_bytes',label:'Available',render:r=>cell(bytes(r.available_bytes),number(r.available_bytes) === null ? 'Available space: Unknown' : 'Available space reported',true)},
      {key:'inodes_free',label:'Inodes free',render:r=>cell(numeric(r.inodes_free),'Total: ' + numeric(r.inodes_total),true)},
      {key:'evidence',label:'Source',render:r=>evidenceCell(r.evidence,(byId.get(r.asset_id)||{}).collected_at)}];
    root.append(tablePanel('storage-capacity','Filesystem capacity','CAPACITY / NOT DISK HEALTH','Warning ≥' + warningPercent + '% and critical ≥' + criticalPercent + '% used are review thresholds. Capacity does not establish SMART, RAID, storage-array or backup health.',capCols,caps,'filesystem / logical-volume census sections.','Unavailable metrics are Unknown; provider capacity is not inferred from a client mount.'));
    const mountCols=[assetColumn,{key:'provider',label:'Provider',render:r=>join(el('div'),byId.has(r.provider_asset_id) ? assetCell(r.provider_asset_id) : cell(r.provider,'Unresolved / external provider identity'),el('span','cell-sub',r.identity_basis || 'Unknown identity basis'))},
      {key:'remote_path',label:'Remote path',render:r=>cell(r.remote_path,text(r.fstype),true)}, {key:'target',label:'Client target',render:r=>cell(r.target,null,true)},
      {key:'mount_state',label:'Mount evidence',render:r=>join(el('div'),pill(text(r.mount_state).replace(/_/g,' '),r.mount_state === 'active' ? '' : 'warning'),el('span','cell-sub',r.active_observed ? 'Active mount observed' : 'Not observed / activity Unknown'),el('span','cell-sub',r.configured_observed ? 'Configuration observed' : 'Configuration not observed / configuration Unknown'),el('span','cell-sub','Collection: ' + text(r.collection_status)))},
      {key:'evidence',label:'Source',render:r=>evidenceCell([...refs(r.evidence),...refs(r.provider_identity_evidence)],(byId.get(r.asset_id)||{}).collected_at)}];
    root.append(tablePanel('storage-mounts','Storage mount map','CONSUMER → PROVIDER','This table records mounting evidence. A storage mount is not proof of an authorized application dependency.',mountCols,allMounts,'Active mount records and configured mount declarations; provider identity source kept per record.'));
    const providerIndex=new Map();
    allMounts.forEach(row=>{
      const key=row.provider_asset_id || row.provider || 'Unknown';
      if(!providerIndex.has(key)) providerIndex.set(key,{asset_id:row.provider_asset_id,provider:row.provider,active_consumers:new Set(),configured_rows:0,unknown_activity_rows:0,identity_basis:new Set(),evidence:[],consumer_ids:new Set()});
      const provider=providerIndex.get(key); provider.consumer_ids.add(row.asset_id);
      if(row.active_observed) provider.active_consumers.add(row.asset_id);
      else provider.unknown_activity_rows++;
      if(row.configured_observed) provider.configured_rows++;
      provider.identity_basis.add(row.identity_basis || 'Unknown'); provider.evidence.push(...refs(row.evidence),...refs(row.provider_identity_evidence));
    });
    const providerRows=[...providerIndex.values()];
    const providerCols=[{key:'provider',label:'Provider',render:r=>byId.has(r.asset_id) ? assetCell(r.asset_id) : cell(r.provider,'Unresolved / external provider identity')},
      {key:'active_consumer_count',label:'Observed active clients',value:r=>r.active_consumers.size,render:r=>cell(r.active_consumers.size,[...r.active_consumers].join(', ') || 'No active clients observed in this scope',true)},
      {key:'configured_rows',label:'Configured mount records',render:r=>cell(r.configured_rows,'Configuration records; activity is independent',true)},
      {key:'unknown_activity_rows',label:'Activity Unknown',render:r=>cell(r.unknown_activity_rows,'Mount records without an active observation',true)},
      {key:'identity_basis',label:'Identity basis',value:r=>[...r.identity_basis].join(', '),render:r=>cell([...r.identity_basis].join(', '),'Manual identity matches remain assertions')},
      {key:'evidence',label:'Source',render:r=>evidenceCell(r.evidence,times([...r.consumer_ids].map(id=>byId.get(id)).filter(Boolean)))}];
    root.append(tablePanel('storage-providers','Observed storage consumers','PROVIDER CONCENTRATION / FILTERED SCOPE','Client counts are distinct assets with active mount observations in this filtered snapshot. They do not establish complete blast radius, approved dependencies or provider availability.',providerCols,providerRows,'Mount observations and provider identity evidence.','Unknown activity and uncollected consumers are excluded from observed active-client counts.'));
    currentExports=[...caps.map(r=>({record_type:'capacity',...r})),...allMounts.map(r=>({record_type:'mount',...r})),...providerRows.map(r=>({record_type:'provider_concentration',provider_asset_id:r.asset_id,provider:r.provider,observed_active_client_count:r.active_consumers.size,observed_active_clients:[...r.active_consumers],configured_mount_records:r.configured_rows,activity_unknown_records:r.unknown_activity_rows,identity_basis:[...r.identity_basis],evidence:unique(r.evidence)}))];
  }
  function resources(rows, ids, root) {
    root.append(callout('Uptime describes this boot.', 'Boot uptime is a point-in-time operating-system fact. No service SLA, availability window, workload trend or latency/error telemetry is available in this product.'));
    const loadValues = asset => {
      const data=sectionData(asset,'load') || {};
      return ['load_1','load_5','load_15'].map(key=>number(data[key]) !== null && data[key] >= 0 ? data[key] : null);
    };
    const cols=[assetColumn,{key:'uptime_seconds',label:'Boot uptime',render:a=>cell(duration(a.uptime_seconds),'Boot: ' + text(a.boot_time),true)},
      {key:'memory_available_percent',label:'Memory available',render:a=>cell(numeric(a.memory_available_percent,'%',1),'Snapshot metric; not a utilization trend',true)},
      {key:'load',label:'Load average',value:a=>loadValues(a)[0],render:a=>cell(loadValues(a).map(v=>numeric(v,'',2)).join(' / '),'1m / 5m / 15m; not CPU percentage',true)},
      {key:'kernel',label:'Kernel / OS',render:a=>cell(a.kernel,text(a.os),true)},
      {key:'freshness',label:'Relative age',value:a=>number((a.freshness||{}).age_seconds),render:a=>cell(duration((a.freshness||{}).age_seconds),(a.freshness||{}).status || 'Unknown timestamp; relative to latest collected snapshot',true)},
      {key:'collected_at',label:'Source',render:a=>evidenceCell([...evidenceFor(a,['uptime','memory','load','identity']),...refs(a.evidence)],a.collected_at)}];
    root.append(tablePanel('resources','Uptime & resource observations','HOST SNAPSHOT','Memory and boot facts can be missing or unsupported independently of other collected sections. Relative age compares records within this bundle, not against the current clock.',cols,rows,'System / identity census sections.','Unknown values need a successful, timestamped resource collection.'));
    currentExports=rows.map(a=>({asset_id:a.asset_id,uptime_seconds:a.uptime_seconds,boot_time:a.boot_time,memory_available_percent:a.memory_available_percent,load_average_1m:loadValues(a)[0],load_average_5m:loadValues(a)[1],load_average_15m:loadValues(a)[2],kernel:a.kernel,os:a.os,collected_at:a.collected_at,evidence:a.evidence}));
  }
  function patch(rows, ids, root) {
    root.append(callout('Patch currentness: Unknown.', 'An installed package date, update history entry or hotfix record is historical evidence. An approved baseline, applicability review and assessment are required to establish patch currentness.'));
    const cols=[assetColumn,{key:'patch_status',label:'Patch currentness',render:a=>cell('Unknown',(a.patch_evidence||{}).reason || 'No approved baseline and assessment supplied')},
      {key:'patch_observed_at',label:'Latest patch observation',value:a=>(a.latest_patch_observation||{}).observed_at,render:a=>cell((a.latest_patch_observation||{}).observed_at,(a.latest_patch_observation||{}).description || 'Unknown historical patch evidence',true)},
      {key:'reboot_pending',label:'Reboot indicator',value:a=>factValue(a.reboot_pending).value,render:a=>factCell(a.reboot_pending)},
      {key:'kernel',label:'Running kernel / OS',render:a=>cell(a.kernel,text(a.os),true)},
      {key:'evidence',label:'Source',render:a=>evidenceCell([...refs((a.patch_evidence||{}).evidence),...refs((a.latest_patch_observation||{}).evidence),...refs((a.reboot_pending||{}).evidence)],a.collected_at)}];
    root.append(tablePanel('patch','Patch & reboot evidence','MAINTENANCE REVIEW','Reboot indicators have platform-specific meanings. Unknown reboot evidence is not equivalent to “no reboot needed.”',cols,rows,'Collected package / update history / reboot-indicator evidence.','Patch assessment and baseline approval are Unknown.'));
    currentExports=rows.map(a=>({asset_id:a.asset_id,patch_currentness:'Unknown',patch_reason:(a.patch_evidence||{}).reason,latest_patch_observation:(a.latest_patch_observation||{}).observed_at,patch_description:(a.latest_patch_observation||{}).description,reboot_indicator:factValue(a.reboot_pending).value,collected_at:a.collected_at,evidence:refs((a.latest_patch_observation||{}).evidence)}));
  }
  function serviceRecords(rows) {
    return rows.flatMap(a=> {
      const data=sectionData(a,'services'), records=list(Array.isArray(data) ? data : (data||{}).services);
      if (!records.length) return [{asset_id:a.asset_id,name:'Unknown',state:'Unknown',start_mode:'Unknown',evidence:evidenceFor(a,['services']),gap:section(a,'services').status || 'not collected'}];
      return records.map((r,i)=>({asset_id:a.asset_id,name:r.name || r.Name || r.unit || r.service,state:r.state || r.State || r.active || r.status,start_mode:r.start_mode || r.StartMode || r.sub || r.sub_state,description:r.description || r.DisplayName,evidence:evidenceFor(a,['services']).map(p=>p + '/data/' + i),collected_at:a.collected_at}));
    });
  }
  function services(rows, ids, root) {
    root.append(callout('Presence is one piece of agent evidence.', 'Installed or running agents do not establish unique enrollment, telemetry transport, persistence or searchable source-attributed logs. Collection failure is an evidence gap, not proof that an application failed.'));
    const hostCols=[assetColumn,{key:'failed_services',label:'Failed service evidence',value:a=>factValue(a.failed_services).value,render:a=>factCell(a.failed_services)},
      {key:'agent',label:'Security agent evidence',value:a=>factValue((a.security||{}).agent).value,render:a=>factCell((a.security||{}).agent)},
      {key:'service_presence',label:'Recorded agent / service names',render:a=>factCell((a.security||{}).service_presence)},
      {key:'evidence',label:'Source',render:a=>evidenceCell([...evidenceFor(a,['services']),...refs((a.failed_services||{}).evidence),...refs(((a.security||{}).agent||{}).evidence)],a.collected_at)}];
    root.append(tablePanel('agents','Services & agent evidence','HOST LEVEL','Names and states come from bounded platform metadata. Application-level logging and coverage still need separate validation.',hostCols,rows,'Services and security agent census sections.','Coverage: Unknown without fresh, source-attributed log evidence.'));
    const records=serviceRecords(rows);
    root.append(tablePanel('service-list','Service state register','COLLECTED SERVICE RECORDS','The collector may bound returned services. State applies to the named record at collection time.',[assetColumn,{key:'name',label:'Service',render:r=>cell(r.name,r.description,true)},
      {key:'state',label:'State',render:r=>cell(r.state,r.gap ? 'Section: ' + r.gap : 'Observed service state')},{key:'start_mode',label:'Start mode / substate'},
      {key:'evidence',label:'Source',render:r=>evidenceCell(r.evidence,r.collected_at || (byId.get(r.asset_id)||{}).collected_at)}],records,'Services census section.'));
    currentExports=records;
  }
  function security(rows, ids, root) {
    root.append(callout('Configuration evidence is not a compliance score.', 'Review the section sources, collection gaps and approved requirements together. Backup and risk context below are manual attestations, not measured controls or completed restore tests.'));
    const cols=[assetColumn,...[['selinux','SELinux'],['firewall','Firewall'],['time_sync','Time synchronization'],['audit','Audit evidence'],['agent','Security agent']].map(([key,label])=>({key,label,value:a=>factValue((a.security||{})[key]).value,render:a=>factCell((a.security||{})[key])})),
      {key:'collected_at',label:'Collection time',render:a=>cell(a.collected_at,'Source references in each fact / asset drawer',true)}];
    root.append(tablePanel('security','Security configuration evidence','ISSO / OBSERVED FACTS','A firewall state or local listener does not establish approved clients, source allowlists, rule correctness or remote reachability.',cols,rows,'Security and platform configuration sections.','Control compliance, exceptions and authorization: Unknown.'));
    const contextCols=[assetColumn,{key:'owner',label:'Owner · attested',render:a=>cell(a.owner,'Manual context; inspect source in asset details')},
      {key:'backup_attestation',label:'Backup · attested',render:a=>{
        const item=a.backup_attestation || {};
        const box=join(el('div'),pill(known(item.value) ? text(item.value) : 'Unknown',known(item.value) ? 'attested' : 'unknown'));
        const assertions=list(item.entries);
        if(assertions.length) assertions.forEach(c=>join(box,el('span','cell-sub',text(c.field) + ': ' + text(c.value)),el('span','cell-sub','Source: ' + text(c.source) + ' · Reviewed: ' + text(c.reviewed_at)),evidenceList(c.evidence)));
        else join(box,el('span','cell-sub','Source: ' + text(item.source) + ' · Reviewed: ' + text(item.reviewed_at)),evidenceList(item.evidence));
        return box;
      }}, {key:'risk',label:'Risk / security context · attested',render:a=>{
        const context=list(a.context).filter(c=>/stig|cis|poam|scan|vulnerab|baseline|patch|exception|approval|authority|risk|security|compliance|backup|restore/i.test(c.field || ''));
        if(!context.length) return cell('Unknown','No attributed security / assurance context supplied');
        const box=el('div'); context.forEach(c=>join(box,pill(text(c.field) + ': ' + text(c.value),'attested'),el('span','cell-sub','Source: ' + text(c.source) + ' · Reviewed: ' + text(c.reviewed_at)),evidenceList(c.evidence))); return box;
      }}];
    root.append(tablePanel('security-context','Owner, backup & risk context','MANUAL ATTESTATIONS','Entered sources and review dates are retained. A backup statement does not verify retention, recoverability or a restore exercise.',contextCols,rows,'Manual context source and review date per assertion.'));
    currentExports=rows.map(a=>({asset_id:a.asset_id,...Object.fromEntries(['selinux','firewall','time_sync','audit','agent'].map(k=>[k, factValue((a.security||{})[k]).value])),owner_attested:a.owner,backup_attested:(a.backup_attestation||{}).value,backup_assertions:(a.backup_attestation||{}).entries,collected_at:a.collected_at}));
  }
  function dependencyRows(ids) {
    return list(model.relationships).filter(r=>ids.has(r.source) || ids.has(r.target)).map(r=>({...r,asset_id:r.source,peer:r.target,basis:r.kind==='observed_connection' || r.kind==='observed_tcp' ? 'Observed endpoint' : r.kind==='physical_neighbor' ? 'Physical neighbor' : r.kind==='declared_dependency' ? 'Declared requirement' : r.kind==='manual_relationship' ? 'Manual: ' + text(r.relationship_type) : r.kind==='storage_mount' ? 'Storage: ' + text(r.status) : text(r.kind)}));
  }
  function listenerRecords(rows) {
    return rows.flatMap(a=> {
      const compound=(a.security||{}).listeners;
      const records=list(compound && (compound.items || compound.value || compound.records || compound.data || compound));
      if(!records.length) return [{asset_id:a.asset_id,local_address:'Unknown',local_port:null,protocol:'Unknown',process:'Unknown',status:compound && compound.status || 'not collected',evidence:refs(compound && compound.evidence)}];
      return records.map(r=>({asset_id:a.asset_id,...r,evidence:refs(r.evidence).length ? r.evidence : refs(compound.evidence),collected_at:a.collected_at}));
    });
  }
  function dependencies(rows, ids, root) {
    root.append(callout('Observation does not establish permission.', 'Sockets retain unknown initiator and purpose. Declared relationships retain their supplied authority; a declaration alone does not grant approval. Physical neighbors describe adjacency. Listeners describe local exposure, not remote reachability.'));
    const relationships=dependencyRows(ids);
    const cols=[assetColumn,{key:'peer',label:'Peer / dependency',render:r=>assetCell(r.peer)}, {key:'basis',label:'Evidence basis',render:r=>pill(r.basis,/Manual|Declared/.test(r.basis) ? 'attested' : '')},
      {key:'remote_port',label:'Endpoint / interface',render:r=>cell((r.protocol || (r.remote_port ? 'Protocol unknown' : 'Unknown')) + (r.remote_port ? ' / ' + r.remote_port : ''),r.local_interface || r.remote_address || 'Initiator: Unknown',true)},
      {key:'purpose',label:'Purpose / authority',render:r=>cell(r.purpose || 'Unknown', 'Authority: ' + text(r.authority || (r.manual_information||{}).source))},
      {key:'evidence',label:'Source',render:r=>evidenceCell(r.evidence,r.observed_at || (byId.get(r.asset_id)||{}).collected_at)}];
    root.append(tablePanel('relationships','Relationship register','ISSE / IDENTITY & PURPOSE', 'A row remains attached to its source asset and evidence reference. Filtering includes relationships touching a selected asset.',cols,relationships,'Observed sockets / neighbor sections / separately declared or entered relationships.','Initiator, required purpose and approval remain Unknown unless explicitly sourced.'));
    const listeners=listenerRecords(rows);
    root.append(tablePanel('listeners','Local listener evidence','HOST EXPOSURE','Listener address and port are local endpoints. No controller or browser connectivity probe is performed.',[assetColumn,
      {key:'local_address',label:'Local address',render:r=>cell(r.local_address || r.address,null,true)}, {key:'local_port',label:'Port / protocol',render:r=>cell(text(r.local_port ?? r.port) + ' / ' + text(r.protocol),null,true)},
      {key:'process',label:'Process / service',render:r=>cell(r.process || r.name,'Remote reachability: Unknown')}, {key:'status',label:'Evidence state',render:r=>pill(r.status || 'observed',/unknown|not collected|unsupported|denied/.test(r.status || '') ? 'unknown' : '')},
      {key:'evidence',label:'Source',render:r=>evidenceCell(r.evidence,r.collected_at || (byId.get(r.asset_id)||{}).collected_at)}],listeners,'Local listener census evidence.','Approved clients, NAT/firewall path and reachability: Unknown.'));
    currentExports=[...relationships.map(r=>({record_type:'relationship',asset_id:r.asset_id,peer:r.peer,basis:r.basis,protocol:r.protocol,port:r.remote_port,purpose:r.purpose,authority:r.authority,evidence:r.evidence})),...listeners.map(r=>({record_type:'listener',...r}))];
  }
  function coverageView(rows, ids, root) {
    const returned=rows.filter(a=>details[a.asset_id]).length, gaps=rows.flatMap(gapRows);
    const grid=el('div','metric-grid');
    join(grid,metric('ASSETS IN VIEW',rows.length,'Filtered asset scope, including manual and expected assets.'),metric('RETURNED CENSUS RECORDS',returned,rows.length - returned + ' assets have no returned census record.'),
      metric('RECORDED SECTION GAPS',gaps.length,'Partial, missing, denied and unsupported evidence remains explicit.',true),metric('COLLECTION TIMING',known(summary.snapshot_at) ? summary.snapshot_at.slice(0,10) : 'Unknown','Evidence age is relative to the newest collected record.',!known(summary.snapshot_at)));
    root.append(grid);
    const cols=[assetColumn,{key:'status',label:'Record state',value:a=>coverage(a).status,render:a=>pill(coverage(a).status,!details[a.asset_id] || coverage(a).gaps.length ? 'warning' : '')},
      {key:'collected_sections',label:'Returned sections',render:a=>coverageCell(a,'collected')}, {key:'gap_sections',label:'Gaps / incomplete sections',render:a=>coverageCell(a,'gaps')},
      {key:'evidence',label:'Source',render:a=>evidenceCell(a.evidence || (details[a.asset_id]||{}).evidence,a.collected_at)}];
    root.append(tablePanel('coverage','Evidence coverage by asset','SCOPE / RETURNED / UNKNOWN','Successful sections can coexist with gaps. An empty or partial response does not prove absence of the target feature.',cols,rows,'Section status, expected-asset scope and per-host source.','Missing source/time and failed sections need follow-up evidence.'));
    const box=panel('Collection & interpretation limits','KEEP WITH THE PRODUCT','',undefined,'Renderer and collector capability limits; review platform qualification separately.');
    const body=el('div','finding-list');
    const limitations=unique([...list(dashboards.limitations),model.interpretation || 'Observed endpoints do not establish initiator, purpose, authorization or criticality.']);
    limitations.forEach(value=>body.append(join(el('div','finding'),el('p','',value))));
    box.append(body); root.append(finishPanel(box));
    currentExports=rows.map(a=>({asset_id:a.asset_id,record_state:coverage(a).status,collected_sections:coverage(a).collected,gap_sections:coverage(a).gaps,collected_at:a.collected_at,evidence:a.evidence}));
  }
  function render() {
    const rows=filteredAssets(), ids=new Set(rows.map(a=>a.asset_id));
    const view=views[currentView];
    $('view-title').textContent=view.title; $('view-audience').textContent=view.audience; $('view-description').textContent=view.description;
    $('filter-count').textContent=rows.length + ' / ' + assets.length + ' assets';
    const root=$('dashboard-view'); root.replaceChildren(); currentExports=[];
    if(!rows.length) root.append(callout('No assets match these filters.', 'Adjust the search or reset the platform and criticality filters. This selection has no evidence records.'));
    ({overview,storage,resources,patch,services,security,dependencies,coverage:coverageView}[currentView])(rows,ids,root);
  }
  function selectView(view) {
    if(!Object.prototype.hasOwnProperty.call(views, view)) return;
    currentView=view;
    document.querySelectorAll('.view-button').forEach(button=>{
      const active=button.dataset.view === view; button.classList.toggle('active',active);
      if(active) button.setAttribute('aria-current','page'); else button.removeAttribute('aria-current');
    });
    render();
  }
  function facts(title, pairs) {
    const section=el('section','drawer-section'), values=el('dl','fact-list');
    pairs.forEach(([key,value])=>join(values,el('dt','',key),el('dd','',value)));
    join(section,el('h3','',title),values); return section;
  }
  function selectAsset(id) {
    const asset=byId.get(id); if(!asset) return;
    const dialog=$('asset-drawer'); lastFocus=document.activeElement;
    $('drawer-title').textContent=asset.label || id;
    $('drawer-subtitle').textContent=id + ' · ' + text(asset.platform) + ' · Collected: ' + text(asset.collected_at);
    $('drawer-map-link').href='dependency-map.html#asset=' + encodeURIComponent(id);
    const root=$('drawer-content'); root.replaceChildren();
    root.append(facts('Asset facts', [['Stable ID',id],['Addresses',list(asset.addresses).length ? text(asset.addresses) : 'Unknown'],['OS / kernel',text(asset.os) + ' / ' + text(asset.kernel)],['Boot uptime',duration(asset.uptime_seconds)],['Evidence kind',asset.source_kind || (details[id] ? 'census' : 'Unknown')],['Collection time',asset.collected_at || 'Unknown']]));
    root.append(facts('Owner & context · attested', [['Owner',asset.owner || 'Unknown'],['Criticality',asset.criticality || 'Unknown'],['Role',asset.role || 'Unknown'],['Backup attestation',text((asset.backup_attestation||{}).value)],['Backup source',list((asset.backup_attestation||{}).entries).map(c=>text(c.source)).join('; ') || 'Unknown'],['Backup reviewed',list((asset.backup_attestation||{}).entries).map(c=>text(c.reviewed_at)).join('; ') || 'Unknown']]));
    const context=el('section','drawer-section'); context.append(el('h3','','Attribution & manual assertions'));
    const entries=list(asset.context);
    if(entries.length) entries.forEach(c=>join(context,el('p','',text(c.field) + ': ' + text(c.value)),el('span','cell-sub','Source: ' + text(c.source) + ' · Reviewed: ' + text(c.reviewed_at)),evidenceList(c.evidence)));
    else list(asset.manual_information).forEach(c=>join(context,el('p','',text(c.fields)),el('span','cell-sub','Source: ' + text(c.source) + ' · Reviewed: ' + text(c.reviewed_at)),evidenceList(c.evidence)));
    if(!entries.length && !list(asset.manual_information).length) context.append(el('p','','Unknown — no attributed manual context supplied.'));
    root.append(context);
    const evidence=el('section','drawer-section'); evidence.append(el('h3','','Collection sections & gaps'));
    const entriesSections=Object.entries((details[id]||{}).sections || {}), recordList=el('ul','drawer-evidence');
    entriesSections.forEach(([name,value])=>join(recordList,join(el('li'),el('strong','',name + ' · ' + text(value.status)),el('span','',((details[id]||{}).evidence || 'Unknown') + '#/sections/' + name),el('span','',value.error || value.reason || 'Collected: ' + text(asset.collected_at)))));
    gapRows(asset).filter(g=>!entriesSections.some(([name])=>name===g.section)).forEach(g=>recordList.append(join(el('li'),el('strong','',g.section + ' · ' + text(g.status)),el('span','',g.evidence || 'Unknown source'))));
    if(!recordList.childElementCount) recordList.append(join(el('li'),el('strong','','Unknown / no census record returned'),el('span','','Manual context does not establish observed state.')));
    evidence.append(recordList); root.append(evidence);
    const raw=el('details','evidence-details'); raw.append(el('summary','','Inspect source facts (JSON)')); raw.append(el('pre','',JSON.stringify({dashboard_asset:asset,census:details[id] || null},null,2))); root.append(raw);
    if(!dialog.open) dialog.showModal(); $('close-drawer').focus();
  }
  function closeDrawer() { $('asset-drawer').close(); }
  function csvValue(value) {
    let result=typeof value==='object' && value!==null ? JSON.stringify(value) : text(value);
    // Apostrophe prevents spreadsheet formulas, including formulas after spaces.
    if (/^[\s]*[=+\-@]/.test(result) || /^[\t\r\n]/.test(result)) result="'" + result;
    return '"' + result.replace(/"/g,'""') + '"';
  }
  function exportCSV() {
    const rows=currentExports, keys=unique(rows.flatMap(r=>Object.keys(r)));
    if(!keys.length) keys.push('asset_id','evidence');
    return '\uFEFF' + [keys.map(csvValue).join(','),...rows.map(row=>keys.map(key=>csvValue(row[key])).join(','))].join('\r\n') + '\r\n';
  }
  function downloadCSV() {
    const blob=new Blob([exportCSV()],{type:'text/csv;charset=utf-8'}), url=URL.createObjectURL(blob), link=el('a');
    link.href=url; link.download='census-' + currentView + '-filtered.csv'; document.body.append(link); link.click(); link.remove();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
    $('export-status').textContent='Exported ' + currentExports.length + ' records from ' + views[currentView].audience + '. Evidence and attestation labels are retained in the columns.';
  }
  function populateFilter(id, values) {
    unique(values.map(text)).sort((a,b)=>a.localeCompare(b)).forEach(value=>{const option=el('option','',value); option.value=value; $(id).append(option);});
  }
  populateFilter('platform-filter',assets.map(a=>a.platform)); populateFilter('criticality-filter',assets.map(a=>a.criticality));
  $('asset-search').addEventListener('input',render); $('platform-filter').addEventListener('change',render); $('criticality-filter').addEventListener('change',render);
  $('reset-filters').addEventListener('click',()=>{$('asset-search').value='';$('platform-filter').value='all';$('criticality-filter').value='all';render();});
  document.querySelectorAll('.view-button').forEach(button=>button.addEventListener('click',()=>selectView(button.dataset.view)));
  $('export-csv').addEventListener('click',downloadCSV); $('print-view').addEventListener('click',()=>window.print());
  $('close-drawer').addEventListener('click',closeDrawer); $('drawer-done').addEventListener('click',closeDrawer);
  $('asset-drawer').addEventListener('close',()=>{if(lastFocus && lastFocus.isConnected) lastFocus.focus();});
  $('asset-drawer').addEventListener('click',event=>{if(event.target===$('asset-drawer')) {const box=event.target.getBoundingClientRect();if(event.clientX<box.left || event.clientX>box.right || event.clientY<box.top || event.clientY>box.bottom) closeDrawer();}});
  const snapshot=summary.snapshot_at || 'Unknown';
  $('snapshot-at').textContent='Collection time: ' + snapshot;
  $('collection-mode').textContent=model.collection_mode==='manual_only' ? 'Manual only · no census collected' : 'Dated evidence · no refresh';
  $('run-date').textContent=known(snapshot) ? snapshot.slice(0,10) : 'Unknown';
  $('run-count').textContent=assets.length + ' assets in this product';
  const initialHash=new URLSearchParams(location.hash.slice(1));
  const requestedView = initialHash.get('view');
  selectView(Object.prototype.hasOwnProperty.call(views, requestedView) ? requestedView : 'overview');
  window.CensusDashboards={selectView,selectAsset,exportCSV,getState:()=>({view:currentView,filtered_assets:filteredAssets().map(a=>a.asset_id),asset_count:assets.length,export_count:currentExports.length})};
  if(initialHash.get('asset')) selectAsset(initialHash.get('asset'));
})();
