#!/bin/bash
# Keep a default route through the srsUE tunnel in its network namespace.
# srsUE recreates tun_srsue on every attach, which removes the route; this puts it back within ~2 s.
# Usage: ue-route-keeper.sh [netns] [tun]   (defaults: ue1 tun_srsue)
NS=${1:-ue1}
TUN=${2:-tun_srsue}
while true; do
  if ip -n "$NS" link show "$TUN" >/dev/null 2>&1 \
     && ! ip -n "$NS" route show default 2>/dev/null | grep -q "dev $TUN"; then
    ip -n "$NS" route replace default dev "$TUN" \
      && logger -t ue-route-keeper "default route via $TUN added in netns $NS"
  fi
  sleep 2
done
