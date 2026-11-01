#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Chris Gallagher
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: vm_disk_info
short_description: List the virtual disks and disk controllers of a vSphere virtual machine
version_added: 0.1.0
description:
  - Returns every virtual disk of a virtual machine in the same shape M(git_cgallagher.vmware.vm_disk) returns, plus the
    SCSI, SATA and NVMe controllers, so a playbook can check a disk layout, or that two cluster nodes really share a
    VMDK (same backing C(uuid)).
author:
  - Chris Gallagher (@git-cgallagher)
extends_documentation_fragment:
  - git_cgallagher.vmware.vsphere
  - git_cgallagher.vmware.vsphere.vm
attributes:
  check_mode:
    description: Only reads.
    support: full
  diff_mode:
    description: Only reads, so there is nothing to diff.
    support: none
seealso:
  - module: git_cgallagher.vmware.vm_disk
"""

EXAMPLES = r"""
- name: Read sql01's disks
  git_cgallagher.vmware.vm_disk_info:
    hostname: vcenter.example.com
    username: svc-ansible@vsphere.local
    password: "{{ vcenter_password }}"
    name: sql01
  delegate_to: localhost
  register: sql01_disks

- name: Both nodes must share the quorum disk
  ansible.builtin.assert:
    that:
      - (sql01_disks.disks | selectattr('filename', 'search', 'quorum') | map(attribute='uuid') | first)
        == (sql02_disks.disks | selectattr('filename', 'search', 'quorum') | map(attribute='uuid') | first)
"""

RETURN = r"""
disks:
  description:
    - The virtual disks, ordered by controller and unit.
    - Each entry has the keys of M(git_cgallagher.vmware.vm_disk)'s RV(git_cgallagher.vmware.vm_disk#module:disk).
  returned: always
  type: list
  elements: dict
  sample:
    - key: 2000
      label: Hard disk 1
      controller_type: paravirtual
      controller_number: 0
      controller_key: 1000
      controller_bus_sharing: nosharing
      unit_number: 0
      size_gb: 40
      size_kb: 41943040
      filename: "[datastore1] sql01/sql01.vmdk"
      datastore: datastore1
      type: thin
      disk_mode: persistent
      sharing: nosharing
      backing: FlatVer2BackingInfo
      uuid: 6000C29f-1234-5678-9abc-def012345678
controllers:
  description: The disk controllers (SCSI, SATA, NVMe), ordered by type and bus number.
  returned: always
  type: list
  elements: dict
  contains:
    key:
      description: Device key.
      type: int
    label:
      description: Device label.
      type: str
    type:
      description: Controller kind, as the O(git_cgallagher.vmware.vm_disk#module:controller_type) choices.
      type: str
    bus_number:
      description: Bus number.
      type: int
    bus_sharing:
      description: SCSI bus sharing; C(null) for SATA and NVMe.
      type: str
    devices:
      description: Device keys attached to the controller.
      type: list
      elements: int
vm:
  description: The virtual machine.
  returned: always
  type: dict
  sample: {"name": "sql01", "moid": "vm-1234", "power_state": "poweredOn", "uuid": "4237...", "instance_uuid": "5037..."}
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.git_cgallagher.vmware.plugins.module_utils import vsphere

VM_PROPERTIES = ("name", "runtime.powerState", "config.hardware.device", "config.uuid", "config.instanceUuid")


def run(service_instance, params):
    vm = vsphere.require_vm(service_instance, params)
    props = vsphere.get_properties(service_instance, vm, VM_PROPERTIES)
    devices = vsphere.devices_of(props)
    controllers = vsphere.controllers_of(devices)
    disks = [vsphere.disk_facts(d, controllers) for d in vsphere.disks_of(devices)]
    disks.sort(key=lambda d: (d["controller_key"] or 0, d["unit_number"] or 0))
    disk_controllers = [vsphere.controller_facts(c, devices) for c in controllers.values() if vsphere.controller_type_of(c)]
    disk_controllers.sort(key=lambda c: (c["type"], c["bus_number"]))
    return dict(
        changed=False,
        disks=disks,
        controllers=disk_controllers,
        vm={
            "name": props.get("name"),
            "moid": vsphere.moid_of(vm),
            "power_state": props.get("runtime.powerState"),
            "uuid": props.get("config.uuid"),
            "instance_uuid": props.get("config.instanceUuid"),
        },
    )


def main():
    argument_spec = dict()
    argument_spec.update(vsphere.connection_argument_spec())
    argument_spec.update(vsphere.vm_argument_spec())
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=vsphere.VM_REQUIRED_ONE_OF,
        mutually_exclusive=vsphere.VM_MUTUALLY_EXCLUSIVE,
    )
    if not vsphere.HAS_PYVMOMI:
        module.fail_json(msg=vsphere.missing_required_lib("pyvmomi"), exception=vsphere.PYVMOMI_IMPORT_ERROR)
    try:
        service_instance = vsphere.connect(module.params)
        result = run(service_instance, module.params)
    except vsphere.VsphereError as e:
        module.fail_json(msg=to_native(e))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
