/* Optional development browser checks. Generated dashboards have no npm runtime. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {spawnSync} = require('node:child_process');
const {chromium} = require('playwright');

function fixture(root, tmp) {
  const evidence = path.join(tmp, 'fictional-evidence');
  fs.mkdirSync(path.join(evidence, 'hosts'), {recursive:true});
  const good = data => ({status:'ok', data});
  const host = (id, platform, sections) => ({schema_version:1, asset_id:id, platform, collected_at:'2026-10-06T12:00:00Z', collector:{name:'fictional-browser-test'}, sections});
  const inputs = [
    host('app01', 'linux', {
      identity:good({hostname:'app01.example.test', os:'Fictional Linux', kernel:'6.0-example'}),
      interfaces:good([{address:'192.0.2.10'}]),
      tcp:good([{local_address:'0.0.0.0',local_port:8443,state:'LISTEN',process:'example-http'}, {local_address:'192.0.2.10',local_port:45310,remote_address:'192.0.2.20',remote_port:443,state:'ESTABLISHED',process:'example-client'}]),
      udp:good([]), uptime:good({uptime_seconds:172920,boot_time:'2026-10-04T11:58:00Z'}), memory:good({total_bytes:8589934592,available_bytes:4294967296}),load:good({load_1:0.8,load_5:0.6,load_15:0.4}),
      services:good([{name:'wazuh-agent.service',active:'active',sub:'running'}, {name:'example-job.service',active:'failed',sub:'failed'}]),
      patch_inventory:good({latest_package_install_at:'2026-10-01T14:15:00Z',installed_kernels:[]}), reboot_pending:good({pending:true}),
      mounts:good({filesystems:[{source:'storage01.example.test:/exports/example',target:'/srv/example',fstype:'nfs4'},{source:'storage01.example.test:/exports/second',target:'/srv/second',fstype:'nfs4'}]}),
      configured_mounts:good({filesystems:[{source:'storage01.example.test:/exports/example',target:'/srv/example',fstype:'nfs4'},{source:'storage01.example.test:/exports/second',target:'/srv/second',fstype:'nfs4'}]}),
      storage_capacity:good([{target:'/',fstype:'xfs',total_bytes:107374182400,used_bytes:96636764160,available_bytes:10737418240,used_percent:90,inodes_total:100000,inodes_free:65000}]),
      selinux:good({mode:'Enforcing'}),firewall:good({active:true,rules_metadata:'Fictional bounded-preview test: ' + 'example rule metadata; '.repeat(500)}),time_sync:good({synchronized:true}),audit:good({active_state:'active',sub_state:'running'})
    }),
    host('win01', 'windows', {
      identity:good({hostname:'win01.example.test',os_name:'Fictional Windows',os_build:'example-build'}),interfaces:good([{address:'192.0.2.20'}]),tcp:good([]),
      services:{status:'access_denied',data:null},reboot_pending:{status:'access_denied',data:null},hotfixes:good([{id:'KB000000',installed_at:'2026-09-29'}]),
      disks:good([{device_id:'C:',drive_type:3,filesystem:'NTFS',size_bytes:0,free_bytes:0}])
    }),
    host('switch01', 'network', {
      identity:good({hostname:'switch01.example.test',os:'Fictional network OS'}),interfaces:good([{address:'192.0.2.30'}]),neighbors:good([]),services:{status:'unsupported',data:null}
    })
  ];
  inputs.forEach(document => fs.writeFileSync(path.join(evidence,'hosts',document.asset_id + '.json'),JSON.stringify(document)));
  fs.writeFileSync(path.join(evidence,'expected-assets.json'),JSON.stringify({schema_version:1,expected_assets:['app01','win01','switch01','missing01']}));
  const context = {schema_version:1,assets:[
    {id:'app01',owner:'=SUM(1,2)',criticality:'high',role:'Example application',source:'Fictional owner interview',reviewed_at:'2026-10-05',attributes:{backup:'Nightly backup attested; restore test unknown',risk:'Exception review pending',stig_review:'Fictional STIG review worksheet',poam_reference:'Fictional POAM-001'}},
    {id:'win01',owner:'<img src="https://example.invalid/x" onerror="window.__dashboardXss=1"><script>window.__dashboardXss=1</script>',criticality:'medium',source:'Fictional XSS test',reviewed_at:'2026-10-05'},
    {id:'storage01',platform:'infrastructure',label:'storage01.example.test',addresses:['198.51.100.40'],owner:'Example storage team',source:'Fictional inventory',reviewed_at:'2026-10-05'}
  ],relationships:[]};
  const manual = path.join(tmp,'fictional-context.json');
  fs.writeFileSync(manual,JSON.stringify(context));
  const output = path.join(tmp,'fictional-products');
  const python = process.env.CENSUS_REPORT_PYTHON || 'python3';
  const result = spawnSync(python,[path.join(root,'renderer/render.py'),'--evidence',evidence,'--manual',manual,'--output',output],{encoding:'utf8'});
  assert.equal(result.status,0,'Fictional fixture render failed: ' + result.stderr + result.stdout);
  return path.join(output,'dashboards.html');
}

async function main() {
  const root = path.resolve(__dirname,'..');
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(),'census-dashboards-browser-'));
  const input = process.argv[2] || fixture(root,tmp);
  const executablePath = process.env.CENSUS_TEST_BROWSER || undefined;
  const browser = await chromium.launch({headless:true,...(executablePath ? {executablePath} : {})});
  const context = await browser.newContext({viewport:{width:1600,height:1100},acceptDownloads:true});
  const page = await context.newPage();
  page.setDefaultTimeout(10000);
  const exceptions = [], remoteRequests = [];
  page.on('pageerror',error => exceptions.push(error.message));
  page.on('request',request => {if(/^https?:/.test(request.url())) remoteRequests.push(request.url());});
  try {
    await page.goto(pathToFileURL(input).href);
    await page.waitForFunction(() => Boolean(window.CensusDashboards));
    const assetCount = (await page.evaluate(() => window.CensusDashboards.getState())).asset_count;
    assert.ok(assetCount >= 1,'asset register is available');
    assert.match(await page.locator('#snapshot-banner').textContent(),/Snapshot, not live monitoring/);
    assert.match(await page.locator('.sidebar-note').textContent(),/no access controls or redaction/);

    // Each audience is a view of the same offline model, with explicit boundaries.
    for(const view of ['overview','storage','resources','patch','services','security','dependencies','coverage']) {
      await page.locator('.view-button[data-view="' + view + '"]').click();
      assert.equal((await page.evaluate(() => window.CensusDashboards.getState())).view,view);
      assert.equal(await page.locator('.view-button[aria-current="page"]').getAttribute('data-view'),view);
      assert.ok(await page.locator('.panel-evidence').count(),'view includes evidence basis / collection time');
    }
    await page.locator('.view-button[data-view="patch"]').click();
    assert.match(await page.locator('#dashboard-view').textContent(),/Patch currentness: Unknown/);
    assert.ok(!/fully patched|compliant|SLA attained/i.test(await page.locator('#dashboard-view').textContent()));

    await page.locator('.view-button[data-view="overview"]').click();
    await page.locator('#asset-search').fill('app01');
    const filtered = await page.evaluate(() => window.CensusDashboards.getState());
    assert.ok(filtered.filtered_assets.every(id => /app01/.test(id)),'search filters all records');
    await page.locator('#platform-filter').selectOption('windows');
    assert.equal((await page.evaluate(() => window.CensusDashboards.getState())).filtered_assets.length,0,'global filters combine');
    assert.match(await page.locator('#dashboard-view').textContent(),/No assets match/);
    await page.locator('#reset-filters').click();
    assert.equal((await page.evaluate(() => window.CensusDashboards.getState())).filtered_assets.length,assetCount);

    const sort = page.locator('[data-table="overview-assets"] [data-sort="asset_id"]');
    await sort.click();
    assert.equal(await sort.locator('..').getAttribute('aria-sort'),'ascending');
    await sort.click();
    assert.equal(await sort.locator('..').getAttribute('aria-sort'),'descending');

    // Keyboard activation, modal semantics, Escape and return focus.
    const host = page.locator('[data-table="overview-assets"] .asset-button').first();
    const hostId = await host.getAttribute('data-asset-id');
    await host.focus(); await page.keyboard.press('Enter');
    assert.equal(await page.locator('#asset-drawer').evaluate(dialog => dialog.open),true);
    assert.match(await page.locator('#drawer-content').textContent(),/Collection time|Unknown/);
    assert.equal(await page.locator('#drawer-map-link').getAttribute('href'),'dependency-map.html#asset=' + encodeURIComponent(hostId));
    await page.keyboard.press('Escape');
    assert.equal(await page.locator('#asset-drawer').evaluate(dialog => dialog.open),false);
    assert.equal(await page.evaluate(() => document.activeElement.dataset.assetId),hostId);

    if(!process.argv[2]) {
      assert.equal(assetCount,5,'fictional fixture preserves collected / manual / missing assets');
      await page.locator('.view-button[data-view="resources"]').click();
      assert.match(await page.locator('[data-table="resources"]').textContent(),/0.8 \/ 0.6 \/ 0.4/);
      assert.match(await page.locator('[data-table="resources"]').textContent(),/not CPU percentage/);
      await page.locator('.view-button[data-view="overview"]').click();
      await page.locator('#criticality-filter').selectOption('high');
      assert.deepEqual((await page.evaluate(() => window.CensusDashboards.getState())).filtered_assets,['app01']);
      const csv = await page.evaluate(() => window.CensusDashboards.exportCSV());
      assert.ok(csv.includes('"\'=SUM(1,2)"'),'CSV formula-like ownership is escaped');
      const downloadPromise = page.waitForEvent('download'); await page.locator('#export-csv').click();
      const download = await downloadPromise;
      const downloaded = path.join(tmp,'filtered.csv'); await download.saveAs(downloaded);
      assert.equal(fs.readFileSync(downloaded,'utf8'),csv,'portable CSV download matches filtered records');
      await page.locator('#reset-filters').click();
      await page.locator('.view-button[data-view="services"]').click();
      assert.match(await page.locator('#dashboard-view').textContent(),/wazuh-agent.service/);
      assert.match(await page.locator('#dashboard-view').textContent(),/example-job.service/);
      await page.locator('.view-button[data-view="security"]').click();
      assert.match(await page.locator('#dashboard-view').textContent(),/Fictional owner interview/);
      assert.match(await page.locator('#dashboard-view').textContent(),/2026-10-05/);
      assert.match(await page.locator('[data-table="security-context"]').textContent(),/Fictional STIG review worksheet/);
      assert.match(await page.locator('[data-table="security-context"]').textContent(),/Fictional POAM-001/);
      assert.match(await page.locator('[data-table="security"]').textContent(),/Display shortened; inspect source facts/);
      assert.ok((await page.locator('[data-table="security"] tbody tr').first().textContent()).length < 2000,'large control metadata is bounded in fleet tables');
      await page.locator('.view-button[data-view="dependencies"]').click();
      assert.match(await page.locator('[data-table="listeners"]').textContent(),/8443/);
      assert.match(await page.locator('[data-table="relationships"]').textContent(),/Observed endpoint/);
      await page.locator('.view-button[data-view="storage"]').click();
      assert.match(await page.locator('[data-table="storage-mounts"]').textContent(),/manual assertion/);
      assert.match(await page.locator('[data-table="storage-capacity"]').textContent(),/90%/);
      assert.equal(await page.locator('.metric').filter({hasText:'CAPACITY NOT KNOWN'}).locator('strong').textContent(),'4','present invalid capacity record still counts as an evidence gap');
      assert.match(await page.locator('.metric').filter({hasText:'CAPACITY NOT KNOWN'}).textContent(),/1 returned record has invalid or unknown capacity/);
      assert.equal(await page.locator('[data-table="storage-providers"] tbody tr').count(),1);
      assert.equal((await page.locator('[data-table="storage-providers"] tbody tr td').nth(1).textContent()).trim(),'1app01','two mount records count as one distinct observed active client');
      assert.ok((await page.evaluate(()=>window.CensusDashboards.exportCSV())).includes('provider_concentration'),'filtered storage CSV retains provider summary records');
      await page.locator('.view-button[data-view="coverage"]').click();
      assert.match(await page.locator('[data-table="coverage"]').textContent(),/access_denied/);
      assert.match(await page.locator('[data-table="coverage"]').textContent(),/missing host record/);

      // Model text containing markup stays text in tables, drawer and JSON views.
      await page.evaluate(() => window.CensusDashboards.selectAsset('win01'));
      assert.match(await page.locator('#drawer-content').textContent(),/<img src=/);
      assert.equal(await page.evaluate(() => window.__dashboardXss),undefined);
      assert.equal(await page.locator('#drawer-content img, #drawer-content script').count(),0);
      await page.locator('#drawer-done').click();

      // Configurable capacity thresholds must agree with displayed labels/counts.
      const customOutput=path.join(tmp,'custom-threshold-products');
      const customRender=spawnSync(process.env.CENSUS_REPORT_PYTHON || 'python3',[
        path.join(root,'renderer/render.py'),'--evidence',path.join(tmp,'fictional-evidence'),'--manual',path.join(tmp,'fictional-context.json'),
        '--capacity-warning-percent','95','--capacity-critical-percent','99','--output',customOutput
      ],{encoding:'utf8'});
      assert.equal(customRender.status,0,customRender.stderr);
      const customPage=await context.newPage();
      customPage.on('pageerror',error=>exceptions.push(error.message));
      await customPage.goto(pathToFileURL(path.join(customOutput,'dashboards.html')).href);
      await customPage.waitForFunction(()=>Boolean(window.CensusDashboards));
      const customMetric=customPage.locator('.metric').filter({hasText:'FILESYSTEMS AT ≥95% USED'});
      assert.equal(await customMetric.locator('strong').textContent(),'0','95% threshold counts no 90% filesystem');
      await customPage.locator('.view-button[data-view="storage"]').click();
      assert.match(await customPage.locator('#dashboard-view').textContent(),/Warning ≥95% and critical ≥99%/);
      await customPage.close();
    }
    await page.locator('.view-button[data-view="overview"]').click();
    if(process.env.CENSUS_TEST_SCREENSHOT) await page.screenshot({path:process.env.CENSUS_TEST_SCREENSHOT,fullPage:true});
    await page.emulateMedia({media:'print'});
    assert.equal(await page.locator('.sidebar').isVisible(),false,'print contains the selected view, with no sidebar');
    assert.equal(await page.locator('#snapshot-banner').isVisible(),true,'snapshot caveat remains visible in print');
    await page.emulateMedia({media:'screen'});
    await page.setViewportSize({width:390,height:844});
    const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth);
    assert.equal(overflow,false,'mobile tables scroll within panels, not the page');

    // Missing dashboard fields and manual-only/empty data still show useful Unknown states.
    const emptyModel = {collection_mode:'manual_only',nodes:[],census_details:{},gaps:[],relationships:[],dashboards:{}};
    const emptyPath = path.join(tmp,'empty-dashboard.html');
    const html = fs.readFileSync(input,'utf8').replace(/(<script id="dashboard-data"[^>]*>)[\s\S]*?(<\/script>)/,(match,start,end) => start + JSON.stringify(emptyModel) + end);
    fs.writeFileSync(emptyPath,html);
    const emptyPage = await context.newPage();
    emptyPage.on('pageerror',error => exceptions.push(error.message));
    await emptyPage.goto(pathToFileURL(emptyPath).href); await emptyPage.waitForFunction(() => Boolean(window.CensusDashboards));
    assert.equal((await emptyPage.evaluate(() => window.CensusDashboards.getState())).asset_count,0);
    assert.match(await emptyPage.locator('#collection-mode').textContent(),/no census collected/);
    for(const view of ['storage','resources','patch','services','security','dependencies','coverage']) {
      await emptyPage.evaluate(value => window.CensusDashboards.selectView(value),view);
      assert.match(await emptyPage.locator('#dashboard-view').textContent(),/Unknown|No records/);
    }
    await emptyPage.close();
    assert.deepEqual(exceptions,[]); assert.deepEqual(remoteRequests,[]);
    console.log(JSON.stringify({result:'PASS',input,checked:'8 views / combined filters / sorting / keyboard drawer / patch Unknown / assurance attribution / listeners / load averages / configurable thresholds / invalid capacity / distinct provider clients / XSS / no HTTP / filtered formula-safe CSV / print / mobile / absent-data states'},null,2));
  } finally { await browser.close(); }
}
main().catch(error => {console.error(error);process.exit(1);});
