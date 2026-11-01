# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Chris Gallagher
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

"""Shared vSphere plumbing: connection, VM lookup, property reads, tasks and
virtual disk/controller helpers.

Two rules learned against vcsim (the govmomi simulator the tests run on), both
of which also hold on a real vCenter:

* Read VM state with the PropertyCollector (`get_properties`), never through
  `vm.runtime` or `vm.summary`. vcsim serialises an empty `faultToleranceState`
  inside `runtime`, which pyvmomi cannot deserialise; fetching the leaves the
  module needs (`runtime.powerState`, `config.hardware.device`, ...) avoids it
  and is one round trip instead of several.
* Wait for tasks with `wait_for_task`, never `pyVim.task.WaitForTask`: the
  latter reads `info.name.info.name` while a task is running, which fails on
  vcsim's task objects and made removals flaky.
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import atexit
import re
import ssl
import time
import traceback

from ansible.module_utils.basic import env_fallback, missing_required_lib
from ansible.module_utils.common.text.converters import to_native

PYVMOMI_IMPORT_ERROR = None
try:
    from pyVim.connect import SmartConnect, Disconnect
    from pyVmomi import vim, vmodl

    HAS_PYVMOMI = True
except Exception:  # pylint: disable=broad-except
    # Not just ImportError: pyvmomi 9 raises a plain Exception on Python < 3.10.
    PYVMOMI_IMPORT_ERROR = traceback.format_exc()
    HAS_PYVMOMI = False
    vim = None
    vmodl = None

KB_PER_GB = 1024 * 1024

CONNECTION_OPTIONS = ("hostname", "username", "password", "port", "validate_certs")
VM_OPTIONS = ("name", "uuid", "moid", "use_instance_uuid", "datacenter")
VM_REQUIRED_ONE_OF = [("name", "uuid", "moid")]
VM_MUTUALLY_EXCLUSIVE = [("name", "uuid", "moid")]

SCSI_CONTROLLER_TYPES = ("paravirtual", "lsilogic", "lsilogicsas", "buslogic")
CONTROLLER_TYPES = SCSI_CONTROLLER_TYPES + ("sata", "nvme")
# Highest bus number, highest unit number and the units a guest cannot use,
# per controller family. These are vSphere's rules; vcsim enforces none of
# them, so the module checks them itself.
CONTROLLER_LIMITS = {
    "scsi": {"max_bus": 3, "max_unit": 15, "reserved_units": (7,)},
    "sata": {"max_bus": 3, "max_unit": 29, "reserved_units": ()},
    "nvme": {"max_bus": 3, "max_unit": 63, "reserved_units": ()},
}

DISK_TYPES = ("thin", "thick", "eagerzeroedthick")
DISK_MODES = ("persistent", "independent_persistent", "independent_nonpersistent")
# Option value -> vSphere API value.
DISK_SHARING = {"nosharing": "sharingNone", "multi_writer": "sharingMultiWriter"}
BUS_SHARING = {"nosharing": "noSharing", "physical": "physicalSharing", "virtual": "virtualSharing"}


class VsphereError(Exception):
    """An error the module should report with fail_json."""


# ---------------------------------------------------------------- argument specs


def connection_argument_spec():
    return dict(
        hostname=dict(type="str", required=True, fallback=(env_fallback, ["VMWARE_HOST"])),
        username=dict(type="str", required=True, fallback=(env_fallback, ["VMWARE_USER"])),
        password=dict(type="str", required=True, no_log=True, fallback=(env_fallback, ["VMWARE_PASSWORD"])),
        port=dict(type="int", default=443, fallback=(env_fallback, ["VMWARE_PORT"])),
        validate_certs=dict(type="bool", default=True, fallback=(env_fallback, ["VMWARE_VALIDATE_CERTS"])),
    )


def vm_argument_spec():
    return dict(
        name=dict(type="str"),
        uuid=dict(type="str"),
        moid=dict(type="str"),
        use_instance_uuid=dict(type="bool", default=False),
        datacenter=dict(type="str"),
    )


# ---------------------------------------------------------------- pure helpers


def controller_family(controller_type):
    """'scsi', 'sata' or 'nvme' for an option value of controller_type."""
    if controller_type in SCSI_CONTROLLER_TYPES:
        return "scsi"
    if controller_type in ("sata", "nvme"):
        return controller_type
    raise ValueError("unknown controller type %r" % (controller_type,))


def validate_slot(controller_type, controller_number, unit_number):
    """Return an error message when the slot is impossible on vSphere, else None."""
    limits = CONTROLLER_LIMITS[controller_family(controller_type)]
    if not 0 <= controller_number <= limits["max_bus"]:
        return "controller_number must be between 0 and %d for a %s controller" % (limits["max_bus"], controller_type)
    if unit_number is None:
        return None
    if not 0 <= unit_number <= limits["max_unit"]:
        return "unit_number must be between 0 and %d on a %s controller" % (limits["max_unit"], controller_type)
    if unit_number in limits["reserved_units"]:
        return "unit_number %d is reserved for the %s controller itself" % (unit_number, controller_type)
    return None


def disk_type_from_backing(thin_provisioned, eagerly_scrub):
    if thin_provisioned:
        return "thin"
    if eagerly_scrub:
        return "eagerzeroedthick"
    return "thick"


def backing_flags(disk_type):
    """(thinProvisioned, eagerlyScrub) for a disk type."""
    if disk_type == "thin":
        return True, False
    if disk_type == "eagerzeroedthick":
        return False, True
    if disk_type == "thick":
        return False, False
    raise ValueError("unknown disk type %r" % (disk_type,))


def api_value(mapping, option_value):
    return mapping[option_value]


def option_value(mapping, api_value_):
    """Reverse lookup; an API value the mapping doesn't know comes back as is."""
    for option, api in mapping.items():
        if api == api_value_:
            return option
    return api_value_


