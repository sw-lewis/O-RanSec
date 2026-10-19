"""Builds the live testbed state every couple of seconds from real sources only:
Kubernetes (is it running), Prometheus (Open5GS metrics, flowmon link traffic, cAdvisor,
node-exporter) and Loki (error rates). The catalog only says what should exist."""
import asyncio
import pathlib
import time

import yaml

from . import kube, ran, sources

CATALOG = yaml.safe_load((pathlib.Path(__file__).parent / "catalog.yaml").read_text())
COMPONENTS = {c["id"]: c for c in CATALOG["components"]}
RECENT_RESTART = 300  # seconds: a restart in the last 5 min marks a component degraded
SETTLE = 240  # restarts during the first 4 min after the dashboard starts (VM boot) are start-up ordering
SESSION_IFACES = {"Uu", "N2", "N3", "N4", "N6", "SBI", "E2", "E42", "DB"}
MONITORING_NS = {"sixg-obs", "sixg-control"}
WATCH_NS = {"sixg-core", "sixg-ran", "sixg-ric", "sixg-edge", "sixg-devices", "sixg-attack",
            "external", "user-plane"}


def _by(results, *keys):
    out = {}
    for labels, v in results:
        out[tuple(labels.get(k, "") for k in keys)] = v
    return out


async def _q(query):
    try:
        return await sources.prom(query)
    except Exception:
        return None


async def gather_metrics():
    queries = {
        # Each Open5GS function is one pod, so max, not sum: after a VM reboot the pod's series from
        # its old IP lingers for 5 minutes (no staleness marker was written) and sum counts twice.
        "gnb": "max(gnb)",
        "ran_ue": "max(ran_ue)",
        "amf_sessions": "max(amf_session)",
        "registered": "max by (snssai) (fivegs_amffunction_rm_registeredsubnbr)",
        "sessions": "max by (snssai) (fivegs_smffunction_sm_sessionnbr)",
        "upf_sessions": "max by (nf) (fivegs_upffunction_upf_sessionnbr)",
        "link_rate": "sum by (src,dst,iface,src_ns,dst_ns) (sixg_link_bits_per_second)",
        "link_pps": "sum by (src,dst,iface) (sixg_link_packets_per_second)",
        "link_flows": "sum by (src,dst,iface,src_ns,dst_ns) (sixg_link_active_flows)",
        "link_total": "sum by (src,dst,iface) (sixg_link_bytes_total)",
        "pod_cpu": 'sum by (namespace,pod) (rate(container_cpu_usage_seconds_total{container!="",namespace=~"sixg-.*|kube-system"}[1m]))',
        "pod_mem": 'sum by (namespace,pod) (container_memory_working_set_bytes{container!="",namespace=~"sixg-.*|kube-system"})',
        "node_cpu": '1 - avg(rate(node_cpu_seconds_total{mode="idle"}[1m]))',
        "node_mem": "1 - sum(node_memory_MemAvailable_bytes) / sum(node_memory_MemTotal_bytes)",
        "node_disk": '1 - sum(node_filesystem_avail_bytes{mountpoint="/"}) / sum(node_filesystem_size_bytes{mountpoint="/"})',
        "flowmon_age": "time() - max(sixg_flowmon_last_poll_timestamp)",
        "targets_up": 'sum by (job) (up)',
        "targets_total": 'count by (job) (up)',
    }
    names = list(queries)
    results = await asyncio.gather(*(_q(queries[n]) for n in names))
    return dict(zip(names, results))


class LogStats:
    """Log counters from Loki, refreshed on their own slower timer. Counting every line of
    every namespace takes Loki >10 s, so it must never sit in the 2 s live-state loop."""

    def __init__(self, period=30):
        self.period = period
        self.errors = None   # namespace -> error lines in the last 5 min
        self.total = None    # namespace -> all lines in the last 5 min
        self.updated = 0.0
        self.ok = False

    async def run(self):
        while True:
            try:
                err = await sources.loki_instant(
                    'sum by (namespace) (count_over_time({namespace=~"sixg-.+", level=~"error|fatal|err|crit"}[5m]))')
                self.errors = {r["metric"].get("namespace"): float(r["value"][1]) for r in err}
                r = await sources.http.get(f"{sources.LOKI}/loki/api/v1/query", timeout=60, params={
                    "query": 'sum by (namespace) (count_over_time({namespace=~"sixg-.+"}[5m]))'})
                r.raise_for_status()
                self.total = {x["metric"].get("namespace"): float(x["value"][1]) for x in r.json()["data"]["result"]}
                self.updated, self.ok = time.time(), True
            except Exception as e:
                self.ok = False
                print("log stats:", repr(e), flush=True)
            await asyncio.sleep(self.period)


