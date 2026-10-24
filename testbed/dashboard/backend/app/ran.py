"""RAN-side live data: UERANSIM (via its own nr-cli inside the pods), srsRAN gNB metrics
(its remote-control WebSocket) and the Open5GS subscriber database."""
import asyncio
import json
import os
import time

import httpx
import websockets
import yaml
from pymongo import MongoClient

from . import kube

SRSGNB_WS = os.environ.get("SRSGNB_WS", "ws://srsgnb.sixg-ran.svc.cluster.local:8001")
# RF lab on sl04 (outside the VM): its O-DU's metrics WebSocket and its OSC RIC's E2 Manager API.
# Empty = not configured; the sl04 components then show as "unknown".
SL04_WS = os.environ.get("SL04_WS", "")
SL04_E2MGR = os.environ.get("SL04_E2MGR_URL", "")
MONGO = os.environ.get("MONGO_URL", "mongodb://core-mongodb.sixg-core.svc.cluster.local:27017/open5gs")


def _nr(ns, workload, args):
    return kube.exec_in(ns, workload, ["nr-cli", *args])


def _yaml(text):
    try:
        return yaml.safe_load(text)
    except yaml.YAMLError:
        return {"raw": text}


def ue_group(ns, workload):
    """All UEs inside one UERANSIM UE pod: identity, RM/CM state, PDU sessions."""
    nodes = [n.strip() for n in _nr(ns, workload, ["--dump"]).splitlines() if n.strip().startswith("imsi-")]
    ues = []
    for node in nodes:
        status = _yaml(_nr(ns, workload, [node, "--exec", "status"])) or {}
        sessions = _yaml(_nr(ns, workload, [node, "--exec", "ps-list"])) or {}
        ues.append({"id": node, "status": status, "sessions": sessions})
    return ues


def gnb_info(ns, workload):
    node = next((n.strip() for n in _nr(ns, workload, ["--dump"]).splitlines() if n.strip()), None)
    if not node:
        return None
    return {
        "node": node,
        "status": _yaml(_nr(ns, workload, [node, "--exec", "status"])),
        "info": _yaml(_nr(ns, workload, [node, "--exec", "info"])),
        "amf": _yaml(_nr(ns, workload, [node, "--exec", "amf-list"])),
        "ues": _yaml(_nr(ns, workload, [node, "--exec", "ue-list"])),
    }


UE_ACTIONS = {
    "deregister": ["deregister", "normal"],
    "switch-off": ["deregister", "switch-off"],
    "ps-release-all": ["ps-release-all"],
}


def ue_action(ns, workload, ue, action, arg=None):
    if action == "ps-establish":
        cmd = ["ps-establish", "IPv4", "--sst", str(arg["sst"]), "--sd", str(arg["sd"]), "--dnn", arg["dnn"]]
    elif action in UE_ACTIONS:
        cmd = UE_ACTIONS[action]
    else:
        raise ValueError(f"unknown action {action}")
    return _nr(ns, workload, [ue, "--exec", " ".join(cmd)])


def traffic_test(ns, workload, iface="uesimtun0", target="8.8.8.8", count=10):
    """Real ICMP test through the UE's tunnel (goes UE -> gNB -> UPF -> Internet)."""
    return kube.exec_in(ns, workload, ["ping", "-I", iface, "-c", str(count), "-i", "0.2", "-W", "2", target], timeout=60)


# ---------- srsRAN gNB metrics ----------

class SrsMetrics:
    """Keeps a subscription to an srsRAN gNB/DU metrics WebSocket; stores the latest reports."""

    def __init__(self, url):
        self.url = url
        self.latest = {}
        self.updated = 0.0
        self.connected = False
        self.error = None

    async def run(self):
        while True:
            try:
                async with websockets.connect(self.url, open_timeout=5, ping_interval=20) as ws:
                    await ws.send(json.dumps({"cmd": "metrics_subscribe"}))
                    self.connected, self.error = True, None
                    async for msg in ws:
                        try:
                            data = json.loads(msg)
                        except ValueError:
                            continue
                        # Each message is one report type (e.g. cells, du, rlc); keep the latest of each.
                        for k, v in data.items():
                            if k not in ("cmd",):
                                self.latest[k] = v
                        self.updated = time.time()
            except Exception as e:  # gNB not deployed or restarting
                self.connected, self.error = False, str(e)[:200]
            await asyncio.sleep(3)

    def snapshot(self):
        return {"connected": self.connected, "error": self.error,
                "age": (time.time() - self.updated) if self.updated else None, "reports": self.latest}

    def fresh(self, max_age=10):
        return self.connected and self.updated and time.time() - self.updated < max_age

    def ues(self):
        return [u for c in (self.latest.get("cells") or []) for u in c.get("ue_list", [])]


def not_configured(what):
    return {"connected": False, "configured": False, "error": f"{what} not configured", "age": None, "reports": {}}


srs = SrsMetrics(SRSGNB_WS)
srs_sl04 = SrsMetrics(SL04_WS) if SL04_WS else None


class E2Manager:
    """Polls an O-RAN SC near-RT RIC's E2 Manager REST API for the E2 nodes it knows and their
    connection state (GET /v1/nodeb/states). Answers 'is the RIC up' and 'which E2 nodes are connected'."""

    def __init__(self, url, period=5):
        self.url = url.rstrip("/")
        self.period = period
        self.nodes = []        # [{"name", "status", "plmn", "nbId"}]
        self.reachable = False
        self.error = None
        self.updated = 0.0

    async def run(self):
        async with httpx.AsyncClient(timeout=4) as http:
            while True:
                try:
                    r = await http.get(f"{self.url}/v1/nodeb/states")
                    r.raise_for_status()
                    nodes = []
                    for n in r.json() or []:
                        g = n.get("globalNbId") or {}
                        nodes.append({"name": n.get("inventoryName") or n.get("ranName"),
                                      "status": n.get("connectionStatus") or "UNKNOWN",
                                      "plmn": g.get("plmnId"), "nbId": g.get("nbId")})
                    self.nodes, self.reachable, self.error, self.updated = nodes, True, None, time.time()
                except Exception as e:  # RIC down, port not published, or sl04 unreachable
                    self.reachable, self.error = False, str(e)[:200]
                await asyncio.sleep(self.period)

    def connected(self, prefix=""):
        return [n for n in self.nodes if n["status"] == "CONNECTED" and (n["name"] or "").startswith(prefix)]

    def snapshot(self):
        return {"configured": True, "reachable": self.reachable, "error": self.error, "url": self.url,
                "age": (time.time() - self.updated) if self.updated else None, "nodes": self.nodes}


ric_sl04 = E2Manager(SL04_E2MGR) if SL04_E2MGR else None


# ---------- Open5GS subscribers ----------

_mongo = None


def subscribers():
    global _mongo
    if _mongo is None:
        _mongo = MongoClient(MONGO, serverSelectionTimeoutMS=3000)
    out = []
    for s in _mongo.get_default_database()["subscribers"].find({}, {"_id": 0, "security": 0}):
        slices = []
        for sl in s.get("slice", []):
            slices.append({"sst": sl.get("sst"), "sd": sl.get("sd"),
                           "dnn": [x.get("name") for x in sl.get("session", [])]})
        out.append({"imsi": s.get("imsi"), "msisdn": s.get("msisdn", []), "slices": slices,
                    "ambr": s.get("ambr"), "status": s.get("subscriber_status")})
    out.sort(key=lambda x: x["imsi"] or "")
    return out
