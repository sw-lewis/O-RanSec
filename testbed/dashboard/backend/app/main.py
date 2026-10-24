"""6G testbed control-panel API."""
import asyncio
import json
import re
import pathlib
import time

import websockets
from fastapi import FastAPI, HTTPException, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import audit, bundle, devices, kube, ran, sources, state, testrecords

app = FastAPI(title="6G Testbed Control Panel", docs_url="/api/docs", openapi_url="/api/openapi.json")
STATIC = pathlib.Path(__file__).parent.parent / "static"


@app.on_event("startup")
async def _start():
    asyncio.create_task(state.hub.run())
    asyncio.create_task(state.logstats.run())
    asyncio.create_task(ran.srs.run())
    if ran.srs_sl04:
        asyncio.create_task(ran.srs_sl04.run())
    if ran.ric_sl04:
        asyncio.create_task(ran.ric_sl04.run())
    asyncio.create_task(_upgrade_devices())


async def _upgrade_devices():
    try:
        done = await _blocking(devices.upgrade_existing)
        if done:
            audit.record("device-upgrade", ",".join(done), spec=devices.SPEC_VERSION)
    except Exception as e:
        print("device upgrade:", repr(e), flush=True)


def _component(cid):
    c = state.COMPONENTS.get(cid)
    if not c or c.get("virtual") or c.get("external"):
        # virtual: no workload; external: runs outside the VM (e.g. the RF lab on sl04)
        raise HTTPException(404, f"unknown component {cid}")
    return c


async def _blocking(fn, *a, **kw):
    return await asyncio.to_thread(fn, *a, **kw)


# ---------------- read ----------------

@app.get("/api/health")
async def health():
    return {"ok": True, "stateAge": time.time() - state.hub.latest["ts"] if state.hub.latest else None}


@app.get("/api/catalog")
async def catalog():
    return state.CATALOG


@app.get("/api/state")
async def get_state():
    return state.hub.latest or await state.build()


@app.websocket("/ws/state")
async def ws_state(ws: WebSocket):
    await ws.accept()
    q = asyncio.Queue(maxsize=2)
    state.hub.subscribers.add(q)
    try:
        if state.hub.latest:
            await ws.send_json(state.hub.latest)
        while True:
            await ws.send_json(await q.get())
    except (WebSocketDisconnect, RuntimeError):
        pass
    finally:
        state.hub.subscribers.discard(q)


@app.get("/api/cluster")
async def cluster():
    workloads, pods, events, node, updated = kube.cache.snapshot()
    return {"node": node, "pods": pods, "events": events[:300],
            "workloads": [{"ns": k[0], "name": k[1], **{x: v[x] for x in ("kind", "desired", "ready", "available")}}
                          for k, v in sorted(workloads.items())]}


@app.get("/api/metrics/range")
async def metrics_range(query: str, seconds: int = Query(900, le=86400), step: int | None = None):
    try:
        return await sources.prom_range(query, seconds, step)
    except Exception as e:
        raise HTTPException(502, f"prometheus: {e}")


@app.get("/api/metrics/targets")
async def metrics_targets():
    t = await sources.prom_targets()
    return [{"job": x["labels"].get("job"), "instance": x["labels"].get("instance"), "health": x["health"],
             "lastError": x.get("lastError"), "lastScrape": x.get("lastScrape")} for x in t]


@app.get("/api/logs")
async def logs(query: str = '{namespace=~"sixg-.+"}', minutes: int = Query(15, le=10080),
               limit: int = Query(500, le=5000)):
    end = time.time_ns()
    try:
        streams = await sources.loki_range(query, end - minutes * 60 * 10**9, end, limit)
    except Exception as e:
        raise HTTPException(502, f"loki: {e}")
    lines = [{"ts": int(ts), "line": line, "labels": s["stream"]}
             for s in streams for ts, line in s["values"]]
    lines.sort(key=lambda x: x["ts"], reverse=True)
    return lines[:limit]


@app.get("/api/logs/labels/{label}")
async def log_labels(label: str):
    return await sources.loki_labels(label)


