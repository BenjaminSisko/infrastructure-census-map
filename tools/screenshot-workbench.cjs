/* Development preview helper; not a dependency of the offline product. */
const path = require('node:path');
const {pathToFileURL} = require('node:url');
const {chromium} = require('playwright');

(async () => {
  const input = path.resolve(process.argv[2]);
  const output = path.resolve(process.argv[3]);
  const browser = await chromium.launch({headless:true, ...(process.env.CENSUS_TEST_BROWSER ? {executablePath:process.env.CENSUS_TEST_BROWSER} : {})});
  try {
    const page = await browser.newPage({viewport:{width:1800,height:1050}, deviceScaleFactor:1});
    await page.goto(pathToFileURL(input).href);
    await page.waitForFunction(() => Boolean(window.CensusWorkbench));
    await page.evaluate(() => window.CensusWorkbench.selectHost('app01'));
    await page.getByRole('tab', {name:'Notes',exact:true}).click();
    await page.locator('#focus-host').click();
    await page.screenshot({path:output});
    console.log('Workbench preview saved');
  } finally {
    await browser.close();
  }
})().catch(error => {console.error(error);process.exit(1);});
