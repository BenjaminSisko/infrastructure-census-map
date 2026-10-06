# Validation record — 2026-10-05

The current source release is 0.3.0. Earlier version checks below are preserved. No production credentials or host facts are included in the generic release, no live Windows/network collection occurred, and no production remoting, packages or network configuration was changed. Private documentation examples remain outside the public release.

## Passed local checks

- Combined collect-census.yml syntax check on ansible-core 2.21.1 / Python 3.14.6.
- Eleven unit tests: IPv4/IPv6 socket parsing, unknown TCP initiator, ambiguous IP ownership, HTML/SVG injection escaping, platform capability gaps, declared relationships remaining declared, filename/asset identity, changed evidence rejection, unsealed-host rejection, and missing expected host records.
- Python source compilation.
- PowerShell source parser on PowerShell 7/macOS.
- Windows mock and unavailable-command checks, structured output round trip, access-denied classification and exception-message exclusion.
- Network unsupported-profile and mocked-facts normalization. Raw configuration/description sentinel did not appear in evidence.
- Combined local failure-path run: missing Linux interpreter, absent PSRP dependency and unsupported network profile each produced its own JSON evidence record. The wrapper retained all three expected assets and sealed the bundle.
- Limited Windows-only run with localhost included: only the selected Windows asset was expected/collected; controller initialization/sealing ran.
- Synthetic bundle checksum verification and HTML/SVG/CSV/JSON/Markdown generation with five fictional assets and seven relationships.
- Synthetic PNG rendered from SVG using existing bundled Node/Sharp. PNG is an optional export, not a dependency of collection or HTML rendering.

## Pending live qualification

1. RHEL 7/8/9/10 canary collection using their existing Python, permissions and executable temporary directory policy.
2. Windows Server 2019/2022 + PowerShell 5.1 + actual production PSRP/WinRM account, CA trust, Kerberos and App Control policy.
3. Cisco IOS/IOS XE and Arista EOS firmware/model/AAA read-permission combinations.
4. Optional Junos compatibility adapter with qualified collection/core/ncclient/firmware versions.
5. Actual transport outage handling (local failure-path tests covered dependency/script failures; device connectivity remains untested).
6. Worst-case volume and duration on large Windows firewall/service/task inventories and large switches.
7. Approved local agent workflow on representative production evidence, with application-owner declarations.

A syntax check or fictional fixture establishes source behavior only. It does not establish production platform support, service health, or application dependency correctness.

## Manual context extension — 0.1.1

Eighteen total tests passed after adding manual YAML/JSON infrastructure context. New checks cover collected/manual identity conflict retention, hypervisor-to-guest placement, manual-only rendering, manual TCP/LLDP identity attribution, duplicate address ambiguity, unsafe input escaping, invalid fields/addresses/ports, hosting cycles, finite structured attributes, and combined manual plus legacy declared inputs. Mixed example produces eight assets and twelve relationships. Both combined and manual-only Ansible rendering entry points executed successfully. SVG and PNG examples were regenerated. These checks exercise entered context and do not assert actual hypervisor state.

## Current product limits

The baseline shows assets, current TCP endpoint observations, LLDP/CDP neighbors, and separately declared dependencies. Linux AD membership, full guest/container dependency graphs, MAC/ARP vendor tables, flow-log/NAT correlation, patch-wave recommendations and automatic multi-run history merging remain follow-on work. Windows role metadata is optional and does not enumerate AD users/groups/GPOs. Only the three documented vendor profiles are implemented; other equipment receives an unsupported record.

## Interactive workbench — 0.2.0, verified 2026-10-06

Twenty-one Python tests passed. Isolated browser tests used the existing Chrome executable with Playwright; no browser installation was required. User-facing checks selected a host, typed and saved a note, reselected the same host without losing text, edited ownership, added an asset/link, exported and downloaded JSON, reloaded the saved draft, and used zoom/fit/drag. Exported context rerendered through Python with the expected notes/ownership and manual asset.

Additional browser checks rejected invalid imports and hosting cycles atomically, preserved measured identity under conflicting manual edits, kept HTML/script strings inert, generated zero HTTP/HTTPS page requests, and supported export when localStorage was blocked. Manual-only workspaces remained separate. Loopback observations stayed on the collecting asset; unresolved peer editing required a stable manual asset; deleting that manual identity retained the observed endpoint. Dynamic identity matching retained manual attribution.

Read-only review found same-asset note loss, transient endpoint annotation loss, stale target attribution and a modal Escape focus race. These were repaired and exercised by browser regression checks. An actual browser screenshot is included in examples/synthetic-with-manual-products/workbench.png. It depicts fictional assets only. Multiuser shared storage, production authentication, and automatic server-side file writes are outside this standalone version; the durable record is the exported manual-context JSON.

The final handoff review also caught a Links-panel footer labeling legacy declared dependencies as collected evidence. Corrected that wording and added a browser assertion that owner-declared dependency cards retain their declared status.

The later private Home Lab documentation example exercised 13 nodes and 21 entered relationships. It exposed overlapping initial hosting groups; group measurement/guest wrapping and an initial-node non-overlap regression were added. Manual-only HTML now persistently says no census collected and does not imply zero gaps means successful collection. The 21 Python tests, portable browser suite and private example edit/export/zero-network checks passed after these changes. Private source data and products remain outside the shareable archive.

## Complete pilot workflow - 0.3.0

Thirty-five Python tests passed after adding workflow/export/offline/release tests. New cases cover bounded live command output, timeout cleanup, immutable resealing, missing expected host visibility, transfer allowlists, generated-output symlink rejection before writes, repeat finish preserving manual context, unique archives, one-command demo, dependency dry-run/checksums/Galaxy working directory and fail-closed public release files.

The full combined-playbook workflow also completed against a fictional local inventory with an intentionally nonexistent collector interpreter. It retained the failure record, sealed it, generated one visible asset with explicit gaps, and printed the archive/checksum WinSCP paths. No remote device or actual host metadata query was performed in that test. The generic release/privacy gate passed for 90 reviewed source/example files.

The full browser suite passed with additional measured-versus-entered identity and unspecified-protocol assertions. Independent read-only reviewers confirmed the corrected validation and attribution behavior on newly rendered pages. The combined playbook syntax check passed. Controller/reporting doctor passed on the local prepared runtime. Public privacy review found no credentials or real network addresses in the candidate source; private output and inventory families are excluded.

GitHub CI is configured to run Python 3.10/3.12 tests, Ansible syntax and browser tests, and a Windows PowerShell parse check using pinned upstream actions and read-only repository permissions. Local/CI success does not close the live qualification checklist above. A matching production controller dependency bundle still requires the actual OS/architecture/Python versions; no developer-host wheels are claimed RHEL-compatible.
