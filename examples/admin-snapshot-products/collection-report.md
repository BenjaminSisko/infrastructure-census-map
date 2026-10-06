# Infrastructure evidence report

Assets: 4; relationships: 3; collection gaps: 5; manual conflicts: 0.

Mode: mixed

Observed endpoints do not establish TCP initiator, purpose, authorization, or criticality.

## Collection gaps

- app01: firewall — access_denied (hosts/app01.json)
- app01: reboot_pending — unsupported (hosts/app01.json)
- nas01: memory — access_denied (hosts/nas01.json)
- nas01: patch_inventory — unsupported (hosts/nas01.json)
- win01: udp — access_denied (hosts/win01.json)

## Manual information conflicts


## Manual source

{&quot;path&quot;: &quot;examples/admin-snapshot/context.json&quot;, &quot;sha256&quot;: &quot;3198aa6a158c77481c0f5d1dcde442bb327a2cab501b098b22f1cf3717c4456d&quot;}
