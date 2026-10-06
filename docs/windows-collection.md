# Collecting Windows Server evidence with Ansible

The Ansible controller opens a PowerShell remoting session to each Windows host, runs `collectors/windows_census.ps1`, and saves its selected metadata on the controller. The collector runs local read queries on the Windows host. It never enables WinRM, creates firewall rules, installs roles, restarts services, or modifies Windows configuration.

This collector targets Windows Server 2019/2022 with Windows PowerShell 5.1 or later. Run Ansible from a Linux controller or a supported automation execution environment; Windows is the managed device. Ansible's Windows guide describes this control/managed-node distinction. [Managing Windows hosts with Ansible](https://docs.ansible.com/projects/ansible-core/2.19/os_guide/intro_windows.html)

## 1. Prepare the controller and existing remoting path

Use your organization's approved remoting configuration. This kit expects an existing WinRM HTTPS listener, access from the controller to TCP 5986, a certificate whose hostname matches the inventory FQDN, and a CA chain trusted by the controller. A domain account with Kerberos is the sample configuration below. The PSRP connection plugin documents HTTPS, CA trust, authentication, and the separate Python dependency. [Ansible PSRP connection](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/psrp_connection.html)

The controller needs:

- The repository's qualified `ansible-core` and `ansible.windows` collection versions.
- `pypsrp` with its Kerberos dependencies in the Python environment that actually runs Ansible. The current PSRP plugin specifies `pypsrp>=0.4.0,<1.0.0`.
- Kerberos runtime tools/libraries, correct realm configuration, DNS resolution to domain services, and synchronized clocks.
- The internal CA certificate chain, readable by the Ansible process.
- A Kerberos ticket or credentials supplied by your approved controller credential mechanism.

