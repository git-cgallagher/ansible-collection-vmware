#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Chris Gallagher
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

DOCUMENTATION = r"""
module: vm_disk
short_description: Manage one virtual disk, and the controller it sits on, of a vSphere virtual machine
version_added: 0.1.0
description:
  - Creates, grows, attaches, reconfigures or removes a single virtual disk of a virtual machine, adding the SCSI, SATA
    or NVMe controller it needs when that controller does not exist yet.
  - A disk is addressed by its slot (O(controller_type), O(controller_number), O(unit_number)) or by the backing file it
    uses (O(filename)), or both. A slot address always refers to the same disk on later runs; a file address finds the
    disk wherever it is attached.
  - Built for clustered guests. A SQL Server failover cluster instance needs disks that two virtual machines share
    (O(filename) pointing at the same VMDK from each VM, on a controller with O(controller_bus_sharing=physical),
    O(type=eagerzeroedthick) and O(sharing=multi_writer)); an availability group needs the same disk layout repeated on
    every replica. Both are a loop over this module.
  - Checks what vSphere would refuse before calling it, so a run against the vcsim simulator (which accepts anything)
    fails the same way a real vCenter would, for example a reserved SCSI unit number, a shrink, or a disk mode change on a
    powered-on virtual machine.
author:
  - Chris Gallagher (@git-cgallagher)
options:
  controller_type:
    description:
      - Kind of controller the disk is on.
    type: str
    choices: [paravirtual, lsilogic, lsilogicsas, buslogic, sata, nvme]
    default: paravirtual
  controller_number:
    description:
      - Bus number of the controller, 0 to 3.
      - A missing controller is added, with O(controller_bus_sharing) when given.
    type: int
    default: 0
  controller_bus_sharing:
    description:
      - SCSI bus sharing of the controller. Only valid with a SCSI O(controller_type).
      - Applied when the controller is created. Changing it on an existing controller needs the virtual machine powered
        off; left unset, an existing controller keeps what it has.
      - V(physical) is what shared disks between virtual machines on different hosts need (clustered VMDKs, RDMs).
    type: str
    choices: [nosharing, physical, virtual]
  unit_number:
    description:
      - Unit number of the disk on the controller. Unit 7 is reserved on SCSI controllers; SATA takes 0 to 29, NVMe 0 to
        63 depending on the virtual hardware version.
      - Required unless O(filename) is given, in which case the disk is found by file and O(unit_number) says where to
        put it when it has to be added (the first free unit when unset).
    type: int
  filename:
    description:
      - Datastore path of the backing file, like C([datastore1] sql01/data.vmdk).
      - When the file already exists, it is attached (a shared disk from another virtual machine, or a disk that was
        detached with O(delete_file=false)); otherwise it is created there, folder included.
      - Without it, a new disk is created in the virtual machine's folder on O(datastore) with a name vSphere picks.
    type: str
  size_gb:
    description:
      - Size of the disk in GiB. Required to create a disk; optional when attaching an existing file.
      - A larger size grows the disk. A smaller size fails, since vSphere cannot shrink a virtual disk.
    type: int
  type:
    description:
      - Provisioning of a new disk. V(thin) when unset.
      - An existing disk cannot be converted in place; when set and different from what the disk is, the module fails.
    type: str
    choices: [thin, thick, eagerzeroedthick]
  disk_mode:
    description:
      - Disk mode. V(persistent) for a new disk when unset; an existing disk keeps its mode when unset.
      - Changing it needs the virtual machine powered off. Shared cluster disks are usually V(independent_persistent),
        so snapshots leave them alone.
    type: str
    choices: [persistent, independent_persistent, independent_nonpersistent]
  sharing:
    description:
      - Multi-writer sharing of the disk. V(nosharing) for a new disk when unset; an existing disk keeps its setting
        when unset.
      - Changing it needs the virtual machine powered off.
    type: str
    choices: [nosharing, multi_writer]
  datastore:
    description:
      - Datastore for a new disk without O(filename). The virtual machine's own datastore when unset.
    type: str
  state:
    description:
      - V(present) makes sure the disk (and its controller) exist as described; V(absent) detaches the disk.
    type: str
    choices: [present, absent]
    default: present
  delete_file:
    description:
      - With O(state=absent), also delete the backing file from the datastore.
      - Off by default, like the vSphere client, because a shared disk's file is still in use by the other virtual
        machines.
    type: bool
    default: false
extends_documentation_fragment:
  - git_cgallagher.vmware.vsphere
  - git_cgallagher.vmware.vsphere.vm
attributes:
  check_mode:
    description: Reports what would change without reconfiguring the virtual machine or touching the datastore.
    support: full
  diff_mode:
    description: Not supported; the returned RV(changes) list says what was done.
    support: none
notes:
  - Adding a disk or a controller works on a running virtual machine (hot-add). Changing an existing disk's mode or
    sharing, or an existing controller's bus sharing, does not; the module refuses those while the virtual machine is
    powered on instead of letting vSphere fail the task.
  - Creating a disk at an explicit O(filename) creates the datastore folder first (vSphere does not), outside check
    mode only.
seealso:
  - module: git_cgallagher.vmware.vm_disk_info
"""

