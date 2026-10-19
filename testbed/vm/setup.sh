#!/usr/bin/env bash
# Inside the VM: full install, every step in order. Safe to run again; finished steps are quick.
# Started by "6g setup" on the host; the log is ~/setup.log.
set -euo pipefail
cd ~

step() { printf '\n===== [%s] %s =====\n' "$(date +%H:%M:%S)" "$*"; }

step "1/5 Kubernetes (k3s) and Helm"
bash ~/vm/01-k3s.sh

step "2/5 Building container images (slowest step, 45-90 min the first time)"
bash ~/vm/04-build-images.sh srsran-gnb srsue srsran-zmq flexric \
  flowmon device-hub device-gateway ardupilot-sitl dashboard

step "3/5 5G core and simulated radio"
bash ~/vm/02-core-ran.sh

step "4/5 Monitoring"
bash ~/vm/03-observability.sh

step "5/5 O-RAN, edge, traffic meter and dashboard"
bash ~/vm/05-apps.sh

step "Setup finished"