logstats = LogStats()


async def loki_alive():
    try:
        r = await sources.http.get(f"{sources.LOKI}/ready", timeout=3)
        return r.status_code == 200
    except Exception:
        return False


def _slice_key(snssai):
    sst = snssai.split("-")[0]
    return {"1": "embb", "2": "urllc", "3": "mmtc"}.get(sst, snssai)


RESTART_BASE = {}  # (ns, pod) -> restart count when first seen
RESTART_SEEN = {}  # (ns, pod) -> time a restart was observed


STARTED = time.time()


def track_restarts(pods):
    now = time.time()
    settling = now - STARTED < SETTLE
    for p in pods:
        k = (p["ns"], p["name"])
        if k not in RESTART_BASE:
            RESTART_BASE[k] = p["restarts"]
        elif p["restarts"] > RESTART_BASE[k]:
            RESTART_BASE[k] = p["restarts"]
            if not settling:
                RESTART_SEEN[k] = now


def component_status(c, workloads, pods_by_wl, m):
    """Returns (status, notes). status: up | degraded | down | stopped | absent | unknown."""
    notes = []
    if c.get("virtual"):
        if c["id"] == "internet":
            rates = m.get("link_rate") or []
            n6 = sum(v for l, v in rates if l.get("iface") == "N6" or l.get("dst") == "internet")
            return ("up" if n6 > 0 else "idle"), [f"N6 traffic {n6:.0f} bit/s"]
        return "unknown", notes

    wl = c.get("workload", c["id"])
    w = workloads.get((c["ns"], wl))
    if not w:
        return "absent", ["not deployed"]
    if w["desired"] == 0:
        return "stopped", ["scaled to 0"]
    pods = pods_by_wl.get((c["ns"], wl), [])
    if c.get("container"):  # a container inside another component's pod
        ok = any(p["containerReady"].get(c["container"]) for p in pods)
        if not ok:
            return "down", [f"container {c['container']} not ready"]
        notes.append(f"container '{c['container']}' in {wl} pod")
    elif w["ready"] == 0:
        reasons = [p["reason"] for p in pods if p["reason"]]
        return "down", [reasons[0] if reasons else "no ready pod"]
    status = "up" if w["ready"] >= w["desired"] else "degraded"
    # Only restarts seen while the dashboard is running count (a VM boot restarts everything).
    now = time.time()
    crashed = [RESTART_SEEN[(c["ns"], p["name"])] for p in pods
               if now - RESTART_SEEN.get((c["ns"], p["name"]), 0) < RECENT_RESTART]
    if crashed:
        status = "degraded"
        notes.append(f"container restarted {int(now - max(crashed))}s ago")

    # functional checks from real metrics
    cid = c["id"]
    flows = m.get("link_flows") or []

    def has_flow(a, iface):
        return any(v > 0 and l.get("iface") == iface and a in (l.get("src"), l.get("dst")) for l, v in flows)

    if cid == "core-amf" and m.get("gnb") is not None:
        n = int(sum(v for _, v in m["gnb"]))
        notes.append(f"{n} gNB connected")
        if n == 0:
            status = "degraded"
    if cid in ("gnb1", "srsgnb"):
        if has_flow(cid, "N2"):
            notes.append("N2 to AMF established")
        elif status == "up":
            status, _ = "degraded", notes.append("no N2 association seen")
    if cid in ("core-upf", "upf-urllc", "upf-mmtc"):
        s = {l.get("nf"): v for l, v in (m.get("upf_sessions") or [])}.get(cid)
        if s is not None:
            notes.append(f"{int(s)} PDU sessions")
        if has_flow(cid, "N4"):
            notes.append("PFCP associated with SMF")
        elif status == "up":
            status = "degraded"
            notes.append("no PFCP (N4) association seen")
    if cid == "srsgnb" and has_flow(cid, "E2"):
        notes.append("E2 connected to RIC")
    if cid == "srsue":  # attached = the gNB reports it in its cell's UE list
        srs = ran.srs.snapshot()
        n = sum(len(c.get("ue_list", [])) for c in (srs["reports"].get("cells") or []))
        if srs["connected"] and n:
            notes.append(f"attached, {n} UE in srsRAN cell")
        elif status == "up":
            status = "degraded"
            notes.append("not attached to the srsRAN cell")
    return status, notes


