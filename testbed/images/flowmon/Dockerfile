# flowmon: per-link traffic exporter built on kernel conntrack (see flowmon.py).
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends conntrack procps \
 && rm -rf /var/lib/apt/lists/* \
 && pip install --no-cache-dir kubernetes==31.0.0 prometheus-client==0.21.1
COPY flowmon.py /app/flowmon.py
CMD ["python", "-u", "/app/flowmon.py"]
