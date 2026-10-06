# Local development and release checks

Python 3.10+ is required for reporting/controller tools. Linux managed-host collection remains Python 3.6+ compatible. Use an isolated reporting environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements-reporting.txt
python -m unittest discover -s tests -v
python -m py_compile collectors/linux_census.py tools/bundle.py tools/census.py tools/offline.py tools/release.py renderer/render.py
python tools/census.py demo --run-id fictional-check
```

Ansible syntax checks also require the selected installed collections and an approved controller environment. They do not contact targets:

```bash
ansible-playbook -i inventories/example/hosts.yml playbooks/collect-census.yml \
  --syntax-check -e census_run_id=syntax-check
```

## Optional existing-repository integration tests

With the qualified Ansible runtime/collections installed, enable the fictional nested-parent fixtures explicitly:

```bash
CENSUS_RUN_INTEGRATION_TESTS=1 python -m unittest discover -s tests -p test_integration.py -v
```

They create a disposable parent repository with a nested kit, a separate wrapper, two inventory sources and existing inventory-adjacent variables. They verify alias/config preservation, localhost normalization and a full gap export. The fixture's collector interpreter intentionally does not exist, so no actual host metadata is collected. Existing maintenance files are not imported. These tests require no real inventory or credentials and are skipped in ordinary Python-only test runs. They qualify this fixture on the test runtime, not every parent variable layout or production platform.

## Optional browser tests

Node/Playwright are developer test dependencies only. The generated workbench has no npm/CDN runtime dependency. On a connected developer machine:

```bash
npm ci
npx playwright install chromium
python renderer/render.py --evidence examples/synthetic \
  --manual model/manual-context.example.yml \
  --declared model/declared-dependencies.example.json \
  --output examples/synthetic-with-manual-products
python renderer/render.py --manual examples/manual-only/context.yml --output examples/manual-only-products
CENSUS_REPORT_PYTHON="$(command -v python)" node tests/workbench-browser.cjs
```

Set CENSUS_TEST_BROWSER to an existing Chrome/Chromium executable if your machine already supplies one; do not download a browser in production. The suite uses fictional data, checks editing/provenance/export round trips, and rejects page network requests. Optional CENSUS_TEST_SCREENSHOT writes a preview in your chosen private/developer location.

## Public release

Stage only reviewed generic source and fictional examples, never output/, evidence/, private inventories, dependencies, credentials or caches. Run `python tools/release.py --check-only`, inspect `git diff --cached`, then commit. The privacy scanner is an additional guard, not exhaustive secret detection.

Run `python tools/release.py --destination dist` from a clean reviewed release tree. It includes only tracked files, rejects private source families/symlinks/private-path/IP/key/token markers, and writes a source archive plus SHA256SUMS. Keep real-environment example maps outside that archive. GitHub Actions runs generic tests only; no production inventory or credentials are supplied. Its actions are pinned to verified upstream commit SHAs and the workflow has read-only repository permissions, following the [GitHub secure-use guidance](https://docs.github.com/en/actions/reference/security/secure-use).
