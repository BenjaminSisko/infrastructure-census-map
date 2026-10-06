# Collect and download the output with WinSCP

Output lives on the **Ansible controller**, not across the managed servers. The default is the home directory of the account running Ansible, followed by `census-output`. Run as the operator who will use WinSCP, not sudo/root. An existing approved SFTP path is required; the collector does not create users, enable SSH/SFTP or open firewall ports.

## Normal workflow

From the source directory in your approved controller environment:

```bash
python tools/census.py collect \
  -i inventories/private/hosts.yml \
  --run-id baseline-20261006T140000Z
```

Collection, evidence verification, product rendering and export happen in that command. The final message prints the exact paths. A typical Linux result is:

```text
/home/your-user/census-output/
├── baseline-20261006T140000Z/
│   ├── hosts/                        Collected host JSON
│   ├── expected-assets.json          Selected scope
│   ├── MANIFEST.json                 Evidence manifest and gaps
│   ├── COLLECTION-SUMMARY.md          Read this first
│   ├── SHA256SUMS                    Original sealed-evidence checksums
│   ├── START-HERE.md                 Operator/agent instructions
│   ├── TRANSFER-SHA256SUMS            Transfer file checksums
│   ├── context/manual-context.json   Entered context for the local agent
│   └── products/
│       ├── dependency-map.html       Clickable offline workbench
│       ├── dependency-map.svg
│       ├── map.json
│       ├── dependency-matrix.csv
│       └── collection-report.md
├── census-baseline-20261006T140000Z.tar.gz
└── census-baseline-20261006T140000Z.tar.gz.sha256
```

1. Open WinSCP and use **SFTP** to connect to the Ansible controller with the same approved account. Validate its known host key through your normal process.
2. Browse to the exact **Controller folder** printed by the command.
3. Download the `census-...tar.gz` archive and matching `.sha256` file. You can instead download the readable run folder, but the archive avoids missing individual files.
4. Retain the checksum through the approved transfer process. On a Linux/reporting machine, verify with `sha256sum -c <archive-name>.sha256`. On Windows, compare `Get-FileHash -Algorithm SHA256 <archive-name>` with the checksum file.
5. Extract with approved archive software, then open `products/dependency-map.html` locally. The map needs no web server, network access or model connection.
6. Give the extracted evidence/context and the source kit's AGENTS.md instructions to the approved local agent.

These checksums are not encryption and require no decryption key. They detect changes against the retained baseline; they do not authenticate the original source by themselves.

## Permissions and alternate location

Run directories use mode 0700; evidence and archive/checksum files use mode 0600. They belong to the executing controller account. Do not use chmod 777 to make WinSCP work. If another account must download the output, request your normal narrowly scoped group/ACL arrangement outside this collector.

Use a pre-provisioned writable location when policy requires one:

```bash
python tools/census.py collect -i inventories/private/hosts.yml \
  --run-id baseline-20261006T140000Z \
  --output-root /srv/census-output
```

The tool does not sudo to provision `/srv`; an administrator must already have assigned the operator suitable access. If collection runs in AWX/AAP or a container, the execution environment's home may be temporary or inaccessible through SFTP. Set `census_output_root` to approved persistent/mounted storage and follow the platform's export mechanism; this CLI kit does not create that integration.

## Separate collection and rendering

If the controller cannot render, collect with `--no-render`. The export still includes verified evidence and START-HERE.md, but no products/context are claimed. Supply manual inputs later on the reporting machine:

```bash
python tools/census.py finish --bundle /private/extracted/run-id \
  --manual /private/context/manual-context.json
```

The finish command contacts no managed hosts. It preserves the original evidence seal and creates a new archive when a prior export already exists. Never reuse a run ID for another collection or reseal edited evidence. Exporting again updates generated products/context but does not alter sealed host records.
