# Production canary qualification

The source release is ready for a bounded pilot, not a claim of universal firmware/account compatibility or production certification. Qualify the exact controller Python/Ansible/collection versions, target OS/firmware, account and security policy before expanding the inventory.

## No-change collection boundary

The collection performs metadata queries using existing SSH/WinRM/PSRP/NETCONF paths. It does not intentionally patch, install packages, reboot, restart services, modify network/firewall settings or configure remote access. Temporary execution files, authentication/audit events, caches, socket activation and query load can still occur. Choose approved accounts and temporary paths. Missing access is recorded as a gap, not automatically fixed.

## Acceptance checklist

1. Review the private inventory graph and intended scope before collection. Exclude fragile or degraded devices unless the owner accepts the query load.
2. Record the controller/runtime versions and install only the required pinned profiles. Do not assume RHEL 7/8/9/10 share the same Python or security policy.
3. Run one representative host per platform using `--limit <asset-id>`; the CLI includes localhost automatically. Use a fresh run ID.
4. Confirm expected assets match scope, checksums pass, no host vanished from products, and access/unsupported/timeout gaps are explained.
5. Check relevant audit/configuration records before/after. Confirm no managed application, package, firewall, addressing, route, remoting or discovery setting changed. Ansible's changed flag is not proof of this.
6. Confirm acceptable command duration/output size, temporary-file cleanup, fapolicyd/SELinux/App Control behavior and least-privilege operation. The Linux collector enforces time/output limits; Windows/network volume and plugin timeout behavior need platform checks.
7. Download the exact output archive/checksum through the approved process and verify/extract it on the reporting machine. Open the HTML and exercise notes/export without network access.
8. Review interpretation with an application owner: sockets show observations, not business purpose, initiation, authorization or patch order. Hosting/storage/backup declarations need their own sources.

## Platform matrix to record

| Profile | Prerequisites to verify | Current source/test claim |
|---|---|---|
| Linux | Existing Python 3.6+, SSH, executable approved temp path, query permissions, installed tools | Parser/limit/failure-path tests; live RHEL canaries pending |
| Windows Server 2019/2022 | PowerShell 5.1+, approved WinRM/PSRP endpoint, CA/Kerberos/account/App Control | Local syntax/mocks; actual Windows account/policy canary pending |
| Cisco IOS/IOS XE | Qualified collection/firmware, SSH CLI and AAA query permissions | Syntax/mock normalization; device canary pending |
| Arista EOS | Qualified collection/firmware, SSH CLI and query permissions | Syntax/mock normalization; device canary pending |
| Junos optional compatibility | Deprecated pinned collection, ncclient, pre-existing NETCONF and tested firmware | Optional adapter source; live qualification pending |

Keep the qualification receipt private with the run, dates, exact versions, approver and remaining deviations. Do not upload evidence to public issues. No standing approval is inferred from an example inventory, passing CI or this checklist.