EXAMPLES = r"""
- name: SQL Server data, log and tempdb disks on their own paravirtual controller
  git_cgallagher.vmware.vm_disk:
    hostname: vcenter.example.com
    username: svc-ansible@vsphere.local
    password: "{{ vcenter_password }}"
    name: sql01
    controller_type: paravirtual
    controller_number: 1
    unit_number: "{{ item.unit }}"
    size_gb: "{{ item.size_gb }}"
    type: thick
  loop:
    - {unit: 0, size_gb: 200}   # data
    - {unit: 1, size_gb: 100}   # log
    - {unit: 2, size_gb: 50}    # tempdb
  delegate_to: localhost

- name: Shared quorum disk for a failover cluster instance, created by the first node
  git_cgallagher.vmware.vm_disk:
    hostname: vcenter.example.com
    username: svc-ansible@vsphere.local
    password: "{{ vcenter_password }}"
    name: sql01
    controller_type: paravirtual
    controller_number: 2
    controller_bus_sharing: physical
    unit_number: 0
    filename: "[vsanDatastore] sqlfci/quorum.vmdk"
    size_gb: 2
    type: eagerzeroedthick
    disk_mode: independent_persistent
    sharing: multi_writer
  delegate_to: localhost

- name: The same quorum disk attached to the second node (the file exists now, so it is attached, not created)
  git_cgallagher.vmware.vm_disk:
    hostname: vcenter.example.com
    username: svc-ansible@vsphere.local
    password: "{{ vcenter_password }}"
    name: sql02
    controller_type: paravirtual
    controller_number: 2
    controller_bus_sharing: physical
    unit_number: 0
    filename: "[vsanDatastore] sqlfci/quorum.vmdk"
    disk_mode: independent_persistent
    sharing: multi_writer
  delegate_to: localhost

- name: Grow the log disk
  git_cgallagher.vmware.vm_disk:
    hostname: vcenter.example.com
    username: svc-ansible@vsphere.local
    password: "{{ vcenter_password }}"
    name: sql01
    controller_number: 1
    unit_number: 1
    size_gb: 150
  delegate_to: localhost

- name: Detach the tempdb disk and delete its file
  git_cgallagher.vmware.vm_disk:
    hostname: vcenter.example.com
    username: svc-ansible@vsphere.local
    password: "{{ vcenter_password }}"
    moid: vm-1234
    controller_number: 1
    unit_number: 2
    state: absent
    delete_file: true
  delegate_to: localhost
"""

