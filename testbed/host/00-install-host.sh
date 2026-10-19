#!/usr/bin/env bash
# One-time host setup for the 6G testbed. Run with sudo.
# Installs KVM + libvirt, creates the isolated network and firewall filter,
# and a disk folder for the VM. Nothing here starts automatically at boot.
set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Run with sudo: sudo bash $0" >&2
  exit 1
fi

REAL_USER="${SUDO_USER:-$(logname)}"
HERE="$(cd "$(dirname "$0")" && pwd)"
IMG_DIR=/var/lib/libvirt/images/sixg

echo "[1/5] Installing KVM, libvirt and tools"
apt-get update -q
apt-get install -y -q qemu-system-x86 qemu-utils libvirt-daemon-system \
  libvirt-clients virtinst ovmf

echo "[2/5] Adding $REAL_USER to libvirt and kvm groups"
usermod -aG libvirt,kvm "$REAL_USER"

echo "[3/5] Creating VM disk folder $IMG_DIR"
install -d -m 0755 -o "$REAL_USER" -g "$REAL_USER" "$IMG_DIR"

echo "[4/5] Defining isolation filter (VM cannot reach host or private networks)"
virsh -c qemu:///system nwfilter-define "$HERE/sixg-isolate.xml"

echo "[5/5] Defining isolated network sixg-net (not autostarted)"
if ! virsh -c qemu:///system net-info sixg-net >/dev/null 2>&1; then
  virsh -c qemu:///system net-define "$HERE/sixg-net.xml"
fi
virsh -c qemu:///system net-autostart sixg-net --disable

# libvirt's own "default" network is not needed; keep it from autostarting.
virsh -c qemu:///system net-autostart default --disable 2>/dev/null || true

echo
echo "Done. Next: ./testbed/6g create"
