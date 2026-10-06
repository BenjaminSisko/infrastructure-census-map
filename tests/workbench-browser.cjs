/* Optional development browser checks. Runtime workbench has no npm dependency. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {spawnSync} = require('node:child_process');
const {chromium} = require('playwright');

async function main() {
  const root = path.resolve(__dirname, '..');
  const input = process.argv[2] || path.join(root, 'examples/synthetic-with-manual-products/dependency-map.html');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'census-workbench-browser-'));
  const executablePath = process.env.CENSUS_TEST_BROWSER || undefined;
  const browser = await chromium.launch({headless:true, ...(executablePath ? {executablePath} : {})});
  const context = await browser.newContext({viewport:{width:1800, height:1050}, acceptDownloads:true});
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const exceptions = [], remoteRequests = [];
  page.on('pageerror', e => exceptions.push(e.message));
  page.on('request', request => {if(/^https?:/.test(request.url())) remoteRequests.push(request.url());});
  try {
    await page.goto(pathToFileURL(input).href);
    await page.waitForFunction(() => Boolean(window.CensusWorkbench));
    let state = await page.evaluate(() => window.CensusWorkbench.getState());
    assert.equal(state.nodes.length, 8, 'synthetic graph has all collected/manual assets');
    const positioned = Object.entries(state.positions).filter(([id]) => state.nodes.some(n => n.id === id));
    positioned.forEach(([id, a], index) => positioned.slice(index + 1).forEach(([other, b]) => {
      assert.ok(!(a.x < b.x + 215 && a.x + 215 > b.x && a.y < b.y + 105 && a.y + 105 > b.y), 'initial nodes do not overlap: ' + id + '/' + other);
    }));

    await page.locator('#add-host').click();
    await page.locator('.modal-dialog').waitFor();
    await page.keyboard.press('Escape');
    await page.locator('.modal-dialog').waitFor({state:'detached'});

    // Exercise user-facing selection, notes form, and saving.
    await page.locator('.host-item').filter({hasText:'app01'}).first().click();
    await page.getByRole('tab', {name:'Links', exact:true}).click();
    const declaredCards = await page.locator('.relationship-card.declared').allTextContents();
    assert.ok(declaredCards.length, 'fixture includes owner-declared dependencies');
    declaredCards.forEach(text => {
      assert.ok(text.includes('Declared dependency · view only'));
      assert.ok(!text.includes('Collected evidence · view only'), 'declarations are not labeled measurements');
    });
    await page.getByRole('tab', {name:'Notes', exact:true}).click();
    const notes = 'Browser test: application owner confirmed this VM needs the database. Validate startup order.';
    await page.locator('#asset-notes').fill(notes);
    await page.locator('.host-item').filter({hasText:'app01'}).first().click();
    assert.equal(await page.locator('#asset-notes').inputValue(), notes, 'reselecting a host preserves pending notes');
    await page.locator('#save-asset').click();
    state = await page.evaluate(() => window.CensusWorkbench.getState());
    assert.equal(state.manual_context.assets.find(a => a.id==='app01').notes, notes);
    assert.equal(state.nodes.find(n => n.id==='app01').addresses[0], '192.0.2.10');

    await page.evaluate(() => window.CensusWorkbench.saveAsset('app01', {owner:'Browser test application team'}));
    await page.evaluate(() => window.CensusWorkbench.addAsset({id:'storage-test', platform:'infrastructure', label:'Test storage', addresses:['192.0.2.99'], source:'Browser test', entered_by:'Test operator', reviewed_at:'2026-10-05'}));
    await page.evaluate(() => window.CensusWorkbench.addRelationship({source:'hv01', target:'storage-test', kind:'uses_storage', purpose:'Test shared datastore', source_reference:'Browser test'}));
    state = await page.evaluate(() => window.CensusWorkbench.getState());
    assert.equal(state.nodes.length, 9);
    assert.ok(state.manual_context.relationships.some(e => e.target==='storage-test'));

    // Reject invalid import atomically, with no loss of the current draft.
    const before = await page.evaluate(() => window.CensusWorkbench.exportContext());
    const rejected = await page.evaluate(() => {
      try {window.CensusWorkbench.importContext({schema_version:1, assets:[{id:'dup'}, {id:'dup'}], relationships:[]}); return false;}
      catch {return true;}
    });
    assert.equal(rejected, true);
    assert.deepEqual(JSON.parse(await page.evaluate(() => window.CensusWorkbench.exportContext())), JSON.parse(before));

    const cycleRejected = await page.evaluate(() => {
      try {window.CensusWorkbench.addRelationship({source:'app01', target:'hv01', kind:'hosts', purpose:'Invalid hosting cycle'}); return false;}
      catch {return true;}
    });
    assert.equal(cycleRejected, true);

    await page.evaluate(() => {
      window.CensusWorkbench.addRelationship({source:'app01', target:'db01', kind:'depends_on', purpose:'Known port; protocol not established', port:53});
      window.CensusWorkbench.selectHost('app01');
      window.CensusWorkbench.showTab('relationships');
    });
    assert.ok((await page.locator('#relationships').textContent()).includes('protocol unspecified / 53'));

    // Collected identity edits stay manual assertions.
    await page.evaluate(() => window.CensusWorkbench.saveAsset('app01', {label:'Entered display assertion', os:'Entered OS assertion', addresses:['192.0.2.88']}));
    state = await page.evaluate(() => window.CensusWorkbench.getState());
    assert.equal(state.nodes.find(n => n.id==='app01').addresses[0], '192.0.2.10');
    assert.ok(state.conflicts.some(c => c.asset_id==='app01'));

    // HTML in user-entered context remains text, including after import/export.
    const payload = '<img src=x onerror="window.__censusXss=1"><script>window.__censusXss=1</script>';
    await page.evaluate(value => window.CensusWorkbench.saveAsset('app01', {notes:value, owner:value}), payload);
    assert.equal(await page.evaluate(() => window.__censusXss), undefined);
    await page.evaluate(() => window.CensusWorkbench.saveAsset('app01', {notes:'Operator note: VM placement confirmed in the virtualization export. Startup order needs validation.', owner:'Application operations'}));

    const finalExport = await page.evaluate(() => window.CensusWorkbench.exportContext());
    fs.writeFileSync(path.join(tmp, 'manual-context.json'), finalExport);
    if(process.env.CENSUS_REPORT_PYTHON) {
      const roundTrip = spawnSync(process.env.CENSUS_REPORT_PYTHON, [path.join(root,'renderer/render.py'), '--evidence', path.join(root,'examples/synthetic'), '--manual', path.join(tmp,'manual-context.json'), '--output', path.join(tmp,'roundtrip')], {encoding:'utf8'});
      assert.equal(roundTrip.status, 0, roundTrip.stderr);
      const regenerated = JSON.parse(fs.readFileSync(path.join(tmp,'roundtrip/map.json'),'utf8'));
      assert.equal(regenerated.nodes.find(n=>n.id==='app01').owner, 'Application operations');
      assert.ok(regenerated.nodes.some(n=>n.id==='storage-test'));
    }
    const downloadPromise = page.waitForEvent('download');
    await page.locator('#export-context').click();
    const download = await downloadPromise;
    await download.saveAs(path.join(tmp, 'downloaded-context.json'));
    assert.deepEqual(JSON.parse(fs.readFileSync(path.join(tmp, 'downloaded-context.json'), 'utf8')), JSON.parse(finalExport));

    // Draft survives reload under the same model identity.
    await page.reload();
    await page.waitForFunction(() => Boolean(window.CensusWorkbench));
    state = await page.evaluate(() => window.CensusWorkbench.getState());
    assert.equal(state.manual_context.assets.find(a => a.id==='app01').owner, 'Application operations');
    assert.ok(state.nodes.some(n => n.id==='storage-test'));

    const beforePositions = await page.evaluate(() => window.CensusWorkbench.getState().positions);
    const hostBox = await page.locator('g.graph-node').filter({hasText:'app01'}).first().boundingBox();
    assert.ok(hostBox, 'asset is draggable on graph');
    await page.mouse.move(hostBox.x + hostBox.width/2, hostBox.y + hostBox.height/2);
    await page.mouse.down();
    await page.mouse.move(hostBox.x + hostBox.width/2 + 45, hostBox.y + hostBox.height/2 + 25, {steps:8});
    await page.mouse.up();
    assert.notDeepEqual(await page.evaluate(() => window.CensusWorkbench.getState().positions), beforePositions);

    // Real control actions: zoom, note inspector, optional screenshot.
    const previousZoom = await page.locator('#zoom-level').textContent();
    await page.locator('#zoom-in').click();
    assert.notEqual(await page.locator('#zoom-level').textContent(), previousZoom);
    await page.locator('#fit-map').click();
    await page.evaluate(() => window.CensusWorkbench.selectHost('app01'));
    await page.getByRole('tab', {name:'Notes', exact:true}).click();
    if(process.env.CENSUS_TEST_SCREENSHOT) await page.screenshot({path:process.env.CENSUS_TEST_SCREENSHOT});

    // Storage can be denied without disabling portable export.
    const blocked = await browser.newContext({viewport:{width:1500,height:1000}});
    const blockedPage = await blocked.newPage();
    await blockedPage.addInitScript(() => {
      Object.defineProperty(window, 'localStorage', {get() {throw new Error('blocked for test');}});
    });
    await blockedPage.goto(pathToFileURL(input).href);
    await blockedPage.waitForFunction(() => Boolean(window.CensusWorkbench));
    await blockedPage.evaluate(() => window.CensusWorkbench.saveAsset('app01', {notes:'Export works when storage is blocked'}));
    assert.ok((await blockedPage.locator('#save-state').textContent()).toLowerCase().match(/unavailable|export|not saved|blocked|session/));
    assert.ok(JSON.parse(await blockedPage.evaluate(() => window.CensusWorkbench.exportContext())).assets.some(a => a.notes==='Export works when storage is blocked'));
    await blocked.close();

    const manualPage = await context.newPage();
    await manualPage.goto(pathToFileURL(path.join(root,'examples/manual-only-products/dependency-map.html')).href);
    await manualPage.waitForFunction(() => Boolean(window.CensusWorkbench));
    const manualState = await manualPage.evaluate(() => window.CensusWorkbench.getState());
    assert.equal(manualState.nodes.length, 2, 'different workspace does not recover another draft');
    assert.ok((await manualPage.locator('.topbar .eyebrow').textContent()).includes('NO CENSUS COLLECTED'));
    assert.ok((await manualPage.locator('#counts').textContent()).includes('Not collected'));
    await manualPage.evaluate(() => window.CensusWorkbench.saveAsset('hv01', {notes:'Manual-only workspace note'}));
    assert.ok(JSON.parse(await manualPage.evaluate(() => window.CensusWorkbench.exportContext())).assets.some(a=>a.notes==='Manual-only workspace note'));
    await manualPage.close();

    if(process.env.CENSUS_REPORT_PYTHON) {
      const evidence = path.join(tmp,'endpoint-evidence');
      fs.mkdirSync(path.join(evidence,'hosts'), {recursive:true});
      fs.writeFileSync(path.join(evidence,'hosts/client.json'), JSON.stringify({schema_version:1,asset_id:'client',platform:'linux',sections:{identity:{status:'ok',data:{hostname:'client'}},interfaces:{status:'ok',data:[{address:'192.0.2.10'}]},tcp:{status:'ok',data:[{state:'Established',remote_address:'127.0.0.1',remote_port:8000},{state:'Established',remote_address:'192.0.2.200',remote_port:443}]}}}));
      const product = path.join(tmp,'endpoint-products');
      const fixture = spawnSync(process.env.CENSUS_REPORT_PYTHON, [path.join(root,'renderer/render.py'),'--evidence',evidence,'--output',product], {encoding:'utf8'});
      assert.equal(fixture.status,0,fixture.stderr);
      const endpointPage = await context.newPage();
      await endpointPage.goto(pathToFileURL(path.join(product,'dependency-map.html')).href);
      await endpointPage.waitForFunction(() => Boolean(window.CensusWorkbench));
      let endpointState = await endpointPage.evaluate(() => window.CensusWorkbench.getState());
      assert.equal(endpointState.relationships.find(e=>e.remote_address==='127.0.0.1').target,'client');
      const unresolved = endpointState.nodes.find(n=>n.external);
      const editingRejected = await endpointPage.evaluate(id => {try {window.CensusWorkbench.saveAsset(id,{notes:'unstable identity'});return false;}catch{return true;}},unresolved.id);
      assert.equal(editingRejected,true);
      await endpointPage.evaluate(() => {
        window.CensusWorkbench.saveAsset('client', {label:'Owner asserted hostname', os:'Owner asserted OS'});
        window.CensusWorkbench.selectHost('client');
      });
      const measuredFacts = await endpointPage.locator('#measured-facts').textContent();
      assert.ok(!measuredFacts.includes('Owner asserted OS'));
      assert.ok(measuredFacts.includes('Unknown'));
      assert.ok(measuredFacts.includes('census facts above remain unchanged'));
      await endpointPage.evaluate(() => window.CensusWorkbench.addAsset({id:'peer',platform:'infrastructure',addresses:['192.0.2.200'],notes:'Stable peer context'}));
      endpointState = await endpointPage.evaluate(() => window.CensusWorkbench.getState());
      const matched = endpointState.relationships.find(e=>e.remote_address==='192.0.2.200');
      assert.equal(matched.target,'peer');
      assert.equal(matched.target_resolution_basis,'manual assertion');
      const peerContextIndex = endpointState.manual_context.assets.findIndex(a => a.id === 'peer');
      assert.equal(matched.target_identity_evidence,'manual-context.json#/assets/' + peerContextIndex);
      await endpointPage.evaluate(() => window.CensusWorkbench.removeAsset('peer'));
      endpointState = await endpointPage.evaluate(() => window.CensusWorkbench.getState());
      const unmatched = endpointState.relationships.find(e=>e.remote_address==='192.0.2.200');
      assert.notEqual(unmatched.target,'peer');
      assert.ok(endpointState.nodes.some(n=>n.id===unmatched.target && n.external));
      await endpointPage.close();
    }
    assert.deepEqual(exceptions, []);
    assert.deepEqual(remoteRequests, []);
    console.log(JSON.stringify({result:'PASS', export_path:path.join(tmp,'manual-context.json'), checked:'select/edit/save/export/download/reload/import rejection/hosting validation/identity conflicts/XSS/no network/storage unavailable/zoom/drag/loopback/manual endpoint attribution'}, null, 2));
  } finally {
    await browser.close();
  }
}
main().catch(error => {console.error(error); process.exit(1);});
