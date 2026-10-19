"""Device onboarding: every connected device gets its own 5G identity and gateway.

For each device the testbed
  1. creates a subscriber in Open5GS (open5gs-dbctl in the populate pod) with fresh keys,
  2. starts a UERANSIM UE in namespace sixg-devices that registers on the chosen slice and
     acts as the device's 5G gateway (it forwards the device's traffic into its PDU session),
  3. removes both again when the device is disconnected."""
import json
import re
import secrets
import time

from kubernetes import client

from . import kube

NS = "sixg-devices"
PLMN = ("999", "70")
IMSI_BASE = 999700000001000  # device IMSIs: 999700000001001, ...
IMAGE = "sixg/device-gateway:latest"  # UERANSIM UE + WireGuard/socat/iptables (images/device-gateway)
SLICES = {
    "embb": {"sst": 1, "sd": "000001", "label": "eMBB"},
    "urllc": {"sst": 2, "sd": "000002", "label": "URLLC"},
    "mmtc": {"sst": 3, "sd": "000003", "label": "mMTC"},
}

# What the tester picks in the UI. "how" lists the manual steps; everything else is automatic.
TYPES = {
    "drone": {"label": "Drone (MAVLink over Wi-Fi)", "slice": "urllc"},
    "phone": {"label": "Phone or laptop", "slice": "embb"},
    "iot": {"label": "IoT sensor", "slice": "mmtc"},
    "generic": {"label": "Any IP device", "slice": "embb"},
}
MODES = {
    "simulated": {"label": "Simulated in the testbed", "real": False},
    "udp-relay": {"label": "Real device, UDP (drones / MAVLink, sensors)", "real": True, "port": 14550},
    "vpn": {"label": "Real device, WireGuard app (phones, laptops)", "real": True, "port": 51820},
}
HUB_IP = "10.43.100.100"            # device live hub (k8s/edge/device-hub.yaml, fixed Service IP)
HUB_MAV_PORTS = range(14551, 14571)  # one MAVLink port per drone on the hub
# Simulated sources start only once the gateway has routed the hub through the 5G tunnel
# (a uesimtun0 route for HUB_IP in /proc/net/route, destination in little-endian hex).
_HUB_HEX = "".join(f"{int(o):02X}" for o in reversed(HUB_IP.split(".")))
WAIT_5G = f"until grep -q '^uesimtun0[[:space:]]*{_HUB_HEX}' /proc/net/route; do sleep 1; done; "
# The tunnel must exist AND reach the slice's UPF gateway (x.y.0.1): after a core restart a UE can
# keep a dead PDU session. A failing probe restarts the gateway, which registers afresh.
GATEWAY_PROBE = client.V1Probe(
    _exec=client.V1ExecAction(command=["sh", "-c",
        "a=$(ip -4 -o addr show uesimtun0 | awk '{print $4}' | cut -d/ -f1); [ -n \"$a\" ] || exit 1; "
        "ping -c1 -W3 -I uesimtun0 \"${a%.*.*}.0.1\" >/dev/null || ping -c1 -W3 -I uesimtun0 \"${a%.*.*}.0.1\" >/dev/null"]),
    initial_delay_seconds=90, period_seconds=20, timeout_seconds=15, failure_threshold=3)
SPEC_VERSION = "4"  # bump when the generated pod spec changes; upgrade_existing() then re-applies it

NETWORKS = {  # how a real device reaches this PC; the gateway side is the same for all of them
    "hotspot": "Phone hotspot (PC and device on the same hotspot)",
    "router": "Personal or lab router (same Wi-Fi/LAN as the PC)",
    "adapter": "USB Wi-Fi adapter given to the VM",
}

apps = client.AppsV1Api()
core = client.CoreV1Api()


def _slug(name):
    s = re.sub(r"[^a-z0-9-]+", "-", name.lower()).strip("-")
    return (s or "device")[:30]


def _dbctl(*args):
    return kube.exec_in("sixg-core", "core-open5gs-populate", ["open5gs-dbctl", *args], container="populate")