def gb_from_kb(kb):
    if kb is None:
        return None
    gb = kb / float(KB_PER_GB)
    return int(gb) if gb == int(gb) else round(gb, 3)


def parse_datastore_path(path):
    """'[ds1] dir/file.vmdk' -> ('ds1', 'dir/file.vmdk'); None when not a datastore path."""
    if not path:
        return None
    match = re.match(r"^\[([^\]]+)\]\s*(.*)$", path)
    if not match:
        return None
    return match.group(1), match.group(2)


def split_datastore_file(path):
    """'[ds1] dir/sub/file.vmdk' -> ('[ds1] dir/sub', 'file.vmdk'); the folder is '[ds1]' at the root."""
    parsed = parse_datastore_path(path)
    if parsed is None:
        raise VsphereError("%r is not a datastore path like '[datastore1] folder/disk.vmdk'" % (path,))
    datastore, relative = parsed
    relative = relative.strip("/")
    if "/" in relative:
        folder, basename = relative.rsplit("/", 1)
        return "[%s] %s" % (datastore, folder), basename
    return "[%s]" % datastore, relative


# ---------------------------------------------------------------- connection


def fault_message(fault):
    """A one-line description of a pyvmomi fault or exception."""
    name = type(fault).__name__
    details = []
    msg = getattr(fault, "msg", None)
    if msg:
        details.append(to_native(msg))
    for attr in ("file", "name", "property", "reason"):
        value = getattr(fault, attr, None)
        if value and isinstance(value, (str, bytes)):
            details.append("%s=%s" % (attr, to_native(value)))
    if not details:
        details.append(to_native(fault))
    return "%s: %s" % (name, "; ".join(details))


def connect(params):
    """Connect with the connection options; returns a ServiceInstance that disconnects at exit."""
    if not HAS_PYVMOMI:
        raise VsphereError(missing_required_lib("pyvmomi"))
    context = None
    if not params["validate_certs"]:
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    try:
        service_instance = SmartConnect(
            host=params["hostname"],
            port=params["port"],
            user=params["username"],
            pwd=params["password"],
            sslContext=context,
        )
    except vim.fault.InvalidLogin:
        raise VsphereError("Login to %s:%s as %s failed: invalid credentials" % (params["hostname"], params["port"], params["username"]))
    except vmodl.MethodFault as e:
        raise VsphereError("Connecting to %s:%s failed: %s" % (params["hostname"], params["port"], fault_message(e)))
    except (OSError, ssl.SSLError) as e:
        raise VsphereError("Connecting to %s:%s failed: %s" % (params["hostname"], params["port"], to_native(e)))
    atexit.register(Disconnect, service_instance)
    return service_instance


def moid_of(obj):
    return obj._moId  # pylint: disable=protected-access


# ---------------------------------------------------------------- reads


def get_properties(service_instance, obj, paths):
    """Fetch the named properties of one managed object in one call: {path: value}."""
    collector = service_instance.content.propertyCollector
    filter_spec = vmodl.query.PropertyCollector.FilterSpec(
        objectSet=[vmodl.query.PropertyCollector.ObjectSpec(obj=obj, skip=False)],
        propSet=[vmodl.query.PropertyCollector.PropertySpec(type=type(obj), pathSet=list(paths))],
    )
    result = collector.RetrievePropertiesEx([filter_spec], vmodl.query.PropertyCollector.RetrieveOptions())
    props = {}
    if result and result.objects:
        for prop in result.objects[0].propSet:
            props[prop.name] = prop.val
    return props


