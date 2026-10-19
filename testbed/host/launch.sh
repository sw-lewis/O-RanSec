#!/usr/bin/env bash
# Desktop launcher: start (or stop) the testbed VM and open the control panel, no terminal needed.
ROOT="$(cd "$(dirname "$(readlink -f "$0")")/.." && pwd)"
notify() { command -v notify-send >/dev/null && notify-send -a "6G Testbed" "6G Testbed" "$1"; }
case ${1:-start} in
  start)
    notify "Starting the testbed VM…"
    if "$ROOT/6g" start >/tmp/sixg-launch.log 2>&1; then
      notify "Testbed running. Opening the control panel."
      xdg-open "http://127.0.0.1:8660/" >/dev/null 2>&1
    else
      notify "Start failed. See /tmp/sixg-launch.log"
    fi ;;
  stop)
    notify "Stopping the testbed VM…"
    "$ROOT/6g" stop >/tmp/sixg-launch.log 2>&1 && notify "Testbed stopped. It now uses no CPU or RAM." || notify "Stop failed. See /tmp/sixg-launch.log" ;;
esac