def _used_imsis():
    out = set()
    for d in apps.list_namespaced_deployment(NS, label_selector="sixg/role=device-gateway").items:
        out.add(int(d.metadata.annotations.get("sixg/imsi", "0")))
    return out


def _next_imsi():
    used = _used_imsis()
    n = IMSI_BASE + 1
    while n in used:
        n += 1
    return n


def ensure_namespace():
    try:
        core.read_namespace(NS)
    except client.ApiException as e:
        if e.status != 404:
            raise
        core.create_namespace(client.V1Namespace(metadata=client.V1ObjectMeta(
            name=NS, labels={"sixg/layer": "devices"})))


def _ue_yaml(imsi, key, opc, sl):
    s = SLICES[sl]
    sd = "0x" + s["sd"]
    return f"""supi: 'imsi-{imsi}'
mcc: '{PLMN[0]}'
mnc: '{PLMN[1]}'
key: '{key}'
op: '{opc}'
opType: 'OPC'
amf: '8000'
imei: '356938035643803'
imeiSv: '4370816125816151'
gnbSearchList:
  - ${{GNB_IP}}
uacAic: {{mps: false, mcs: false}}
uacAcc: {{normalClass: 0, class11: false, class12: false, class13: false, class14: false, class15: false}}
sessions:
  - type: 'IPv4'
    apn: '{sl}'
    slice: {{sst: {s['sst']}, sd: {sd}}}
configured-nssai:
  - {{sst: {s['sst']}, sd: {sd}}}
default-nssai:
  - {{sst: {s['sst']}, sd: {sd}}}
integrity: {{IA1: true, IA2: true, IA3: true}}
ciphering: {{EA1: true, EA2: true, EA3: true}}
integrityMaxRate: {{uplink: 'full', downlink: 'full'}}
"""


def _wg_keypair():
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    import base64
    k = X25519PrivateKey.generate()
    raw = lambda b: base64.b64encode(b).decode()
    priv = raw(k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption()))
    pub = raw(k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw))
    return priv, pub


def _host_port(mode):
    """Port on the PC's hotspot/router address that the device uses (one per device)."""
    used = set()
    for d in apps.list_namespaced_deployment(NS, label_selector="sixg/role=device-gateway").items:
        p = (d.metadata.annotations or {}).get("sixg/host-port")
        if p:
            used.add(int(p))
    p = MODES[mode]["port"]
    while p in used:
        p += 1
    return p


def _hub_port():
    used = {int((d.metadata.annotations or {}).get("sixg/hub-port", 0))
            for d in apps.list_namespaced_deployment(NS, label_selector="sixg/role=device-gateway").items}
    return next(p for p in HUB_MAV_PORTS if p not in used)


