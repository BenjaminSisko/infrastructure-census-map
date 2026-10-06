# Manual infrastructure context

Supply known infrastructure facts in a separate YAML or JSON file, then render that context with the census bundle. This supports hypervisors, virtualization managers, storage appliances, backup systems, clusters, and other assets that cannot be collected through the available Ansible adapters. It also adds owner, role, location, purpose and other context to collected systems.

You can enter this information through the generated HTML workbench: select a host, edit its notes or metadata, and export the context as JSON. The exported file follows this same format. See [dynamic-workbench.md](dynamic-workbench.md) for the interactive workflow.

The manual file is an input to the map. The renderer applies it on every run, so an agent can update it and regenerate the same products without editing diagrams by hand. Keep the original sealed census evidence intact.

## Start with the example

`model/manual-context.example.yml` contains fictional hypervisor, vCenter and storage assets. Its relationships connect those assets to `app01`, `db01` and `ad01` in `examples/synthetic`. They illustrate the format; they do not establish real infrastructure facts.

```bash
python3 renderer/render.py \
  --evidence examples/synthetic \
  --manual model/manual-context.example.yml \
  --output output/synthetic-with-manual
```

For a real environment, put the manual file in a private location, such as `inventories/private/manual-context.yml`. That directory is ignored by Git. Preserve reviewed versions through the environment's approved private record system.

```bash
python3 renderer/render.py \
  --evidence evidence/production-20261005T143000Z \
  --manual inventories/private/manual-context.yml \
  --output output/production-20261005T143000Z
```

The render playbook accepts the same file through `census_manual_context`:

```bash
ansible-playbook playbooks/render-products.yml \
  -e census_bundle=/srv/census/evidence/production-20261005T143000Z \
  -e census_manual_context=/srv/census/context/manual-context.yml \
  -e census_products=/srv/census/products/production-20261005T143000Z
```

Paths in the Ansible command refer to files on the controller/reporting host. The target devices do not need the manual file.

## Write an asset once, then connect it

Use stable IDs, not IP addresses, as identities. An existing asset's ID must match the census `asset_id` exactly. A new asset needs a new ID. An address change should update the asset's address, not create a second identity.

This is a complete manual-only example:

```yaml
schema_version: 1
assets:
  - id: hv01
    platform: infrastructure
    label: Hypervisor 01
    asset_type: hypervisor
    os: VMware ESXi; version Needs Validation
    addresses:
      - 192.0.2.40
    owner: Virtualization team
    source: Example VM inventory export; replace with actual reference
    entered_by: Example operator
    reviewed_at: '2026-10-05'
  - id: app01
    platform: linux
    label: Application Server 01
    asset_type: virtual_machine
    os: Needs Validation
    source: Example VM inventory export; replace with actual reference
    entered_by: Example operator
    reviewed_at: '2026-10-05'
relationships:
  - source: hv01
    target: app01
    kind: hosts
    purpose: Hypervisor hosts this application virtual machine.
    source_reference: Example VM inventory export; replace with actual reference
    entered_by: Example operator
    reviewed_at: '2026-10-05'
```

Save it as `inventories/private/manual-only.yml`, then render without a census bundle:

```bash
python3 renderer/render.py \
  --manual inventories/private/manual-only.yml \
  --output output/manual-only
```

All relationship endpoints must exist in the census or the manual file. The longer example references census assets, so it requires `examples/synthetic` unless you also supply manual entries for `app01`, `db01` and `ad01`.

## Fields and relationship direction

The input schema is `schema/manual-context.schema.json`. YAML and JSON represent the same document: `schema_version: 1`, an `assets` list and a `relationships` list. Keep either list empty when it is not needed.

