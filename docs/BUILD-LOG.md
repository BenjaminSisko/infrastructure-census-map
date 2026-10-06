# Build and verification log

## Product goal

Provide a portable infrastructure census for an air-gapped work environment. Operators collect metadata without intentional managed configuration changes, add their own infrastructure notes, and generate editable offline diagrams and reports.

## Release 0.3.0 - 2026-10-06

The release finishes the operator workflow: tools/census.py provides doctor, demo, collect and finish commands; the main playbook renders and exports after collection. The default output is the executing controller account's census-output directory. A private run folder and a separate tar.gz/checksum pair can be downloaded over an existing approved SFTP path using WinSCP.

The transfer archive includes only checksum-listed evidence, a fixed product set and explicit context inputs. Unrelated files and symlinks are rejected or excluded. Existing run IDs are preserved. Additional exports receive unique names rather than replacing a retained archive.

Read-only review found and corrected:

- Linux command output was limited only after being written to a target-side spool. A bounded pipe now enforces the retained-byte limit while the child runs, with timeout/process cleanup.
- Sealing could replace an earlier integrity baseline. Existing seals now verify unchanged data and reject modified or partial baselines.
- Expected hosts without records were absent from the map. They now remain inventory-only nodes with explicit collection gaps.
- Renderer/browser manual-input validation differed. Reserved nested attribute keys and scoped manual IPs now fail before generating an unusable page.
- Manual identity enrichment was shown in measured facts, and an omitted protocol was labeled TCP. Visible census facts now use immutable records and unspecified protocols remain unspecified.
- The public guide used an unignored production inventory path. All real inventory paths now use the protected private directory.

Source privacy and release checks exclude real inventory, collected evidence, private output, runtime dependencies, caches and external credentials. Public fixtures contain only reserved documentation addresses. A private documentation-based integration example is not shipped.

## Verification commands

Run these from the source root using the prepared controller/reporting Python. Commands marked fictional do not contact managed systems.

```bash
python tools/census.py doctor
python -m unittest discover -s tests -v
python -m py_compile collectors/linux_census.py tools/bundle.py tools/census.py tools/offline.py tools/release.py renderer/render.py
ansible-playbook -i inventories/example/hosts.yml playbooks/collect-census.yml --syntax-check -e census_run_id=syntax-review
python tools/census.py demo --run-id fictional-pilot
node --check renderer/static/workbench.js
node tests/workbench-browser.cjs
python tools/release.py --check-only
python tools/release.py --destination dist
```

Doctor reads local prerequisites. Unit tests exercise parsing, validation, integrity, export boundaries and fictional workflows. Syntax-check parses Ansible without executing targets. Demo uses the five fictional host records. Browser tests exercise editing, attribution, export/import, reload, input safety and zero page network requests. The release helper checks tracked generic source before packaging.

The local build used ansible-core 2.21.1 / Python 3.14.6, plus an existing Chrome executable and Playwright for optional browser checks. These workstation versions do not establish production support. The source includes portable developer setup and a matching-system offline staging helper.

Release results: 35 Python tests passed; the complete isolated-browser suite passed; Python compilation, combined Ansible syntax, doctor and the public-source gate passed. A fictional local interpreter-failure collection completed the full seal/render/export flow with its gap retained and no remote host queried. The public repository is https://github.com/BenjaminSisko/infrastructure-census-map. Cloud CI results and release assets are verified through that repository's run/release records; none of those checks establishes live production qualification.

## Earlier increments

- 0.1.0: Linux/Windows/network collector source, expected scope, checksummed evidence and generated SVG/HTML/JSON/CSV/Markdown products.
- 0.1.1: Manual assets, ownership and hosting/storage/backup/management/dependency relationships with independent provenance.
- 0.2.0: Interactive workbench, notes, context editing, scoped browser drafts, JSON import/export, Undo and graph interaction.

Earlier archive releases are retained separately. Detailed private build-path history remains outside the public source.

## Qualification boundary

Local/CI checks prove the tested source behavior, not live firmware, account, policy or runtime compatibility. No production collection or configuration deployment is claimed. Follow docs/qualification.md for canary acceptance and docs/winscp-output.md for private export handling.
