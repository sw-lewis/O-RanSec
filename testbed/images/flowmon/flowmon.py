"""flowmon: real per-link traffic for the 6G testbed.

Reads the kernel's connection tracking table (conntrack, with byte accounting on),
maps every IP to the Kubernetes workload that owns it, names the link by its 3GPP /
O-RAN interface, and exports cumulative byte and packet counters to Prometheus.
Nothing is estimated: every number comes from kernel counters.
"""
import os
import subprocess
import threading
import time

from kubernetes import client, config, watch
from prometheus_client import Counter, Gauge, start_http_server

POLL = float(os.environ.get("POLL_SECONDS", "1"))
WINDOW = float(os.environ.get("RATE_WINDOW_SECONDS", "5"))
NODE_IPS = set(os.environ.get("NODE_IPS", "10.166.0.10,10.42.0.1").split(","))
KUBELET_IP = os.environ.get("KUBELET_IP", "10.42.0.1")  # source of kubelet health probes
# Hosts outside the cluster that are part of the testbed, e.g. the RF lab's RAN node:
# "192.168.2.14=sl04-cu:sl04,..." -> ip -> (name, namespace). Their links keep their 3GPP
# interface names (N2, N3 ...) instead of being treated as the internet.
EXTERNAL_HOSTS = {}
for _entry in filter(None, (e.strip() for e in os.environ.get("EXTERNAL_HOSTS", "").split(","))):
    _ip, _, _who = _entry.partition("=")
    _name, _, _ns = _who.partition(":")
    EXTERNAL_HOSTS[_ip.strip()] = (_name.strip() or _ip.strip(), _ns.strip() or "lab")

# (protocol, server port) -> interface name
INTERFACES = {
    ("sctp", 38412): "N2",   # NGAP, gNB <-> AMF
    ("udp", 2152): "N3",     # GTP-U, gNB <-> UPF
    ("udp", 8805): "N4",     # PFCP, SMF <-> UPF
    ("tcp", 7777): "SBI",    # HTTP/2 service-based interface between core NFs
    ("tcp", 80): "SBI",
    ("udp", 4997): "Uu",     # UERANSIM radio link simulation, UE <-> gNB
    ("tcp", 2000): "Uu",     # srsRAN ZeroMQ IQ samples, gNB -> UE
    ("tcp", 2001): "Uu",     # srsRAN ZeroMQ IQ samples, UE -> gNB
    ("sctp", 36421): "E2",   # gNB E2 agent <-> near-RT RIC
    ("sctp", 36422): "E42",  # xApp <-> near-RT RIC
    ("tcp", 27017): "DB",    # MongoDB
    ("udp", 53): "DNS",
    ("tcp", 9090): "metrics",   # Prometheus scrapes
    ("tcp", 9100): "metrics",
    ("tcp", 9105): "metrics",
    ("tcp", 10250): "metrics",
    ("tcp", 8001): "metrics",   # srsRAN remote-control metrics WebSocket
}

LINK_BYTES = Counter("sixg_link_bytes", "Bytes seen on a link (both directions)",
                     ["src", "dst", "src_ns", "dst_ns", "iface", "proto", "port"])
LINK_PKTS = Counter("sixg_link_packets", "Packets seen on a link (both directions)",
                    ["src", "dst", "src_ns", "dst_ns", "iface", "proto", "port"])
LINK_FLOWS = Gauge("sixg_link_active_flows", "Active conntrack flows on a link",
                   ["src", "dst", "src_ns", "dst_ns", "iface", "proto", "port"])
LINK_BPS = Gauge("sixg_link_bits_per_second", f"Link throughput averaged over the last {WINDOW:.0f}s",
                 ["src", "dst", "src_ns", "dst_ns", "iface", "proto", "port"])
LINK_PPS = Gauge("sixg_link_packets_per_second", f"Link packet rate averaged over the last {WINDOW:.0f}s",
                 ["src", "dst", "src_ns", "dst_ns", "iface", "proto", "port"])
WIFI = Gauge("sixg_wifi_adapter_present", "A Wi-Fi interface exists in the VM (for real devices)", ["iface"])
UP = Gauge("sixg_flowmon_last_poll_timestamp", "Unix time of the last successful poll")

def parse(line):
    """One `conntrack -L -o extended` line -> dict, or None.
    The first src/dst/sport/dport/packets/bytes belong to the original direction,
    the second set to the reply direction."""
    tok = line.split()
    if len(tok) < 5:
        return None
    out = {"proto": tok[2], "orig": {}, "reply": {}}
    side = "orig"
    for t in tok[5:]:
        if "=" not in t:
            continue
        k, v = t.split("=", 1)
        if k == "src" and "src" in out["orig"]:
            side = "reply"
        if k in ("src", "dst", "sport", "dport", "packets", "bytes"):
            out[side].setdefault(k, v)
    return out if "src" in out["reply"] else None


