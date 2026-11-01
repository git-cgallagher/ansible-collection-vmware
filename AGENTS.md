# AGENTS.md — ansible-collection-vmware

> Read `~/Code/AGENTS.md` first (workspace-wide rules). This file covers only
> this repo.

## What this is

Public Ansible collection **`git_cgallagher.vmware`** (MIT): vSphere
automation, starting with the disk layer for SQL Server AAG and FCI guests.
Tested against **vcsim** (govmomi's vCenter simulator) only, so CI needs no
vCenter and no self-hosted runner.

- `plugins/modules/vm_disk.py` — one disk per task: create, grow, attach an
  existing VMDK, change mode/sharing/controller bus sharing, remove (optionally
  deleting the file). Adds the controller it needs.
- `plugins/modules/vm_disk_info.py` — every disk (same dict shape as
  `vm_disk`'s `disk`) and disk controller of a VM.
- `plugins/module_utils/vsphere.py` — connection, VM lookup, property reads,
  task waits, controller/disk helpers, and the slot rules.
- `plugins/doc_fragments/vsphere.py` — the connection options (default
  fragment) and the VM selector options (`.vm`).
- `meta/runtime.yml` — action group `vsphere`, so
  `group/git_cgallagher.vmware.vsphere` in `module_defaults` sets the
  connection for every module. **Add each new module to it.**

Standalone on purpose: plain pyvmomi, no dependency on community.vmware or
vmware.vmware, whose module_utils move between releases. The connection
option and env var names match community.vmware so inventories carry over.

## ⚠️ Maturity

Never run against a real vCenter. vcsim proves the API calls are right, not
that a shared disk works for WSFC. Before relying on it for a real cluster,
run `examples/sql_cluster_disks.yml` against a lab vCenter.

## Tests

| Where | What | How |
|---|---|---|
| `tests/unit` | pure helpers in module_utils (slot rules, backing flags, path parsing, mappings) | pytest |
| `tests/integration/targets/module_vm_disk` | vm_disk: check mode (incl. no datastore folder created), create, idempotence, grow/shrink, every refusal, shared disk create + attach on a second VM, powered-off changes, SATA/NVMe, lookup by moid/uuid, absent with and without `delete_file` | playbook against vcsim |
| `tests/integration/targets/module_vm_disk_info` | vm_disk_info: stock layout, lookups, matches what vm_disk returns, failures | playbook against vcsim |
| `tests/integration/molecule/vm_disk` | two-node SQL layout (3 per-node disks + 2 shared) from a remote container, idempotence, both nodes share the same VMDK UUIDs | Molecule, shared driver |

Each integration target's `runme.sh` wraps the playbook in
`tests/integration/targets/setup_vcsim/files/with_vcsim.sh`, which downloads the pinned vcsim
release (checksum-verified, cached in `/tmp`) inside ansible-test's container
and starts it on a free port. The Molecule scenario builds
`tests/integration/targets/setup_vcsim/files/Dockerfile` instead. **The Dockerfile's `ARG` lines
are the only vcsim pin**; `with_vcsim.sh` reads them. Bump version and both
checksums there, from the release's `checksums.txt`.

`tests/integration/targets/setup_vcsim/files/vmctl.py` powers VMs on/off and lists datastore
folders for the tests (the modules don't do either).

## Commands

`ansible-test` needs the checkout at `ansible_collections/git_cgallagher/vmware/`.
Python on this Mac is 3.14 only, so use `--docker default`.

```bash
ansible-test sanity --docker default
ansible-test units --docker default
ansible-test integration --docker default      # ~1 min; downloads vcsim once per container
yamllint . && ansible-lint

# the Molecule scenario, exactly as CI runs it (needs Docker only)
export RUNTIME_IMAGE=$(sed -n 's/^  RUNTIME_IMAGE: //p' .github/workflows/ansible-test.yml)
(cd tests/integration && ../../.github/ci/runtime.sh molecule test -s vm_disk)

ansible-galaxy collection build --force
```

Release flow is the same as the other collections: a PR that changes shipped
files bumps `galaxy.yml` and adds a `CHANGELOG.md` entry (CI-enforced); after
the merge's green run on main, `release.yml` publishes to Galaxy and tags
`v<version>`. `GALAXY_API_KEY` lives in the main-only `galaxy` environment and
comes from Chris. **Merge one PR at a time** and let its release run finish.

## ⚠️ Gotchas (vcsim and pyvmomi)

- **The vcsim harness lives in the hidden target `setup_vcsim`**, not a
  plain folder under `tests/integration`: ansible-test copies only targets
  (and the ones named by `needs/target/...` in `aliases`) into its temp tree,
  so a shared folder outside `targets/` isn't there at run time (`runme.sh`
  exit 127). A new target that uses vcsim needs `needs/target/setup_vcsim`.
- **Never read `vm.runtime` or `vm.summary`.** vcsim serialises an empty
  `faultToleranceState` inside them and pyvmomi (8.x and 9.x) raises
  `AttributeError: 'vim.VirtualMachine.FaultToleranceState' has no attribute ''`,
  which pyvmomi's lazy accessor turns into a bare `AttributeError: runtime`.
  Read leaves through `vsphere.get_properties()` (PropertyCollector):
  `runtime.powerState` works. Don't "simplify" it back.
- **Never use `pyVim.task.WaitForTask`.** It reads `info.name.info.name` while
  a task runs and fails on vcsim's task objects. Use `vsphere.wait_for_task`.
- **vcsim runs with `-api-version 8.0.3.0`** in both launch paths. Its
  default is 6.5; the property-collector rule above is what actually avoids
  the fault, the flag just keeps the negotiated API current.
- **The official `vmware/vcsim` image is amd64-only** and this Mac's Docker
  has no amd64 emulation ("exec format error"). That's why the Dockerfile
  builds from the release tarball for either architecture.
- **vcsim accepts what vSphere refuses**: SCSI unit 7, bus sharing or disk
  mode changes on a powered-on VM, reconfiguring an attached file's type. The
  module checks those itself (`vsphere.validate_slot`, the power-state checks
  in `update_disk`); keep doing so, or vcsim-green won't mean vSphere-green.
  It does refuse shrinking, duplicate slots and attaching a missing file.
- **vcsim doesn't keep a controller's `device` list current** (it listed a
  stale key). `controller_facts()` works out attached devices from each
  device's `controllerKey`.
- **vcsim needs the datastore folder before `fileOperation=create` at an
  explicit path** (`FileNotFound`). vSphere does too for nested folders. The
  module calls `MakeDirectory(createParent=True)` just before creating, never
  in check mode (the check-mode test asserts the folder doesn't appear).
- **vcsim forgets an attached VMDK's provisioning and size**: it reports
  what the attach spec said (thick, capacity 0 when not given). So on attach
  the module passes `type` and `size_gb` through when given (vSphere ignores
  them for an existing file and reports the real ones), and the Molecule
  converge gives both on every node. With them, a re-run is zero-change.
- **A datastore search with no `matchPattern` returns nothing on vcsim.**
  Pass `["*"]` (`vmctl.py ls`) or the file's name (`datastore_file_exists`).
- **pyvmomi 9 raises a plain `Exception` on Python 3.9**, not `ImportError`,
  so the import guard in module_utils catches `Exception`, and
  `tests/unit/requirements.txt` installs pyvmomi on 3.10+ only (ansible-test
  units also runs 3.9). The module reports `missing_required_lib` there.
- **The Dockerfile can't rely on `TARGETARCH`**: the runtime image's docker
  CLI has no buildx, and the legacy builder leaves it empty. It falls back to
  `uname -m`.
- **SCSI controllers must carry `sharedBus`** or pyvmomi refuses to serialise
  the spec (`Field "sharedBus" is not optional`); `vsphere.new_controller`
  always sets it.
- **Molecule has no base config on purpose** (same as aws): the version gate
  counts `.config/` as shipped. `.github/ci/runtime.sh` links the checkout in
  as `git_cgallagher.vmware` under `collections/`.

## TODO

- Prove `examples/sql_cluster_disks.yml` against a real vCenter (a manual
  `workflow_dispatch` job through a tunnel, like isc's `windows-dc`), then
  drop the maturity warning.
- Next modules for the AAG/FCI scaffold: VM create/clone and power state,
  RDMs, anti-affinity (DRS) rules for cluster nodes.