@app.websocket("/ws/logs")
async def ws_logs(ws: WebSocket, query: str = '{namespace=~"sixg-.+"}'):
    """Live tail: proxies Loki's /loki/api/v1/tail WebSocket."""
    await ws.accept()
    url = sources.LOKI.replace("http", "ws", 1) + "/loki/api/v1/tail"
    from urllib.parse import urlencode
    try:
        async with websockets.connect(f"{url}?{urlencode({'query': query, 'limit': 100})}",
                                      max_size=2**24) as loki:
            async for msg in loki:
                data = json.loads(msg)
                out = [{"ts": int(ts), "line": line, "labels": s["stream"]}
                       for s in data.get("streams", []) for ts, line in s["values"]]
                if out:
                    await ws.send_json(out)
    except (WebSocketDisconnect, RuntimeError):
        pass
    except Exception as e:
        try:
            await ws.send_json({"error": str(e)})
            await ws.close()
        except Exception:
            pass


# ---------------- RAN / subscribers ----------------

@app.get("/api/ran/ues/{cid}")
async def ran_ues(cid: str):
    c = _component(cid)
    try:
        return await _blocking(ran.ue_group, c["ns"], cid)
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/api/ran/gnb/{cid}")
async def ran_gnb(cid: str):
    c = _component(cid)
    try:
        return await _blocking(ran.gnb_info, c["ns"], cid)
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/api/ran/srsgnb")
async def ran_srsgnb():
    return ran.srs.snapshot()


@app.get("/api/ran/sl04")
async def ran_sl04():
    """Live per-UE metrics from the RF lab's O-DU on sl04 (same format as srsgnb)."""
    return {**ran.srs_sl04.snapshot(), "configured": True, "url": ran.srs_sl04.url} if ran.srs_sl04 \
        else ran.not_configured("SL04_WS")


@app.get("/api/ric/sl04")
async def ric_sl04():
    """E2 nodes known to the OSC near-RT RIC on sl04 (its E2 Manager API)."""
    return ran.ric_sl04.snapshot() if ran.ric_sl04 \
        else {"configured": False, "reachable": False, "error": "SL04_E2MGR_URL not configured", "nodes": []}


class UeAction(BaseModel):
    action: str
    sst: int | None = None
    sd: str | None = None
    dnn: str | None = None


@app.post("/api/ran/ues/{cid}/{ue}")
async def ran_ue_action(cid: str, ue: str, body: UeAction):
    c = _component(cid)
    arg = {"sst": body.sst, "sd": body.sd, "dnn": body.dnn} if body.action == "ps-establish" else None
    try:
        out = await _blocking(ran.ue_action, c["ns"], cid, ue, body.action, arg)
        audit.record("ue-" + body.action, f"{cid}/{ue}", output=out[:500])
        return {"output": out}
    except Exception as e:
        audit.record("ue-" + body.action, f"{cid}/{ue}", result="error", error=str(e))
        raise HTTPException(502, str(e))


@app.post("/api/ran/traffic/{cid}")
async def ran_traffic(cid: str, target: str = "8.8.8.8", count: int = Query(10, le=100)):
    c = _component(cid)
    if not c.get("ueGroup"):
        raise HTTPException(400, "traffic tests run from UE groups")
    try:
        out = await _blocking(ran.traffic_test, c["ns"], cid, "uesimtun0", target, count)
        audit.record("traffic-test", cid, destination=target, count=count)
        return {"output": out}
    except Exception as e:
        raise HTTPException(502, str(e))


@app.get("/api/core/subscribers")
async def core_subscribers():
    try:
        return await _blocking(ran.subscribers)
    except Exception as e:
        raise HTTPException(502, f"mongodb: {e}")


# ---------------- control ----------------

@app.post("/api/components/{cid}/{action}")
async def component_action(cid: str, action: str):
    c = _component(cid)
    kind = c.get("kind", "Deployment")
    wl = c.get("workload", cid)  # e.g. srsue lives in the srsgnb pod
    try:
        if action == "start":
            await _blocking(kube.scale, c["ns"], wl, kind, 1)
        elif action == "stop":
            if kind == "DaemonSet":
                raise HTTPException(400, "DaemonSets cannot be stopped from here")
            await _blocking(kube.scale, c["ns"], wl, kind, 0)
        elif action == "restart":
            await _blocking(kube.restart, c["ns"], wl, kind)
        else:
            raise HTTPException(400, f"unknown action {action}")
    except HTTPException:
        raise
    except Exception as e:
        audit.record(f"component-{action}", cid, result="error", error=str(e))
        raise HTTPException(502, str(e))
    audit.record(f"component-{action}", cid)
    return {"ok": True}


