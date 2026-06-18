# Compiles Python deps that don't ship aarch64 wheels for the runtime Python
# (e.g. crc32c, a transitive dep of oci 2.178+). build-essential stays here;
# the runtime stage copies only the installed packages out of /install.
FROM python:3.14-slim AS py-builder

RUN apt-get update && \
    apt-get install -y --no-install-recommends build-essential && \
    rm -rf /var/lib/apt/lists/*

WORKDIR /build
COPY pyproject.toml .
RUN pip install --no-cache-dir --prefix=/install .


FROM python:3.14-slim

# Apply security upgrades only; no build tools needed in the final image.
RUN apt-get update && \
    apt-get -y upgrade && \
    rm -rf /var/lib/apt/lists/*

# Copy Python deps installed in the py-builder stage
COPY --from=py-builder /install /usr/local

WORKDIR /app

# Copy application code
COPY src/ ./src/

# Run as non-root user
RUN useradd -m -u 1000 exporter && \
    chown -R exporter:exporter /app

USER exporter

ENV PYTHONUNBUFFERED=1

# Prometheus scrape target (/metrics) + health probe (/healthz). Override with
# METRICS_PORT if 9090 collides with another container in the Pod.
EXPOSE 9090

CMD ["python", "-m", "src.oci_monitoring_exporter"]