The Kerberos guide explains controller prerequisites and ticket management. The controller must be able to contact its domain/KDC during authentication; air-gapped means internal access, not access to the public internet. [Ansible Kerberos authentication](https://docs.ansible.com/projects/ansible/latest/os_guide/windows_winrm_kerberos.html)

For offline installation, stage collection archives, Python wheels, and OS prerequisite RPMs on a connected staging machine matching the controller's OS, architecture, and Python version. Preserve the selected versions and hashes with the deployment bundle. Install from the approved internal source, for example:

```bash
ansible-galaxy collection install /approved-media/collections/ansible-windows-3.8.0.tar.gz
python3 -m pip install --no-index --find-links /approved-media/wheels \
  'pypsrp[kerberos]>=0.4.0,<1.0.0'
```

Use the Python environment containing Ansible. If an execution environment is used, put these dependencies in that image and qualify the image before transfer. Native Kerberos wheels must match the controller platform; prepare them on staging rather than unexpectedly compiling dependencies during a production census.

## 2. Supply a local Windows inventory

Use inventory aliases containing only letters, numbers, dots, underscores, or dashes. The alias becomes the evidence filename and stable asset ID. Keep production inventory and credentials in the internal environment.

```yaml
all:
  children:
    census_windows:
      hosts:
        app-win01.example.test:
          ansible_host: app-win01.example.test
        dc01.example.test:
          ansible_host: dc01.example.test
      vars:
        ansible_connection: ansible.builtin.psrp
        ansible_psrp_protocol: https
        ansible_port: 5986
        ansible_psrp_auth: kerberos
        ansible_psrp_cert_validation: validate
        ansible_psrp_ca_cert: /etc/ansible/pki/internal-ca-chain.pem
        ansible_user: census-reader@EXAMPLE.TEST
        ansible_become: false
```

Use your actual domain, certificates, and account. The example supplies no password. Use `kinit census-reader@EXAMPLE.TEST` for an existing approved ticket workflow, or inject credentials from your automation controller. Do not save a password in plaintext inventory or the evidence bundle. Avoid replacing the FQDN with an IP address: certificate names and Kerberos service principals must resolve to the intended host.

The account needs permission to enter the remoting endpoint and permission for each requested query. Permission to connect does not imply permission to read all CIM classes, firewall rules, or roles. Qualify an account/endpoint combination on a canary. A limited account can still produce a useful partial census: denied sections explicitly report `access_denied`. Microsoft describes endpoint permissions and remote-session requirements. [PowerShell remote requirements](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.core/about/about_remote_requirements?view=powershell-7.5)

## 3. Test the connection, then collect

```bash
ansible -i /internal/inventories/production.yml census_windows \
  -m ansible.windows.win_ping --limit app-win01.example.test

ansible-playbook -i /internal/inventories/production.yml \
  playbooks/collect-census.yml \
  -e census_run_id=prod-20261005T140000Z \
  -e census_output_root=/srv/census/evidence \
  --limit 'app-win01.example.test,localhost'
```

`win_ping` validates Ansible remoting, not ICMP. After reviewing canary evidence, remove `--limit` to collect the selected Windows group. Run `playbooks/collect-census.yml` to collect all enabled platform groups and produce the shared bundle/manifest.

The Windows play saves:

```text
/srv/census/evidence/prod-20261005T140000Z/hosts/
  app-win01.example.test.json
  dc01.example.test.json
```

Use a new `census_run_id` for each observation. The combined wrapper rejects an existing run ID. The lower-level platform play can replace that host's record, so use the combined wrapper for routine collection. Both the run ID and inventory alias are constrained to safe filename characters. No evidence is copied to a public service.

The script sets `$Ansible.Changed = $false` and returns one object. The play persists `output[0]` with a serialization depth suitable for nested sections. This follows the module's structured-output contract. [Ansible win_powershell module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/windows/win_powershell_module.html)

## 4. Read the result and its limits

Each host record contains `schema_version`, `asset_id`, `platform`, collection time, collector version, and named `sections`. Each section has a status, followed by data or a safe reason code.

| Status | Meaning |
|---|---|
| `ok` | Query succeeded; an empty data list is a valid empty result. |
| `not_installed` | A required cmdlet is unavailable in this remoting session. |
| `access_denied` | The query was denied by permissions. |
| `error` | A query failed for another reason; raw exception text is omitted. |
| `skipped` | Optional role collection is disabled, or the module was skipped. |
| `unreachable` | Ansible could not establish or retain a usable connection. |

Missing commands can also reflect a restricted endpoint, not merely absent Windows software. Treat these statuses as collection evidence rather than a reason to remove the server from the map. An unreachable host gets a small `sections.collection` record; other hosts continue.

The default collection includes:

| Section | Selected information |
|---|---|
| `identity` | OS/build, hostname, domain membership, hardware, CPU, memory, last boot. |
| `interfaces`, `dns`, `routes` | Addresses, MACs, prefixes, DNS servers/suffixes, route next hops. |
| `tcp` | Current connections/listeners, address/port pairs, state, PID, process name. |
| `udp` | Local UDP endpoints, PID, process name. |
| `services` | Service name, state, start mode, service-account name, PID, service dependencies. |
| `features` | Installed Windows roles/features. |
| `installed_software` | Selected uninstall-registry name/version/publisher metadata. |
| `disks` | Drive/filesystem identifiers, capacity, free space, mapped provider name. |
| `scheduled_tasks` | Task name/state, action executable basename, trigger type/start. |
| `firewall` | Active profiles and selected rules, port/address filters, actions. |
| `capabilities` | PowerShell version/language mode and available collector commands. |

TCP data is a snapshot, and the `state` field separates listeners from connections. An established connection proves traffic was observed; it does not prove business purpose, approved access, or which application initiated it. Process lookup can race with process exit and then return `null`. [Microsoft Get-NetTCPConnection](https://learn.microsoft.com/en-us/powershell/module/nettcpip/get-nettcpconnection?view=windowsserver2025-ps)

UDP endpoint data does not provide a remote peer. It cannot establish a UDP application dependency by itself. Use approved logs/flow evidence and declared service relationships to explain those paths.

Firewall rules are queried from `ActiveStore`. Rule port/address conditions live in associated filter objects, so the collector queries those too. A permitted path does not establish actual use or organizational approval. [Microsoft Get-NetFirewallRule](https://learn.microsoft.com/en-us/powershell/module/netsecurity/get-netfirewallrule?view=windowsserver2025-ps)

Scheduled-task arguments and working directories are omitted because those often contain credentials or connection strings. That deliberately limits discovery of job destinations. Obtain a separately sanitized, owner-confirmed dependency declaration to fill those gaps. [Microsoft Get-ScheduledTask](https://learn.microsoft.com/en-us/powershell/module/scheduledtasks/get-scheduledtask?view=windowsserver2025-ps)

Installed software is queried from the HKLM uninstall registry views. It is not a complete inventory of portable or per-user software. The collector never queries `Win32_Product`: Microsoft documents that queries of that class can initiate Windows Installer consistency/reconfiguration activity. [Microsoft Windows Installer reconfiguration guidance](https://learn.microsoft.com/en-us/troubleshoot/windows-server/admin-development/windows-installer-reconfigured-all-applications)

## 5. Optional IIS and Active Directory metadata

Enable installed-role metadata explicitly:

```bash
ansible-playbook -i /internal/inventories/production.yml \
  playbooks/collect-census.yml \
  -e census_run_id=prod-roles-20261005T150000Z \
  -e census_output_root=/srv/census/evidence \
  -e census_windows_role_metadata=true \
  --limit 'dc01.example.test,localhost'
```

The IIS section reads site state, application-pool name, and binding protocol/address/port/hostname. It omits physical paths, application settings, passwords, and certificate private keys. The AD section reads domain/forest functional metadata and a domain-controller list. It does not inventory users, groups, memberships, computer accounts, GPO content, or credentials.

These sections use only cmdlets already available on the target. They install no management tools. AD commands may contact a domain controller/AD Web Services and can encounter remoting's credential-delegation restrictions. An AD query failure is explicit evidence. This kit does not turn on CredSSP or credential delegation to bypass it; qualify the approved role-query endpoint/account with the Windows team.

## 6. Troubleshooting without weakening transport settings

| Symptom | Check |
|---|---|
| Certificate verification fails | CA chain, expiry, server-auth certificate, and inventory FQDN/SAN. |
| Kerberos fails | KDC/DNS access, realm, clock offset, ticket, and target SPN. |
| `win_ping` works but a section is denied | Query permissions and remoting endpoint policy. |
| Commands unavailable | Installed role/module and endpoint command visibility. |
| Collection marked `unreachable` | WinRM service/listener, approved TCP 5986 path, timeout, authentication. |
| Script fails under WDAC/App Control | Qualify the module/script signing and language-mode policy on a canary. |

Keep certificate validation enabled and the remoting listener's existing security policy intact. Fix the trust/name/authentication mismatch rather than adding `cert_validation: ignore`, disabling message encryption, or enabling broad trusted-host/firewall rules.

Custom scripts can be constrained by Windows App Control and PowerShell language mode. Ansible documents signing requirements and its current experimental App Control support; the `capabilities.language_mode` field helps identify that environment. This source uses an inline file lookup in `win_powershell`; an organization requiring signed content must qualify its approved signed-script invocation before production use. [Ansible Windows App Control](https://docs.ansible.com/projects/ansible/latest/os_guide/windows_app_control.html)

## Qualification status

The delivered collector has been parsed with PowerShell 7 on macOS, exercised with unavailable-command/optional-role handling, and its playbook passed Ansible syntax checking. These checks validate source structure and offline handling, not Windows Server behavior or a WinRM authentication path. Qualify on Windows Server 2019 and 2022 canaries using the intended production account, PowerShell endpoint, App Control policy, and CA/Kerberos settings. Review the JSON before broad collection.

References were checked against vendor documentation on 2026-10-05. The environment that runs the transferred kit should pin its qualified dependencies; `latest` documentation can change.
