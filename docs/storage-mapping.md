# Read-only storage mount mapping

The storage map answers: **which client uses a share/export provided by which server, and where does it appear locally?** A storage link records a mount observation/configuration, not an approved business dependency or proof of storage-server health.

Example (fictional): `app01` mounts `files01.example.test:/exports/data` at `/data` using NFS. The client is app01, the provider is files01, the export is /exports/data and the local mountpoint is /data.

## Collection

Linux active mounts retain only target, source and filesystem type. Configured mounts use the same fields from `/etc/fstab`; options are omitted because they can contain passwords or credential-file paths. No mount, unmount, mount verification, directory walk, remote share probe, DNS lookup or package installation is performed. `findmnt --fstab` reads the configuration table rather than establishing a mount. [Upstream findmnt documentation](https://www.man7.org/linux/man-pages/man8/findmnt.8.html)

Supported local static autofs declarations can contribute configured mounts. Dynamic/program maps, LDAP/NSS-backed maps, wildcard expansions, replicas and unsupported formats remain explicit gaps. The collector never executes a map or accesses a mountpoint to trigger it. Access restrictions, unsupported versions and collection limits remain visible. This is not universal autofs/systemd/GPO discovery; obtain a sanitized owner declaration for unsupported configuration.

Windows current-session SMB mappings are queried with Get-SmbMapping, plus logical-disk provider information where available. Persisted mappings from the current account's HKCU Network keys may supply configured records. Other users' profiles, unloaded registry hives, GPO drive mappings, service-specific credentials and every Windows NFS implementation are not automatically covered. Microsoft describes mappings with or without a local drive path. [Microsoft Get-SmbMapping](https://learn.microsoft.com/en-us/powershell/module/smbshare/get-smbmapping?view=windowsserver2025-ps)

Credentials and mount options are not report inputs. Credential-bearing source strings are sanitized/omitted; never paste passwords or full mount command lines into manual notes to recover missing detail.

## Interpretation

- **Active:** returned in the current mount/mapping evidence. Not proof that the server responds or that reads/writes succeed.
- **Configured-only:** configuration was observed but no corresponding active entry was returned from a sufficiently collected active section. Often intentional, especially with autofs.
- **Unknown / configuration unknown:** one side was unavailable, partial or not collected; do not assert that a mount is absent or disconnected.
- **Unresolved / ambiguous provider:** no unique exact identity match was available. Keep the provider name/IP and candidates instead of guessing.

Matching uses recorded inventory aliases, collected hostnames and observed addresses. A manual asset/name/address match remains a manual assertion. Short names, FQDN aliases, clustered storage VIPs, DFS namespaces, NAT and duplicate address ownership need explicit reconciliation; the renderer does not silently truncate names or assume a namespace is the physical storage server.

Local bind/device mounts are not server-to-server dependencies. NFS and SMB share sources receive storage links; unsupported remote filesystem types remain a documented capability gap, not a fabricated NFS relationship. The share path is preserved as evidence; a volume label is not a server identity.

## Operational limits

Do not use this snapshot to choose patch order automatically. A storage provider with several observed clients is a useful concentration to review, but the list may omit applications, other namespaces, mounts under different accounts and inactive jobs. Ask the storage/application owners to confirm required dependencies and redundancy before a change.

The HTML and CSV show paths and server names and therefore contain sensitive infrastructure data. Download via the existing approved WinSCP/SFTP route, retain original checksums and evidence, and keep results out of the public source repo.
