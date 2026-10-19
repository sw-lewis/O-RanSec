# srsRAN Project gNB (official source, release_25_10) with the ZeroMQ virtual radio and E2 agent.
FROM ubuntu:22.04 AS build
ARG SRSRAN_REF=release_25_10
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      git ca-certificates cmake make gcc g++ pkg-config libfftw3-dev libmbedtls-dev \
      libsctp-dev libyaml-cpp-dev libgtest-dev libzmq3-dev && rm -rf /var/lib/apt/lists/*
RUN git clone --depth 1 --branch ${SRSRAN_REF} https://github.com/srsran/srsRAN_Project.git /src
WORKDIR /src/build
# Portable build (AVX2 baseline) so the image also runs on the future server.
RUN cmake .. -DENABLE_ZEROMQ=ON -DAUTO_DETECT_ISA=OFF -DMARCH=x86-64-v3 \
      -DBUILD_TESTING=OFF -DCMAKE_BUILD_TYPE=Release \
 && make -j"$(nproc)" gnb

FROM ubuntu:22.04
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libfftw3-3 libmbedtls14 libmbedcrypto7 libsctp1 libyaml-cpp0.7 libzmq5 \
      iproute2 iputils-ping dnsutils gettext-base procps && rm -rf /var/lib/apt/lists/*
COPY --from=build /src/build/apps/gnb/gnb /usr/local/bin/gnb
ENTRYPOINT ["/usr/local/bin/gnb"]
