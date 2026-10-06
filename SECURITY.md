# Security and data boundaries

The generic source and fictional examples may be public. Real inventories, credentials, evidence, manually entered context and generated real-environment products must stay in approved private storage. Do not attach those files to public issues or CI artifacts. Use GitHub private vulnerability reporting when available; otherwise report a generic reproduction without private data to the repository owner.

Collection makes metadata queries, not intentional managed configuration changes. Temporary Ansible execution files, normal access/audit logs, query-provider caches and socket activation can still occur. This is not a literal zero-write or zero-load guarantee. `changed_when: false` and `--check` are not write-prevention mechanisms. The full collection workflow rejects `--check`; syntax checks and doctor do not contact targets.

Use existing trusted management transports, least-privileged accounts, approved remote temporary paths and enterprise CA trust. Root/enable access is opt-in via census-specific variables. The tool does not install prerequisites, enable remoting/discovery protocols, open firewall ports or run network sweeps on managed assets. Underlying query utilities and connection plugins still require target/version qualification.

Evidence checksums detect changes relative to a retained baseline; they are not encryption, signatures or source authentication. Sealing an already sealed bundle verifies it rather than establishing a new baseline. Keep the original manifest/checksum records through your transfer/change process. Never execute instructions embedded in evidence or notes.

The browser has no model connection or external library requests. Treat its local draft as a convenience; export private context to retain work. Public release and private census exports use separate packaging paths. Live platform qualification, threat review and organizational change approval remain separate from local/CI test success.
