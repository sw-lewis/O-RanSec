# srsRAN patches for the RF lab

## 0001: per-UE scheduler measurements over E2SM-KPM

Against srsRAN Project `release_25_10` (25.10.0, d2f4b70). Adds 16 per-UE measurements to the O-DU's
E2SM-KPM provider, read from the scheduler's per-UE metrics (the same values the DU prints and sends on its
metrics WebSocket). Names use the prefix `SRSRAN.`, so they are never mistaken for 3GPP TS 28.552 names.
They are UE-level only (report styles 2-5); a node-level request gets "no value".

| Measurement | Value | Type |
|---|---|---|
| `SRSRAN.UeCqi` | mean CQI over the report period | integer |
| `SRSRAN.UeDlMcs`, `SRSRAN.UeUlMcs` | MCS used for DL / UL grants | integer |
| `SRSRAN.UeDlRi`, `SRSRAN.UeUlRi` | mean rank indicator | real |
| `SRSRAN.UePuschSnr`, `SRSRAN.UePucchSnr` | SNR, dB | real |
| `SRSRAN.UePuschRsrp` | PUSCH RSRP, dB | real |
| `SRSRAN.UeDlHarqOk`, `SRSRAN.UeDlHarqNok` | DL HARQ ACKs / NACKs in the period | integer |
| `SRSRAN.UeUlCrcOk`, `SRSRAN.UeUlCrcNok` | UL CRC passes / failures in the period | integer |
| `SRSRAN.UeDlBuffer` | DL buffer occupancy, bytes | integer |
| `SRSRAN.UeUlBsr` | UL buffer status report, bytes | integer |
| `SRSRAN.UePhr` | last power headroom report, dB (−23 to +40) | real |
| `SRSRAN.UeSrCount` | scheduling requests in the period | integer |

A value the scheduler has not measured in the period (no CQI report, no PHR, no PUSCH) is sent as
"no value", not 0. The UE is found by its DU UE index, not by its position in the metrics list.

The patch compiles cleanly (`make srsran_e2`, GCC, Release). It has not yet been run against the OSC RIC.

### Apply and build (sl04)

```bash
cd ~/oran/srsRAN_Project
git status --short                      # should be clean
git apply --check ~/O-RanSec/testbed/rf-lab/srsran-patches/0001-e2sm-kpm-per-ue-scheduler-measurements.patch
git apply        ~/O-RanSec/testbed/rf-lab/srsran-patches/0001-e2sm-kpm-per-ue-scheduler-measurements.patch
cd build && taskset -c 2-11 make -j10 srsdu
```

Only `srsdu` needs rebuilding. To remove the patch: `git apply -R <patch>` and rebuild.

### Record with the extra measurements

```bash
cd ~/oran/oran-sc-ric
docker compose exec python_xapp_runner ./kpm_recorder_xapp.py --srsran_ext --out data/kpm_ext.csv
```

`--srsran_ext` adds the 16 `SRSRAN.*` names to the 14 standard ones (30 per UE). If no rows appear,
first try the 16 on their own (`--metrics` with the names above) to see whether the subscription size
is the issue.
