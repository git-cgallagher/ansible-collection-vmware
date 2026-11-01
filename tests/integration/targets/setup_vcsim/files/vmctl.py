#!/usr/bin/env python
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)
"""Test helper: power a vcsim VM on or off, or list a datastore folder.

    vmctl.py power off DC0_H0_VM0
    vmctl.py power on DC0_H0_VM0
    vmctl.py ls LocalDS_0 sqlfci          # prints one file per line, nothing when the folder is missing

Connection from VCSIM_HOST, VCSIM_PORT, VCSIM_USER and VCSIM_PASSWORD (set by
with_vcsim.sh). The modules under test don't power VMs on or off, and the tests
need both states (hot-add works on a running VM; a disk mode change doesn't).
"""

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os
import ssl
import sys
import time

from pyVim.connect import SmartConnect
from pyVmomi import vim


def wait(task):
    while task.info.state not in ("success", "error"):
        time.sleep(0.1)
    if task.info.state == "error":
        raise SystemExit("task failed: %s" % task.info.error)
    return task.info.result


def main(argv):
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE
    si = SmartConnect(
        host=os.environ["VCSIM_HOST"],
        port=int(os.environ["VCSIM_PORT"]),
        user=os.environ["VCSIM_USER"],
        pwd=os.environ["VCSIM_PASSWORD"],
        sslContext=context,
    )
    content = si.content
    if argv[0] == "power":
        wanted, name = argv[1], argv[2]
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.VirtualMachine], True)
        vm = [v for v in view.view if v.name == name][0]
        view.Destroy()
        wait(vm.PowerOnVM_Task() if wanted == "on" else vm.PowerOffVM_Task())
        return 0
    if argv[0] == "ls":
        ds_name, folder = argv[1], argv[2]
        view = content.viewManager.CreateContainerView(content.rootFolder, [vim.Datastore], True)
        ds = [d for d in view.view if d.name == ds_name][0]
        view.Destroy()
        # matchPattern is required: vcsim returns no files for a spec without one.
        try:
            result = wait(ds.browser.SearchDatastore_Task("[%s] %s" % (ds_name, folder), vim.host.DatastoreBrowser.SearchSpec(matchPattern=["*"])))
        except SystemExit as e:
            if "FileNotFound" in str(e):
                return 0
            raise
        for f in result.file:
            print(f.path)
        return 0
    raise SystemExit("usage: vmctl.py power on|off VM | ls DATASTORE FOLDER")


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
