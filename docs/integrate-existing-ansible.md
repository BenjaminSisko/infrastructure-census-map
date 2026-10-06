# Integrate into an existing Ansible repository

This guide is for the operator or approved local LLM adding the census kit alongside existing playbooks. It does not authorize running a production census or altering managed configuration. The actual parent repository, inventory and runtime are environment inputs: inspect them rather than inventing their layout.

Use [llm-integration-prompt.md](llm-integration-prompt.md) as the paste-ready task. The example wrapper, inventory overlay and settings file are under `model/integration/`.

## Integration contract

Add a separate entry point that runs the entire census workflow. Do not turn the collector into a patching role or append unrelated configuration plays to its run. Preserve the parent's existing playbooks, roles, inventories, credentials, host keys, `ansible.cfg`, plugins, Vault handling, dependencies and CI. Changes should be additive and reviewable.

The census is a set of **plays**, including controller initialization and export. Use a top-level `import_playbook`, not `include_tasks`/`import_tasks` inside a role. Ansible supports imports at the playbook level; see its [import_playbook reference](https://docs.ansible.com/projects/ansible/latest/collections/ansible/builtin/import_playbook_module.html).

## 1. Inspect the parent repository without exposing secrets

Read its AGENTS.md/CLAUDE.md and workflow instructions first. Record the branch/dirty state, config location, inventory sources, variable layout, collections/roles, controller or execution environment, and approved output path. Preserve all unrelated edits. Use existing branch/review conventions.

Safe local starting points include `git status --short`, file names, `ansible --version` and the inventory graph. Inventory graphs still contain private identities; retain them privately. Inventory plugins or lookups may contact their configured APIs even though no managed task is running.

Do not print full decrypted `ansible-inventory --list`/`--host` output, Vault contents, private keys, tokens or passwords. Avoid broad config dumps, raw SSH/WinRM logs and unnecessary high verbosity. Inspect sensitive values locally only when necessary and report variable names or redacted conclusions. Review callbacks, log_path, fact caches and persistent connection logging so census data is not sent to an unapproved service.

Identify these inputs explicitly:

| Input | What the LLM must establish |
|---|---|
| Parent root/config | Exact repository root and actual active config; do not replace it with the kit example |
| Inventory | Existing files, directories, dynamic plugins and the normal Vault/credential invocation |
| Platform scope | Exact stable aliases/groups mapped to Linux, Windows, IOS/EOS or qualified Junos |
| Runtime | Actual ansible-core/AAP, Ansible interpreter, collections and connection dependencies |
| Private output | Writable persistent controller path, owner, SFTP/WinSCP access and retention policy |
| Source pin | Reviewed kit release/commit/checksum and approved offline import method |
| Run authority | Named canary hosts/account/window, if collection is separately authorized |

Unknowns remain TODO or Needs Validation. Do not guess a hostname, IP, kernel, transport, secret, privilege or firmware version.

## 2. Place a reviewed kit beside the existing playbooks

Recommended layout (adapt names to the parent conventions):

```text
existing-ansible-repo/
├── ansible.cfg                           Existing; preserve it
├── playbooks/
│   ├── existing-maintenance.yml          Existing; preserve it
│   └── collect-infrastructure-census.yml New, separate entry point
├── inventories/                         Existing sources; preserve them
├── private/census/                      Approved ignored private inputs
│   ├── census-groups.yml
│   └── census-settings.yml
├── vendor/infrastructure-census-map/     Reviewed complete source kit
│   ├── playbooks/
│   ├── collectors/
│   ├── tools/
│   ├── renderer/
│   ├── model/
│   └── docs/ ... LICENSE ... VERSION
└── docs/census-integration.md            Parent-specific operating record
```

Import a checksum-verified release archive through the approved media process. Preserve the complete kit tree; do not copy only the playbooks or flatten their directories. Keep license/upstream notices and a version/commit/import receipt. Do not copy the kit's development virtual environment, private output, real inventories or nested .git into the parent repository. A submodule is an option only if the parent's normal workflow supports it; air-gapped checkout must not depend on fetching it from the internet.

Copy `model/integration/collect-infrastructure-census.yml` to the parent's chosen playbook directory. Adjust its relative import only if the directory layout differs. Its contents are simply:

```yaml
---
- name: Run the complete census workflow
  ansible.builtin.import_playbook: ../vendor/infrastructure-census-map/playbooks/collect-census.yml
```

Kit collector/tools paths are relative to the imported playbook's directory. The nested-wrapper fixture is tested on the qualified Ansible runtime; validate it on the real runtime too. Ansible's `playbook_dir` can refer to an imported playbook rather than the command-line wrapper. See [special variables](https://docs.ansible.com/projects/ansible/latest/reference_appendices/special_variables.html).

## 3. Reuse the existing inventory with a minimal private overlay

Adapt `model/integration/census-groups.example.yml` into the approved private location. Load the existing inventory first and the census overlay second. The overlay adds group membership; it does not replace your original host definitions. Multiple sources and child-group composition are supported by Ansible; variable merge order still matters. See [inventory sources and grouping](https://docs.ansible.com/projects/ansible/latest/inventory_guide/intro_inventory.html).

Map verified existing groups beneath `census_linux`, `census_windows`, or the vendor-specific children of `census_network`. A selected host must belong to only one platform profile. The kit checks overlaps among Linux/Windows/network across the full inventory, even outside a canary limit. Separately verify that each network alias belongs to exactly one chosen vendor adapter group (IOS, EOS or qualified Junos); the current guard does not detect overlap among those vendor children. Exclude unsupported network platforms rather than forcing them into an IOS profile.

If a broad group contains the controller, unsupported assets or overlapping platforms, list exact **existing aliases** in the overlay instead:

```yaml
all:
  children:
    census_linux:
      hosts:
        existing-app-alias: {}
        existing-db-alias: {}
```

Typos can create new inventory hosts. Compare the merged aliases with the original inventory; do not rename existing inventory_hostname values or duplicate endpoints. Safe census IDs use letters/numbers, dots, underscores and hyphens, begin with a letter/number, and have at most 128 characters. Flag incompatible aliases for an approved mapping decision rather than changing the production inventory.

Keep localhost out of every census platform group. The template supplies controller-only localhost settings: local connection, the Ansible controller interpreter, no escalation, and a POSIX shell. Higher-precedence inventory/playbook host_vars (especially host_vars/localhost) or extra-vars may override them. Check the effective localhost connection is local, its Python resolves to ansible_playbook_python, become is false, and its shell is sh with /bin/sh. Treat unresolved conflicts as an execution blocker; preserve parent host_vars and propose a census-scoped reconciliation, not a global target override. The fixture tests conflicting inline inventory values only. Existing host/group vars retain addresses, accounts, keys, ProxyJump settings, CA trust and transport details; the census overlay should not duplicate them.

Existing root-only or playbook-adjacent group_vars/host_vars may resolve differently after imports. Running from the parent root alone is not proof that every parent variable was loaded. Inspect inventory-adjacent variable directories and the parent's playbook_vars_root convention; qualify effective **non-secret** connection/privilege variables. Do not move existing variables or blindly inject broad vars_files/extra-vars merely to silence errors.

## 4. Bind config, runtime and census options explicitly

Keep the original ansible.cfg active. When working-directory discovery is uncertain, set an absolute ANSIBLE_CONFIG for this invocation only. Do not disable host-key/certificate validation, replace the root config or change global library paths.

The Ansible interpreter shown by `ansible --version` runs seal/render/export through `ansible_playbook_python`. It needs Python 3.10+, Jinja2 and PyYAML. A successful doctor run using another shell Python does not qualify that interpreter. Linux targets need their existing Python 3.6+ at census_python; this is separate from Ansible's module interpreter.

Review dependencies against the existing pinned environment. Static playbook imports may require ansible.windows even for a Linux-only limit. Do not upgrade the parent's global Ansible/collections or modify an AAP execution environment automatically. Use a separately approved scoped environment/collection path if required; stage dependencies on a matching connected system and install offline only through the documented process.

Adapt `census-settings.example.yml` and pass it as explicit census options with `-e @...`. In particular, census_output_root and the Windows optional role flag are play defaults, so inventory/group_vars of the same name alone may not override them. Import variables or explicit extra-vars do. Use absolute controller paths for output/manual/declared inputs and a fresh run ID each time.

Keep census_linux_become and census_network_become false unless specific read access is separately approved; Windows escalation is disabled. Reject or reconcile inherited **global** extra-vars such as ansible_connection, ansible_become, shell/interpreter or credentials: their precedence can override controller/target safeguards. Do not import the parent's patching extra-var set wholesale.

The standalone `tools/census.py collect` helper accepts one primary inventory **file** and changes Ansible's working directory to the kit root. Invoking it from the parent root does not automatically retain the parent config. For multiple inventories/directories/plugins and established repo conventions, use the wrapper/direct ansible-playbook command below. Trusted --ansible-arg values are an advanced escape hatch, not the recommended integration interface.

## 5. Validate locally before any production run

From the parent repository root, using its approved runtime and credential handling, replace paths with the reviewed inputs:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" ansible-inventory \
  -i inventories/current/hosts.yml -i private/census/census-groups.yml --graph

ANSIBLE_CONFIG="$PWD/ansible.cfg" ansible-playbook \
  -i inventories/current/hosts.yml -i private/census/census-groups.yml \
  playbooks/collect-infrastructure-census.yml \
  -e @private/census/census-settings.yml --syntax-check

ANSIBLE_CONFIG="$PWD/ansible.cfg" ansible-playbook \
  -i inventories/current/hosts.yml -i private/census/census-groups.yml \
  playbooks/collect-infrastructure-census.yml \
  -e @private/census/census-settings.yml \
  --limit 'existing-app-alias,localhost' --list-hosts
```

Also exercise the kit's fictional demo/nested-wrapper fixture, review the additive diff, and confirm the existing maintenance entry points have not changed. These checks are not proof of live Windows/device support. Existing plugins/lookups may have their own approved external reads; a syntax check is not a substitute for that policy review.

Do not use --check as a safety lock: the full collection rejects it. Do not use --tags, --skip-tags or --start-at-task to cherry-pick census tasks; skipping initialization/sealing/export makes an incomplete workflow. Put a scheduler/job label on the separate entry point instead of adding it to a mutating playbook's tag chain.

## 6. A real canary needs separate scope approval

Only after the operator authorizes exact targets/account/window, run the complete wrapper with a fresh run ID and a limit that includes localhost:

```bash
ANSIBLE_CONFIG="$PWD/ansible.cfg" ansible-playbook \
  -i inventories/current/hosts.yml -i private/census/census-groups.yml \
  playbooks/collect-infrastructure-census.yml \
  -e @private/census/census-settings.yml \
  --limit 'existing-app-alias,localhost'
```

Use the parent's existing Vault prompt/identity/credential mechanism; do not put secrets in the command line or census settings. Validate complex limit intersections/exclusions with --list-hosts, including all controller plays. Never widen a canary to all merely because a limited run succeeds. Configuration changes or remediation require separate authority.

## 7. Keep output private and downloadable

The operator-owned default is `$HOME/census-output`. The kit prints the exact archive/checksum paths for WinSCP. Choose approved persistent storage explicitly for a service account or AAP/AWX execution environment; its home may be ephemeral or inaccessible through SFTP. The kit does not implement AWX artifact upload or provision mounts/accounts/firewalls. Preserve the organization's existing export route.

The kit's .gitignore does not protect private files placed elsewhere in the parent. Use the parent's approved ignored private directory or local .git/info/exclude entries; verify `git check-ignore` for census context, overlays, output and archives before staging. Do not remove existing legitimately tracked inventory or rewrite the entire parent .gitignore. Never publish real results to this public kit or CI artifacts. Keep private run IDs/history, checksums and context versions under the normal records process.

## Integration closeout the LLM must provide

- Source version/commit/checksum and parent branch/diff; exact new/adapted file paths.
- Private group/alias mapping, active config/runtime and dependencies, without secrets.
- Exact graph/syntax/demo/fixture checks performed and their results.
- Operator collection command with a named limit and controller initialization/export included.
- Output owner/path, WinSCP transfer instructions, retention and privacy/ignore checks.
- Rollback: revert the additive wrapper/overlay/vendor integration through normal Git review; retain evidence, exports and pre-existing playbooks. No destructive cleanup is automatic.
- Explicit remaining TODOs, authorization gates and live qualification gaps. Distinguish integrated files from an executed canary; never claim production acceptance from documentation or CI alone.