# Safe order learned in testing: UPFs first, then SMF, then the gNBs, then the UEs.
# Reattaching UEs while the SMF is down crashes the Open5GS 2.7.5 AMF, so every step waits until
# the NEW pods are ready and the network function is really back (not just the container).
SAFE_CORE_ORDER = [
    ["core-upf", "upf-urllc", "upf-mmtc"],
    ["core-smf"],
    ["gnb1", "srsgnb"],
    ["ue-embb-phones", "ue-urllc-ctrl", "ue-mmtc-sensors", "srsue"],
]
procedures = {}


def _smf_pfcp_peers():
    """UPFs the running SMF is associated with, counted from its own log since it started."""
    _, pods, *_ = kube.cache.snapshot()
    pod = next((p for p in pods if p["ns"] == "sixg-core" and p["workload"] == "core-smf"
                and p["ready"] and not p["deleting"]), None)
    if not pod:
        return 0
    log = kube.pod_logs("sixg-core", pod["name"], tail=2000)
    return len(set(re.findall(r"PFCP associated \[([\d.]+)\]", log)))


async def _until(check, timeout, every=3):
    t0 = time.time()
    while time.time() - t0 < timeout:
        try:
            if await check():
                return True
        except Exception:
            pass
        await asyncio.sleep(every)
    return False


def _kpi(name):
    return ((state.hub.latest or {}).get("kpis") or {}).get(name) or 0


async def _run_procedure(pid, steps):
    p = procedures[pid]
    sessions_before = _kpi("sessionsTotal")
    gnbs_before = _kpi("gnbs")

    def fail(msg):
        p["log"].append(msg)
        p["status"] = "failed"
        audit.record("procedure", pid, result="failed", log=p["log"])

    for i, group in enumerate(steps):
        p["step"] = i + 1
        present = [cid for cid in group if (state.COMPONENTS[cid]["ns"], cid) in kube.cache.snapshot()[0]]
        # srsue has no workload of its own; restarting srsgnb restarts it too
        p["log"].append(f"step {i + 1}: restarting {', '.join(present)}")
        old = {}
        for cid in present:
            c = state.COMPONENTS[cid]
            old[cid] = kube.pod_names(c["ns"], cid)
            await _blocking(kube.restart, c["ns"], cid, c.get("kind", "Deployment"))
        for cid in present:
            ok = await kube.wait_ready(state.COMPONENTS[cid]["ns"], cid, old=old[cid])
            p["log"].append(f"  {cid}: {'ready' if ok else 'NOT ready after timeout'}")
            if not ok:
                return fail(f"  stopped: {cid} did not come back")
        if "core-smf" in present:
            ok = await _until(lambda: _blocking(lambda: _smf_pfcp_peers() >= 3), 90)
            p["log"].append(f"  SMF linked to all 3 UPFs: {'yes' if ok else 'NO'}")
            if not ok:
                return fail("  stopped: SMF has no PFCP link to every UPF")
        if "gnb1" in present or "srsgnb" in present:
            want = max(gnbs_before, 1)
            ok = await _until(lambda: asyncio.sleep(0, _kpi("gnbs") >= want), 120)
            p["log"].append(f"  gNBs connected to the AMF: {int(_kpi('gnbs'))}/{int(want)}")
            if not ok:
                return fail("  stopped: not every gNB is connected to the AMF")
        await asyncio.sleep(3)

    # the network is only back when the PDU sessions are back
    want = sessions_before
    ok = await _until(lambda: asyncio.sleep(0, _kpi("sessionsTotal") >= want), 240, every=5)
    p["log"].append(f"PDU sessions: {int(_kpi('sessionsTotal'))}/{int(want)}")
    if not ok:
        return fail("not every session came back in 4 minutes")
    p["status"] = "done"
    audit.record("procedure", pid, log=p["log"])


