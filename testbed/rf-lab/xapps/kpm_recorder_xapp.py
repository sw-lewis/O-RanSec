#!/usr/bin/env python3
"""KPM recorder xApp for the O-RAN SC near-RT RIC (srsRAN oran-sc-ric Python xApp framework).

Subscribes to E2SM-KPM on every connected O-DU (or the E2 nodes given with --e2_node_id) and
writes every measurement to a CSV file in long format, one row per value:

    rx_utc, collet_start_utc, e2_node, report_style, ue_id, granul_ms, metric, value

- rx_utc:           when the xApp received the RIC Indication (UTC, millisecond resolution).
                    This is the clock to align with flow records (run chrony on every machine).
- collet_start_utc: the collection start time the E2 node put in the indication header (UTC).
- ue_id:            the RAN's UE identifier in the KPM report (report styles 3-5), not an IMSI
                    or IP address; map it with the UE resolver. Empty for node-level reports.

Default is report style 4 (per-UE, all UEs that match a condition every UE satisfies), every
1 s, with the fourteen measurements that the srsRAN 25.10 O-DU reports per UE (see METRICS).

Run inside the python_xapp_runner container (this file goes in oran-sc-ric/xApps/python/):
    docker compose exec python_xapp_runner ./kpm_recorder_xapp.py --out data/kpm.csv
Rows are flushed as they arrive; stop with Ctrl-C (the subscriptions are removed on exit).
"""
import argparse
import csv
import datetime
import json
import os
import signal
import sys
import threading
import urllib.request

from lib.xAppBase import xAppBase

# srsRAN 25.10 O-DU, per-UE (style 4): all fourteen DU measurements below were recorded together in
# one subscription on 25 Oct 2026 (units from lib/e2/e2sm/e2sm_kpm/e2sm_kpm_du_meas_provider_impl.cpp):
#   DRB.UEThpDl/Ul                    kbit/s
#   DRB.RlcSduTransmittedVolumeDL/UL  kbit per period
#   RRU.PrbUsedDl/Ul                  mean PRBs used per slot by the UE (integer)
#   RRU.PrbAvailDl/Ul                 cell PRBs minus mean PRBs used (integer)
#   RRU.PrbTotDl/Ul                   PRB usage, % of the cell (integer)
#   DRB.RlcSduDelayDl                 DL RLC SDU delay, 0.1 ms units
#   DRB.RlcDelayUl                    UL RLC SDU delay, 0.1 ms units
#   DRB.AirIfDelayUl                  UL air-interface (CRC) delay, 0.1 ms units
#   DRB.RlcPacketDropRateDl           DL RLC packet drop rate, %
# DRB.PacketSuccessRateUlgNBUu is a CU-UP measurement (not on the DU). CQI, RSRP and RSRQ are declared
# by the DU but not supported.
METRICS = ",".join([
    "DRB.UEThpDl", "DRB.UEThpUl",
    "DRB.RlcSduTransmittedVolumeDL", "DRB.RlcSduTransmittedVolumeUL",
    "RRU.PrbUsedDl", "RRU.PrbUsedUl", "RRU.PrbAvailDl", "RRU.PrbAvailUl", "RRU.PrbTotDl", "RRU.PrbTotUl",
    "DRB.RlcSduDelayDl", "DRB.RlcDelayUl", "DRB.AirIfDelayUl",
    "DRB.RlcPacketDropRateDl",
])
# Per-UE scheduler measurements added by rf-lab/srsran-patches/0001 (non-standard names, "SRSRAN." prefix).
# Only an O-DU built with that patch reports them; request them with --srsran_ext.
SRSRAN_EXT = ",".join([
    "SRSRAN.UeCqi", "SRSRAN.UeDlMcs", "SRSRAN.UeUlMcs", "SRSRAN.UeDlRi", "SRSRAN.UeUlRi",
    "SRSRAN.UePuschSnr", "SRSRAN.UePucchSnr", "SRSRAN.UePuschRsrp",
    "SRSRAN.UeDlHarqOk", "SRSRAN.UeDlHarqNok", "SRSRAN.UeUlCrcOk", "SRSRAN.UeUlCrcNok",
    "SRSRAN.UeDlBuffer", "SRSRAN.UeUlBsr", "SRSRAN.UePhr", "SRSRAN.UeSrCount",
])
FIELDS = ["rx_utc", "collet_start_utc", "e2_node", "report_style", "ue_id", "granul_ms", "metric", "value"]


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def connected_dus(e2mgr_url):
    """O-DU E2 nodes (names starting 'gnbd') that the RIC's E2 Manager reports as CONNECTED."""
    with urllib.request.urlopen(f"{e2mgr_url.rstrip('/')}/v1/nodeb/states", timeout=5) as r:
        nodes = json.load(r) or []
    return [n["inventoryName"] for n in nodes
            if n.get("inventoryName", "").startswith("gnbd") and n.get("connectionStatus") == "CONNECTED"]