def build_links(m, statuses, device_ids=()):
    rate = {}
    for l, v in m.get("link_rate") or []:
        key = (l.get("src"), l.get("dst"), l.get("iface"))
        rate[key] = rate.get(key, 0) + v
    pps = {}
    for l, v in m.get("link_pps") or []:
        pps[(l.get("src"), l.get("dst"), l.get("iface"))] = v
    flows = {}
    ns_of = {}
    for l, v in m.get("link_flows") or []:
        k = (l.get("src"), l.get("dst"), l.get("iface"))
        flows[k] = flows.get(k, 0) + v
        ns_of[k] = (l.get("src_ns"), l.get("dst_ns"))
    for l, _ in m.get("link_rate") or []:
        ns_of.setdefault((l.get("src"), l.get("dst"), l.get("iface")), (l.get("src_ns"), l.get("dst_ns")))

    def sum_pair(d, a, b, iface):
        return d.get((a, b, iface), 0) + d.get((b, a, iface), 0)

    # srsUE <-> srsRAN gNB runs over ZMQ on localhost inside one pod, invisible to conntrack;
    # its real source is the gNB's own per-UE MAC bit rates.
    srs = ran.srs.snapshot()
    srs_bps = None
    if srs["connected"] and (srs["age"] or 99) < 10:
        cells = srs["reports"].get("cells") or []
        srs_bps = sum((u.get("dl_brate") or 0) + (u.get("ul_brate") or 0)
                      for c in cells for u in c.get("ue_list", []))

    links = []
    covered = set()
    expected = CATALOG["links"] + [{"a": d, "b": "gnb1", "iface": "Uu"} for d in device_ids]
    for L in expected:
        a, b, iface = L["a"], L["b"], L["iface"]
        covered |= {(a, b, iface), (b, a, iface)}
        r = sum_pair(rate, a, b, iface)
        f = sum_pair(flows, a, b, iface)
        if (a, b, iface) == ("srsue", "srsgnb", "Uu") and srs_bps is not None:
            r, f = srs_bps, 1
        ends = (statuses.get(a, "unknown"), statuses.get(b, "unknown"))
        if any(s in ("down", "stopped", "absent") for s in ends):
            st = "down"
        elif r > 1:
            st = "active"
        elif f > 0:
            st = "connected"
        else:
            st = "idle"
        links.append({"a": a, "b": b, "iface": iface, "bps": r, "pps": sum_pair(pps, a, b, iface),
                      "flows": f, "status": st, "expected": True})

    # Links that exist in reality but are not in the architecture model (e.g. an attacker).
    for (s, d, iface), r in rate.items():
        if (s, d, iface) in covered or iface not in SESSION_IFACES | {"other"} or "vm-node" in (s, d):
            continue
        sn, dn = ns_of.get((s, d, iface), ("", ""))
        if sn not in WATCH_NS and dn not in WATCH_NS:
            continue
        if {sn, dn} & MONITORING_NS:
            continue  # the testbed's own monitoring/control traffic
        if s == d:
            continue
        covered |= {(s, d, iface), (d, s, iface)}
        links.append({"a": s, "b": d, "iface": iface, "bps": sum_pair(rate, s, d, iface),
                      "pps": sum_pair(pps, s, d, iface), "flows": sum_pair(flows, s, d, iface),
                      "status": "active" if r > 1 else "connected", "expected": False,
                      "ns": [sn, dn]})
    return links


