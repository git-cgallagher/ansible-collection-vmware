#!/usr/bin/env bash
# Runs a command in the ansible-runtime image (ghcr.io/git-cgallagher/ansible-runtime),
# the pinned toolchain the collections' CI shares: ansible-core, Molecule with the
# molecule-git-cgallagher driver, the docker CLI and the third-party collections. The
# image is the pin: the job installs nothing itself. The same wrapper as
# ansible-collection-isc's.
#   RUNTIME_IMAGE=ghcr.io/git-cgallagher/ansible-runtime:X.Y.Z-ci@sha256:... .github/ci/runtime.sh molecule test
#
# `docker run` with the checkout at the SAME path, not a `container:` job: Molecule
# starts its containers through the runner's Docker socket, and the daemon resolves
# paths on the host.
set -euo pipefail
: "${RUNTIME_IMAGE:?set RUNTIME_IMAGE (ansible-test.yml sets it)}"
root=$(git rev-parse --show-toplevel)

# Temporary files go under the checkout too (.cache/ is gitignored), so anything a test
# mounts into `docker run` is on a path the host daemon sees.
tmp="$root/.cache/tmp"
mkdir -p "$tmp"

# Molecule runs the module as git_cgallagher.vmware.vm_disk; the scenario's
# ANSIBLE_COLLECTIONS_PATH puts collections/ first. collections/ rather than isc's
# .molecule-collections/: it is already gitignored and in galaxy.yml's build_ignore, so
# the link can never end up in a built tarball.
if [ "${1:-}" = molecule ]; then
  mkdir -p "$root/collections/ansible_collections/git_cgallagher"
  ln -sfn ../../.. "$root/collections/ansible_collections/git_cgallagher/vmware"
fi

# The checkout belongs to the runner's user and the image runs as root, so git needs the
# checkout marked safe.
exec docker run --rm --network host \
  -v /var/run/docker.sock:/var/run/docker.sock \
  -v "$root:$root" -w "$PWD" -e TMPDIR="$tmp" \
  -e GIT_CONFIG_COUNT=1 -e GIT_CONFIG_KEY_0=safe.directory -e GIT_CONFIG_VALUE_0='*' \
  -e PY_COLORS -e ANSIBLE_FORCE_COLOR -e GITHUB_ACTIONS \
  "$RUNTIME_IMAGE" "$@"
