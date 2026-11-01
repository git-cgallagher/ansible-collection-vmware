# -*- coding: utf-8 -*-

# Copyright: (c) 2026, Chris Gallagher
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type


class ModuleDocFragment(object):
    # Connection to vCenter or ESXi. The same option and environment variable
    # names as community.vmware, so inventories and module_defaults carry over.
    DOCUMENTATION = r"""
options:
  hostname:
    description:
      - Hostname or IP address of the vCenter Server or ESXi host.
      - Falls back to the E(VMWARE_HOST) environment variable.
    type: str
    required: true
  username:
    description:
      - Username to log in with.
      - Falls back to the E(VMWARE_USER) environment variable.
    type: str
    required: true
  password:
    description:
      - Password for O(username).
      - Falls back to the E(VMWARE_PASSWORD) environment variable.
    type: str
    required: true
  port:
    description:
      - TCP port of the vSphere API.
      - Falls back to the E(VMWARE_PORT) environment variable.
    type: int
    default: 443
  validate_certs:
    description:
      - Verify the server's TLS certificate. Turn off only for a lab or a simulator with a self-signed certificate.
      - Falls back to the E(VMWARE_VALIDATE_CERTS) environment variable.
    type: bool
    default: true
notes:
  - Requires C(pyvmomi) 9.0 or newer where the module runs. Delegate to C(localhost) (or run the play there) unless the
    managed host has pyvmomi and can reach the vSphere API itself.
requirements:
  - pyvmomi >= 9.0.0
"""

    # Picking one virtual machine.
    VM = r"""
options:
  name:
    description:
      - Name of the virtual machine.
      - One of O(name), O(uuid) or O(moid) is required. A name that matches more than one virtual machine is an
        error; narrow it with O(datacenter) or use O(uuid) or O(moid).
    type: str
  uuid:
    description:
      - BIOS UUID of the virtual machine, or its instance UUID with O(use_instance_uuid=true).
    type: str
  moid:
    description:
      - Managed object ID of the virtual machine, for example C(vm-1234).
    type: str
  use_instance_uuid:
    description:
      - Treat O(uuid) as the vCenter instance UUID instead of the BIOS UUID.
    type: bool
    default: false
  datacenter:
    description:
      - Name of the datacenter to look in. Only needed when the same name exists in several datacenters.
    type: str
"""
