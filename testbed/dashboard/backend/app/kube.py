"""Kubernetes access: a cached view of workloads/pods/events plus control actions."""
import asyncio
import datetime as dt
import threading
import time

from kubernetes import client, config
from kubernetes.stream import stream

SIXG_NAMESPACES = ["sixg-core", "sixg-ran", "sixg-ric", "sixg-edge", "sixg-devices",
                   "sixg-attack", "sixg-obs", "sixg-control", "kube-system"]


def _load():
    try:
        config.load_incluster_config()
    except config.ConfigException:
        config.load_kube_config()


_load()
core = client.CoreV1Api()
apps = client.AppsV1Api()


def _exec_api():
    # kubernetes.stream() switches its ApiClient to WebSocket mode while it runs, so exec must
    # never share the client the background cache uses. A fresh client per call is cheap.
    return client.CoreV1Api(client.ApiClient())


def _age(ts):
    if not ts:
        return None
    return (dt.datetime.now(dt.timezone.utc) - ts).total_seconds()


class Cache:
    """Refreshes workloads, pods and events every `period` seconds in a thread."""

    def __init__(self, period=2.0):
        self.period = period
        self.workloads = {}   # (ns, name) -> dict
        self.pods = []        # list of dicts
        self.events = []      # newest first
        self.node = {}
        self.updated = 0.0
        self.lock = threading.Lock()
        threading.Thread(target=self._loop, daemon=True).start()

    def _loop(self):
        while True:
            try:
                self._refresh()
            except Exception as e:  # API briefly unavailable
                print("kube cache:", e, flush=True)
            time.sleep(self.period)

    def _refresh(self):
        workloads = {}
        for d in apps.list_deployment_for_all_namespaces().items:
            workloads[(d.metadata.namespace, d.metadata.name)] = {
                "kind": "Deployment",
                "desired": d.spec.replicas or 0,
                "ready": d.status.ready_replicas or 0,
                "available": d.status.available_replicas or 0,
                "labels": d.metadata.labels or {},
            }
        for s in apps.list_stateful_set_for_all_namespaces().items:
            workloads[(s.metadata.namespace, s.metadata.name)] = {
                "kind": "StatefulSet",
                "desired": s.spec.replicas or 0,
                "ready": s.status.ready_replicas or 0,
                "available": s.status.available_replicas or s.status.ready_replicas or 0,
                "labels": s.metadata.labels or {},
            }
        for d in apps.list_daemon_set_for_all_namespaces().items:
            workloads[(d.metadata.namespace, d.metadata.name)] = {
                "kind": "DaemonSet",
                "desired": d.status.desired_number_scheduled or 0,
                "ready": d.status.number_ready or 0,
                "available": d.status.number_available or 0,
                "labels": d.metadata.labels or {},
            }

        pods = []
        for p in core.list_pod_for_all_namespaces().items:
            owner = None
            for r in p.metadata.owner_references or []:
                owner = r.name.rsplit("-", 1)[0] if r.kind == "ReplicaSet" else r.name
            statuses = p.status.container_statuses or []
            restarts = sum(c.restart_count for c in statuses)
            last_restart = None
            for c in statuses:
                t = c.last_state.terminated if c.last_state else None
                if t and t.finished_at and (last_restart is None or t.finished_at > last_restart):
                    last_restart = t.finished_at
            ready = bool(statuses) and all(c.ready for c in statuses)
            container_ready = {c.name: c.ready for c in statuses}
            waiting = [c.state.waiting.reason for c in statuses if c.state and c.state.waiting]
            pods.append({
                "ns": p.metadata.namespace,
                "name": p.metadata.name,
                "workload": owner or p.metadata.name,
                "phase": p.status.phase,
                "ready": ready,
                "reason": waiting[0] if waiting else None,
                "ip": p.status.pod_ip,
                "restarts": restarts,
                "lastRestartAgo": _age(last_restart),
                "age": _age(p.metadata.creation_timestamp),
                "containers": [c.name for c in p.spec.containers],
                "containerReady": container_ready,
                "images": [c.image for c in p.spec.containers],
                "labels": p.metadata.labels or {},
                "deleting": p.metadata.deletion_timestamp is not None,
            })

        events = []
        for e in core.list_event_for_all_namespaces(limit=400).items:
            ts = e.last_timestamp or e.event_time or e.metadata.creation_timestamp
            events.append({
                "ns": e.metadata.namespace,
                "type": e.type,
                "reason": e.reason,
                "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                "message": e.message,
                "count": e.count or 1,
                "time": ts.isoformat() if ts else None,
            })
        events.sort(key=lambda x: x["time"] or "", reverse=True)

        n = core.list_node().items[0]
        conds = {c.type: c.status for c in n.status.conditions}
        node = {
            "name": n.metadata.name,
            "ready": conds.get("Ready") == "True",
            "kubelet": n.status.node_info.kubelet_version,
            "os": n.status.node_info.os_image,
            "kernel": n.status.node_info.kernel_version,
            "runtime": n.status.node_info.container_runtime_version,
            "cpu": n.status.capacity.get("cpu"),
            "memory": n.status.capacity.get("memory"),
        }

        with self.lock:
            self.workloads, self.pods, self.events, self.node = workloads, pods, events, node
            self.updated = time.time()

    def snapshot(self):
        with self.lock:
            return self.workloads, list(self.pods), list(self.events), dict(self.node), self.updated


