#!/usr/bin/env python3
"""Host relay for real devices (runs on the PC, started/stopped by `6g`).

Real devices (drones, phones, laptops) on the same phone hotspot or router as this PC send to
<this PC's address>:<port>. This relay forwards those UDP packets to the device's own 5G
gateway in the VM and carries the replies back. It only listens on private (hotspot/LAN)
addresses, only accepts private senders, and only opens ports the dashboard asks for.
Direction is always PC -> VM; the VM never connects to the PC."""
import asyncio
import ipaddress
import json
import socket
import subprocess
import time
import urllib.request

API = "http://127.0.0.1:8660"
VM_IP = "10.166.0.10"
SKIP = ("lo", "docker", "br-", "virbr", "veth", "vnet", "tun", "tap", "wg", "cni", "flannel")


def lan_addresses():
    out = []
    raw = subprocess.run(["ip", "-4", "-o", "addr", "show", "scope", "global"], capture_output=True, text=True).stdout
    for line in raw.splitlines():
        f = line.split()
        iface, ip = f[1], f[3].split("/")[0]
        if iface.startswith(SKIP) or not ipaddress.ip_address(ip).is_private:
            continue
        ssid = None
        try:
            r = subprocess.run(["nmcli", "-t", "-f", "GENERAL.CONNECTION", "dev", "show", iface],
                               capture_output=True, text=True, timeout=3).stdout
            ssid = r.split(":", 1)[1].strip() or None
        except Exception:
            pass
        out.append({"iface": iface, "ip": ip, "network": ssid})
    return out


class Relay(asyncio.DatagramProtocol):
    """One listening port on one PC address; one upstream socket per device address."""

    def __init__(self, node_port, stats):
        self.node_port, self.stats = node_port, stats
        self.peers = {}

    def connection_made(self, transport):
        self.transport = transport

    def datagram_received(self, data, addr):
        if not ipaddress.ip_address(addr[0]).is_private:
            return
        self.stats["packets"] += 1
        self.stats["last"] = time.time()
        self.stats["clients"] = sorted({*self.stats.get("clients", []), addr[0]})
        up = self.peers.get(addr)
        if up is None:
            loop = asyncio.get_running_loop()
            up = self.peers[addr] = Upstream(self, addr)
            loop.create_task(loop.create_datagram_endpoint(lambda: up, remote_addr=(VM_IP, self.node_port)))
        up.send(data)


class Upstream(asyncio.DatagramProtocol):
    def __init__(self, relay, client):
        self.relay, self.client, self.transport, self.queue = relay, client, None, []

    def connection_made(self, transport):
        self.transport = transport
        for d in self.queue:
            transport.sendto(d)
        self.queue = []

    def send(self, data):
        (self.transport.sendto(data) if self.transport else self.queue.append(data))

    def datagram_received(self, data, _):
        self.relay.transport.sendto(data, self.client)


def api(path, body=None):
    req = urllib.request.Request(API + path, data=json.dumps(body).encode() if body is not None else None,
                                 headers={"Content-Type": "application/json"}, method="POST" if body is not None else "GET")
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


async def main():
    loop = asyncio.get_running_loop()
    running = {}  # (ip, hostPort) -> (transport, nodePort)
    stats = {}    # hostPort -> {"packets", "clients"}
    while True:
        try:
            wanted = {e["hostPort"]: e["nodePort"] for e in api("/api/host/exposures")}
            addrs = lan_addresses()
            for (ip, port), (tr, node) in list(running.items()):
                if wanted.get(port) != node or ip not in {a["ip"] for a in addrs}:
                    tr.close()
                    del running[(ip, port)]
                    print(f"relay closed {ip}:{port}", flush=True)
            for port, node in wanted.items():
                st = stats.setdefault(str(port), {"packets": 0, "clients": []})
                for a in addrs:
                    if (a["ip"], port) not in running:
                        try:
                            tr, _ = await loop.create_datagram_endpoint(lambda n=node, s=st: Relay(n, s),
                                                                        local_addr=(a["ip"], port), family=socket.AF_INET)
                            running[(a["ip"], port)] = (tr, node)
                            print(f"relay {a['ip']}:{port} -> {VM_IP}:{node}", flush=True)
                        except OSError as e:
                            print(f"cannot listen on {a['ip']}:{port}: {e}", flush=True)
            api("/api/host/info", {"addresses": addrs, "relays": {p: s for p, s in stats.items() if int(p) in wanted}})
        except Exception as e:
            print(f"relay: {e}", flush=True)
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())