@app.post("/api/procedures/restart-network")
async def restart_network():
    pid = f"restart-network-{int(time.time())}"
    procedures[pid] = {"id": pid, "status": "running", "step": 0, "steps": len(SAFE_CORE_ORDER), "log": []}
    audit.record("procedure-start", pid)
    asyncio.create_task(_run_procedure(pid, SAFE_CORE_ORDER))
    return procedures[pid]


@app.get("/api/procedures/{pid}")
async def procedure(pid: str):
    if pid not in procedures:
        raise HTTPException(404)
    return procedures[pid]


@app.get("/api/audit")
async def audit_log(minutes: int = 1440, limit: int = 500):
    end = time.time_ns()
    streams = await sources.loki_range('{namespace="sixg-control"} |= "\\"audit\\": true"',
                                       end - minutes * 60 * 10**9, end, limit)
    out = []
    for s in streams:
        for _, line in s["values"]:
            try:
                out.append(json.loads(line))
            except ValueError:
                pass
    out.sort(key=lambda x: x.get("ts", 0), reverse=True)
    return out


# ---------------- tests (named, described, exported, kept) ----------------

class TestIn(BaseModel):
    name: str
    kind: str = "free-test"
    purpose: str = ""
    description: str = ""
    tester: str = ""
    components: list[str] = []


class TestEdit(BaseModel):
    name: str | None = None
    purpose: str | None = None
    description: str | None = None
    tester: str | None = None
    components: list[str] | None = None
    notes: str | None = None
    outcome: str | None = None


def _test(test_id):
    t = testrecords.one(test_id)
    if not t:
        raise HTTPException(404, "no such test")
    return t


@app.get("/api/tests")
async def tests_list():
    return testrecords.all_tests()


@app.post("/api/tests")
async def tests_new(body: TestIn):
    bad = [c for c in body.components if c not in state.COMPONENTS]
    if bad:
        raise HTTPException(400, f"unknown components: {bad}")
    try:
        t = testrecords.new(body.name, body.kind, body.purpose, body.description, body.tester, body.components)
    except ValueError as e:
        raise HTTPException(400, str(e))
    audit.record("test-created", t["id"], session=t["id"], name=t["name"])
    return t


@app.get("/api/tests/{test_id}")
async def tests_get(test_id: str):
    return _test(test_id)


@app.patch("/api/tests/{test_id}")
async def tests_edit(test_id: str, body: TestEdit):
    _test(test_id)
    fields = {k: v for k, v in body.model_dump().items() if v is not None}
    if "outcome" in fields and fields["outcome"] not in ("", "pass", "fail", "inconclusive"):
        raise HTTPException(400, "outcome must be pass, fail or inconclusive")
    return testrecords.update(test_id, **fields)


@app.post("/api/tests/{test_id}/start")
async def tests_start(test_id: str):
    t = _test(test_id)
    if t["state"] != "planned":
        raise HTTPException(409, f"test is {t['state']}")
    other = next((x for x in testrecords.all_tests() if x["state"] == "running"), None)
    if other:
        raise HTTPException(409, f"test '{other['name']}' is still running; finish it first")
    t = testrecords.update(test_id, state="running", started=time.time())
    audit.record("test-started", test_id, session=test_id)
    return t


class Finish(BaseModel):
    notes: str = ""
    outcome: str = ""


@app.post("/api/tests/{test_id}/finish")
async def tests_finish(test_id: str, body: Finish):
    t = _test(test_id)
    if t["state"] != "running":
        raise HTTPException(409, f"test is {t['state']}")
    testrecords.update(test_id, state="finished", finished=time.time(), notes=body.notes, outcome=body.outcome)
    audit.record("test-finished", test_id, session=test_id, outcome=body.outcome)
    await asyncio.sleep(3)  # let the last log lines reach Loki
    try:
        await bundle.build(test_id)
    except Exception as e:
        raise HTTPException(502, f"test saved, but the export failed: {e}")
    return testrecords.one(test_id)


@app.get("/api/tests/{test_id}/export")
async def tests_export(test_id: str, rebuild: bool = False):
    t = _test(test_id)
    if t["state"] == "planned":
        raise HTTPException(409, "the test has not started")
    f = testrecords.DATA / "exports" / (t["export_file"] or "")
    if rebuild or not t["export_file"] or not f.is_file():
        f = await bundle.build(test_id)
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in t["name"])[:60]
    return FileResponse(f, media_type="application/zip", filename=f"{test_id}_{safe}.zip")


