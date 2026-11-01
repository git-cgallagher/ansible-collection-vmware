# Changelog

## 0.1.0 — 2026-11-01

First release.

- New module `git_cgallagher.vmware.vm_disk`: creates, grows, attaches,
  reconfigures or removes one virtual disk of a virtual machine, adding the
  SCSI (paravirtual, LSI Logic, LSI Logic SAS, BusLogic), SATA or NVMe
  controller it needs. A disk is addressed by slot or by backing file, so a
  shared VMDK is created by the first VM that asks for it and attached by the
  rest. Options for clustered guests: controller bus sharing, multi-writer
  sharing, eager-zeroed thick provisioning, independent disk modes. Refuses up
  front what vSphere would refuse (SCSI unit 7, out-of-range slots, shrinking,
  in-place type conversion, mode or sharing changes on a powered-on VM). Check
  mode writes nothing, datastore folders included.
- New module `git_cgallagher.vmware.vm_disk_info`: lists a VM's disks (same
  shape as `vm_disk` returns) and disk controllers.
- `module_defaults` group `group/git_cgallagher.vmware.vsphere` for the
  connection options, which also fall back to the `VMWARE_HOST`,
  `VMWARE_USER`, `VMWARE_PASSWORD`, `VMWARE_PORT` and `VMWARE_VALIDATE_CERTS`
  environment variables, like community.vmware.
