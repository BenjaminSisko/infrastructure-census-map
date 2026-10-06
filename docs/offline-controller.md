# Prepare the offline Ansible controller

Use a connected staging machine matching the production controller's OS, architecture and Python version. Record your AAP execution-environment or ansible-core version. This kit's local checks used ansible-core 2.21.1; that does not qualify every combination in requirements-controller.in. Use the versions supported by your organization's controller, then lock and qualify that environment before transfer.

The selected collection versions are pinned in requirements.yml. Junos is a separate optional deprecated compatibility collection in requirements-junos.yml. Check the vendor guide before including it. Collections and Python libraries belong on the controller, not on the switch or Windows target.

## Supported staging helper

The source release deliberately does not ship Mac-built wheels as if they were RHEL-compatible. Run the helper on connected staging with the same OS/distribution, architecture and Python major/minor as the offline controller:

```bash
python tools/offline.py stage \
  --destination /approved/staging/census-dependencies \
  --profile controller --confirm-matching-controller
```

It downloads binary wheels and pinned collections, resolves a version lock from actual wheel metadata, records the staging environment, and generates checksums. Optional `--include-junos` adds its separate collection and ncclient; `--profile reporting` stages only rendering dependencies. `--dry-run` prints planned commands without downloads or writes. A missing binary wheel fails clearly; approved staging must supply/build it rather than compiling on production.

Transfer the entire directory, then create a new isolated environment on the matching offline machine:

```bash
python tools/offline.py install \
  --bundle /approved/import/census-dependencies \
  --venv /approved/runtimes/census
```

Installation verifies checksums/environment before creating the environment, uses pip `--no-index` and Galaxy `--offline`, and runs collection installation from the folders containing local tarballs. Existing runtime paths are not overwritten. No managed host is contacted or changed. Set ANSIBLE_COLLECTIONS_PATH to the installed environment's collections directory and use its executables.

Native OS prerequisites such as existing Python/venv, Kerberos libraries, enterprise CA trust and SFTP remain environment inputs. The helper does not download RHEL entitlement RPMs or provision AWX/AAP storage. Target-specific runtime qualification is still required.

## Connected staging

Create an isolated controller Python environment according to your normal process. Install the input requirements and verify compatible versions, then freeze them:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-controller.in
.venv/bin/python -m pip freeze > controller-requirements.lock
.venv/bin/python -m pip download --only-binary=:all: \
  -r controller-requirements.lock --dest wheelhouse
.venv/bin/ansible-galaxy collection download -r requirements.yml -p collections
```

`pip freeze` is an environment inventory, not a hash lock. Generate a checksum manifest for the wheelhouse and collection tarballs under your media process. If binary-only download fails, obtain/build the missing wheel on the matching staging system and document native prerequisites. Do not silently build source distributions on production. Kerberos may require approved system krb5 libraries and development tools on staging; existing production runtime dependencies must also be covered.

If an AAP execution environment is your controller, build and qualify that image on staging instead of layering arbitrary pip packages into an existing managed controller.

## Offline installation

Transfer the generic kit, locked wheels, collection tarballs, dependencies, checksum manifest, and local documentation through the approved import process. Verify the transferred files. Use your existing enterprise CA and credentials locally.

```bash
python3 -m venv .venv
.venv/bin/python -m pip install --no-index --find-links=wheelhouse \
  -r controller-requirements.lock
.venv/bin/ansible-galaxy collection install -r collections/requirements.yml \
  -p ./collections/ansible_collections
```

Inspect the generated collections/requirements.yml: downloaded requirements must refer to local tarball paths. Set ANSIBLE_COLLECTIONS_PATH to the appropriate installed parent directory, or install under your normal Ansible collection path. Inventory, private CA references, passwords and network enable credentials are environment inputs.

For PSRP the Python dependency is pypsrp; for the alternate winrm plugin it is pywinrm. They are different libraries. Kerberos extras are needed when that authentication is selected. NETCONF requires ncclient; vendor libraries depend on the chosen collection. Do not transfer every vendor collection if your inventory uses only a few.

References: [WinRM/PSRP controller libraries](https://docs.ansible.com/projects/ansible/latest/os_guide/windows_winrm.html), [offline collection downloads](https://docs.ansible.com/projects/ansible/latest/collections_guide/collections_downloading.html).