def list_names(service_instance, root, vim_type):
    """[(object, name)] for every object of vim_type under root, in one or a few calls."""
    content = service_instance.content
    view = content.viewManager.CreateContainerView(root, [vim_type], True)
    try:
        traversal = vmodl.query.PropertyCollector.TraversalSpec(name="view", path="view", skip=False, type=vim.view.ContainerView)
        filter_spec = vmodl.query.PropertyCollector.FilterSpec(
            objectSet=[vmodl.query.PropertyCollector.ObjectSpec(obj=view, skip=True, selectSet=[traversal])],
            propSet=[vmodl.query.PropertyCollector.PropertySpec(type=vim_type, pathSet=["name"])],
        )
        collector = content.propertyCollector
        found = []
        result = collector.RetrievePropertiesEx([filter_spec], vmodl.query.PropertyCollector.RetrieveOptions())
        while result:
            for entry in result.objects:
                names = [p.val for p in entry.propSet if p.name == "name"]
                found.append((entry.obj, names[0] if names else None))
            if not result.token:
                break
            result = collector.ContinueRetrievePropertiesEx(result.token)
        return found
    finally:
        view.Destroy()


def find_datacenter(service_instance, name):
    matches = [obj for obj, dc_name in list_names(service_instance, service_instance.content.rootFolder, vim.Datacenter) if dc_name == name]
    if not matches:
        raise VsphereError("Datacenter %r not found" % (name,))
    return matches[0]


def find_vm(service_instance, params):
    """The VM the vm options describe, or None when it does not exist."""
    content = service_instance.content
    datacenter = find_datacenter(service_instance, params["datacenter"]) if params.get("datacenter") else None
    if params.get("moid"):
        root = datacenter.vmFolder if datacenter else content.rootFolder
        for obj, dummy in list_names(service_instance, root, vim.VirtualMachine):
            if moid_of(obj) == params["moid"]:
                return obj
        return None
    if params.get("uuid"):
        return content.searchIndex.FindByUuid(datacenter, params["uuid"], True, bool(params.get("use_instance_uuid")))
    root = datacenter.vmFolder if datacenter else content.rootFolder
    matches = [obj for obj, name in list_names(service_instance, root, vim.VirtualMachine) if name == params["name"]]
    if len(matches) > 1:
        raise VsphereError(
            "%d virtual machines are named %r; narrow the search with datacenter, or use uuid or moid" % (len(matches), params["name"])
        )
    return matches[0] if matches else None


def describe_vm_selector(params):
    for key in ("name", "uuid", "moid"):
        if params.get(key):
            return "%s=%s" % (key, params[key])
    return "?"


def require_vm(service_instance, params):
    vm = find_vm(service_instance, params)
    if vm is None:
        raise VsphereError("Virtual machine %s not found" % describe_vm_selector(params))
    return vm


def datacenter_of(obj):
    """Walk up the inventory to the Datacenter that holds obj."""
    parent = obj.parent
    while parent is not None and not isinstance(parent, vim.Datacenter):
        parent = parent.parent
    if parent is None:
        raise VsphereError("Could not find the datacenter of %s" % (obj,))
    return parent


def find_datastore(service_instance, name, datacenter=None):
    root = datacenter.datastoreFolder if datacenter else service_instance.content.rootFolder
    for obj, ds_name in list_names(service_instance, root, vim.Datastore):
        if ds_name == name:
            return obj
    raise VsphereError("Datastore %r not found" % (name,))


def datastore_file_exists(service_instance, datacenter, path):
    """Whether '[ds] folder/file' exists, through the datastore browser."""
    folder, basename = split_datastore_file(path)
    datastore_name = parse_datastore_path(path)[0]
    datastore = find_datastore(service_instance, datastore_name, datacenter)
    spec = vim.host.DatastoreBrowser.SearchSpec(matchPattern=[basename])
    try:
        result = wait_for_task(datastore.browser.SearchDatastore_Task(folder, spec))
    except VsphereError as e:
        if "FileNotFound" in to_native(e):
            return False
        raise
    return bool(result and result.file)


# ---------------------------------------------------------------- tasks


def wait_for_task(task, timeout=600):
    """Block until the task finishes; return its result or raise VsphereError."""
    deadline = time.time() + timeout
    while True:
        info = task.info
        if info.state == vim.TaskInfo.State.success:
            return info.result
        if info.state == vim.TaskInfo.State.error:
            raise VsphereError(fault_message(info.error) if info.error is not None else "task failed")
        if time.time() > deadline:
            raise VsphereError("Timed out after %ds waiting for task %s" % (timeout, moid_of(task)))
        time.sleep(0.2)


