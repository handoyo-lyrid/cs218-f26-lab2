#!/bin/sh
# Boots the Lab 2 VM under QEMU with KVM. Run through `docker run`, never by hand; see
# VM-SETUP.md. State (the downloaded image and the VM's disk) lives in /vm, which is a
# Docker volume, so stopping and starting the container is stopping and starting the VM.
set -eu

IMAGE_URL="https://cloud-images.ubuntu.com/releases/noble/release/ubuntu-24.04-server-cloudimg-amd64.img"
VM_MEM_MB="${VM_MEM_MB:-1024}"
VM_CPUS="${VM_CPUS:-1}"

if [ ! -c /dev/kvm ]; then
  echo "No /dev/kvm in this container, so there is no hardware virtualization to use." >&2
  echo "Start it with --device /dev/kvm. If that fails, your laptop cannot use this route:" >&2
  echo "see VM-SETUP.md for Multipass or the Google Cloud route." >&2
  exit 3
fi

if [ ! -f /lab2/cloud-init.yaml ]; then
  echo "Missing /lab2/cloud-init.yaml. Mount your repo's vm/ folder at /lab2 and run" >&2
  echo "'python lab.py render' first." >&2
  exit 4
fi

mkdir -p /vm
if [ ! -f /vm/base.img ]; then
  echo "Downloading the Ubuntu 24.04 cloud image (about 600 MB, first run only)..." >&2
  curl -fsSL --retry 3 -o /vm/base.img.part "$IMAGE_URL"
  mv /vm/base.img.part /vm/base.img
fi
if [ ! -f /vm/disk.qcow2 ]; then
  # A copy-on-write overlay: the VM writes here, and the downloaded image stays pristine.
  qemu-img create -q -f qcow2 -F qcow2 -b /vm/base.img /vm/disk.qcow2 10G
fi
# A key so `vm-exec` can run commands inside the guest. It goes in through cloud-init's
# meta-data, which leaves your cloud-init.yaml identical to everyone else's.
[ -f /vm/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -f /vm/id_ed25519
# The instance-id follows the cloud-init file's content, so if that file ever changes,
# cloud-init treats the next boot as a new instance and applies it again.
cat > /vm/meta-data <<META
instance-id: cs218-lab2-$(sha256sum /lab2/cloud-init.yaml | cut -c1-12)
local-hostname: lab2
public-keys:
  - $(cat /vm/id_ed25519.pub)
META
cloud-localds /vm/seed.iso /lab2/cloud-init.yaml /vm/meta-data

qemu-system-x86_64 \
  -name lab2 \
  -machine q35,accel=kvm -cpu host \
  -smp "$VM_CPUS" -m "$VM_MEM_MB" \
  -drive file=/vm/disk.qcow2,if=virtio,cache=none \
  -drive file=/vm/seed.iso,if=virtio,format=raw,readonly=on \
  -nic user,model=virtio-net-pci,hostfwd=tcp::8080-:8080,hostfwd=tcp::2222-:22 \
  -monitor unix:/run/qemu-monitor,server,nowait \
  -pidfile /run/qemu.pid \
  -display none -serial file:/vm/console.log &
QEMU=$!

# `docker stop` sends SIGTERM. Pass it on as an ACPI power-button press so the guest
# shuts down cleanly, the way pressing a real machine's power button would.
powerdown() {
  echo "system_powerdown" | socat - UNIX-CONNECT:/run/qemu-monitor 2>/dev/null \
    || kill -TERM "$QEMU" 2>/dev/null || true
  wait "$QEMU" 2>/dev/null || true
  exit 0
}
trap powerdown TERM INT

wait "$QEMU"