RETURN = r"""
changes:
  description: What the module did (or would do in check mode), in order.
  returned: always
  type: list
  elements: str
  sample: [add_controller, create_disk]
disk:
  description: The disk after the change; what it would look like in check mode. Empty after O(state=absent).
  returned: always
  type: dict
  contains:
    key:
      description: Device key. Unknown (C(null)) for a disk predicted in check mode.
      type: int
    label:
      description: Device label, for example C(Hard disk 2).
      type: str
    controller_type:
      description: Controller kind, as the O(controller_type) choices.
      type: str
    controller_number:
      description: Bus number of the controller.
      type: int
    controller_key:
      description: Device key of the controller.
      type: int
    controller_bus_sharing:
      description: SCSI bus sharing of the controller; C(null) for SATA and NVMe.
      type: str
    unit_number:
      description: Unit number on the controller.
      type: int
    size_gb:
      description: Capacity in GiB.
      type: float
    size_kb:
      description: Capacity in KiB.
      type: int
    filename:
      description: Datastore path of the backing file.
      type: str
    datastore:
      description: Datastore name.
      type: str
    type:
      description: C(thin), C(thick) or C(eagerzeroedthick); C(null) for a backing that is not a flat VMDK.
      type: str
    disk_mode:
      description: Disk mode.
      type: str
    sharing:
      description: C(nosharing) or C(multi_writer).
      type: str
    backing:
      description: Backing class, for example C(FlatVer2BackingInfo).
      type: str
    uuid:
      description: UUID of the backing file. Two virtual machines sharing a VMDK see the same UUID.
      type: str
vm:
  description: The virtual machine the disk belongs to.
  returned: always
  type: dict
  sample: {"name": "sql01", "moid": "vm-1234", "power_state": "poweredOn"}
"""

from ansible.module_utils.basic import AnsibleModule
from ansible.module_utils.common.text.converters import to_native

from ansible_collections.git_cgallagher.vmware.plugins.module_utils import vsphere

VM_PROPERTIES = ("name", "runtime.powerState", "config.hardware.device", "datastore")


def vm_summary(vm, props):
    return {"name": props.get("name"), "moid": vsphere.moid_of(vm), "power_state": props.get("runtime.powerState")}


def find_existing(module, devices, controller):
    """(existing disk or None, device occupying the slot or None)."""
    p = module.params
    existing = None
    occupant = None
    if controller is not None and p["unit_number"] is not None:
        occupant = vsphere.device_in_slot(devices, controller.key, p["unit_number"])
        if isinstance(occupant, vsphere.vim.vm.device.VirtualDisk):
            existing = occupant
    if existing is None and p["filename"]:
        by_file = [d for d in vsphere.disks_of(devices) if getattr(d.backing, "fileName", None) == p["filename"]]
        if by_file:
            if occupant is not None:
                module.fail_json(
                    msg="%s is attached elsewhere on this virtual machine (%s), and the requested slot holds %s"
                    % (p["filename"], by_file[0].deviceInfo.label, occupant.deviceInfo.label)
                )
            existing = by_file[0]
            if p["unit_number"] is not None and (controller is None or existing.controllerKey != controller.key or existing.unitNumber != p["unit_number"]):
                module.fail_json(
                    msg="%s is already attached as %s on another slot; give that slot or leave unit_number unset" % (p["filename"], existing.deviceInfo.label)
                )
    if existing is not None and p["filename"] and getattr(existing.backing, "fileName", None) != p["filename"]:
        module.fail_json(
            msg="Slot %s/%d/%d holds %s backed by %s, not %s"
            % (p["controller_type"], p["controller_number"], p["unit_number"], existing.deviceInfo.label, existing.backing.fileName, p["filename"])
        )
    if occupant is not None and existing is None:
        module.fail_json(
            msg="Slot %s/%d/%d is used by %s, which is not a virtual disk"
            % (p["controller_type"], p["controller_number"], p["unit_number"], occupant.deviceInfo.label)
        )
    return existing


def first_free_unit(devices, controller, controller_type):
    limits = vsphere.CONTROLLER_LIMITS[vsphere.controller_family(controller_type)]
    used = set()
    if controller is not None:
        used = set(getattr(d, "unitNumber", None) for d in devices if getattr(d, "controllerKey", None) == controller.key)
    for unit in range(0, limits["max_unit"] + 1):
        if unit not in used and unit not in limits["reserved_units"]:
            return unit
    return None


def remove_disk(module, vm, props, existing, controllers):
    p = module.params
    changes = ["remove_disk"]
    if p["delete_file"]:
        changes.append("delete_file")
    facts = vsphere.disk_facts(existing, controllers)
    if not module.check_mode:
        spec = vsphere.vim.vm.device.VirtualDeviceSpec(operation=vsphere.vim.vm.device.VirtualDeviceSpec.Operation.remove, device=existing)
        if p["delete_file"]:
            spec.fileOperation = vsphere.vim.vm.device.VirtualDeviceSpec.FileOperation.destroy
        vsphere.reconfigure(vm, [spec])
    return dict(changed=True, changes=changes, disk={}, removed_disk=facts, vm=vm_summary(vm, props))


