#!/usr/bin/env bash
# Runs test.yml against a vcsim started by ../setup_vcsim/files/with_vcsim.sh, which
# exports VCSIM_HOST, VCSIM_PORT, VCSIM_USER and VCSIM_PASSWORD for it.
set -eux
exec ../setup_vcsim/files/with_vcsim.sh ansible-playbook test.yml "$@"
