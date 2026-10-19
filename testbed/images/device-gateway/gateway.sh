#!/bin/bash
# Device gateway. Env: MODE = simulated | udp-relay | vpn, GNB_HOSTNAME, and per mode:
#   simulated: TARGET INTERVAL SIZE
#   udp-relay: RELAYS = "listenport>host:port,..." (each is one device stream carried into the 5G session)
#   always:    HUB_IP = device live hub address; traffic to it is forced through the 5G tunnel
#   vpn:       WG_PRIVATE_KEY WG_PEER_PUBLIC_KEY WG_ADDRESS (gateway side, e.g. 10.99.1.1/30) WG_PORT
set -u
log() { echo "[gateway] $*"; }

until GNB_IP=$(getent hosts "$GNB_HOSTNAME" | awk '{print $1; exit}') && [ -n "$GNB_IP" ]; do sleep 2; done
export GNB_IP
envsubst < /etc/ueransim/ue.yaml > /tmp/ue.yaml
nr-ue -c /tmp/ue.yaml &
UE=$!
bye() {
  for n in $(nr-cli --dump 2>/dev/null); do nr-cli "$n" --exec "deregister switch-off" >/dev/null 2>&1; done
  sleep 2; kill $UE ${CHILD:-} 2>/dev/null; exit 0
}
trap bye TERM INT

sysctl -qw net.ipv4.ip_forward=1
POD_IP=$(ip -4 -o addr show eth0 | awk '{print $4}' | cut -d/ -f1)
# Addresses that must only ever be reached through the 5G session: the hub, plus relay targets.
FORCED=${HUB_IP:-}
if [ "$MODE" = udp-relay ]; then
  for pr in ${RELAYS//,/ }; do
    h=${pr#*>}; h=${h%:*}
    FORCED="$FORCED $(getent hosts "$h" | awk '{print $1; exit}')"
  done
fi
# If the tunnel is down, these addresses are unreachable instead of silently going out on eth0.
for d in $FORCED; do ip route replace prohibit "$d/32" metric 1000; done
# Traffic leaving through the tunnel always carries the current UE IP (the UPF drops anything else),
# so pod sockets keep working when the session is rebuilt with a new IP.
iptables -t nat -C POSTROUTING -o uesimtun0 -j MASQUERADE 2>/dev/null || iptables -t nat -A POSTROUTING -o uesimtun0 -j MASQUERADE
iptables -t mangle -C FORWARD -o uesimtun0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu 2>/dev/null ||
  iptables -t mangle -A FORWARD -o uesimtun0 -p tcp --tcp-flags SYN,RST SYN -j TCPMSS --clamp-mss-to-pmtu

# (Re)applies the 5G routes. uesimtun0 is deleted and recreated, maybe with a new IP, whenever the
# UE loses and rebuilds its PDU session; its routes vanish with it, so this runs in a loop.
CUR_IP=""
apply_routes() {
  local ip
  ip=$(ip -4 -o addr show uesimtun0 2>/dev/null | awk '{print $4}' | cut -d/ -f1)
  [ -n "$ip" ] || return 1
  ip route replace default dev uesimtun0 table 100
  if [ "$ip" != "$CUR_IP" ]; then
    [ -n "$CUR_IP" ] && ip rule del from "$CUR_IP" table 100 priority 100 2>/dev/null
    ip rule add from "$ip" table 100 priority 100 2>/dev/null || true
    log "5G session up: UE IP $ip"
    CUR_IP=$ip
  fi
  # src = the stable pod IP, so sockets opened by sidecars never hold a stale UE IP (MASQUERADE maps it).
  for d in $FORCED; do ip route replace "$d/32" dev uesimtun0 src "$POD_IP"; done
}
until apply_routes; do kill -0 $UE || exit 1; sleep 1; done
[ -n "${HUB_IP:-}" ] && log "hub $HUB_IP reached through the 5G session"
( up=1
  while kill -0 $UE 2>/dev/null; do
    if apply_routes; then
      [ $up = 0 ] && log "5G session back: UE IP $CUR_IP"; up=1
    else
      [ $up = 1 ] && log "5G session lost, waiting for it to come back"; up=0
    fi
    sleep 2
  done ) &

case "$MODE" in
  simulated)
    log "simulated device traffic -> $TARGET every ${INTERVAL}s, ${SIZE} bytes"
    while kill -0 $UE 2>/dev/null; do
      if ping -I uesimtun0 -c 1 -W 2 -s "$SIZE" "$TARGET" >/dev/null; then echo "[device] packet ok"; else echo "[device] packet lost"; fi
      sleep "$INTERVAL" & wait $!
    done ;;
  udp-relay)
    IFS=',' read -ra pairs <<<"$RELAYS"
    for pr in "${pairs[@]}"; do
      lp=${pr%%>*}; dst=${pr#*>}
      log "relaying UDP from the device (port $lp) to $dst through the 5G session"
      # one device -> one bidirectional stream; socat locks onto the first sender (the device)
      ( while true; do
          socat -d -d UDP4-LISTEN:"$lp",reuseaddr UDP4:"$dst" 2>&1 | sed -u "s/^/[relay $lp] /"
          sleep 1
        done ) &
    done
    wait $UE ;;
  vpn)
    ip link add wg0 type wireguard
    echo "$WG_PRIVATE_KEY" > /tmp/wg.key; chmod 600 /tmp/wg.key
    wg set wg0 listen-port "$WG_PORT" private-key /tmp/wg.key peer "$WG_PEER_PUBLIC_KEY" allowed-ips 0.0.0.0/0
    ip addr add "$WG_ADDRESS" dev wg0; ip link set wg0 up
    net=$(ip -4 -o addr show wg0 | awk '{print $4}')
    ip rule add from "$net" table 100 priority 101 2>/dev/null || true
    log "WireGuard up on udp/$WG_PORT, device network $net, all device traffic -> 5G session"
    while kill -0 $UE 2>/dev/null; do
      hs=$(wg show wg0 latest-handshakes | awk '{print $2}')
      [ "${hs:-0}" != 0 ] && log "device handshake $(( $(date +%s) - hs ))s ago, $(wg show wg0 transfer | awk '{print "rx="$2" tx="$3}')"
      sleep 15 & wait $!
    done ;;
  *) log "unknown MODE $MODE"; exit 1 ;;
esac
