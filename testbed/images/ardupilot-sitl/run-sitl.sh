#!/bin/bash
# Starts the simulated copter.
#   serial0 -> MAVLink telemetry to the ground/edge app ($TELEMETRY_TARGET, host:port, UDP)
#   serial1 -> local TCP 5762, used only by mission.py (the simulated pilot) inside this pod
set -u
: "${TELEMETRY_TARGET:?set TELEMETRY_TARGET=host:port}"
: "${HOME_LOCATION:=-35.363261,149.165230,584,353}"
host=${TELEMETRY_TARGET%:*}; port=${TELEMETRY_TARGET##*:}
until ip=$(getent hosts "$host" | awk '{print $1; exit}') && [ -n "$ip" ]; do sleep 2; done
echo "[sitl] telemetry -> $ip:$port  home=$HOME_LOCATION"
arducopter --model quad --speedup 1 --home "$HOME_LOCATION" --defaults /opt/sitl/copter.parm,/opt/sitl/sixg.parm \
  --serial0 "udpclient:$ip:$port" --serial1 tcp:5762 -I0 &
SITL=$!
trap 'kill $SITL $PILOT 2>/dev/null; exit 0' TERM INT
sleep 5
python3 -u /opt/sitl/mission.py &
PILOT=$!
wait -n $SITL $PILOT
echo "[sitl] a process exited"; kill $SITL $PILOT 2>/dev/null; exit 1
