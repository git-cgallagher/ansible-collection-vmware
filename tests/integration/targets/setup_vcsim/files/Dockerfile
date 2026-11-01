# vcsim, the vCenter/ESXi API simulator from VMware's govmomi project
# (https://github.com/vmware/govmomi/tree/main/vcsim), as a container for the
# Molecule scenario. Built from the pinned release tarball for whatever
# architecture Docker is building for: the official vmware/vcsim image is
# amd64-only, which suits GitHub's runners but not an Apple-silicon Mac without
# amd64 emulation.
#
# The ARG lines below are the single pin for vcsim in this repo: the
# integration targets' with_vcsim.sh reads the version and checksums from this
# file, so bump them here and nowhere else. Checksums come from the release's
# checksums.txt.
FROM alpine:3.22 AS fetch
ARG TARGETARCH
ARG VCSIM_VERSION=0.56.2
ARG VCSIM_SHA256_AMD64=4c79fd49d94ffdb7a9095350ff71f38e77e90036bd0bc26b50362219ac88fd13
ARG VCSIM_SHA256_ARM64=efe4aa048ac9d04abf5b393ff03e5a5f5fa5fabcf05f33a74e1c6ab70bfd4b8e
# TARGETARCH is only set by BuildKit; the legacy builder (the docker CLI in
# the ansible-runtime image) leaves it empty, so fall back to the build host.
RUN set -eu; \
    arch=${TARGETARCH:-$(uname -m)}; \
    case "$arch" in \
      amd64|x86_64) asset=vcsim_Linux_x86_64.tar.gz; sum=$VCSIM_SHA256_AMD64 ;; \
      arm64|aarch64) asset=vcsim_Linux_arm64.tar.gz; sum=$VCSIM_SHA256_ARM64 ;; \
      *) echo "unsupported architecture $arch" >&2; exit 1 ;; \
    esac; \
    wget -q -O /tmp/vcsim.tgz "https://github.com/vmware/govmomi/releases/download/v${VCSIM_VERSION}/${asset}"; \
    echo "$sum  /tmp/vcsim.tgz" | sha256sum -c -; \
    tar -xzf /tmp/vcsim.tgz -C /usr/local/bin vcsim; \
    chmod 0755 /usr/local/bin/vcsim

FROM alpine:3.22
COPY --from=fetch /usr/local/bin/vcsim /usr/local/bin/vcsim
RUN adduser -D -H vcsim
USER vcsim
EXPOSE 8989
ENTRYPOINT ["/usr/local/bin/vcsim"]
# -api-version: vcsim advertises 6.5 by default; a current pyvmomi negotiates a
# current API version against a current vCenter, so make the simulator look
# like one. Same flag as with_vcsim.sh.
CMD ["-l", "0.0.0.0:8989", "-api-version", "8.0.3.0"]