@app.delete("/api/tests/{test_id}")
async def tests_delete(test_id: str):
    t = _test(test_id)
    if t["state"] == "running":
        raise HTTPException(409, "finish the test before deleting it")
    if t["export_file"]:
        (testrecords.DATA / "exports" / t["export_file"]).unlink(missing_ok=True)
    testrecords.remove(test_id)
    audit.record("test-deleted", test_id, name=t["name"])
    return {"ok": True}


# ---------------- devices (each gets its own 5G identity and gateway) ----------------

class DeviceIn(BaseModel):
    name: str
    type: str = "generic"
    slice: str | None = None
    mode: str = "simulated"
    network: str = "router"
    dest: str | None = None
    target: str = "8.8.8.8"
    interval: int = 5
    size: int = 200


@app.get("/api/devices/options")
async def devices_options():
    wifi = []
    try:
        wifi = [l.get("iface") for l, v in await sources.prom("sixg_wifi_adapter_present") if v > 0]
    except Exception:
        pass
    return {**devices.options(), "wifiAdapters": wifi, "host": devices.get_host()}


@app.get("/api/devices")
async def devices_list():
    return await _blocking(devices.list_devices)


@app.post("/api/devices")
async def devices_connect(body: DeviceIn):
    if not body.name.strip():
        raise HTTPException(400, "give the device a name")
    if body.mode != "simulated" and body.network == "adapter":
        opts = await devices_options()
        if not opts["wifiAdapters"]:
            raise HTTPException(409, "no USB Wi-Fi adapter is attached to the VM")
    running = next((t["id"] for t in testrecords.all_tests() if t["state"] == "running"), None)
    try:
        d = await _blocking(devices.connect, body.name.strip(), body.type, body.slice, body.mode,
                            body.target, max(1, body.interval), max(56, min(body.size, 1400)), running,
                            body.network, body.dest)
    except (ValueError, RuntimeError) as e:
        audit.record("device-connect", body.name, result="error", error=str(e))
        raise HTTPException(400, str(e))
    audit.record("device-connect", d["id"], imsi=d["imsi"], slice=d["slice"], mode=body.mode)
    return d


@app.get("/api/devices/{dev_id}")
async def devices_detail(dev_id: str):
    try:
        d = await _blocking(devices.detail, dev_id)
    except Exception as e:
        raise HTTPException(404, str(e))
    # live traffic of this device, measured by flowmon on its radio link to the gNB
    st = state.hub.latest or {}
    d["linkBps"] = sum(l["bps"] for l in st.get("links", []) if dev_id in (l["a"], l["b"]))
    return d


@app.post("/api/devices/{dev_id}/test")
async def devices_test(dev_id: str, target: str = "8.8.8.8", count: int = Query(10, le=50), size: int = Query(500, le=1400)):
    try:
        r = await _blocking(devices.connection_test, dev_id, target, count, size)
    except Exception as e:
        raise HTTPException(502, str(e))
    audit.record("device-connection-test", dev_id, destination=target, lossPct=r["lossPct"], rttAvg=r["rttAvg"])
    return r


