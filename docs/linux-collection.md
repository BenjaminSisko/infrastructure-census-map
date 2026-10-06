# Linux collection

Use the census_linux group and an existing SSH identity. The playbook invokes an allowlisted collector through ansible.builtin.script, so it can collect a RHEL 7 host using existing Python 3.6 even when a newer Ansible setup module would require a newer target interpreter. This is a compatibility design, not a claim of live RHEL 7 qualification.

```yaml
census_linux:
  hosts:
    app01:
      ansible_host: 192.0.2.10
      ansible_user: census-reader
      census_python: /usr/bin/python3
      census_linux_become: false
```

The baseline covers OS, kernel, CPU, interfaces, IP routes/rules, local neighbor cache, disks, mounts without options, services, timers, installed packages, repository network origins, DNS, TCP/UDP endpoints, firewall metadata, SELinux, GPU inventory, visible containers and VM names. Metadata remains scoped to the current account; rootless container stores owned by other users require their own collection identities. A firewall or hypervisor query can require elevated permission. Set census_linux_become only after selecting the appropriate local account and sudo policy.

It omits full process command lines, environment values, service command lines, application configs, cron commands, mount options, full container inspections, and passwords. Repository credentials, query parameters, and paths are omitted. The initial Linux baseline does not collect AD membership, systemd graph metadata, full VM guest topology, or backup success. These are explicit follow-on profiles; the agent must not invent them.

Each command has an execution timeout and retained output limit. Expected command errors, absent tools and timeouts become section statuses. Python and packages are never installed on a target by this playbook. Linux scripts need an executable temporary filesystem according to your controller connection policy; restricted hosts may need an existing approved remote temporary path.

Reference: [Ansible script module](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/script_module.html).
