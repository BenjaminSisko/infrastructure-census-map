# Infrastructure census and dependency mapping

The language used to describe evidence collected inside an environment and the relationships represented in its diagrams.

## Language

**Asset**:
A distinct managed host or network device identified by a stable inventory identifier. An address is a property of an asset, not its identity.
_Avoid_: IP as server identity

**Census**:
A dated collection of selected infrastructure metadata from an explicit inventory scope.
_Avoid_: full backup, network scan

**Evidence bundle**:
A collection of host evidence documents, expected scope, manifest, checksums, and a collection summary for one census run.
_Avoid_: agent memory, authoritative architecture

**Observation**:
A measured fact from one collection time and source. It may describe a socket, listener, interface, or neighbor without proving purpose or permission.
_Avoid_: approved dependency, verified business requirement

**Dependency**:
A declared relationship in which a consumer requires another service for an identified purpose. Observation alone does not establish the requirement.
_Avoid_: every connection, every firewall rule

**Manual context**:
Attributed information entered by an operator or transcribed by an agent, including assets, ownership, purpose and relationships. Its source and review date are retained independently of census observations.
_Avoid_: observed evidence, automatically verified fact

**Hosting relationship**:
A declared placement in which a physical host or hypervisor hosts a guest asset. It establishes placement rather than network traffic.
_Avoid_: TCP connection

**Manual conflict**:
A discrepancy between an entered assertion and a collected value that needs reconciliation against their sources. Collected evidence remains unchanged.
_Avoid_: silent overwrite

**Workbench**:
The interactive map where an operator explores assets and edits attributed context and notes. Changes apply to entered context and do not alter census evidence.
_Avoid_: live server configuration console

**Draft**:
An operator's local, editable context and layout state awaiting durable export. A browser draft is not the shared infrastructure record.
_Avoid_: saved production source of truth

**Context export**:
A portable manual-context document exported from the workbench for private storage, agent interpretation and regeneration.
_Avoid_: updated census bundle

**Physical neighbor**:
A device/interface relationship reported by LLDP or CDP. It does not establish an application dependency.
_Avoid_: application connection

**Collection gap**:
A section or asset for which the census has incomplete evidence because of access, capability, timeout, or missing scope.
_Avoid_: failed service, offline asset without supporting evidence

**Product**:
A generated diagram, report, or structured model derived from an evidence bundle and declared relationships.
_Avoid_: independent source of truth
