# A real virtual machine, packaged so Docker can start it.
#
# This container runs QEMU with KVM, which boots an Ubuntu 24.04 cloud image with its
# own kernel. The container is only the delivery vehicle: the thing you measure is the
# guest, which is a full VM with virtual hardware, firmware, a kernel and systemd. It
# needs /dev/kvm, which Windows 11 (WSL2) and Linux laptops have and Macs do not.
FROM debian:13-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      qemu-system-x86 qemu-utils cloud-image-utils ca-certificates curl \
      socat openssh-client \
 && rm -rf /var/lib/apt/lists/*

COPY start-vm.sh vm-exec /usr/local/bin/
RUN chmod 0755 /usr/local/bin/start-vm.sh /usr/local/bin/vm-exec

ENTRYPOINT ["/usr/local/bin/start-vm.sh"]
