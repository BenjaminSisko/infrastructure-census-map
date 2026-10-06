# Administrator, security and leadership dashboards

Open `products/dashboards.html` after collection or rendering. This is a self-contained offline HTML product: no database, dashboard server, cloud model, external fonts or CDN is required. It uses the same sealed evidence as the interactive dependency map. The archive printed for WinSCP includes both products.

These are **dated census snapshots**, not continuous monitoring. Recollect through an approved scope/window to update them. A browser refresh does not query servers. Audience views are navigation aids, not access controls: everyone holding the HTML can inspect all embedded private evidence. Do not send a full dashboard to a wider audience merely because it has a Leadership tab. Produce and review an appropriately sanitized report separately.

## Views and what they answer

| View | Useful questions | Boundary |
|---|---|---|
| Overview / Leadership | What was collected? Which assets lack owners or criticality? What findings need follow-up? | Coverage is collection completeness, not service availability or compliance. |
| Storage | Which clients use which NFS/SMB providers? What is active versus configured-only? Which local filesystems are near capacity? | Capacity is not SMART, RAID, SAN, backup or end-to-end storage health. |
| Uptime / Resources | When did each host boot? What memory or local-capacity evidence is available? | Boot uptime is not an availability percentage; memory is a point-in-time sample. |
| Patch / Reboot | What kernel/hotfix evidence is installed? What local reboot indicators exist? | Installation dates are not patch currency; no approved baseline means currency Unknown. |
| Services / Agents | Which units report failed state? Which audit/security services were visible? | Stopped is not always failed; running agents do not prove enrollment or log delivery. |
| ISSO / Security evidence | What firewall, SELinux, time-sync and audit observations were collected? Where are the gaps? | These are selected observations, not a STIG/CIS pass or authorization decision. |
| ISSE / Dependencies and exposure | What storage/provider concentrations, endpoint observations and listeners need engineering review? | A listener is not proven external exposure; a connection is not an approved PPS flow. |
| Evidence coverage | Which hosts/sections were missing, restricted, unsupported or incomplete? | Missing evidence is Unknown, not proof that an asset is down. |

Search/filter by asset, platform and criticality where supported. Select a host for its evidence and context, and open it in the map for notes or relationship editing. Export reviewed CSV views or print the chosen view. Browser-exported context must be retained privately and rerendered; a dashboard is not automatically updated from edits in a separate map tab.

## Storage dependencies

See [storage-mapping.md](storage-mapping.md). The graph adds directed **Storage** links from a client to a provider. Active and configured-only relationships retain their mount/share paths, collection source and identity-resolution basis. Configured-only is not synonymous with broken: it may be an intentional on-demand mount. Unknown or ambiguous provider identities remain visible; the renderer performs no DNS/network lookups.

Local capacity warning/critical thresholds default to 80% / 90%. These are triage thresholds, not organizational standards or hardware-health verdicts. Unknown totals, invalid numbers and missing sections must not become 0% used or green status. Remote filesystem capacity is intentionally not probed by the census, to avoid triggering mounts or blocking on unavailable servers.

For a separately reviewed rendering threshold, use the renderer's `--capacity-warning-percent` and `--capacity-critical-percent` options (0 <= warning < critical <= 100). The normal collection/finish helper uses 80/90 defaults; rerunning that helper does not retain thresholds supplied only to a previous direct renderer command. Record custom thresholds with the retained product/change record rather than treating them as policy.

## Patch and assurance inputs

The read-only profile records local RPM/kernel installation evidence or Windows hotfix/reboot observations. It does not refresh package repositories, query Windows Update, install PSWindowsUpdate, download patches, apply updates or reboot. `Get-HotFix` reports a limited update inventory; Microsoft documents that it is not a complete list of every update. [Microsoft Get-HotFix](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.management/get-hotfix)

To decide whether a host is current, your team needs an approved baseline and dated repository/Satellite/WSUS/update-management evidence. Red Hat security-update reporting depends on advisory/package information; the generic kit does not invent that information for an air-gapped repository. [Red Hat security update management](https://docs.redhat.com/en/documentation/red_hat_enterprise_linux/9/html-single/managing_and_monitoring_security_updates/index)

Add ownership, maintenance windows, approved baseline references, scan/STIG review records, POA&M references, backup/restore evidence and risk decisions as attributed **manual context**. Use `model/assurance-context.example.yml` as a format example, not policy. These statements remain entered context with source/review date, not measured compliance. Never infer backup success from a backup agent or infer accreditation from a security service.

No live vulnerability scanner, full STIG parser, RAID/SMART controller adapter, storage-array API, SLO history, patch-baseline comparison engine or continuous metrics service is bundled. These require separately qualified, approved evidence adapters. Do not supply credentials or unredacted scanner/export files in public issues; keep all real records private.

## Local agent task

> Read AGENTS.md, docs/agent-workflow.md, docs/admin-dashboards.md and docs/storage-mapping.md. Verify the supplied private sealed bundle. Render the dashboards and dependency map, preserving Unknowns, configured-versus-active mounts and manual provenance. Explain each finding using its host/section/evidence reference and observation date. Do not claim fully patched, healthy storage, STIG compliance, approved flows, backup success or an availability SLA without the required dated source evidence. Propose owner-confirmation questions and record reviewed context separately; never edit sealed evidence or run remediation.

## Products

- `dashboards.html`: offline views and host drill-down.
- `dashboard-summary.json`: structured facts/findings and interpretation limits for a local LLM.
- `storage-mounts.csv`: client/provider/path/type/state/evidence records.
- `assets-summary.csv`: host summary evidence.
- Existing map/report/matrix products remain included.

The exact new collected fields and limits are documented in the platform guides. Existing older bundles can be rerendered, but absent new health sections remain Unknown; rendering cannot recreate data that was never collected.
