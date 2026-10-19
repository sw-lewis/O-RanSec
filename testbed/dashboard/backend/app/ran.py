"""RAN-side live data: UERANSIM (via its own nr-cli inside the pods), srsRAN gNB metrics
(its remote-control WebSocket) and the Open5GS subscriber database."""
import asyncio
import json
import os
import time

import websockets
import yaml
from pymongo import MongoClient

from . import kube

SRSGNB_WS = os.environ.get("SRSGNB_WS", "ws://srsgnb.sixg-ran.svc.cluster.local:8001")
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
    """Keeps a subscription to the srsRAN gNB metrics WebSocket; stores the latest reports."""

    def __init__(self):
        self.latest = {}
        self.updated = 0.0
        self.connected = False
        self.error = None

    async def run(self):
        while True:
            try:
                async with websockets.connect(SRSGNB_WS, open_timeout=5, ping_interval=20) as ws:
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


srs = SrsMetrics()


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