def _sources(dtype, dev_id, hub_port, interval):
    """Simulated device data, running beside the gateway and sent through its 5G session."""
    camera = client.V1Container(
        name="camera", image="docker.io/linuxserver/ffmpeg:latest", image_pull_policy="IfNotPresent",
        # retried here, not by Kubernetes: a dropped SRT link must not end in CrashLoopBackOff
        command=["bash", "-c", WAIT_5G + "while true; do ffmpeg -hide_banner -loglevel warning -re "
                 "-f lavfi -i testsrc2=size=960x540:rate=25 -c:v libx264 -preset veryfast -tune zerolatency "
                 "-g 50 -b:v 1200k -pix_fmt yuv420p -f mpegts "
                 f"'srt://{HUB_IP}:8890?streamid=publish:{dev_id}&pkt_size=1316'; "
                 "echo '[camera] stream ended, reconnecting'; sleep 2; done"])
    out = []
    if dtype == "drone":
        out.append(client.V1Container(
            name="flight", image="sixg/ardupilot-sitl:latest", image_pull_policy="Never",
            command=["bash", "-c", WAIT_5G + "exec /usr/local/bin/run-sitl.sh"],
            env=[client.V1EnvVar(name="TELEMETRY_TARGET", value=f"{HUB_IP}:{hub_port}")]))
        out.append(camera)
    elif dtype in ("phone", "iot"):
        if dtype == "phone":
            out.append(camera)
        topic = f"devices/{dev_id}/telemetry"
        # plain POSIX shell (busybox ash): integer maths + printf, values as a small random walk
        common = f"""
dec() {{ v=$1; n=$2; s=""; [ $v -lt 0 ] && s="-" && v=$((0 - v)); d=1; i=0
  while [ $i -lt $n ]; do d=$((d * 10)); i=$((i + 1)); done
  printf "%s%d.%0${{n}}d" "$s" $((v / d)) $((v % d)); }}
pub() {{ mosquitto_pub -h {HUB_IP} -q 1 -t {topic} -m "$1" || echo "publish failed"; }}
"""
        if dtype == "iot":
            profile = common + f"""
t=2150; h=450; b=10000
while true; do
  t=$((t + RANDOM % 41 - 20)); h=$((h + RANDOM % 13 - 6)); [ $b -gt 500 ] && b=$((b - 2)) || b=10000
  pub "$(printf '{{"temperature_c":%s,"humidity_pct":%s,"battery_pct":%s}}' "$(dec $t 2)" "$(dec $h 1)" "$(dec $b 2)")"
  sleep {interval}
done"""
        else:
            profile = common + f"""
lat=-35362900; lon=149165800; b=10000
while true; do
  lat=$((lat + RANDOM % 81 - 40)); lon=$((lon + RANDOM % 81 - 40)); [ $b -gt 500 ] && b=$((b - 1)) || b=10000
  pub "$(printf '{{"lat":%s,"lon":%s,"battery_pct":%s,"signal_dbm":%d}}' "$(dec $lat 6)" "$(dec $lon 6)" "$(dec $b 2)" $((-70 - RANDOM % 15)))"
  sleep {interval}
done"""
        out.append(client.V1Container(
            name="sensors", image="docker.io/eclipse-mosquitto:2.0.20", image_pull_policy="IfNotPresent",
            command=["sh", "-c", WAIT_5G + profile]))
    return out


def _host_port_video():
    used = {int((d.metadata.annotations or {}).get("sixg/host-video-port", 0))
            for d in apps.list_namespaced_deployment(NS, label_selector="sixg/role=device-gateway").items}
    p = 8890
    while p in used:
        p += 1
    return p