def predicted_bus_sharing(p, controller):
    """Bus sharing the disk's controller will have: None for SATA/NVMe."""
    if vsphere.controller_family(p["controller_type"]) != "scsi":
        return None
    if p["controller_bus_sharing"]:
        return p["controller_bus_sharing"]
    if controller is not None and hasattr(controller, "sharedBus"):
        return vsphere.option_value(vsphere.BUS_SHARING, controller.sharedBus)
    return "nosharing"


def predicted_new_disk(p, controller, unit_number, attach, datastore_name):
    """What the disk will look like, for check mode."""
    size_kb = p["size_gb"] * vsphere.KB_PER_GB if p["size_gb"] is not None else None
    return {
        "key": None,
        "label": None,
        "controller_type": p["controller_type"],
        "controller_number": p["controller_number"],
        "controller_key": controller.key if controller is not None else None,
        "controller_bus_sharing": predicted_bus_sharing(p, controller),
        "unit_number": unit_number,
        "size_kb": size_kb,
        "size_gb": vsphere.gb_from_kb(size_kb),
        "filename": p["filename"],
        "datastore": vsphere.parse_datastore_path(p["filename"])[0] if p["filename"] else datastore_name,
        "disk_mode": p["disk_mode"] or "persistent",
        "sharing": p["sharing"] or "nosharing",
        "type": p["type"] if attach else (p["type"] or "thin"),
        "backing": "FlatVer2BackingInfo",
        "uuid": None,
    }


def add_disk(module, service_instance, vm, props, devices, controller):
    p = module.params
    vim = vsphere.vim
    changes = []
    datacenter = None
    attach = False
    if p["filename"]:
        datacenter = vsphere.datacenter_of(vm)
        attach = vsphere.datastore_file_exists(service_instance, datacenter, p["filename"])
    if not attach and p["size_gb"] is None:
        module.fail_json(msg="size_gb is required to create a disk" + (" (%s does not exist yet)" % p["filename"] if p["filename"] else ""))

    unit_number = p["unit_number"]
    if unit_number is None:
        unit_number = first_free_unit(devices, controller, p["controller_type"])
        if unit_number is None:
            module.fail_json(msg="No free unit on %s controller %d" % (p["controller_type"], p["controller_number"]))

    if controller is None:
        changes.append("add_controller")
    changes.append("attach_disk" if attach else "create_disk")

    datastore_name = p["datastore"]
    if datastore_name is None and not p["filename"]:
        vm_datastores = props.get("datastore") or []
        if not vm_datastores:
            module.fail_json(msg="The virtual machine has no datastore; give datastore or filename")
        datastore_name = vm_datastores[0].name

    if module.check_mode:
        return dict(changed=True, changes=changes, disk=predicted_new_disk(p, controller, unit_number, attach, datastore_name), vm=vm_summary(vm, props))

    if controller is None:
        vsphere.reconfigure(vm, [vsphere.new_controller(p["controller_type"], p["controller_number"], p["controller_bus_sharing"])])
        devices = vsphere.devices_of(vsphere.get_properties(service_instance, vm, ["config.hardware.device"]))
        controller = vsphere.find_controller(devices, p["controller_type"], p["controller_number"])
        if controller is None:
            module.fail_json(
                msg="vSphere accepted the new %s controller %d but it is not on the virtual machine" % (p["controller_type"], p["controller_number"])
            )

    backing = vim.vm.device.VirtualDisk.FlatVer2BackingInfo(
        diskMode=p["disk_mode"] or "persistent",
        fileName=p["filename"] or "[%s]" % datastore_name,
        sharing=vsphere.api_value(vsphere.DISK_SHARING, p["sharing"] or "nosharing"),
    )
    if not attach:
        backing.thinProvisioned, backing.eagerlyScrub = vsphere.backing_flags(p["type"] or "thin")
    elif p["type"]:
        # vSphere reports an existing file's real provisioning and ignores these;
        # vcsim stores them, and otherwise reports a re-attached file as thick.
        backing.thinProvisioned, backing.eagerlyScrub = vsphere.backing_flags(p["type"])
    disk = vim.vm.device.VirtualDisk(key=-200, controllerKey=controller.key, unitNumber=unit_number, backing=backing)
    if p["size_gb"] is not None:
        disk.capacityInKB = p["size_gb"] * vsphere.KB_PER_GB
    spec = vim.vm.device.VirtualDeviceSpec(operation=vim.vm.device.VirtualDeviceSpec.Operation.add, device=disk)
    if not attach:
        spec.fileOperation = vim.vm.device.VirtualDeviceSpec.FileOperation.create
        if p["filename"]:
            folder = vsphere.split_datastore_file(p["filename"])[0]
            if " " in folder:  # a folder below the datastore root
                service_instance.content.fileManager.MakeDirectory(folder, datacenter, True)
                changes.insert(changes.index("create_disk"), "create_folder")
    vsphere.reconfigure(vm, [spec])

    devices = vsphere.devices_of(vsphere.get_properties(service_instance, vm, ["config.hardware.device"]))
    controllers = vsphere.controllers_of(devices)
    created = vsphere.device_in_slot(devices, controller.key, unit_number)
    if not isinstance(created, vim.vm.device.VirtualDisk):
        module.fail_json(msg="vSphere accepted the disk but nothing is at %s/%d/%d" % (p["controller_type"], p["controller_number"], unit_number))
    return dict(changed=True, changes=changes, disk=vsphere.disk_facts(created, controllers), vm=vm_summary(vm, props))


