# git_cgallagher.vmware

vSphere automation for clustered workloads, tested in CI against
[vcsim](https://github.com/vmware/govmomi/tree/main/vcsim), VMware's vCenter simulator, so no vCenter or self-hosted
runner is needed.

It starts with the disk layer that SQL Server clusters sit on. An Always On **availability group** needs the same
data, log and tempdb disks on every replica. A **failover cluster instance** also needs disks that every node
shares: one VMDK attached to each VM, on a controller with physical bus sharing, eager-zeroed, multi-writer. Both
are a loop over `vm_disk`.

## Included content

| Name | Type | Description |
|------|------|-------------|
| `git_cgallagher.vmware.vm_disk` | module | Create, grow, attach, reconfigure or remove one virtual disk, and the controller it sits on |
| `git_cgallagher.vmware.vm_disk_info` | module | List a VM's virtual disks and disk controllers |

## Requirements

- ansible-core 2.18 or newer
- `pyvmomi` 9.0 or newer where the modules run (`pip install -r requirements.txt`); usually the controller, with
  `delegate_to: localhost`

## Installation

```bash
ansible-galaxy collection install git_cgallagher.vmware
```

## Usage

```yaml
- name: SQL Server cluster disks
  hosts: localhost
  gather_facts: false
  module_defaults:
    group/git_cgallagher.vmware.vsphere:
      hostname: vcenter.example.com
      username: svc-ansible@vsphere.local
      password: "{{ vcenter_password }}"
  tasks:
    - name: Per-node data, log and tempdb disks (every AAG replica / FCI node)
      git_cgallagher.vmware.vm_disk:
        name: "{{ item.0 }}"
        controller_type: paravirtual
        controller_number: 1
        unit_number: "{{ item.1.unit }}"
        size_gb: "{{ item.1.size_gb }}"
        type: thick
      loop: "{{ ['sql01', 'sql02'] | product([{'unit': 0, 'size_gb': 200}, {'unit': 1, 'size_gb': 100}, {'unit': 2, 'size_gb': 50}]) | list }}"

    - name: Shared quorum disk (FCI). The first node creates the VMDK, the second attaches it.
      git_cgallagher.vmware.vm_disk:
        name: "{{ item }}"
        controller_type: paravirtual
        controller_number: 2
        controller_bus_sharing: physical
        unit_number: 0
        filename: "[vsanDatastore] sqlfci/quorum.vmdk"
        size_gb: 2
        type: eagerzeroedthick
        disk_mode: independent_persistent
        sharing: multi_writer
      loop: [sql01, sql02]
```

[`examples/sql_cluster_disks.yml`](examples/sql_cluster_disks.yml) is the full playbook, including a check that both
nodes see the same VMDK. Every option is in `ansible-doc git_cgallagher.vmware.vm_disk`.

### How `vm_disk` finds a disk

- By **slot**: `controller_type` + `controller_number` + `unit_number`. The same slot is the same disk on every run.
- By **file**: `filename`. An existing file is attached; a missing one is created (folder included). With a slot as
  well, both must agree, or the module fails instead of guessing.

A missing controller is added. Adding disks and controllers works on a running VM. Changing an existing disk's mode
or sharing, or a controller's bus sharing, needs the VM powered off, and the module says so instead of letting the
vSphere task fail. A disk can grow but never shrink, and its provisioning type can't change in place.

### Connection

`hostname`, `username`, `password`, `port` (443) and `validate_certs` (true), with the same environment variable
fallbacks as community.vmware (`VMWARE_HOST`, `VMWARE_USER`, `VMWARE_PASSWORD`, `VMWARE_PORT`,
`VMWARE_VALIDATE_CERTS`). Set them once for every module with `module_defaults` and
`group/git_cgallagher.vmware.vsphere`. A VM is chosen by `name`, `uuid` (BIOS, or instance with
`use_instance_uuid`) or `moid`, optionally within a `datacenter`.

## What vcsim can and can't prove

CI exercises the modules against vcsim: check mode, real changes, a second run that changes nothing, and failure
paths, on a two-node shared-disk layout. vcsim implements the vSphere API's inventory and reconfiguration
behaviour, not real storage or guests. So a green run means the modules drive the API correctly. It does not prove
that a shared disk works for Windows Server Failover Clustering, which needs a real vSphere cluster.

vcsim also accepts some things vSphere refuses (SCSI unit 7, a bus sharing change on a running VM). The module
checks those itself, so it fails the same way on both.

## Not yet

- RDMs (raw device mappings) and vVols.
- Creating, powering or cloning VMs.
- Anything for SQL Server inside the guest.

## Testing

`ansible-test` sanity, units and integration on ansible-core 2.18–2.21, yamllint, ansible-lint, a build check, and
a Molecule scenario that lays down the two-node layout from a remote container. See `AGENTS.md` for the commands.

## License

MIT. See [LICENSE](LICENSE).