def connect(name, dtype, slice_id=None, mode="simulated", target="8.8.8.8", interval=5, size=200,
            session=None, network="router", dest=None):
    if dtype not in TYPES:
        raise ValueError(f"unknown device type {dtype}")
    if mode not in MODES:
        raise ValueError(f"unknown mode {mode}")
    if MODES[mode]["real"] and network not in NETWORKS:
        raise ValueError(f"unknown network {network}")
    if dest and not re.fullmatch(r"[A-Za-z0-9.-]+:\d{1,5}", dest):
        raise ValueError("a custom destination must be host:port")
    sl = slice_id or TYPES[dtype]["slice"]
    if sl not in SLICES:
        raise ValueError(f"unknown slice {sl}")
    ensure_namespace()
    imsi = _next_imsi()
    key, opc = secrets.token_hex(16).upper(), secrets.token_hex(16).upper()
    s = SLICES[sl]
    out = _dbctl("add_ue_with_slice", str(imsi), key, opc, sl, str(s["sst"]), s["sd"])
    if "error" in out.lower() and "duplicate" not in out.lower():
        raise RuntimeError(f"open5gs-dbctl: {out.strip()[:300]}")

    dev_id = f"dev-{_slug(name)}-{str(imsi)[-4:]}"
    labels = {"app.kubernetes.io/part-of": "sixg", "sixg/layer": "device", "sixg/role": "device-gateway",
              "sixg/device": dev_id, "sixg/slice": sl}
    if session:
        labels["sixg/session"] = session
    meta = {"sixg/imsi": str(imsi), "sixg/name": name, "sixg/type": dtype, "sixg/mode": mode,
            "sixg/created": str(time.time()), "sixg/spec-version": SPEC_VERSION}
    env = {"GNB_HOSTNAME": "gnb1.sixg-ran.svc.cluster.local", "MODE": mode, "HUB_IP": HUB_IP,
           "TARGET": target, "INTERVAL": str(interval), "SIZE": str(size)}
    secret_env = []
    port = None
    service_ports = []
    if dtype == "drone":
        meta["sixg/hub-port"] = str(_hub_port())
    if MODES[mode]["real"]:
        port = MODES[mode]["port"]
        meta.update({"sixg/network": network, "sixg/host-port": str(_host_port(mode))})
        service_ports.append(("device", port))
    if mode == "udp-relay":
        tele = dest or f"{HUB_IP}:{meta.get('sixg/hub-port', 14551)}"
        env["RELAYS"] = f"{port}>{tele},8890>{HUB_IP}:8890"   # telemetry + camera (SRT)
        meta.update({"sixg/dest": tele, "sixg/host-video-port": str(_host_port_video())})
        service_ports.append(("video", 8890))
    if mode == "vpn":
        n = imsi % 250 + 1
        srv_priv, srv_pub = _wg_keypair()
        cli_priv, cli_pub = _wg_keypair()
        env.update(WG_PEER_PUBLIC_KEY=cli_pub, WG_ADDRESS=f"10.99.{n}.1/30", WG_PORT=str(port))
        core.create_namespaced_secret(NS, client.V1Secret(
            metadata=client.V1ObjectMeta(name=dev_id, labels=labels),
            string_data={"server-private-key": srv_priv, "server-public-key": srv_pub,
                         "client-private-key": cli_priv, "client-address": f"10.99.{n}.2/32"}))
        secret_env = [client.V1EnvVar(name="WG_PRIVATE_KEY", value_from=client.V1EnvVarSource(
            secret_key_ref=client.V1SecretKeySelector(name=dev_id, key="server-private-key")))]

    core.create_namespaced_config_map(NS, client.V1ConfigMap(
        metadata=client.V1ObjectMeta(name=dev_id, labels=labels, annotations=meta),
        data={"ue.yaml": _ue_yaml(imsi, key, opc, sl)}))
    container = client.V1Container(
        name="gateway", image=IMAGE, image_pull_policy="IfNotPresent",
        env=[client.V1EnvVar(name=k, value=v) for k, v in env.items()] + secret_env,
        ports=[client.V1ContainerPort(name=n, container_port=p, protocol="UDP") for n, p in service_ports] or None,
        security_context=client.V1SecurityContext(privileged=True, capabilities=client.V1Capabilities(add=["NET_ADMIN"])),
        liveness_probe=GATEWAY_PROBE,
        volume_mounts=[client.V1VolumeMount(name="cfg", mount_path="/etc/ueransim/ue.yaml", sub_path="ue.yaml")])
    sidecars = _sources(dtype, dev_id, int(meta.get("sixg/hub-port", 0)), interval) if mode == "simulated" else []
    apps.create_namespaced_deployment(NS, client.V1Deployment(
        metadata=client.V1ObjectMeta(name=dev_id, labels=labels, annotations=meta),
        spec=client.V1DeploymentSpec(
            replicas=1, selector=client.V1LabelSelector(match_labels={"sixg/device": dev_id}),
            # never two copies of one SIM at once: the old UE's release would kill the new one's session
            strategy=client.V1DeploymentStrategy(type="Recreate"),
            template=client.V1PodTemplateSpec(
                metadata=client.V1ObjectMeta(labels=labels),
                spec=client.V1PodSpec(containers=[container, *sidecars], termination_grace_period_seconds=10,
                                      volumes=[client.V1Volume(name="cfg", config_map=client.V1ConfigMapVolumeSource(name=dev_id))])))))
    if service_ports:  # reachable from the PC (the host relay forwards the hotspot/router ports to it)
        core.create_namespaced_service(NS, client.V1Service(
            metadata=client.V1ObjectMeta(name=dev_id, labels=labels),
            spec=client.V1ServiceSpec(type="NodePort", selector={"sixg/device": dev_id},
                                      ports=[client.V1ServicePort(name=n, port=p, target_port=p, protocol="UDP")
                                             for n, p in service_ports])))
    return {"id": dev_id, "imsi": imsi, "slice": sl}