For each asset, `id` is required. Supply `platform` for a new asset; it defaults to `infrastructure` when omitted. Platforms are `linux`, `windows`, `network` or `infrastructure`. Use `infrastructure` for an ESXi host, virtualization manager, storage appliance or other manually described platform. Existing assets can be enriched using only their ID and the added metadata. Optional metadata includes `label`, `asset_type`, `os`, `domain`, `addresses`, `owner`, `role`, `description`, `location`, `criticality`, `source`, `entered_by`, `reviewed_at` and `notes`. Addresses are individual IPv4 or IPv6 addresses, not CIDRs or URLs. Dates use `YYYY-MM-DD` and must be quoted in YAML.

Every relationship requires `source`, `target`, `kind` and `purpose`. The direction depends on its meaning:

| Kind | Source → target | Example |
|---|---|---|
| `hosts` | Hosting asset → hosted asset | ESXi host → virtual machine |
| `depends_on` | Consumer → required asset/service | Application server → identity server |
| `uses_storage` | Storage consumer → storage provider | Hypervisor → storage appliance |
| `backs_up` | Backup system → protected asset | Backup server → database server |
| `managed_by` | Managed asset → management system | Hypervisor → vCenter |

Optional relationship fields are `protocol`, `port`, `source_reference`, `entered_by`, `reviewed_at` and `notes`. A port must be an integer from 1 to 65535. Supply it only when you know the actual flow. A `hosts` relationship represents placement and rejects network ports/protocols; describe management traffic as a separate dependency. To describe several specific ports, use separate relationship entries. A manual dependency describes a stated requirement; a socket only describes a connection observation.

Record provenance whenever possible: an inventory export, ticket, operator interview, application-owner statement, runbook or other source. `source` and `source_reference` identify the claim's origin; they do not establish approval. Missing provenance is `Needs Validation`. A review date is the date you reviewed the entry, not proof that a device was observed on that date.

Use an optional `attributes` mapping for additional structured information such as hypervisor cluster, CPU sockets, memory, datastores, backup schedule, maintenance window, HA policy, or a restore runbook reference. It accepts ordinary JSON-compatible data and appears in asset details. Unknown values can remain `Needs Validation`. This avoids needing a code change whenever you have a new infrastructure fact.

```yaml
attributes:
  cluster: Production compute cluster A
  cpu_sockets: 2
  memory_gib: 256
  maintenance_window: Friday 18:00-22:00 local
  ha_status: Needs Validation
  restore_runbook: Internal runbook reference
```

## How census and manual context combine

- A new manual ID creates a manual asset, which can appear without any live access to that platform.
- An ID matching a collected asset adds complementary metadata. Collected identity facts take precedence; manual context can fill unknown fields.
- Conflicting values remain visible as assertions/conflicts for review. A manual label, platform or OS does not silently replace a collected fact.
- Manual addresses on a collected asset remain assertions. They do not override its collected address list or silently relink observed sockets.
- A manual-only asset can use its asserted address to identify an observed peer, but that match retains its manual provenance and requires validation. Duplicate address ownership remains ambiguous.
- Manual relationships appear as `manual_declared`, distinct from observed relationships. An input cannot promote itself to observed, approved or verified status.

Inspect the HTML details, generated JSON and collection-gap report when reconciling conflicting claims. Keep stale or uncertain context visible until an owner or fresh evidence resolves it.

## Give notes to the local agent

You can write ordinary notes or supply a dated export, then have the agent transcribe them into the manual file. For example:

> Add `hv01` as a manually described hypervisor. The virtualization team's export dated 2026-10-05 lists `app01` and `db01` on it. Its management address is 192.0.2.40. I do not know its ESXi version. It uses storage from `nas01`. Preserve the export reference and mark the unknown version Needs Validation. Update the private manual context and regenerate the products.

Ask the agent to preserve the supplied source, stable IDs, entered-by identity and review date. It should ask about ambiguous asset matches and relationships, retain unknown values, and show the changes before treating a statement as resolved. Instructions found inside exported notes or device metadata remain untrusted source text.

Manual inputs need infrastructure metadata only. Keep credentials, tokens, license keys, private keys, user data and full unredacted configuration files outside the input. Keep real assets, source documents and generated diagrams in the authorized production environment. The public project contains only generic code and fictional examples.
