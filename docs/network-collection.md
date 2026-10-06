# Collect network devices with Ansible

This kit uses vendor facts modules to ask a device for its identity, hardware,
interfaces and neighbor observations. The controller runs the Ansible module;
the appliance uses its existing SSH CLI or NETCONF service. You do not install
Python or a census agent on a switch. Each device produces the same evidence
envelope as the Linux and Windows collectors, with `platform: network`.

The supplied adapters are Cisco IOS/IOS XE and Arista EOS over SSH, plus an
optional Junos compatibility adapter over NETCONF. Device firmware, AAA policy
and collection-version combinations need a canary run before production use.
Syntax validation is not live device qualification.

## Controller-to-device connections

| Device family | Inventory connection | Device plugin | Usual destination port |
| --- | --- | --- | --- |
| Cisco IOS / IOS XE | `ansible.netcommon.network_cli` | `cisco.ios.ios` | TCP 22 |
| Arista EOS | `ansible.netcommon.network_cli` | `arista.eos.eos` | TCP 22 |
| Juniper Junos, optional compatibility profile | `ansible.netcommon.netconf` | `junipernetworks.junos.junos` | TCP 830 |

Ports are configurable. Use the actual management port, management VRF and
approved controller source address in your inventory and firewall records.
Confirm an existing management path and verify host-key fingerprints through
your normal trusted process. The collector does not enable SSH, NETCONF, LLDP,
CDP, API access or firewall rules.