def upgrade_existing():
    """Bring devices created by an older version up to the current pod spec (run at startup)."""
    done = []
    for d in apps.list_namespaced_deployment(NS, label_selector="sixg/role=device-gateway").items:
        a = d.metadata.annotations or {}
        if a.get("sixg/spec-version") == SPEC_VERSION:
            continue
        spec = d.spec.template.spec
        gw = next(c for c in spec.containers if c.name == "gateway")
        envs = {e.name: e.value for e in gw.env or []}
        # the first devices ran the stock UERANSIM image with an inline script: move them to ours
        gw.image, gw.command, gw.args = IMAGE, None, None
        gw.security_context = client.V1SecurityContext(privileged=True,
                                                       capabilities=client.V1Capabilities(add=["NET_ADMIN"]))
        gw.volume_mounts = [m for m in gw.volume_mounts or [] if m.name == "cfg"]
        gw.liveness_probe = GATEWAY_PROBE
        if "HUB_IP" not in envs:  # devices from before the live hub existed
            gw.env = [*(gw.env or []), client.V1EnvVar(name="HUB_IP", value=HUB_IP)]
        containers = [gw]
        if a.get("sixg/mode") == "simulated":
            containers += _sources(a.get("sixg/type", "generic"), d.metadata.name,
                                   int(a.get("sixg/hub-port", 0) or 0), int(envs.get("INTERVAL", 5)))
        # JSON patch: replaces the container list and the strategy as a whole
        kube.patch_deployment_json(NS, d.metadata.name, [
            {"op": "add", "path": "/metadata/annotations/sixg~1spec-version", "value": SPEC_VERSION},
            {"op": "replace", "path": "/spec/strategy", "value": {"type": "Recreate"}},
            {"op": "replace", "path": "/spec/template/spec/containers",
             "value": client.ApiClient().sanitize_for_serialization(containers)}])
        done.append(d.metadata.name)
    return done


def _gateway_status(dev_id):
    try:
        out = kube.exec_in(NS, dev_id, ["sh", "-c", "ip -4 -br addr show uesimtun0 2>/dev/null; "
                                                     "n=$(nr-cli --dump | head -1); [ -n \"$n\" ] && nr-cli $n --exec status"])
    except Exception:
        return {"registered": False, "ip": None}
    ip = re.search(r"uesimtun0\s+\S+\s+([\d.]+)", out)
    rm = re.search(r"rm-state:\s*(\S+)", out)
    return {"registered": bool(rm and rm.group(1) == "RM-REGISTERED"), "ip": ip.group(1) if ip else None,
            "rmState": rm.group(1) if rm else None}


def list_devices(with_status=True):
    ensure_namespace()
    _, pods, *_ = kube.cache.snapshot()
    out = []
    for d in apps.list_namespaced_deployment(NS, label_selector="sixg/role=device-gateway").items:
        a, l = d.metadata.annotations or {}, d.metadata.labels or {}
        dev_id = d.metadata.name
        dp = [p for p in pods if p["ns"] == NS and p["workload"] == dev_id]
        item = {"id": dev_id, "name": a.get("sixg/name"), "type": a.get("sixg/type"),
                "typeLabel": TYPES.get(a.get("sixg/type"), {}).get("label"), "mode": a.get("sixg/mode"),
                "imsi": a.get("sixg/imsi"), "slice": l.get("sixg/slice"), "session": l.get("sixg/session"),
                "created": float(a.get("sixg/created", 0)), "podReady": any(p["ready"] for p in dp),
                "restarts": sum(p["restarts"] for p in dp)}
        if with_status and item["podReady"]:
            item.update(_gateway_status(dev_id))
        item["deviceOnline"] = _presence(dev_id, a, item["podReady"])
        out.append(item)
    out.sort(key=lambda x: x["created"])
    return out