class KpmRecorder(xAppBase):
    def __init__(self, config, http_server_port, rmr_port, out_path, quiet):
        super().__init__(config, http_server_port, rmr_port)
        os.makedirs(os.path.dirname(os.path.abspath(out_path)), exist_ok=True)
        new = not os.path.exists(out_path) or os.path.getsize(out_path) == 0
        self.file = open(out_path, "a", newline="")
        self.csv = csv.writer(self.file)
        if new:
            self.csv.writerow(FIELDS)
            self.file.flush()
        self.lock = threading.Lock()
        self.quiet = quiet
        self.rows = 0

    def _write(self, rx, collet, node, style, ue_id, granul, meas):
        n = 0
        with self.lock:
            for metric, values in meas.items():
                for v in (values if isinstance(values, (list, tuple)) else [values]):
                    self.csv.writerow([rx, collet, node, style, "" if ue_id is None else ue_id, granul or "", metric, v])
                    n += 1
            self.file.flush()
            self.rows += n
        return n

    def on_indication(self, e2_node, sub_id, hdr, msg, style):
        rx = utc_now()
        hdr = self.e2sm_kpm.extract_hdr_info(hdr)
        data = self.e2sm_kpm.extract_meas_data(msg)
        collet = hdr["colletStartTime"].isoformat(timespec="milliseconds") + "Z"
        n = 0
        if style in (1, 2):
            n += self._write(rx, collet, e2_node, style, None, data.get("granulPeriod"), data["measData"])
        else:
            for ue_id, ue in data["ueMeasData"].items():
                n += self._write(rx, collet, e2_node, style, ue_id, ue.get("granulPeriod", data.get("granulPeriod")), ue["measData"])
        if not self.quiet:
            ues = "" if style in (1, 2) else f", UEs {sorted(data['ueMeasData'])}"
            print(f"{rx} {e2_node} style {style}{ues}: {n} values (total {self.rows})", flush=True)

    @xAppBase.start_function
    def start(self, e2_nodes, style, ue_ids, metrics, period_ms):
        for node in e2_nodes:
            cb = lambda agent, sub, hdr, msg: self.on_indication(agent, sub, hdr, msg, style)
            print(f"Subscribing to {node}: E2SM-KPM report style {style}, every {period_ms} ms, metrics {metrics}", flush=True)
            if style == 1:
                self.e2sm_kpm.subscribe_report_service_style_1(node, period_ms, metrics, period_ms, cb)
            elif style == 4:
                # A condition every UE satisfies, so the report covers all UEs on the node.
                conds = [{"testCondInfo": {"testType": ("ul-rSRP", "true"), "testExpr": "lessthan", "testValue": ("valueInt", 1000)}}]
                self.e2sm_kpm.subscribe_report_service_style_4(node, period_ms, conds, metrics, period_ms, cb)
            elif style == 5:
                ids = ue_ids if len(ue_ids) > 1 else ue_ids + [ue_ids[0] + 1]  # style 5 needs at least two UE IDs
                self.e2sm_kpm.subscribe_report_service_style_5(node, period_ms, ids, metrics, period_ms, cb)
            else:
                sys.exit(f"report style {style} not supported here (use 1, 4 or 5)")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Record E2SM-KPM measurements to CSV")
    p.add_argument("--out", default="data/kpm.csv", help="CSV file (appended to if it exists)")
    p.add_argument("--kpm_report_style", type=int, default=4, choices=(1, 4, 5))
    p.add_argument("--metrics", default=METRICS, help="comma-separated measurement names")
    p.add_argument("--period_ms", type=int, default=1000, help="reporting and granularity period (srsRAN minimum: 1000)")
    p.add_argument("--e2_node_id", default="", help="comma-separated E2 node IDs; default: every connected O-DU")
    p.add_argument("--e2mgr_url", default=os.environ.get("E2MGR_URL", "http://10.0.2.11:3800"), help="E2 Manager API, for node discovery")
    p.add_argument("--ue_ids", default="0", help="for style 5: comma-separated UE IDs")
    p.add_argument("--ran_func_id", type=int, default=2, help="E2SM-KPM RAN function ID (srsRAN: 2)")
    # Same ports as kpm_mon_xapp.py (the ones the RIC's routes are known to deliver to), so run one
    # of the two at a time.
    p.add_argument("--http_server_port", type=int, default=8092)
    p.add_argument("--rmr_port", type=int, default=4562)
    p.add_argument("--quiet", action="store_true", help="do not print one line per indication")
    p.add_argument("--srsran_ext", action="store_true",
                   help="also request the SRSRAN.* per-UE scheduler measurements (patched O-DU only)")
    a = p.parse_args()
    if a.srsran_ext:
        a.metrics = ",".join([a.metrics, SRSRAN_EXT])

    nodes = [n for n in a.e2_node_id.split(",") if n] or connected_dus(a.e2mgr_url)
    if not nodes:
        sys.exit(f"No connected O-DU found via {a.e2mgr_url}; start the DU or pass --e2_node_id")

    x = KpmRecorder("", a.http_server_port, a.rmr_port, a.out, a.quiet)
    x.e2sm_kpm.set_ran_func_id(a.ran_func_id)
    for s in (signal.SIGQUIT, signal.SIGTERM, signal.SIGINT):
        signal.signal(s, x.signal_handler)
    print(f"Writing to {os.path.abspath(a.out)}", flush=True)
    x.start(nodes, a.kpm_report_style, [int(u) for u in a.ue_ids.split(",")], a.metrics.split(","), a.period_ms)