def update_disk(module, service_instance, vm, props, existing, controller, controllers):
    p = module.params
    vim = vsphere.vim
    powered_on = props.get("runtime.powerState") == "poweredOn"
    changes = []
    specs = []
    current = vsphere.disk_facts(existing, controllers)

    if (
        p["controller_bus_sharing"] is not None
        and hasattr(controller, "sharedBus")
        and vsphere.option_value(vsphere.BUS_SHARING, controller.sharedBus) != p["controller_bus_sharing"]
    ):
        if powered_on:
            module.fail_json(msg="Changing bus sharing of %s from %s to %s needs the virtual machine powered off"
                             % (controller.deviceInfo.label, current["controller_bus_sharing"], p["controller_bus_sharing"]), disk=current)
        controller.sharedBus = vsphere.api_value(vsphere.BUS_SHARING, p["controller_bus_sharing"])
        specs.append(vim.vm.device.VirtualDeviceSpec(operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=controller))
        changes.append("set_controller_bus_sharing")

    if p["type"] is not None and current["type"] is not None and current["type"] != p["type"]:
        module.fail_json(msg="%s is %s and cannot be converted to %s in place" % (current["label"], current["type"], p["type"]), disk=current)

    disk_changed = False
    if p["size_gb"] is not None:
        wanted_kb = p["size_gb"] * vsphere.KB_PER_GB
        if wanted_kb < existing.capacityInKB:
            module.fail_json(msg="%s is %s GiB; a virtual disk cannot shrink to %d GiB" % (current["label"], current["size_gb"], p["size_gb"]), disk=current)
        if wanted_kb > existing.capacityInKB:
            existing.capacityInKB = wanted_kb
            existing.capacityInBytes = wanted_kb * 1024
            disk_changed = True
            changes.append("grow")
    if p["disk_mode"] is not None and current["disk_mode"] != p["disk_mode"]:
        if powered_on:
            module.fail_json(msg="Changing the disk mode of %s from %s to %s needs the virtual machine powered off"
                             % (current["label"], current["disk_mode"], p["disk_mode"]), disk=current)
        existing.backing.diskMode = p["disk_mode"]
        disk_changed = True
        changes.append("set_disk_mode")
    if p["sharing"] is not None and current["sharing"] != p["sharing"]:
        if powered_on:
            module.fail_json(msg="Changing the sharing of %s from %s to %s needs the virtual machine powered off"
                             % (current["label"], current["sharing"], p["sharing"]), disk=current)
        existing.backing.sharing = vsphere.api_value(vsphere.DISK_SHARING, p["sharing"])
        disk_changed = True
        changes.append("set_sharing")
    if disk_changed:
        specs.append(vim.vm.device.VirtualDeviceSpec(operation=vim.vm.device.VirtualDeviceSpec.Operation.edit, device=existing))

    if not changes:
        return dict(changed=False, changes=[], disk=current, vm=vm_summary(vm, props))

    if module.check_mode:
        # The device objects were edited in memory above; describe them.
        return dict(changed=True, changes=changes, disk=vsphere.disk_facts(existing, controllers), vm=vm_summary(vm, props))

    vsphere.reconfigure(vm, specs)
    devices = vsphere.devices_of(vsphere.get_properties(service_instance, vm, ["config.hardware.device"]))
    controllers = vsphere.controllers_of(devices)
    after = [d for d in vsphere.disks_of(devices) if d.key == existing.key]
    if not after:
        module.fail_json(msg="%s disappeared during the reconfiguration" % current["label"])
    return dict(changed=True, changes=changes, disk=vsphere.disk_facts(after[0], controllers), vm=vm_summary(vm, props))