def _presence(dev_id, a, pod_ready):
    """True/False for real devices (measured now), None for simulated ones."""
    mode = a.get("sixg/mode")
    if not MODES.get(mode, {}).get("real"):
        return None
    if mode == "vpn":
        if not pod_ready:
            return False
        try:
            ts = int((kube.exec_in(NS, dev_id, ["wg", "show", "wg0", "latest-handshakes"]).split() or ["0", "0"])[-1])
        except Exception:
            return False
        return bool(ts) and time.time() - ts < 180
    last = get_host().get("relays", {}).get(a.get("sixg/host-port", ""), {}).get("last")
    return bool(last) and time.time() - last < 30


def disconnect(dev_id):
    d = apps.read_namespaced_deployment(dev_id, NS)
    imsi = (d.metadata.annotations or {}).get("sixg/imsi")
    apps.delete_namespaced_deployment(dev_id, NS)
    for delete in (core.delete_namespaced_config_map, core.delete_namespaced_service, core.delete_namespaced_secret):
        try:
            delete(dev_id, NS)
        except client.ApiException:
            pass
    if imsi:
        _dbctl("remove", imsi)
    return {"removed": dev_id, "imsi": imsi}


def gateway_logs(dev_id, tail=200):
    _, pods, *_ = kube.cache.snapshot()
    pod = next((p for p in pods if p["ns"] == NS and p["workload"] == dev_id), None)
    return kube.pod_logs(NS, pod["name"], container="gateway", tail=tail) if pod else ""


def options():
    return {"types": TYPES, "modes": MODES, "slices": SLICES, "networks": NETWORKS}


def dumps(x):
    return json.dumps(x)


def _pod(dev_id):
    _, pods, *_ = kube.cache.snapshot()
    return next((p for p in pods if p["ns"] == NS and p["workload"] == dev_id and not p["deleting"]), None)


