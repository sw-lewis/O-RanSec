"""Clients for Prometheus, Loki and Alertmanager (all inside the cluster)."""
import os
import time

import httpx

PROM = os.environ.get("PROM_URL", "http://kps-prometheus.sixg-obs.svc.cluster.local:9090")
LOKI = os.environ.get("LOKI_URL", "http://loki.sixg-obs.svc.cluster.local:3100")
ALERTMANAGER = os.environ.get("AM_URL", "http://kps-alertmanager.sixg-obs.svc.cluster.local:9093")

http = httpx.AsyncClient(timeout=10)


async def prom(query):
    """Instant PromQL query -> list of (labels, float value)."""
    r = await http.get(f"{PROM}/api/v1/query", params={"query": query})
    r.raise_for_status()
    out = []
    for s in r.json()["data"]["result"]:
        try:
            out.append((s["metric"], float(s["value"][1])))
        except (KeyError, ValueError):
            pass
    return out


async def prom_range(query, seconds=900, step=None):
    end = time.time()
    start = end - seconds
    step = step or max(2, int(seconds / 300))
    r = await http.get(f"{PROM}/api/v1/query_range",
                       params={"query": query, "start": start, "end": end, "step": step})
    r.raise_for_status()
    return r.json()["data"]["result"]


async def prom_targets():
    r = await http.get(f"{PROM}/api/v1/targets", params={"state": "active"})
    r.raise_for_status()
    return r.json()["data"]["activeTargets"]


async def loki_range(query, start_ns=None, end_ns=None, limit=1000, direction="backward"):
    params = {"query": query, "limit": limit, "direction": direction}
    if start_ns:
        params["start"] = str(int(start_ns))
    if end_ns:
        params["end"] = str(int(end_ns))
    r = await http.get(f"{LOKI}/loki/api/v1/query_range", params=params, timeout=30)
    r.raise_for_status()
    return r.json()["data"]["result"]


async def loki_instant(query):
    r = await http.get(f"{LOKI}/loki/api/v1/query", params={"query": query})
    r.raise_for_status()
    return r.json()["data"]["result"]


async def loki_labels(label):
    r = await http.get(f"{LOKI}/loki/api/v1/label/{label}/values",
                       params={"start": str(int((time.time() - 86400) * 1e9))})
    r.raise_for_status()
    return r.json().get("data", [])


async def alerts():
    try:
        r = await http.get(f"{ALERTMANAGER}/api/v2/alerts", params={"active": "true", "silenced": "false"})
        r.raise_for_status()
        return r.json()
    except httpx.HTTPError:
        return None
