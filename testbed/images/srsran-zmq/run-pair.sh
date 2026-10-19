#!/bin/bash
# Supervisor for the srsRAN ZMQ pair. ZMQ REQ/REP cannot recover if one side restarts alone,
# so the gNB and srsUE always start together (gNB first) and stop together.
set -u
res() { local ip; until ip=$(getent hosts "$1" | awk '{print $1; exit}') && [ -n "$ip" ]; do sleep 2; done; echo "$ip"; }

export AMF_IP=$(res "$AMF_HOST")
export RIC_IP=$(res "$RIC_HOST")
echo "[pair] AMF=$AMF_IP RIC=$RIC_IP POD=$POD_IP"
envsubst < /cfg/gnb/gnb.yml.tpl > /tmp/gnb.yml
envsubst < /cfg/ue/ue.conf.tpl > /tmp/ue.conf
mkdir -p /pcap
ip netns list | grep -q '^ue1' || ip netns add ue1

rm -f /tmp/e2-lost
gnb -c /tmp/gnb.yml > >(while IFS= read -r l; do
    echo "[gnb] $l"
    case "$l" in *"E2 connection was closed"*) touch /tmp/e2-lost ;; esac
  done) 2>&1 &
GNB=$!

# srsRAN's E2 agent does not reconnect on its own. If the RIC goes away, wait for it to come
# back, then restart the pair so E2 (and the xApps' data) returns.
( until [ -f /tmp/e2-lost ]; do sleep 2; done
  echo "[pair] E2 connection to the RIC lost; waiting for the RIC"
  until getent hosts "$RIC_HOST" >/dev/null; do sleep 3; done
  sleep 10; echo "[pair] RIC is back, restarting the pair to re-establish E2"; kill $GNB ) &
trap 'echo "[pair] stopping"; kill $GNB ${UE:-} 2>/dev/null; exit 0' TERM INT

# the UE may only connect once the gNB's radio (ZMQ tx socket) is listening
until ss -ltn | grep -q "127.0.0.1:2000"; do
  kill -0 $GNB 2>/dev/null || { echo "[pair] gNB exited during start"; exit 1; }
  sleep 1
done
sleep 2
srsue /tmp/ue.conf > >(sed -u 's/^/[ue] /') 2>&1 &
UE=$!

# once attached, route the UE namespace's traffic through the 5G tunnel
( until ip netns exec ue1 ip link show tun_srsue >/dev/null 2>&1; do sleep 1; done
  ip netns exec ue1 ip route replace default dev tun_srsue && echo "[pair] UE data tunnel up" ) &

wait -n $GNB $UE
echo "[pair] a process exited; restarting the pair"
kill $GNB $UE 2>/dev/null
exit 1