def detail(dev_id):
    """Everything the Devices page shows for one device, measured live."""
    d = apps.read_namespaced_deployment(dev_id, NS)
    a, l = d.metadata.annotations or {}, d.metadata.labels or {}
    pod = _pod(dev_id)
    info = {"id": dev_id, "name": a.get("sixg/name"), "type": a.get("sixg/type"),
            "typeLabel": TYPES.get(a.get("sixg/type"), {}).get("label"), "mode": a.get("sixg/mode"),
            "imsi": a.get("sixg/imsi"), "slice": l.get("sixg/slice"), "session": l.get("sixg/session"),
            "created": float(a.get("sixg/created", 0)), "pod": pod}
    status, sessions, log = {}, {}, ""
    if pod and pod["ready"]:
        try:
            raw = kube.exec_in(NS, dev_id, ["sh", "-c", 'n=$(nr-cli --dump | head -1); nr-cli $n --exec status; echo ===; nr-cli $n --exec ps-list'])
            st, _, ps = raw.partition("===")
            import yaml
            status = yaml.safe_load(st) or {}
            sessions = yaml.safe_load(ps) or {}
        except Exception as e:
            status = {"error": str(e)[:200]}
        log = gateway_logs(dev_id, tail=400)
    ok = log.count("[device] packet ok")
    lost = log.count("[device] packet lost")
    ip = None
    for s in (sessions or {}).values():
        if isinstance(s, dict) and s.get("address"):
            ip = s["address"]
    registered = status.get("rm-state") == "RM-REGISTERED"
    steps = [
        {"key": "subscriber", "label": "5G identity created in the core", "done": True,
         "detail": f"IMSI {info['imsi']}, slice {info['slice']}"},
        {"key": "gateway", "label": "Gateway started", "done": bool(pod and pod["ready"]),
         "detail": pod["name"] if pod else "waiting for Kubernetes"},
        {"key": "registered", "label": "Registered with the network", "done": registered,
         "detail": status.get("mm-state") or status.get("rm-state") or "–"},
        {"key": "session", "label": "Data session (PDU) up", "done": bool(ip), "detail": f"UE IP {ip}" if ip else "–"},
        {"key": "traffic", "label": "Traffic flowing", "done": ok > 0,
         "detail": f"{ok} packets delivered, {lost} lost (recent)" if ok + lost else "no traffic yet"},
    ]
    acc = access(dev_id, a)
    device_online = None  # None = simulated (the gateway is the device)
    if acc is not None:
        # Presence of the REAL device, measured now: WireGuard handshake age, or the last packet
        # the PC relay received from it. Old log lines never count.
        last = None
        if a.get("sixg/mode") == "vpn" and pod and pod["ready"]:
            try:
                wg = kube.exec_in(NS, dev_id, ["sh", "-c", "wg show wg0 latest-handshakes; echo ===; wg show wg0 transfer"])
                hs, _, tr = wg.partition("===")
                ts = int((hs.split() or ["0", "0"])[-1])
                last = ts or None
                t = tr.split()
                if len(t) >= 3:
                    acc["wgRx"], acc["wgTx"] = int(t[-2]), int(t[-1])
            except Exception:
                pass
            limit = 180  # WireGuard re-handshakes every 2 min while the tunnel is up
        else:
            last = acc.get("relayLast")
            limit = 30
        age = (time.time() - last) if last else None
        device_online = age is not None and age < limit
        acc["lastSeenSeconds"] = age
        steps[-1] = {"key": "device", "label": "Real device connected", "done": device_online,
                     "detail": (f"last contact {int(age)} s ago" if device_online else
                                f"no contact for {int(age // 60)} min {int(age % 60)} s: device disconnected" if age else
                                f"waiting: connect the device to {acc['networkLabel'] or 'the network'}")}
    info.update(status=status, sessions=sessions, ip=ip, registered=registered, delivered=ok, lost=lost,
                steps=steps, access=acc, deviceOnline=device_online,
                gatewayReady=all(x["done"] for x in steps[:4]))
    return info


def connection_test(dev_id, target="8.8.8.8", count=10, size=500):
    """Real round-trip test through the device's own 5G session (UE -> gNB -> UPF -> data network)."""
    out = kube.exec_in(NS, dev_id, ["ping", "-I", "uesimtun0", "-c", str(count), "-i", "0.2", "-W", "2",
                                    "-s", str(size), target], timeout=60)
    loss = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", out)
    return {"target": target, "sent": count, "size": size, "lossPct": float(loss.group(1)) if loss else None,
            "rttMin": float(rtt.group(1)) if rtt else None, "rttAvg": float(rtt.group(2)) if rtt else None,
            "rttMax": float(rtt.group(3)) if rtt else None, "output": out}


# ---------- the PC side: which address the device should use ----------

def _host_file():
    import os
    import pathlib
    return pathlib.Path(os.environ.get("DATA_DIR", "/data")) / "host.json"


def set_host(info):
    """Called by the relay running on the PC: its addresses on the hotspot/router networks."""
    info = {"addresses": info.get("addresses", []), "relays": info.get("relays", {}), "seen": time.time()}
    _host_file().write_text(json.dumps(info))
    return info


def get_host():
    try:
        h = json.loads(_host_file().read_text())
        h["online"] = time.time() - h["seen"] < 20
        return h
    except (OSError, ValueError):
        return {"addresses": [], "relays": {}, "seen": None, "online": False}


def exposures():
    """What the PC relay must forward: PC port -> VM NodePort, one entry per real device."""
    out = []
    for d in apps.list_namespaced_deployment(NS, label_selector="sixg/role=device-gateway").items:
        a = d.metadata.annotations or {}
        if not a.get("sixg/host-port"):
            continue
        try:
            svc = core.read_namespaced_service(d.metadata.name, NS)
        except client.ApiException:
            continue
        nodes = {p.name: p.node_port for p in svc.spec.ports}
        for kind, key in (("device", "sixg/host-port"), ("video", "sixg/host-video-port")):
            if a.get(key) and nodes.get(kind):
                out.append({"device": d.metadata.name, "stream": kind, "mode": a.get("sixg/mode"),
                            "network": a.get("sixg/network"), "hostPort": int(a[key]), "nodePort": nodes[kind], "proto": "udp"})
    return out


