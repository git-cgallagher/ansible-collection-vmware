#!/usr/bin/env bash
# Runs a command with a vcsim (govmomi vCenter simulator) listening on a free
# loopback port, for the integration targets:
#
#   ../setup_vcsim/files/with_vcsim.sh ansible-playbook test.yml "$@"
#
# The command gets VCSIM_HOST, VCSIM_PORT, VCSIM_USER and VCSIM_PASSWORD in its
# environment (vcsim accepts any credentials). vcsim's default inventory is one
# datacenter DC0 with datastore LocalDS_0, a cluster of three hosts and four
# powered-on VMs: DC0_H0_VM0, DC0_H0_VM1, DC0_C0_RP0_VM0, DC0_C0_RP0_VM1.
#
# ansible-test runs each target inside its own container (no Docker in there),
# so the vcsim binary comes from the pinned release tarball, verified against
# the checksum in ./Dockerfile, which is the single pin for the version.
# The download is cached per version and architecture in /tmp, so the second
# target in the same container doesn't fetch it again.
set -euo pipefail

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
pin() { sed -n "s/^ARG $1=//p" "$here/Dockerfile"; }
version=$(pin VCSIM_VERSION)
case "$(uname -m)" in
  x86_64)  asset=vcsim_Linux_x86_64.tar.gz; sum=$(pin VCSIM_SHA256_AMD64) ;;
  aarch64|arm64) asset=vcsim_Linux_arm64.tar.gz; sum=$(pin VCSIM_SHA256_ARM64) ;;
  *) echo "with_vcsim.sh: no vcsim build for $(uname -m)" >&2; exit 1 ;;
esac
if [ -z "$version" ] || [ -z "$sum" ]; then
  echo "with_vcsim.sh: could not read the vcsim pin from $here/Dockerfile" >&2
  exit 1
fi

cache="/tmp/vcsim-${version}-$(uname -m)"
if [ ! -x "$cache/vcsim" ]; then
  mkdir -p "$cache"
  python3 - "https://github.com/vmware/govmomi/releases/download/v${version}/${asset}" "$sum" "$cache/vcsim.tgz" <<'PY'
import hashlib, sys, urllib.request
url, expected, dest = sys.argv[1:]
data = urllib.request.urlopen(url, timeout=120).read()
actual = hashlib.sha256(data).hexdigest()
if actual != expected:
    sys.exit("with_vcsim.sh: %s: sha256 %s, expected %s" % (url, actual, expected))
open(dest, "wb").write(data)
PY
  tar -xzf "$cache/vcsim.tgz" -C "$cache" vcsim
  rm -f "$cache/vcsim.tgz"
fi

port=$(python3 -c 'import socket; s = socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1])')
log="${OUTPUT_DIR:-.}/vcsim.log"
# The same -api-version as the Dockerfile's CMD (see there).
"$cache/vcsim" -l "127.0.0.1:${port}" -api-version 8.0.3.0 > "$log" 2>&1 &
vcsim_pid=$!
trap 'kill "$vcsim_pid" 2>/dev/null || true' EXIT

for _ in $(seq 1 100); do
  if python3 -c 'import socket, sys; socket.create_connection(("127.0.0.1", int(sys.argv[1])), 1).close()' "$port" 2>/dev/null; then
    break
  fi
  kill -0 "$vcsim_pid" 2>/dev/null || { echo "with_vcsim.sh: vcsim exited:"; cat "$log"; exit 1; } >&2
  sleep 0.1
done

export VCSIM_HOST=127.0.0.1 VCSIM_PORT="$port" VCSIM_USER=user VCSIM_PASSWORD=Example-not-secret
exec "$@"
