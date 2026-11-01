# -*- coding: utf-8 -*-
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)
"""The pure helpers of module_utils/vsphere.py. Everything that talks to
vSphere is covered by the integration targets against vcsim."""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import pytest

from ansible_collections.git_cgallagher.vmware.plugins.module_utils import vsphere


@pytest.mark.parametrize(
    "controller_type,family",
    [("paravirtual", "scsi"), ("lsilogic", "scsi"), ("lsilogicsas", "scsi"), ("buslogic", "scsi"), ("sata", "sata"), ("nvme", "nvme")],
)
def test_controller_family(controller_type, family):
    assert vsphere.controller_family(controller_type) == family


def test_controller_family_unknown():
    with pytest.raises(ValueError):
        vsphere.controller_family("ide")


@pytest.mark.parametrize(
    "controller_type,bus,unit,expected",
    [
        ("paravirtual", 0, 0, None),
        ("paravirtual", 3, 15, None),
        ("paravirtual", 0, None, None),
        ("paravirtual", 0, 7, "reserved"),
        ("lsilogic", 0, 16, "between 0 and 15"),
        ("paravirtual", 0, -1, "between 0 and 15"),
        ("paravirtual", 4, 0, "between 0 and 3"),
        ("paravirtual", -1, 0, "between 0 and 3"),
        ("sata", 0, 29, None),
        ("sata", 0, 30, "between 0 and 29"),
        ("sata", 0, 7, None),
        ("nvme", 0, 63, None),
        ("nvme", 0, 64, "between 0 and 63"),
    ],
)
def test_validate_slot(controller_type, bus, unit, expected):
    result = vsphere.validate_slot(controller_type, bus, unit)
    if expected is None:
        assert result is None
    else:
        assert expected in result


@pytest.mark.parametrize(
    "thin,eager,disk_type",
    [(True, False, "thin"), (False, True, "eagerzeroedthick"), (False, False, "thick"), (None, None, "thick"), (True, True, "thin")],
)
def test_disk_type_from_backing(thin, eager, disk_type):
    assert vsphere.disk_type_from_backing(thin, eager) == disk_type


@pytest.mark.parametrize("disk_type", vsphere.DISK_TYPES)
def test_backing_flags_round_trip(disk_type):
    assert vsphere.disk_type_from_backing(*vsphere.backing_flags(disk_type)) == disk_type


def test_backing_flags_unknown():
    with pytest.raises(ValueError):
        vsphere.backing_flags("sparse")


def test_sharing_mappings_round_trip():
    for mapping in (vsphere.DISK_SHARING, vsphere.BUS_SHARING):
        for option in mapping:
            assert vsphere.option_value(mapping, vsphere.api_value(mapping, option)) == option
    assert vsphere.option_value(vsphere.DISK_SHARING, "sharingSomethingNew") == "sharingSomethingNew"


@pytest.mark.parametrize("kb,gb", [(None, None), (0, 0), (1048576, 1), (20971520, 20), (1572864, 1.5), (1, 0.0)])
def test_gb_from_kb(kb, gb):
    assert vsphere.gb_from_kb(kb) == gb


@pytest.mark.parametrize(
    "path,expected",
    [
        ("[ds1] dir/file.vmdk", ("ds1", "dir/file.vmdk")),
        ("[ds1]dir/file.vmdk", ("ds1", "dir/file.vmdk")),
        ("[LocalDS_0]", ("LocalDS_0", "")),
        ("[my datastore] a b/c.vmdk", ("my datastore", "a b/c.vmdk")),
        ("dir/file.vmdk", None),
        ("", None),
        (None, None),
    ],
)
def test_parse_datastore_path(path, expected):
    assert vsphere.parse_datastore_path(path) == expected


@pytest.mark.parametrize(
    "path,expected",
    [
        ("[ds1] dir/file.vmdk", ("[ds1] dir", "file.vmdk")),
        ("[ds1] a/b/c.vmdk", ("[ds1] a/b", "c.vmdk")),
        ("[ds1] file.vmdk", ("[ds1]", "file.vmdk")),
        ("[ds1] /dir/file.vmdk", ("[ds1] dir", "file.vmdk")),
    ],
)
def test_split_datastore_file(path, expected):
    assert vsphere.split_datastore_file(path) == expected


def test_split_datastore_file_rejects_plain_paths():
    with pytest.raises(vsphere.VsphereError):
        vsphere.split_datastore_file("dir/file.vmdk")


class FakeFault(Exception):
    def __init__(self, msg=None, **attrs):
        super(FakeFault, self).__init__(msg)
        self.msg = msg
        for key, value in attrs.items():
            setattr(self, key, value)


def test_fault_message_uses_msg_and_known_attributes():
    text = vsphere.fault_message(FakeFault("*types.FileNotFound", file="/vmfs/x.vmdk"))
    assert text == "FakeFault: *types.FileNotFound; file=/vmfs/x.vmdk"


def test_fault_message_falls_back_to_str():
    text = vsphere.fault_message(RuntimeError("boom"))
    assert text == "RuntimeError: boom"


def test_argument_specs_are_consistent_with_option_lists():
    assert set(vsphere.connection_argument_spec()) == set(vsphere.CONNECTION_OPTIONS)
    assert set(vsphere.vm_argument_spec()) == set(vsphere.VM_OPTIONS)
    assert vsphere.connection_argument_spec()["password"]["no_log"] is True
    for controller_type in vsphere.CONTROLLER_TYPES:
        vsphere.controller_family(controller_type)


@pytest.mark.skipif(not vsphere.HAS_PYVMOMI, reason="pyvmomi not installed")
def test_controller_classes_cover_every_type():
    classes = vsphere.controller_classes()
    assert set(classes) == set(vsphere.CONTROLLER_TYPES)
    for name, cls in classes.items():
        assert vsphere.controller_type_of(cls(key=1, busNumber=0)) == name


@pytest.mark.skipif(not vsphere.HAS_PYVMOMI, reason="pyvmomi not installed")
def test_new_controller_sets_shared_bus_on_scsi_only():
    scsi = vsphere.new_controller("paravirtual", 1, "physical").device
    assert scsi.busNumber == 1
    assert scsi.sharedBus == "physicalSharing"
    default = vsphere.new_controller("lsilogic", 0).device
    assert default.sharedBus == "noSharing"
    nvme = vsphere.new_controller("nvme", 0).device
    assert not hasattr(nvme, "sharedBus") or nvme.sharedBus is None