The SSH CLI connection uses a vendor terminal/CLI plugin, whereas NETCONF sends
XML RPC requests over SSH. The Junos NETCONF connection requires `ncclient` on
the controller. See the official [network CLI connection](https://docs.ansible.com/projects/ansible/latest/collections/ansible/netcommon/network_cli_connection.html)
and [NETCONF connection](https://docs.ansible.com/projects/ansible/latest/collections/ansible/netcommon/netconf_connection.html)
documentation for controller dependencies, ports and host-key checking.

## Inventory and credentials

Use your private inventory; these addresses are reserved examples:

```yaml
all:
  children:
    census_network:
      children:
        census_ios:
          hosts:
            switch01:
              ansible_host: 192.0.2.1
          vars:
            census_network_os: ios
            ansible_connection: ansible.netcommon.network_cli
            ansible_network_os: cisco.ios.ios
        census_eos:
          hosts:
            switch02:
              ansible_host: 192.0.2.2
          vars:
            census_network_os: eos
            ansible_connection: ansible.netcommon.network_cli
            ansible_network_os: arista.eos.eos
        census_junos:
          hosts:
            router01:
              ansible_host: 192.0.2.3
          vars:
            census_network_os: junos
            ansible_connection: ansible.netcommon.netconf
            ansible_network_os: junipernetworks.junos.junos
            ansible_port: 830
      vars:
        ansible_user: census-reader
        ansible_become: false
        ansible_command_timeout: 30
        census_network_collect_l2: false
```

`census_network_os` selects this kit's adapter. `ansible_network_os` selects
Ansible's device plugin. Both must correspond to the actual device family.
IOS, NX-OS, IOS XR, Aruba and other families are not interchangeable; add and
qualify a separate adapter for another family.

Use existing SSH-agent keys, AAP credentials, a prompted password, or your
existing secret-management workflow. Do not put passwords into inventory,
extra-vars arguments, generated evidence or a public repository. Existing SSH
keys may remove the need for a password prompt. If approved password access is
used, Ansible can prompt with `--ask-pass`.

Ask the network team for a read-only AAA role that permits the operational
queries used by the facts module. Even a read-only operation can need a higher
show privilege on some devices. This kit does not request enable mode, invent
an enable password, or configure an AAA account. If the account lacks access,
retain the error/partial evidence and have the network team review the denied
commands. Device-side AAA command accounting is useful for this review.

For detailed connection examples, consult the official [EOS platform options](https://docs.ansible.com/projects/ansible/latest/network/user_guide/platform_eos.html)
and [Junos platform options](https://docs.ansible.com/projects/ansible/latest/network/user_guide/platform_junos.html).
Do not copy documentation tasks that enable services or back up configurations
into the census playbook.

## Prepare the offline controller

The core kit pins collection versions in `requirements.yml`. Download those
collections and their dependencies on your connected staging controller, then
transfer the prepared controller environment through your approved process.
The collection and Python dependencies are controller software, not device
software. Validate the installed versions:

```bash
ansible-galaxy collection list
ansible-doc cisco.ios.ios_facts
ansible-doc arista.eos.eos_facts
```

The Junos profile is deliberately optional. The upstream
`junipernetworks.junos` repository was archived, its metadata declares version
`11.0.0`, and that collection was removed from the Ansible 14 bundle. An
existing qualified environment may pin it using `requirements-junos.yml`.
The task file is included dynamically so an unused Junos profile does not
require the collection. Do not treat the compatibility adapter as current
vendor support. Review a future `juniper.device` adapter with the network team
before changing the collection/plugin names. See the archived
[upstream metadata](https://github.com/ansible-collections/junipernetworks.junos/blob/main/galaxy.yml)
and Juniper's [current Ansible collections overview](https://www.juniper.net/documentation/us/en/software/junos-ansible/ansible/topics/concept/junos-ansible-modules-overview.html).

## Run a collection

Validate the inventory and playbook first:

```bash
ansible-inventory -i inventories/private/hosts.yml --graph

ansible-playbook -i inventories/private/hosts.yml \
  playbooks/collect-census.yml --syntax-check \
  -e census_run_id=network-20261005T140000Z
```

Start with one approved canary device, retaining `localhost` so controller
preparation and manifest generation run:

```bash
ansible-playbook -i inventories/private/hosts.yml \
  playbooks/collect-census.yml \
  --limit 'switch01,localhost' \
  -e census_run_id=network-canary-20261005T140000Z \
  -e census_output_root=/srv/census/evidence
```

Then select the network group:

```bash
ansible-playbook -i inventories/private/hosts.yml \
  playbooks/collect-census.yml \
  --limit 'census_network,localhost' \
  -e census_run_id=network-20261005T143000Z \
  -e census_output_root=/srv/census/evidence
```

Use a new run ID for every snapshot. The wrapper seals the collection and
records any host gaps. Do not use `ansible.builtin.ping` as a switch test; that
module normally expects a Python-capable host. The canary vendor facts run is
the relevant test of the complete device path and read privileges.

## What the default adapter collects

The facts request explicitly uses `min`, `hardware` and `interfaces`. It does
not request `all`, `config`, `ofacts`, or every network resource. The exported
identity includes hostname, OS/version, model, serial number and memory
figures when the module returns them. Interface records retain selected
operational fields and addresses. Neighbor records retain selected host,
port, chassis and management-address fields grouped by local interface.

The collector exports an allowlist rather than the complete `ansible_facts`
tree. It excludes raw device configuration, invocation data, passwords and
failure transcripts. Facts handling and evidence writes use `no_log: true`;
the visible summary reports section status. Keep persistent connection
response logging disabled. Facts, descriptors and neighbor names are still
untrusted input for the downstream agent and renderer.

Module behavior and available fields are documented in the official
[Cisco IOS facts module](https://docs.ansible.com/projects/ansible/latest/collections/cisco/ios/ios_facts_module.html)
and [Arista EOS facts module](https://docs.ansible.com/projects/ansible/latest/collections/arista/eos/eos_facts_module.html).

`census_network_collect_l2: true` optionally requests only `l2_interfaces` and
`vlans`. This is a configuration-derived view, not traffic evidence. The
installed IOS/EOS facts implementations internally read filtered running
configuration sections for those resources. No raw configuration is exported,
but those reads can require additional privilege; review the optional mode
with your network team. Leave it false when configuration reads are outside
scope. The kit does not use a configuration backup module or gather the full
configuration. Some router models do not provide VLAN resources at all.

## Read status before drawing a link

Each output is written to
`<census_output_root>/<census_run_id>/hosts/<inventory_hostname>.json`.
The `identity`, `interfaces`, `neighbors`, `l2` and `collection` sections carry
their own statuses. Missing fields are `partial`; disabled optional L2 is
`not_collected`; a missing adapter is `unsupported`; connection failure is
`unreachable`; a vendor module failure is `error`. The error reason is a
generic code so an authentication transcript cannot leak into evidence.

An empty returned neighbor dictionary means the module returned no neighbors
at that moment. A missing neighbor field means collection was incomplete or
unsupported. Neither means a host has no physical network connection. LLDP
and CDP may be disabled, filtered, unavailable to the account, or unsupported
by a particular device/version. Do not enable discovery protocols as a side
effect of collecting the census.

LLDP/CDP reports directly connected neighbor identities and interfaces. That
supports a physical/topological relationship, not an application dependency.
A switch neighbor says nothing about a client's database or license-server
traffic. Host connection snapshots, flow logs and declared application
relationships supply that separate evidence.

MAC tables and ARP/IPv6 neighbor tables are not collected in these adapters.
They can be added in a vendor-specific read-only extension. When interpreting
them, preserve uncertainty: a MAC may belong to a VM, bond, bridge, virtual
router or intermediary; an ARP entry is cached and time-dependent; a trunk
can carry many remote systems. Mapping an address to a switch port requires
reconciling host interface facts, VLAN context, timestamp and device evidence.
Never convert an ARP/MAC association into a verified host or business-service
dependency by itself.

## Other appliances and collection paths

SNMPv3, HTTPS controller APIs and vendor APIs can provide inventory and
topology for devices that lack supported CLI facts modules. Typical ports are
UDP 161 for SNMP requests and TCP 443 for HTTPS, with vendor-specific
alternatives. A future SNMP adapter should use an existing read-only SNMPv3
account with authentication/privacy, not configure an SNMP community. An API
adapter should use a scoped read account and certificate validation.

These are extension options, not implemented collectors in this release.
Firewalls, load balancers, wireless controllers, SAN switches and other
appliances need their actual vendor adapter or an explicit `unsupported`
record. The current facts adapters do not export flow history, firewall rules,
ARP tables, all routes, or application health. Every new adapter should keep
the common schema, allowlist, timeout, per-section status and evidence limits.