def run(module, service_instance):
    p = module.params
    vm = vsphere.require_vm(service_instance, p)
    props = vsphere.get_properties(service_instance, vm, VM_PROPERTIES)
    devices = vsphere.devices_of(props)
    controllers = vsphere.controllers_of(devices)
    controller = vsphere.find_controller(devices, p["controller_type"], p["controller_number"])
    existing = find_existing(module, devices, controller)

    if p["state"] == "absent":
        if existing is None:
            return dict(changed=False, changes=[], disk={}, vm=vm_summary(vm, props))
        return remove_disk(module, vm, props, existing, controllers)
    if existing is None:
        return add_disk(module, service_instance, vm, props, devices, controller)
    return update_disk(module, service_instance, vm, props, existing, controllers[existing.controllerKey], controllers)


def main():
    argument_spec = dict(
        controller_type=dict(type="str", default="paravirtual", choices=list(vsphere.CONTROLLER_TYPES)),
        controller_number=dict(type="int", default=0),
        controller_bus_sharing=dict(type="str", choices=list(vsphere.BUS_SHARING)),
        unit_number=dict(type="int"),
        filename=dict(type="str"),
        size_gb=dict(type="int"),
        type=dict(type="str", choices=list(vsphere.DISK_TYPES)),
        disk_mode=dict(type="str", choices=list(vsphere.DISK_MODES)),
        sharing=dict(type="str", choices=list(vsphere.DISK_SHARING)),
        datastore=dict(type="str"),
        state=dict(type="str", default="present", choices=["present", "absent"]),
        delete_file=dict(type="bool", default=False),
    )
    argument_spec.update(vsphere.connection_argument_spec())
    argument_spec.update(vsphere.vm_argument_spec())
    module = AnsibleModule(
        argument_spec=argument_spec,
        supports_check_mode=True,
        required_one_of=vsphere.VM_REQUIRED_ONE_OF + [("unit_number", "filename")],
        mutually_exclusive=vsphere.VM_MUTUALLY_EXCLUSIVE,
    )
    p = module.params

    if not vsphere.HAS_PYVMOMI:
        module.fail_json(msg=vsphere.missing_required_lib("pyvmomi"), exception=vsphere.PYVMOMI_IMPORT_ERROR)
    if p["controller_bus_sharing"] is not None and vsphere.controller_family(p["controller_type"]) != "scsi":
        module.fail_json(msg="controller_bus_sharing only applies to SCSI controllers, not %s" % p["controller_type"])
    slot_error = vsphere.validate_slot(p["controller_type"], p["controller_number"], p["unit_number"])
    if slot_error:
        module.fail_json(msg=slot_error)
    if p["size_gb"] is not None and p["size_gb"] < 1:
        module.fail_json(msg="size_gb must be at least 1")

    try:
        service_instance = vsphere.connect(p)
        result = run(module, service_instance)
    except vsphere.VsphereError as e:
        module.fail_json(msg=to_native(e))
    module.exit_json(**result)


if __name__ == "__main__":
    main()
