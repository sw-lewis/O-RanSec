"""Device live hub (edge / MEC application of the 6G testbed).

Collects what connected devices send through their 5G sessions and serves it to the dashboard:
  - MAVLink telemetry (drones), decoded with pymavlink, one UDP port per drone
  - MQTT messages (IoT sensors, phones) from the Mosquitto broker in this pod, topic devices/<id>/...
  - video streams are held by MediaMTX in this pod (SRT/RTMP/RTSP in, HLS out)."""
import asyncio
import collections
import os
import time

import json

import paho.mqtt.client as mqtt
from fastapi import FastAPI, HTTPException
from fastapi.responses import PlainTextResponse
from pymavlink.dialects.v20 import ardupilotmega as mav
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

# One UDP port per connected drone (the testbed assigns them), so data is never mixed up.
PORT_FIRST, PORT_LAST = (int(x) for x in os.environ.get("MAVLINK_PORTS", "14551-14570").split("-"))
TRACK_LEN = 2000

MSGS = Counter("drone_mavlink_messages_total", "MAVLink messages received", ["sysid", "type"])
BAD = Counter("drone_mavlink_bad_packets_total", "Undecodable packets received")
LAST = Gauge("drone_last_seen_timestamp", "Unix time of the last message from a drone", ["sysid"])
ALT = Gauge("drone_relative_altitude_m", "Altitude above home", ["sysid"])
SPEED = Gauge("drone_ground_speed_mps", "Ground speed", ["sysid"])
BATT = Gauge("drone_battery_remaining_pct", "Battery remaining", ["sysid"])


class Drone:
    def __init__(self, sysid, port):
        self.sysid = sysid
        self.port = port
        self.first_seen = time.time()
        self.last_seen = 0.0
        self.source = None
        self.state = {}
        self.track = collections.deque(maxlen=TRACK_LEN)
        self.counts = collections.Counter()

    def view(self):
        return {"sysid": self.sysid, "port": self.port, "source": self.source, "firstSeen": self.first_seen,
                "lastSeen": self.last_seen, "ageSeconds": round(time.time() - self.last_seen, 1),
                "state": self.state, "messages": dict(self.counts)}


drones: dict[tuple, Drone] = {}  # (port, sysid) -> Drone


def handle(msg, addr, port):
    t = msg.get_type()
    if t == "BAD_DATA":
        BAD.inc()
        return
    sid = msg.get_srcSystem()
    d = drones.get((port, sid)) or drones.setdefault((port, sid), Drone(sid, port))
    d.last_seen = time.time()
    d.source = f"{addr[0]}:{addr[1]}"
    d.counts[t] += 1
    MSGS.labels(str(sid), t).inc()
    LAST.labels(str(sid)).set(d.last_seen)
    s = d.state
    if t == "GLOBAL_POSITION_INT":
        s.update(lat=msg.lat / 1e7, lon=msg.lon / 1e7, altAmsl=msg.alt / 1000, altRel=msg.relative_alt / 1000,
                 heading=msg.hdg / 100 if msg.hdg != 65535 else None)
        ALT.labels(str(sid)).set(s["altRel"])
        d.track.append((round(d.last_seen, 1), s["lat"], s["lon"], s["altRel"]))
    elif t == "VFR_HUD":
        s.update(groundSpeed=msg.groundspeed, airSpeed=msg.airspeed, climb=msg.climb, throttle=msg.throttle)
        SPEED.labels(str(sid)).set(msg.groundspeed)
    elif t == "ATTITUDE":
        s.update(roll=round(msg.roll * 57.2958, 1), pitch=round(msg.pitch * 57.2958, 1), yaw=round(msg.yaw * 57.2958, 1))
    elif t == "SYS_STATUS":
        s.update(batteryPct=msg.battery_remaining, batteryV=msg.voltage_battery / 1000)
        BATT.labels(str(sid)).set(msg.battery_remaining)
    elif t == "GPS_RAW_INT":
        s.update(gpsFix=msg.fix_type, satellites=msg.satellites_visible)
    elif t == "HEARTBEAT":
        s.update(armed=bool(msg.base_mode & mav.MAV_MODE_FLAG_SAFETY_ARMED),
                 mode=mav.enums["COPTER_MODE"].get(msg.custom_mode, None) and mav.enums["COPTER_MODE"][msg.custom_mode].name.replace("COPTER_MODE_", ""),
                 vehicleType=mav.enums["MAV_TYPE"][msg.type].name.replace("MAV_TYPE_", "") if msg.type in mav.enums["MAV_TYPE"] else msg.type)


