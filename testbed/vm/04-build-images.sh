#!/usr/bin/env bash
# Inside the VM: build the testbed's own images from official source and load them into k3s.
set -euo pipefail
if ! command -v docker >/dev/null; then
  sudo apt-get update -q && sudo apt-get install -y -q docker.io
  sudo usermod -aG docker "$USER"
fi
build() {  # name dir
  echo "[build] $1"
  local src=~/images/"$2"; [[ $2 == dashboard ]] && src=~/dashboard
  sudo docker build -t "$1" "$src" > ~/build-"$2".log 2>&1 || { tail -40 ~/build-"$2".log; return 1; }
  sudo docker save "$1" | sudo k3s ctr -n k8s.io images import - >/dev/null
  echo "[build] $1 loaded into k3s"
}
fail=0
for x in "$@"; do
  case $x in
    flexric)    build sixg/flexric:73650812 flexric || fail=1 ;;
    srsran-gnb) build sixg/srsran-gnb:25.10 srsran-gnb || fail=1 ;;
    srsue)      build sixg/srsue:25.10 srsue || fail=1 ;;
    srsran-zmq) build sixg/srsran-zmq:25.10 srsran-zmq || fail=1 ;;   # needs srsran-gnb + srsue first
    *)          build "sixg/$x:latest" "$x" || fail=1 ;;
  esac
done
exit $fail
