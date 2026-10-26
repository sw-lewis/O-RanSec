# Edge UPF for the sl04 MEC: Open5GS UPF from the project's PPA (2.7.x, same series as the testbed core).
FROM ubuntu:24.04
RUN apt-get update \
 && apt-get install -y --no-install-recommends software-properties-common gnupg iproute2 iptables \
 && add-apt-repository -y ppa:open5gs/latest \
 && apt-get update \
 && apt-get install -y --no-install-recommends open5gs-upf \
 && rm -rf /var/lib/apt/lists/*
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh
ENTRYPOINT ["/entrypoint.sh"]
