# -*- coding: utf-8 -*-
# MIT License (see LICENSE or https://opensource.org/licenses/MIT)

from __future__ import absolute_import, division, print_function

__metaclass__ = type

import os

from ansible.utils.collection_loader import AnsibleCollectionConfig

# ansible-test sets up the collection loader itself. When running plain pytest from the
# repo, point the loader at the ansible_collections/ directory this repo sits in.
if AnsibleCollectionConfig.collection_finder is None:
    from ansible.plugins.loader import init_plugin_loader

    _here = os.path.dirname(os.path.abspath(__file__))
    _collections_root = os.path.abspath(os.path.join(_here, "..", "..", "..", "..", ".."))
    init_plugin_loader([_collections_root])