def access(dev_id, annotations):
    """How the real device reaches its gateway: the PC's address + port, and for WireGuard the config."""
    mode = annotations.get("sixg/mode")
    if not MODES.get(mode, {}).get("real"):
        return None
    host = get_host()
    port = int(annotations.get("sixg/host-port", 0))
    relay = host.get("relays", {}).get(str(port), {})
    addrs = host.get("addresses", [])
    info = {"network": annotations.get("sixg/network"), "networkLabel": NETWORKS.get(annotations.get("sixg/network")),
            "port": port, "addresses": addrs, "relayOnline": host.get("online", False),
            "relayActive": bool(relay), "relayPackets": relay.get("packets", 0), "relayLast": relay.get("last"),
            "dest": annotations.get("sixg/dest")}
    if mode == "vpn":
        n = int(annotations.get("sixg/imsi", "0")) % 250 + 1
        info["deviceTunnelIp"] = f"10.99.{n}.2"
    # where the device's data goes to be shown live in the dashboard
    if mode == "udp-relay":
        vport = annotations.get("sixg/host-video-port")
        info["video"] = {"send": [f"{x['ip']}:{vport}" for x in addrs] or [f"<this PC>:{vport}"],
                         "streamId": f"publish:{dev_id}", "protocol": "SRT (MPEG-TS)"}
    else:
        info["hub"] = {"ip": HUB_IP,
                       "srt": f"srt://{HUB_IP}:8890?streamid=publish:{dev_id}",
                       "rtmp": f"rtmp://{HUB_IP}:1935/{dev_id}",
                       "rtsp": f"rtsp://{HUB_IP}:8554/{dev_id}",
                       "mqttBroker": f"{HUB_IP}:1883", "mqttTopic": f"devices/{dev_id}/telemetry"}
    if mode == "vpn":
        sec = core.read_namespaced_secret(dev_id, NS)
        import base64
        dec = {k: base64.b64decode(v).decode() for k, v in (sec.data or {}).items()}
        ep = f"{addrs[0]['ip']}:{port}" if addrs else f"<PC address>:{port}"
        info["wireguard"] = (
            "[Interface]\n"
            f"PrivateKey = {dec['client-private-key']}\n"
            f"Address = {dec['client-address']}\n"
            "DNS = 8.8.8.8\nMTU = 1280\n\n"
            "[Peer]\n"
            f"PublicKey = {dec['server-public-key']}\n"
            f"Endpoint = {ep}\n"
            "AllowedIPs = 0.0.0.0/0\nPersistentKeepalive = 25\n")
    return info


def device_test(dev_id, count=5):
    """Ping the real device itself through its WireGuard tunnel (fails when the device is off)."""
    d = apps.read_namespaced_deployment(dev_id, NS)
    a = d.metadata.annotations or {}
    if a.get("sixg/mode") != "vpn":
        raise ValueError("only WireGuard devices can be pinged; UDP devices are shown by their last packet")
    ip = f"10.99.{int(a['sixg/imsi']) % 250 + 1}.2"
    out = kube.exec_in(NS, dev_id, ["ping", "-I", "wg0", "-c", str(count), "-i", "0.5", "-W", "2", ip], timeout=40)
    loss = re.search(r"(\d+(?:\.\d+)?)% packet loss", out)
    rtt = re.search(r"= ([\d.]+)/([\d.]+)/([\d.]+)", out)
    return {"target": ip, "sent": count, "size": 56, "lossPct": float(loss.group(1)) if loss else 100.0,
            "rttMin": float(rtt.group(1)) if rtt else None, "rttAvg": float(rtt.group(2)) if rtt else None,
            "rttMax": float(rtt.group(3)) if rtt else None, "output": out}
