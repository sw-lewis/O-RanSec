#!/bin/sh
# Create the UE-side tunnel for DNN "mec" (10.48.0.0/16) on the host, then run the UPF.
# No NAT: UE addresses reach the MEC server unchanged.
set -e
ip link show ogsmec >/dev/null 2>&1 || ip tuntap add name ogsmec mode tun
ip addr replace 10.48.0.1/16 dev ogsmec
ip link set ogsmec up
exec open5gs-upfd -c /etc/open5gs/upf.yaml
