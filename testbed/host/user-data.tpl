#cloud-config
# First-boot setup of the 6G testbed VM. __SSH_KEY__ is filled in by "6g create".
hostname: sixg-testbed
manage_etc_hosts: true
users:
  - name: sixg
    groups: [sudo]
    shell: /bin/bash
    sudo: "ALL=(ALL) NOPASSWD:ALL"
    lock_passwd: true
    ssh_authorized_keys:
      - __SSH_KEY__
ssh_pwauth: false
disable_root: true

write_files:
  # The VM has no IPv6 (the host filter drops it too).
  - path: /etc/sysctl.d/90-sixg.conf
    content: |
      net.ipv6.conf.all.disable_ipv6 = 1
      net.ipv6.conf.default.disable_ipv6 = 1
      net.ipv4.ip_forward = 1
      # per-flow byte counters for flowmon (live link traffic)
      net.netfilter.nf_conntrack_acct = 1
      # many pods watch files; the default of 128 inotify instances runs out
      fs.inotify.max_user_instances = 1024
      fs.inotify.max_user_watches = 524288
  # SCTP is used between the gNB and the AMF (N2).
  - path: /etc/modules-load.d/sixg.conf
    content: |
      sctp
      nf_conntrack

package_update: true
package_upgrade: true
packages:
  - qemu-guest-agent
  - curl
  - git
  - jq
  - tcpdump
  - tshark
  - net-tools
  - iproute2

runcmd:
  - sysctl --system
  - modprobe sctp || true
  - systemctl enable --now qemu-guest-agent
  - touch /var/lib/sixg-cloud-init-done
