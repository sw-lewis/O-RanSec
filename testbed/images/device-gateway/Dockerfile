# Per-device 5G gateway: a UERANSIM UE (the device's 5G identity) plus the tools that carry a
# real device's traffic into that UE's PDU session (WireGuard, socat relay, iptables NAT).
FROM docker.io/gradiant/ueransim:3.2.6
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      wireguard-tools iptables socat iputils-ping iproute2 && rm -rf /var/lib/apt/lists/*
COPY gateway.sh /usr/local/bin/gateway.sh
ENTRYPOINT ["/usr/local/bin/gateway.sh"]
