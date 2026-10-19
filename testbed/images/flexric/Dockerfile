# FlexRIC near-RT RIC + example xApps for srsRAN (per srsRAN's RIC guide: branch br-flexric,
# KPM v3.00, gcc-10). The guide's commit 1a3903a7 predates the KPM_V3_00 option, so we pin
# br-flexric head 73650812 (2024-09-20) which has it.
FROM ubuntu:22.04 AS build
ARG FLEXRIC_COMMIT=736508123fe4b5dc3db83fb5baf5f0a8e9b04fe8
ARG E2AP_VERSION=E2AP_V2
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates cmake make gcc-10 g++-10 libsctp-dev python3 libpcre2-dev libconfig-dev \
      automake autoconf libtool pkg-config && rm -rf /var/lib/apt/lists/*
RUN git clone https://gitlab.eurecom.fr/mosaic5g/flexric.git /src && cd /src \
 && git checkout br-flexric && git checkout ${FLEXRIC_COMMIT}
WORKDIR /src/build
RUN CC=gcc-10 CXX=g++-10 cmake .. -DKPM_VERSION=KPM_V3_00 -DE2AP_VERSION=${E2AP_VERSION} -DXAPP_DB=NONE_XAPP \
      -DXAPP_MULTILANGUAGE=OFF -DCMAKE_BUILD_TYPE=Release \
 && make -j"$(nproc)" && make install

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libsctp1 libpcre2-8-0 libconfig9 iproute2 dnsutils coreutils && rm -rf /var/lib/apt/lists/*
COPY --from=build /usr/local/lib/flexric /usr/local/lib/flexric
COPY --from=build /usr/local/etc/flexric /usr/local/etc/flexric
COPY --from=build /src/build/examples/ric/nearRT-RIC /usr/local/bin/nearRT-RIC
COPY --from=build /src/build/examples/xApp/c /opt/flexric/xapps
ENTRYPOINT ["/usr/local/bin/nearRT-RIC"]