class Directory:
    """IP -> (workload, namespace) for pods and services, kept current by a watch."""

    def __init__(self):
        self.pods = {}
        self.svcs = {}
        self.lock = threading.Lock()

    @staticmethod
    def workload(pod):
        refs = pod.metadata.owner_references or []
        for r in refs:
            if r.kind == "ReplicaSet":
                return r.name.rsplit("-", 1)[0]
            return r.name
        return pod.metadata.name

    def run(self, v1):
        threading.Thread(target=self._watch_pods, args=(v1,), daemon=True).start()
        threading.Thread(target=self._watch_svcs, args=(v1,), daemon=True).start()

    def _watch_pods(self, v1):
        while True:
            try:
                for ev in watch.Watch().stream(v1.list_pod_for_all_namespaces, timeout_seconds=300):
                    p = ev["object"]
                    ip = p.status.pod_ip
                    if not ip or p.spec.host_network:
                        continue
                    with self.lock:
                        if ev["type"] == "DELETED":
                            self.pods.pop(ip, None)
                        else:
                            self.pods[ip] = (self.workload(p), p.metadata.namespace)
            except Exception as e:  # watch expired or API restarted
                print("pod watch:", e, flush=True)
                time.sleep(2)

    def _watch_svcs(self, v1):
        while True:
            try:
                for ev in watch.Watch().stream(v1.list_service_for_all_namespaces, timeout_seconds=300):
                    s = ev["object"]
                    ip = s.spec.cluster_ip
                    if not ip or ip == "None":
                        continue
                    with self.lock:
                        if ev["type"] == "DELETED":
                            self.svcs.pop(ip, None)
                        else:
                            self.svcs[ip] = (s.metadata.name, s.metadata.namespace)
            except Exception as e:
                print("svc watch:", e, flush=True)
                time.sleep(2)

    def name(self, ip):
        with self.lock:
            if ip in self.pods:
                return self.pods[ip]
        if ip in EXTERNAL_HOSTS:
            return EXTERNAL_HOSTS[ip]
        if ip in NODE_IPS:
            return ("vm-node", "host")
        if ip.startswith(("10.45.", "10.46.", "10.47.")):
            return ("ue-ip-pool", "user-plane")
        if ip.startswith(("10.", "172.16.", "192.168.", "127.")):
            return ("unknown", "unknown")
        return ("internet", "external")


def classify(proto, sport, dport):
    for port in (dport, sport):
        if (proto, port) in INTERFACES:
            return INTERFACES[(proto, port)], port
    return "other", dport


history = []  # (time, {labels: (bytes, packets)}) for the rate window


def poll(directory, last):
    out = subprocess.run(["conntrack", "-L", "-o", "extended"], capture_output=True, text=True).stdout
    seen = {}
    flows = {}
    deltas = {}
    for line in out.splitlines():
        m = parse(line)
        if not m:
            continue
        o, r = m["orig"], m["reply"]
        counted = "bytes" in o  # flows opened before accounting was on have no counters
        proto = m["proto"]
        if proto not in ("tcp", "udp", "sctp", "icmp"):
            continue
        # Original direction: client -> (maybe a Service IP). Reply source is the real server pod.
        client_ip, server_ip = o["src"], r["src"]
        sport, dport = int(o.get("sport", 0)), int(o.get("dport", 0))
        key = (proto, o["src"], o["dst"], sport, dport)
        b = int(o.get("bytes", 0)) + int(r.get("bytes", 0))
        p = int(o.get("packets", 0)) + int(r.get("packets", 0))
        src, src_ns = directory.name(client_ip)
        dst, dst_ns = directory.name(server_ip)
        if src_ns == "external" and dst_ns == "external":
            continue  # the VM's own traffic, not part of the testbed
        iface, port = classify(proto, sport, dport)
        if dst == "device-hub" and iface not in ("probe", "metrics"):
            iface = "N6"  # the edge hub is the data network that devices send to
        elif "external" in (src_ns, dst_ns):
            inside = dst if src_ns == "external" else src
            iface = "N6" if "upf" in inside else "egress"  # N6 = UPF <-> data network
        if client_ip == KUBELET_IP and iface not in ("Uu", "N2", "N3", "N4", "E2", "E42"):
            iface = "probe"  # kubelet liveness/readiness checks
        labels = (src, dst, src_ns, dst_ns, iface, proto, str(port))
        flows[labels] = flows.get(labels, 0) + 1
        if not counted:
            continue
        pb, pp = last.get(key, (0, 0))
        db, dp = (b - pb, p - pp) if b >= pb else (b, p)
        if db > 0:
            LINK_BYTES.labels(*labels).inc(db)
            LINK_PKTS.labels(*labels).inc(dp)
            tb, tp = deltas.get(labels, (0, 0))
            deltas[labels] = (tb + db, tp + dp)
        seen[key] = (b, p)
    LINK_FLOWS.clear()
    for labels, n in flows.items():
        LINK_FLOWS.labels(*labels).set(n)

    now = time.time()
    history.append((now, deltas))
    while history and history[0][0] < now - WINDOW:
        history.pop(0)
    span = max(POLL, now - history[0][0] + POLL) if history else WINDOW
    sums = {}
    for _, d in history:
        for labels, (db, dp) in d.items():
            tb, tp = sums.get(labels, (0, 0))
            sums[labels] = (tb + db, tp + dp)
    LINK_BPS.clear()
    LINK_PPS.clear()
    for labels, (db, dp) in sums.items():
        LINK_BPS.labels(*labels).set(db * 8 / span)
        LINK_PPS.labels(*labels).set(dp / span)
    WIFI.clear()
    for iface in os.listdir("/sys/class/net"):
        if os.path.isdir(f"/sys/class/net/{iface}/wireless") or os.path.exists(f"/sys/class/net/{iface}/phy80211"):
            WIFI.labels(iface).set(1)
    UP.set(time.time())
    return seen


def main():
    config.load_incluster_config()
    directory = Directory()
    directory.run(client.CoreV1Api())
    start_http_server(9105)
    subprocess.run(["sysctl", "-w", "net.netfilter.nf_conntrack_acct=1"], check=False)
    last = {}
    time.sleep(3)  # let the first watch fill the directory
    while True:
        try:
            last = poll(directory, last)
        except Exception as e:
            print("poll:", e, flush=True)
        time.sleep(POLL)


if __name__ == "__main__":
    main()
