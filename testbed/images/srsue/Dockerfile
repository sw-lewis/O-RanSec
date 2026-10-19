# srsUE (official srsRAN_4G source, release_25_10) with the ZeroMQ virtual radio. 5G SA capable.
FROM ubuntu:22.04 AS build
ARG SRSRAN4G_REF=release_25_10
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates cmake make gcc g++ pkg-config libfftw3-dev libmbedtls-dev \
      libboost-program-options-dev libconfig++-dev libsctp-dev libzmq3-dev && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${SRSRAN4G_REF} https://github.com/srsran/srsRAN_4G.git /src
WORKDIR /src/build
# Portable AVX2 baseline (x86-64-v3) like the gNB image: SIMD detection on, AVX-512 off.
RUN cmake .. -DAUTO_DETECT_ISA=ON -DENABLE_AVX512=OFF -DGCC_ARCH=x86-64-v3 -DCMAKE_BUILD_TYPE=Release -DENABLE_SRSENB=OFF -DENABLE_SRSEPC=OFF \
 && make -j"$(nproc)" srsue

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libfftw3-3 libmbedtls14 libmbedcrypto7 libboost-program-options1.74.0 libconfig++9v5 \
      libsctp1 libzmq5 iproute2 iputils-ping iperf3 dnsutils gettext-base procps && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/srsue/src/srsue /usr/local/bin/srsue
COPY --from=build /src/build/lib/src/phy/rf/libsrsran_rf*.so* /usr/local/lib/
RUN ldconfig
ENTRYPOINT ["/usr/local/bin/srsue"]
