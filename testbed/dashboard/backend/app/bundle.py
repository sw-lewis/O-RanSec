"""Builds the downloadable package for one finished test: only data from that test's time
window and the components it involved (plus anything labelled with the test's id)."""
import datetime as dt
import io
import json
import zipfile

from . import sources, state, testrecords

LOG_LIMIT = 5000


def _iso(ts):
    return dt.datetime.fromtimestamp(ts).isoformat(timespec="seconds") if ts else "–"


def _selector(comp):
    wl = comp.get("workload", comp["id"])
    sel = f'namespace="{comp["ns"]}", pod=~"{wl}-.*"'
    if comp.get("container"):
        sel += f', container="{comp["container"]}"'
    return "{" + sel + "}"


async def _lines(query, t0, t1):
    try:
        streams = await sources.loki_range(query, t0 * 1e9, t1 * 1e9, LOG_LIMIT, direction="forward")
    except Exception as e:
        return [], str(e)
    rows = [(int(ts), line, s["stream"]) for s in streams for ts, line in s["values"]]
    rows.sort(key=lambda r: r[0])
    return rows, None


def _fmt(rows):
    return "\n".join(
        f'{dt.datetime.fromtimestamp(ts / 1e9).isoformat(timespec="milliseconds")} '
        f'[{lab.get("pod", lab.get("job", ""))}] {line}' for ts, line, lab in rows)


async def _series(query, t0, t1):
    step = max(2, int((t1 - t0) / 300))
    try:
        return await sources.http.get(f"{sources.PROM}/api/v1/query_range",
                                      params={"query": query, "start": t0, "end": t1, "step": step})
    except Exception:
        return None


async def build(test_id):
    t = testrecords.one(test_id)
    if not t or not t["started"]:
        raise ValueError("This test has not been started.")
    t0 = t["started"]
    # small margin so the "test-finished" action and the last log lines are included
    t1 = (t["finished"] or dt.datetime.now().timestamp()) + 5
    comps = [state.COMPONENTS[c] for c in t["components"] if c in state.COMPONENTS and not state.COMPONENTS[c].get("virtual")]

    buf = io.BytesIO()
    z = zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED)
    summary = {"logs": {}, "errors": {}}

    # 1. logs of each involved component, only inside the test window
    for c in comps:
        rows, err = await _lines(_selector(c), t0, t1)
        z.writestr(f"logs/{c['id']}.log", _fmt(rows) if not err else f"could not read logs: {err}")
        summary["logs"][c["id"]] = len(rows)
        summary["errors"][c["id"]] = sum(1 for _, _, lab in rows if lab.get("level") in ("error", "fatal", "err", "crit"))

    # 2. anything tagged with this test (pods labelled sixg/session=<id>, e.g. a device gateway)
    rows, _ = await _lines(f'{{session="{test_id}"}}', t0, t1)
    if rows:
        z.writestr("logs/tagged-with-this-test.log", _fmt(rows))
    summary["taggedLines"] = len(rows)

    # 3. Kubernetes events about the involved workloads
    names = "|".join(c.get("workload", c["id"]) for c in comps) or "^$"
    rows, _ = await _lines(f'{{job=~".*kubernetes_events.*"}} |~ "{names}"', t0, t1)
    z.writestr("kubernetes-events.log", _fmt(rows))
    summary["events"] = len(rows)

    # 4. operator actions taken during the test
    rows, _ = await _lines('{namespace="sixg-control"} |= "\\"audit\\": true"', t0, t1)
    actions = []
    for _, line, _ in rows:
        try:
            actions.append(json.loads(line))
        except ValueError:
            pass
    z.writestr("operator-actions.json", json.dumps(actions, indent=1))

    # 5. measured metrics over the window
    ids = "|".join(c.get("workload", c["id"]) for c in comps) or "^$"
    metrics = {}
    for key, q in {
        "link_bits_per_second": f'sum by (src,dst,iface) (sixg_link_bits_per_second{{src=~"{ids}"}} or sixg_link_bits_per_second{{dst=~"{ids}"}})',
        "registered_ues_per_slice": "sum by (snssai) (fivegs_amffunction_rm_registeredsubnbr)",
        "pdu_sessions_per_slice": "sum by (snssai) (fivegs_smffunction_sm_sessionnbr)",
    }.items():
        r = await _series(q, t0, t1)
        metrics[key] = r.json().get("data", {}).get("result", []) if r is not None and r.status_code == 200 else None
    z.writestr("metrics.json", json.dumps(metrics))
    traffic = {}
    for s in metrics.get("link_bits_per_second") or []:
        vals = [float(v) for _, v in s["values"]]
        if vals:
            m = s["metric"]
            if m.get("iface") in ("metrics", "probe", "DNS") or "unknown" in (m.get("src"), m.get("dst")):
                continue  # testbed monitoring, not part of the test's network traffic
            traffic[f'{m.get("iface")} {m.get("src")} -> {m.get("dst")}'] = (max(vals), sum(vals) / len(vals))

    # 6. the record itself and a readable report
    z.writestr("test.json", json.dumps(t, indent=1))
    lines = [
        f"# {t['name']}", "",
        f"- Test ID: {t['id']}",
        f"- Type: {t['kindLabel']}",
        f"- Tester: {t['tester'] or '–'}",
        f"- Started: {_iso(t0)}   Finished: {_iso(t['finished'])}   Duration: {int((t['finished'] or t1) - t0)} s",
        f"- Outcome: {t['outcome'] or '–'}", "",
        "## Purpose", t["purpose"] or "–", "",
        "## Description", t["description"] or "–", "",
        "## Notes after the test", t["notes"] or "–", "",
        "## Components involved",
        *[f"- {c['label']} ({c.get('software', '')}): {summary['logs'][c['id']]} log lines, "
          f"{summary['errors'][c['id']]} errors" for c in comps], "",
        "## Measured traffic (max / average over the test)",
        *([f"- {k}: {mx / 1000:.1f} / {avg / 1000:.1f} kbit/s" for k, (mx, avg) in sorted(traffic.items())] or ["- none measured"]), "",
        f"## Operator actions during the test: {len(actions)}",
        *[f"- {_iso(a.get('ts'))} {a.get('action')} {a.get('target') or ''} ({a.get('result')})" for a in actions], "",
        f"Kubernetes events: {summary['events']}. Lines tagged with this test: {summary['taggedLines']}.", "",
        "Contents: test.json, report.md, logs/<component>.log, kubernetes-events.log, operator-actions.json, metrics.json",
    ]
    z.writestr("report.md", "\n".join(lines))
    z.close()

    name = f"{test_id}.zip"
    path = testrecords.DATA / "exports"
    path.mkdir(exist_ok=True)
    (path / name).write_bytes(buf.getvalue())
    testrecords.update(test_id, export_file=name, export_bytes=len(buf.getvalue()))
    return path / name