@app.post("/api/devices/{dev_id}/device-test")
async def devices_device_test(dev_id: str):
    try:
        r = await _blocking(devices.device_test, dev_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    except Exception as e:  # ping exits non-zero when the device does not answer
        r = {"target": None, "sent": 5, "size": 56, "lossPct": 100.0, "rttMin": None, "rttAvg": None, "rttMax": None, "output": str(e)[:300]}
    audit.record("device-reachability-test", dev_id, lossPct=r["lossPct"])
    return r


@app.delete("/api/devices/{dev_id}")
async def devices_disconnect(dev_id: str):
    try:
        r = await _blocking(devices.disconnect, dev_id)
    except Exception as e:
        raise HTTPException(404, str(e))
    audit.record("device-disconnect", dev_id, imsi=r["imsi"])
    return r


@app.get("/api/devices/{dev_id}/logs")
async def devices_logs(dev_id: str):
    return {"log": await _blocking(devices.gateway_logs, dev_id)}


# ---------------- the relay on the PC (host -> VM only; the VM never calls the PC) ----------------

@app.get("/api/host/exposures")
async def host_exposures():
    return await _blocking(devices.exposures)


@app.post("/api/host/info")
async def host_info(info: dict):
    return devices.set_host(info)


# ---------------- device live data (from the device live hub on the edge) ----------------

HUB = "http://10.43.100.100"


@app.get("/api/devices/{dev_id}/live")
async def devices_live(dev_id: str):
    """Everything a device is sending right now, plus its end-to-end path with measured traffic."""
    try:
        d = await _blocking(devices.apps.read_namespaced_deployment, dev_id, devices.NS)
    except Exception:
        raise HTTPException(404, "no such device")
    a = d.metadata.annotations or {}
    out = {"id": dev_id, "name": a.get("sixg/name"), "type": a.get("sixg/type"), "mode": a.get("sixg/mode"),
           "slice": (d.metadata.labels or {}).get("sixg/slice"), "telemetry": None, "track": [], "mqtt": None, "video": None}
    http = sources.http
    try:
        if a.get("sixg/hub-port"):
            r = await http.get(f"{HUB}:8000/api/ports/{a['sixg/hub-port']}", timeout=3)
            drones = r.json() if r.status_code == 200 else []
            out["telemetry"] = max(drones, key=lambda x: x["lastSeen"]) if drones else None
            if drones:
                t = await http.get(f"{HUB}:8000/api/ports/{a['sixg/hub-port']}/track?last=400", timeout=3)
                out["track"] = t.json() if t.status_code == 200 else []
        r = await http.get(f"{HUB}:8000/api/mqtt/{dev_id}?feed=40", timeout=3)
        out["mqtt"] = r.json() if r.status_code == 200 else None
        r = await http.get(f"{HUB}:9997/v3/paths/get/{dev_id}", timeout=3)
        if r.status_code == 200:
            v = r.json()
            out["video"] = {"ready": v.get("ready"), "tracks": v.get("tracks"), "bytesReceived": v.get("bytesReceived"),
                            "source": (v.get("source") or {}).get("type"), "hls": f"/api/video/{dev_id}/index.m3u8"}
        out["hubOnline"] = True
    except Exception as e:
        out["hubOnline"], out["hubError"] = False, str(e)[:200]

    # the device's path through the network, each hop with the traffic measured on it
    st = state.hub.latest or {}
    links = st.get("links", [])
    upf = {"embb": "core-upf", "urllc": "upf-urllc", "mmtc": "upf-mmtc"}.get(out["slice"])

    def rate(x, y, iface=None):
        return sum(l["bps"] for l in links if {l["a"], l["b"]} == {x, y} and (iface is None or l["iface"] == iface))

    hub_bps = sum(l["bps"] for l in links if "device-hub" in (l["a"], l["b"]) and upf in (l["a"], l["b"]))
    out["path"] = {"upf": upf, "hops": {
        "radio": rate(dev_id, "gnb1", "Uu"), "n3": rate("gnb1", upf, "N3") if upf else 0, "n6hub": hub_bps}}
    return out


@app.get("/api/video/{path:path}")
async def video_proxy(path: str, request: Request):
    """HLS from MediaMTX in the hub, so the browser (behind the SSH tunnel) can play device video.
    Query parameters are forwarded: low-latency HLS uses them (_HLS_msn, _HLS_part) for blocking reloads."""
    from fastapi.responses import Response
    try:
        r = await sources.http.get(f"{HUB}:8888/{path}", params=dict(request.query_params), timeout=15,
                                   follow_redirects=True)
    except Exception as e:
        raise HTTPException(502, str(e))
    return Response(r.content, status_code=r.status_code,
                    media_type=r.headers.get("content-type", "application/octet-stream"),
                    headers={"Cache-Control": "no-cache"})


# ---------------- frontend ----------------

if STATIC.exists():
    app.mount("/assets", StaticFiles(directory=STATIC / "assets"), name="assets")

    @app.get("/{path:path}")
    async def spa(path: str):
        f = STATIC / path
        if path and f.is_file():
            return FileResponse(f)
        return FileResponse(STATIC / "index.html")
else:
    @app.get("/")
    async def no_ui():
        return JSONResponse({"error": "frontend not built"}, 503)
