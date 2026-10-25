# RF lab: O-RAN split RAN on sl04

The RF lab runs the RAN outside the testbed VM, on a separate machine (`sl04`, Core i5-14400F,
64 GB, RTX 5060 Ti), and attaches it to the testbed's 5G core over the LAN. It is where the
USRP B210 and the commercial 5G modems connect.

```
srsUE / modems ⇄ O-DU (srsdu) ⇄F1⇄ O-CU (srscu) ──LAN──► AMF / eMBB UPF (testbed VM on Pop!_OS)
                   │
                   └──E2──► OSC near-RT RIC (Docker on sl04) ──► Python KPM xApps
```

| Item | Value |
|---|---|
| sl04 LAN address | `192.168.2.14` (DHCP reservation) |
| Pop!_OS LAN address | `192.168.1.54` (DHCP reservation) |
| AMF (k3s service `core-amf-ngap`) | `10.43.210.84:38412` |
| PLMN / TAC / slices | `99970` / `1` / SST 1-3, SD 1-3 |
| sl04 UE subscriber | `999700000000401` (in `k8s/core/values.yaml` populate list) |
| CPU pinning on sl04 | OS + Docker on CPUs 0-1, 12-15 (`CPUAffinity`); CU/DU/UE on P-cores 4-11 |

## Files

`sl04/` holds reference copies of the configs that run on sl04 (live copies: `~/oran/configs/`):

- `cu_testbed.yml`: O-CU (CU-CP + CU-UP), N2/N3 to the testbed core.
- `du_testbed.yml`: O-DU, cell, E2 to the OSC RIC, metrics and the `remote_control` WebSocket.
- `ue_testbed.conf`: srsUE (ZMQ) with the testbed identity `999700000000401`.

## Network path

- **sl04** routes `10.166.0.0/24`, `10.42.0.0/16` and `10.43.0.0/16` via `192.168.1.54`
  (stored in its NetworkManager profile).
- **Pop!_OS**: `./6g start` runs `ranlink_up`, which routes `10.42.0.0/16` and `10.43.0.0/16`
  to the VM and lets sl04's traffic through libvirt's forwarding; `./6g stop` removes it.
- **VM filter** (`host/sixg-isolate.xml`) accepts traffic to and from `192.168.2.14` only;
  everything else on the LAN stays blocked.

## Dashboard

The dashboard shows sl04's UEs, O-DU, O-CU and OSC RIC as external components (zone
"RF lab · sl04" on Live Architecture, and two panels on RAN & RIC). Their health comes from:

| Component | Source |
|---|---|
| O-DU, UEs, Uu and F1 links | O-DU metrics WebSocket `SL04_WS` (`ws://192.168.2.14:8001`) |
| O-CU, N2 and N3 links | flowmon, which labels `192.168.2.14` as `sl04-cu` (`EXTERNAL_HOSTS`) |
| OSC RIC and E2 link | the RIC's E2 Manager API `SL04_E2MGR_URL` (`http://192.168.2.14:3800/v1/nodeb/states`) |

Requirements on sl04:

1. `du_testbed.yml` has `remote_control` enabled (port 8001) and `metrics.enable_json: true`.
2. The OSC RIC publishes the E2 Manager's REST port. In `~/oran/oran-sc-ric/docker-compose.yml`,
   under the `e2mgr` service, add:
   ```yaml
       ports:
         - "3800:3800"
   ```
   then `docker compose up -d` in that directory.

## Recording KPM

`xapps/kpm_recorder_xapp.py` subscribes to E2SM-KPM (report style 4, per UE, every 1 s) on every
connected O-DU with the seven measurements srsRAN 25.10 reports per UE, and appends each value to a
CSV in UTC: `rx_utc, collet_start_utc, e2_node, report_style, ue_id, granul_ms, metric, value`.

| Measurement | Unit |
|---|---|
| `DRB.UEThpDl`, `DRB.UEThpUl` | kbit/s |
| `DRB.RlcSduTransmittedVolumeDL`, `DRB.RlcSduTransmittedVolumeUL` | kbit per period |
| `RRU.PrbUsedDl`, `RRU.PrbUsedUl` | mean PRBs per slot (integer) |
| `DRB.RlcDelayUl` | UL RLC SDU delay, 0.1 ms units |

```bash
# on sl04, from a clone of this repo in ~/O-RanSec
cd ~/O-RanSec && git pull
cp ~/O-RanSec/testbed/rf-lab/xapps/kpm_recorder_xapp.py ~/oran/oran-sc-ric/xApps/python/
cd ~/oran/oran-sc-ric
docker compose exec python_xapp_runner ./kpm_recorder_xapp.py --out data/kpm.csv
# the file appears on sl04 at ~/oran/oran-sc-ric/xApps/python/data/kpm.csv
```

It finds the O-DU through the E2 Manager, so it keeps working when the DU's E2 node name
changes (it includes the PLMN). It uses the same RMR port as `kpm_mon_xapp.py` (4562), so run
one at a time. Adding `DRB.RlcPacketDropRateDl` or `DRB.PacketSuccessRateUlgNBUu` to a per-UE
subscription makes the srsRAN 25.10 DU accept it but never send a report. `CQI`, `RSRP` and `RSRQ`
are declared by the DU but not supported. Older copies of this recorder listened on RMR port 4561 and
at times received nothing even though the DU log showed `Sending E2 indication`: if a subscription
succeeds but no rows appear, check that the startup line says `p=4562`.

## Start order on sl04 (ZMQ radio)

1. CU, then wait for `N2: Connection to AMF ... completed`.
2. DU (at least 60 s after the DU last disconnected: the OSC RIC's E2 reconnect timer).
3. srsUE straight after the DU, then `sudo ip netns exec ue1 ip route add default dev tun_srsue`.

With the ZMQ radio, the DU and UE must restart together, DU first: a new srsUE cannot sync to
a DU that has already streamed to another one.