async def build():
    workloads, pods, events, node, kube_updated = kube.cache.snapshot()
    kube_age = time.time() - kube_updated  # measured now, not after the queries below
    m, loki_ok = await asyncio.gather(gather_metrics(), loki_alive())
    log_err, log_tot = logstats.errors, logstats.total

    track_restarts(pods)
    pods_by_wl = {}
    for p in pods:
        pods_by_wl.setdefault((p["ns"], p["workload"]), []).append(p)

    cpu = {(l.get("namespace"), l.get("pod")): v for l, v in (m.get("pod_cpu") or [])}
    mem = {(l.get("namespace"), l.get("pod")): v for l, v in (m.get("pod_mem") or [])}

    # connected devices (created from the Devices tab) are real components too
    device_comps = [
        {"id": name, "label": name.removeprefix("dev-").rsplit("-", 1)[0], "layer": "ue", "ns": ns,
         "kind": "Deployment", "software": "Device gateway (UERANSIM UE)", "slice": w["labels"].get("sixg/slice"),
         "device": True}
        for (ns, name), w in sorted(workloads.items())
        if ns == "sixg-devices" and w["labels"].get("sixg/role") == "device-gateway"]
    for d in device_comps:
        COMPONENTS[d["id"]] = d

    comps = []
    statuses = {}
    for c in CATALOG["components"] + device_comps:
        st, notes = component_status(c, workloads, pods_by_wl, m)
        statuses[c["id"]] = st
        cp = pods_by_wl.get((c.get("ns"), c.get("workload", c["id"])), [])
        comps.append({
            **{k: c.get(k) for k in ("id", "label", "layer", "ns", "kind", "software", "slice", "virtual", "ueGroup", "device")},
            "status": st,
            "notes": notes,
            "pods": [{"name": p["name"], "ready": p["ready"], "phase": p["phase"], "ip": p["ip"],
                      "restarts": p["restarts"], "age": p["age"], "reason": p["reason"]} for p in cp],
            "cpu": sum(cpu.get((p["ns"], p["name"]), 0) for p in cp),
            "mem": sum(mem.get((p["ns"], p["name"]), 0) for p in cp),
            "desired": (workloads.get((c.get("ns"), c.get("workload", c["id"]))) or {}).get("desired"),
            "workload": c.get("workload", c["id"]),
            "container": c.get("container"),
        })

    links = build_links(m, statuses, [d["id"] for d in device_comps])

    # slice KPIs
    reg = {_slice_key(l.get("snssai", "")): v for l, v in (m.get("registered") or [])}
    ses = {_slice_key(l.get("snssai", "")): v for l, v in (m.get("sessions") or [])}
    upf_of = {"embb": "core-upf", "urllc": "upf-urllc", "mmtc": "upf-mmtc"}
    slices = []
    for s in CATALOG["slices"]:
        upf = upf_of[s["id"]]
        n3 = sum(l["bps"] for l in links if l["iface"] == "N3" and upf in (l["a"], l["b"]))
        n6 = sum(l["bps"] for l in links if l["iface"] == "N6" and upf in (l["a"], l["b"]))
        slices.append({**s, "upf": upf, "registered": reg.get(s["id"]), "sessions": ses.get(s["id"]),
                       "n3_bps": n3, "n6_bps": n6, "upfStatus": statuses.get(upf)})

    def one(key):
        r = m.get(key)
        return None if not r else r[0][1]

    up = {l.get("job"): v for l, v in (m.get("targets_up") or [])}
    tot = {l.get("job"): v for l, v in (m.get("targets_total") or [])}
    alerts = await sources.alerts()
    active_alerts = [a for a in (alerts or []) if a.get("labels", {}).get("severity") != "none"]

    counts = {}
    for c in comps:
        counts[c["status"]] = counts.get(c["status"], 0) + 1

    return {
        "ts": time.time(),
        "sources": {
            "kubernetes": {"ok": kube_age < 10, "age": kube_age},
            "prometheus": {"ok": m.get("gnb") is not None or m.get("node_cpu") is not None},
            "loki": {"ok": loki_ok, "statsAge": (time.time() - logstats.updated) if logstats.updated else None},
            "flowmon": {"ok": (one("flowmon_age") or 999) < 15, "age": one("flowmon_age")},
            "alertmanager": {"ok": alerts is not None},
        },
        "node": {**node, "cpuUsed": one("node_cpu"), "memUsed": one("node_mem"), "diskUsed": one("node_disk")},
        "kpis": {
            "gnbs": one("gnb"),
            "ranUes": one("ran_ue"),
            "amfSessions": one("amf_sessions"),
            "registeredTotal": sum(v for v in reg.values() if v is not None) if reg else None,
            "sessionsTotal": sum(v for v in ses.values() if v is not None) if ses else None,
            "n3Bps": sum(s["n3_bps"] for s in slices),
            "n6Bps": sum(s["n6_bps"] for s in slices),
            "alerts": len(active_alerts),
            "logErrors5m": sum(log_err.values()) if log_err is not None else None,
            "logLines5m": sum(log_tot.values()) if log_tot is not None else None,
            "logErrorsByNs": log_err,
            "componentCounts": counts,
            "scrapeTargets": {j: {"up": up.get(j, 0), "total": t} for j, t in tot.items()},
        },
        "components": comps,
        "links": links,
        "slices": slices,
        "alerts": [{"name": a["labels"].get("alertname"), "severity": a["labels"].get("severity"),
                    "summary": a.get("annotations", {}).get("summary") or a.get("annotations", {}).get("description"),
                    "since": a.get("startsAt")} for a in active_alerts][:50],
        "events": events[:60],
    }


class Hub:
    """Rebuilds state on a timer and fans it out to WebSocket subscribers."""

    def __init__(self, period=2.0):
        self.period = period
        self.latest = None
        self.subscribers = set()

    async def run(self):
        while True:
            try:
                self.latest = await build()
                dead = []
                for q in list(self.subscribers):
                    if q.full():
                        try:
                            q.get_nowait()
                        except asyncio.QueueEmpty:
                            pass
                    try:
                        q.put_nowait(self.latest)
                    except asyncio.QueueFull:
                        dead.append(q)
                for q in dead:
                    self.subscribers.discard(q)
            except Exception as e:
                print("state build:", repr(e), flush=True)
            await asyncio.sleep(self.period)


hub = Hub()
