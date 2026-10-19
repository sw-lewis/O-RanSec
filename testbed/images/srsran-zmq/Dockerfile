# srsRAN gNB + srsUE in one image, for the ZMQ virtual radio pair that must start and stop together.
# Both binaries come from the images built from official source (srsran-gnb, srsue, release_25_10).
FROM sixg/srsue:25.10 AS ue
FROM sixg/srsran-gnb:25.10
ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && apt-get install -y --no-install-recommends \
      libboost-program-options1.74.0 libconfig++9v5 iperf3 && rm -rf /var/lib/apt/lists/*
COPY --from=ue /usr/local/bin/srsue /usr/local/bin/srsue
COPY --from=ue /usr/local/lib/ /usr/local/lib/
RUN ldconfig && srsue --version >/dev/null 2>&1 || true
COPY run-pair.sh /usr/local/bin/run-pair.sh
ENTRYPOINT ["/usr/local/bin/run-pair.sh"]