class Receiver(asyncio.DatagramProtocol):
    """One UDP port. Like any ground station, it asks each drone it hears to stream its telemetry
    (ArduPilot only sends position, battery, GPS ... after a REQUEST_DATA_STREAM)."""

    def __init__(self, port):
        self.port = port
        self.parsers = {}
        self.requested = {}
        self.gcs = mav.MAVLink(None, srcSystem=255, srcComponent=190)

    def connection_made(self, transport):
        self.transport = transport

    def _request_streams(self, addr, sysid):
        now = time.time()
        if now - self.requested.get((addr, sysid), 0) < 15:
            return
        self.requested[(addr, sysid)] = now
        msg = self.gcs.request_data_stream_encode(sysid, 1, mav.MAV_DATA_STREAM_ALL, 4, 1)
        self.transport.sendto(msg.pack(self.gcs), addr)

    def _parser(self, addr):
        p = self.parsers.get(addr)
        if p is None:
            # robust parsing: malformed bytes come back as BAD_DATA instead of raising and
            # leaving them in the buffer (which blocked every following packet)
            p = self.parsers[addr] = mav.MAVLink(None, srcSystem=255)
            p.robust_parsing = True
        return p

    def datagram_received(self, data, addr):
        p = self._parser(addr)
        try:
            for msg in p.parse_buffer(data) or []:
                handle(msg, addr, self.port)
                if msg.get_type() == "HEARTBEAT" and msg.get_srcComponent() == 1:
                    self._request_streams(addr, msg.get_srcSystem())
        except mav.MAVError:
            BAD.inc()
            self.parsers.pop(addr, None)  # start clean on the next packet
        except Exception as e:  # never let one packet kill this port's receiver
            BAD.inc()
            self.parsers.pop(addr, None)
            print(f"port {self.port}: {e!r}", flush=True)


# ---------- MQTT ----------
MQTT_HOST = os.environ.get("MQTT_HOST", "127.0.0.1")
MQTT_MSGS = Counter("device_mqtt_messages_total", "MQTT messages received", ["device"])
mqtt_latest = collections.defaultdict(dict)                     # device -> topic -> {value, t}
mqtt_feed = collections.defaultdict(lambda: collections.deque(maxlen=300))  # device -> recent messages


def _on_message(_c, _u, msg):
    parts = msg.topic.split("/")
    if len(parts) < 2 or parts[0] != "devices":
        return
    dev, sub = parts[1], "/".join(parts[2:]) or "data"
    raw = msg.payload.decode(errors="replace")[:2000]
    try:
        value = json.loads(raw)
    except ValueError:
        value = raw
    now = time.time()
    mqtt_latest[dev][sub] = {"value": value, "t": now}
    mqtt_feed[dev].append({"t": now, "topic": sub, "value": value})
    MQTT_MSGS.labels(dev).inc()


def start_mqtt():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="device-hub")
    c.on_message = _on_message
    c.on_connect = lambda cl, *_: cl.subscribe("devices/#")
    c.connect_async(MQTT_HOST, 1883)
    c.loop_start()


app = FastAPI(title="Testbed device live hub (edge)")


@app.on_event("startup")
async def start():
    loop = asyncio.get_running_loop()
    for p in range(PORT_FIRST, PORT_LAST + 1):
        await loop.create_datagram_endpoint(lambda p=p: Receiver(p), local_addr=("0.0.0.0", p))
    print(f"listening for MAVLink on udp/{PORT_FIRST}-{PORT_LAST}", flush=True)
    start_mqtt()
    asyncio.create_task(summary())


async def summary():
    while True:
        await asyncio.sleep(10)
        for d in drones.values():
            s = d.state
            print(f"drone {d.sysid} on port {d.port} from {d.source}: {sum(d.counts.values())} msgs, "
                  f"lat={s.get('lat')} lon={s.get('lon')} alt={s.get('altRel')} mode={s.get('mode')} "
                  f"armed={s.get('armed')} batt={s.get('batteryPct')}%", flush=True)


@app.get("/api/drones")
def list_drones():
    return [d.view() for d in drones.values()]


@app.get("/api/ports/{port}")
def by_port(port: int):
    """The drone(s) received on one port (the testbed gives each connected drone its own port)."""
    return [d.view() for d in drones.values() if d.port == port]


@app.get("/api/ports/{port}/track")
def track(port: int, last: int = 600):
    ds = [d for d in drones.values() if d.port == port]
    if not ds:
        raise HTTPException(404, "nothing received on this port yet")
    d = max(ds, key=lambda x: x.last_seen)
    return [dict(zip(("t", "lat", "lon", "alt"), p)) for p in list(d.track)[-last:]]


@app.get("/api/mqtt/{device}")
def mqtt_device(device: str, feed: int = 50):
    return {"latest": mqtt_latest.get(device, {}), "feed": list(mqtt_feed.get(device, []))[-feed:]}


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)