cache = Cache()


# ---------- control ----------

def _patch_replicas(ns, name, kind, n):
    body = {"spec": {"replicas": n}}
    if kind == "StatefulSet":
        apps.patch_namespaced_stateful_set(name, ns, body)
    else:
        apps.patch_namespaced_deployment(name, ns, body)


def scale(ns, name, kind, n):
    _patch_replicas(ns, name, kind, n)


def restart(ns, name, kind):
    now = dt.datetime.now(dt.timezone.utc).isoformat()
    body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}}
    if kind == "StatefulSet":
        apps.patch_namespaced_stateful_set(name, ns, body)
    elif kind == "DaemonSet":
        apps.patch_namespaced_daemon_set(name, ns, body)
    else:
        apps.patch_namespaced_deployment(name, ns, body)


def patch_deployment_json(ns, name, ops):
    """JSON patch (RFC 6902; the client sends a list as application/json-patch+json): lists such as
    containers are replaced as a whole, not merged by name like a strategic merge patch."""
    apps.patch_namespaced_deployment(name, ns, ops)


def pod_names(ns, workload):
    _, pods, *_ = cache.snapshot()
    return {p["name"] for p in pods if p["ns"] == ns and p["workload"] == workload}


async def wait_ready(ns, name, timeout=180, old=()):
    """Wait until a workload's desired replicas are all ready. After a restart pass the pod names
    from before it as `old`: right after the patch the OLD pod is still ready, so only new pods
    count, and every old pod must be gone."""
    t0 = time.time()
    while time.time() - t0 < timeout:
        await asyncio.sleep(2)
        workloads, pods, *_ = cache.snapshot()
        w = workloads.get((ns, name))
        mine = [p for p in pods if p["ns"] == ns and p["workload"] == name]
        if not w or w["desired"] == 0 or any(p["name"] in old for p in mine):
            continue
        fresh = [p for p in mine if p["ready"] and not p["deleting"]]
        if len(fresh) >= w["desired"] and not any(p["deleting"] for p in mine):
            return True
    return False


def exec_in(ns, workload, command, container=None, timeout=20):
    """Run a command in the first ready pod of a workload and return its output."""
    _, pods, *_ = cache.snapshot()
    pod = next((p for p in pods if p["ns"] == ns and p["workload"] == workload
                and p["ready"] and not p["deleting"]), None)
    if not pod:
        raise RuntimeError(f"no ready pod for {ns}/{workload}")
    return stream(_exec_api().connect_get_namespaced_pod_exec, pod["name"], ns,
                  command=command, container=container or pod["containers"][0],
                  stderr=True, stdin=False, stdout=True, tty=False, _request_timeout=timeout)


def pod_logs(ns, pod, container=None, tail=500):
    return core.read_namespaced_pod_log(pod, ns, container=container, tail_lines=tail)
