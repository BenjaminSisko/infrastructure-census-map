# Third-party dependencies

The source kit does not vendor NVIDIA, Red Hat, MATLAB or other proprietary software/documentation. The operator supplies their own inventory and source records. Public fixtures use reserved documentation addresses.

Ansible, Jinja2, PyYAML, Python libraries, browser-development dependencies and Ansible collections are declared in requirements files or optional developer setup. They retain their respective licenses. A dependency bundle staged by `tools/offline.py` contains those upstream distributions and their metadata/license files; preserve them when transferring or redistributing it. This project's MIT license does not replace upstream licenses.

Optional Junos uses a separately pinned deprecated compatibility collection; its support and licensing remain upstream concerns. The product is independent and is not endorsed or certified by Red Hat, Microsoft, Cisco, Arista, Juniper, NVIDIA or GitHub.
