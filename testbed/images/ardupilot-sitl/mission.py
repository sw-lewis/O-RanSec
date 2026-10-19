"""Simulated pilot for the SITL copter: arm, take off and fly a square around home, forever.
Talks to ArduPilot on its local serial1 (tcp:127.0.0.1:5762). Nothing here touches a real aircraft."""
import math
import os
import time

from pymavlink import mavutil

ALT = float(os.environ.get("MISSION_ALT_M", "30"))
SIDE = float(os.environ.get("MISSION_SIDE_M", "120"))

m = mavutil.mavlink_connection("tcp:127.0.0.1:5762", source_system=250)
m.wait_heartbeat()
print(f"[pilot] connected to system {m.target_system}", flush=True)
# like a ground station: ask for telemetry on this link (GPS, position, status)
m.mav.request_data_stream_send(m.target_system, m.target_component, mavutil.mavlink.MAV_DATA_STREAM_ALL, 4, 1)


def wait_ready():
    # wait for a GPS fix and EKF so arming is accepted
    while True:
        msg = m.recv_match(type="GPS_RAW_INT", blocking=True, timeout=5)
        if msg and msg.fix_type >= 3:
            return


def cmd(command, *params):
    """Send a command and return the COMMAND_ACK for THIS command (other acks are ignored)."""
    p = list(params) + [0] * (7 - len(params))
    m.mav.command_long_send(m.target_system, m.target_component, command, 0, *p)
    t0 = time.time()
    while time.time() - t0 < 5:
        ack = m.recv_match(type="COMMAND_ACK", blocking=True, timeout=1)
        if ack and ack.command == command:
            return ack
    return None


def armed():
    hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=3)
    return bool(hb and hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED)


def goto(lat, lon, alt):
    m.mav.set_position_target_global_int_send(
        0, m.target_system, m.target_component, mavutil.mavlink.MAV_FRAME_GLOBAL_RELATIVE_ALT_INT,
        0b0000111111111000, int(lat * 1e7), int(lon * 1e7), alt, 0, 0, 0, 0, 0, 0, 0, 0)


def rel_alt():
    msg = m.recv_match(type="GLOBAL_POSITION_INT", blocking=True, timeout=3)
    return msg.relative_alt / 1000 if msg else 0.0


def take_off():
    """Arm and climb; True once the copter is actually in the air."""
    m.set_mode("GUIDED")
    for _ in range(40):
        ack = cmd(mavutil.mavlink.MAV_CMD_COMPONENT_ARM_DISARM, 1)
        if ack and ack.result == 0 and armed():
            print("[pilot] armed", flush=True)
            break
        time.sleep(3)  # pre-arm checks (EKF position estimate, GPS) still settling
    else:
        return False
    ack = cmd(mavutil.mavlink.MAV_CMD_NAV_TAKEOFF, 0, 0, 0, 0, 0, 0, ALT)
    print(f"[pilot] take-off command answer: {ack.result if ack else 'none'}", flush=True)
    t0 = time.time()
    while time.time() - t0 < 20:
        msg = m.recv_match(type=["GLOBAL_POSITION_INT", "STATUSTEXT"], blocking=True, timeout=2)
        if msg is None:
            continue
        if msg.get_type() == "STATUSTEXT":
            print(f"[autopilot] {msg.text}", flush=True)
        elif msg.relative_alt / 1000 > 2:
            return True
    return False


while True:
    wait_ready()
    time.sleep(20)  # let the EKF converge after the GPS fix
    home = m.recv_match(type="GLOBAL_POSITION_INT", blocking=True)
    lat0, lon0 = home.lat / 1e7, home.lon / 1e7
    if not take_off():
        print("[pilot] take-off did not happen, retrying", flush=True)
        continue
    print(f"[pilot] airborne at {rel_alt():.0f} m, flying a {SIDE:.0f} m square", flush=True)
    time.sleep(10)
    dlat = SIDE / 111_320
    dlon = SIDE / (111_320 * math.cos(math.radians(lat0)))
    corners = [(lat0 + dlat, lon0), (lat0 + dlat, lon0 + dlon), (lat0, lon0 + dlon), (lat0, lon0)]
    try:
        while True:
            for lat, lon in corners:
                goto(lat, lon, ALT)
                time.sleep(20)
            hb = m.recv_match(type="HEARTBEAT", blocking=True, timeout=5)
            if hb and not hb.base_mode & mavutil.mavlink.MAV_MODE_FLAG_SAFETY_ARMED:
                print("[pilot] disarmed, restarting the flight", flush=True)
                break
    except Exception as e:
        print(f"[pilot] {e}", flush=True)
        time.sleep(5)