def reconfigure(vm, device_changes):
    spec = vim.vm.ConfigSpec(deviceChange=device_changes)
    wait_for_task(vm.ReconfigVM_Task(spec=spec))


# ---------------------------------------------------------------- devices


def controller_classes():
    return {
        "paravirtual": vim.vm.device.ParaVirtualSCSIController,
        "lsilogic": vim.vm.device.VirtualLsiLogicController,
        "lsilogicsas": vim.vm.device.VirtualLsiLogicSASController,
        "buslogic": vim.vm.device.VirtualBusLogicController,
        "sata": vim.vm.device.VirtualAHCIController,
        "nvme": vim.vm.device.VirtualNVMEController,
    }


def controller_type_of(device):
    for name, cls in controller_classes().items():
        if isinstance(device, cls):
            return name
    return None


def new_controller(controller_type, bus_number, bus_sharing=None, key=-100):
    """A device spec that adds a controller. SCSI controllers must carry sharedBus."""
    cls = controller_classes()[controller_type]
    controller = cls(key=key, busNumber=bus_number)
    if controller_family(controller_type) == "scsi":
        controller.sharedBus = api_value(BUS_SHARING, bus_sharing or "nosharing")
    return vim.vm.device.VirtualDeviceSpec(operation=vim.vm.device.VirtualDeviceSpec.Operation.add, device=controller)


def devices_of(props):
    return list(props.get("config.hardware.device") or [])


def controllers_of(devices):
    return dict((d.key, d) for d in devices if isinstance(d, vim.vm.device.VirtualController))


def disks_of(devices):
    return [d for d in devices if isinstance(d, vim.vm.device.VirtualDisk)]


def find_controller(devices, controller_type, bus_number):
    cls = controller_classes()[controller_type]
    for device in devices:
        if isinstance(device, cls) and device.busNumber == bus_number:
            return device
    return None


def device_in_slot(devices, controller_key, unit_number):
    for device in devices:
        if getattr(device, "controllerKey", None) == controller_key and getattr(device, "unitNumber", None) == unit_number:
            return device
    return None


def controller_facts(controller, devices):
    """A controller as a dictionary. Its attached devices are worked out from each
    device's controllerKey, not from the controller's own device list, which vcsim
    does not keep up to date."""
    facts = {
        "key": controller.key,
        "label": controller.deviceInfo.label if controller.deviceInfo else None,
        "type": controller_type_of(controller),
        "bus_number": controller.busNumber,
        "bus_sharing": None,
        "devices": sorted(d.key for d in devices if getattr(d, "controllerKey", None) == controller.key),
    }
    if hasattr(controller, "sharedBus"):
        facts["bus_sharing"] = option_value(BUS_SHARING, controller.sharedBus)
    return facts


def disk_facts(disk, controllers):
    """A plain dictionary describing a VirtualDisk, the shape both modules return."""
    backing = disk.backing
    controller = controllers.get(disk.controllerKey)
    flat = isinstance(backing, vim.vm.device.VirtualDisk.FlatVer2BackingInfo)
    filename = getattr(backing, "fileName", None)
    datastore = None
    if getattr(backing, "datastore", None) is not None:
        datastore = backing.datastore.name
    elif filename:
        parsed = parse_datastore_path(filename)
        datastore = parsed[0] if parsed else None
    bus_sharing = None
    if controller is not None and hasattr(controller, "sharedBus"):
        bus_sharing = option_value(BUS_SHARING, controller.sharedBus)
    facts = {
        "key": disk.key,
        "label": disk.deviceInfo.label if disk.deviceInfo else None,
        "controller_type": controller_type_of(controller) if controller is not None else None,
        "controller_number": controller.busNumber if controller is not None else None,
        "controller_key": disk.controllerKey,
        "controller_bus_sharing": bus_sharing,
        "unit_number": disk.unitNumber,
        "size_kb": disk.capacityInKB,
        "size_gb": gb_from_kb(disk.capacityInKB),
        "filename": filename,
        "datastore": datastore,
        "disk_mode": getattr(backing, "diskMode", None),
        "sharing": option_value(DISK_SHARING, getattr(backing, "sharing", None) or "sharingNone"),
        "type": disk_type_from_backing(getattr(backing, "thinProvisioned", None), getattr(backing, "eagerlyScrub", None)) if flat else None,
        "backing": type(backing).__name__.rsplit(".", 1)[-1] if backing is not None else None,
        "uuid": getattr(backing, "uuid", None),
    }
    return facts
