#!/bin/bash
# sl04 host rules for the MEC. Run after "docker compose up -d" (and after every reboot or Docker restart).
#  - UEs on DNN mec (ogsmec, 10.48.0.0/16) may reach the MEC server (br-mec, 10.0.3.0/24) and nothing else:
#    not sl04 itself (RIC, SSH, O-DU), not the LAN, not the internet. Attack traffic stays inside the MEC.
#  - Traffic is routed, not NATed, so the server sees real UE addresses.
set -euo pipefail
sysctl -qw net.ipv4.ip_forward=1

# Forwarding: only UE pool <-> MEC server (DOCKER-USER is evaluated before Docker's own rules).
iptables -N MEC-FWD 2>/dev/null || iptables -F MEC-FWD
iptables -A MEC-FWD -i ogsmec -o br-mec -s 10.48.0.0/16 -d 10.0.3.0/24 -j ACCEPT
iptables -A MEC-FWD -i br-mec -o ogsmec -s 10.0.3.0/24 -d 10.48.0.0/16 -j ACCEPT
iptables -A MEC-FWD -i ogsmec -j DROP
iptables -A MEC-FWD -o ogsmec -j DROP
iptables -C DOCKER-USER -j MEC-FWD 2>/dev/null || iptables -I DOCKER-USER 1 -j MEC-FWD

# sl04 itself: UEs may only ping the UE gateway 10.48.0.1 (for tests); everything else to the host is dropped.
iptables -N MEC-IN 2>/dev/null || iptables -F MEC-IN
iptables -A MEC-IN -p icmp -d 10.48.0.1 -j ACCEPT
iptables -A MEC-IN -j DROP
iptables -C INPUT -i ogsmec -j MEC-IN 2>/dev/null || iptables -I INPUT 1 -i ogsmec -j MEC-IN

# Docker masquerades traffic leaving br-mec; replies to UEs are conntrack-reversed, but make sure
# server-initiated traffic to UEs is not NATed either.
iptables -t nat -C POSTROUTING -s 10.0.3.0/24 -o ogsmec -j RETURN 2>/dev/null \
  || iptables -t nat -I POSTROUTING 1 -s 10.0.3.0/24 -o ogsmec -j RETURN

echo "MEC rules in place:"; iptables -S MEC-FWD; iptables -S MEC-IN
