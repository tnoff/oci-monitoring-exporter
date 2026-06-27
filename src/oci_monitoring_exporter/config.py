"""Configuration for the OCI Monitoring exporter.

Two sources, kept deliberately separate:

* **Environment variables** — runtime knobs (OTLP, HTTP port, poll cadence,
  OCI auth pointers). Loaded by :meth:`Config.from_env`.
* **A YAML query file** — the ``(compartment, namespace, metric_names)``
  tuples to poll, mounted as a ConfigMap in production. Parsed by
  :func:`load_queries`.

The query list is intentionally *not* hardcoded here — terraform/docker-apps
stamps it into a ConfigMap so coverage changes don't require an image rebuild.
"""

import os
from dataclasses import dataclass, field

import yaml


@dataclass
class MetricQuery:
    """One OCI Monitoring query — a ``(compartment, namespace, metrics)`` tuple.

    At poll time each query expands into one or more Prometheus series (one per
    resource × dimension set OCI returns for the named metrics).
    """

    compartment_id: str
    namespace: str
    metric_names: list[str]
    # OCI resourceGroup filter; None means "no resourceGroup dimension".
    resource_group: str | None = None
    # Aggregation applied in the MQL statement, e.g. "mean" → `Metric[1m].mean()`.
    statistic: str = "mean"
    # MQL window.
    interval: str = "1m"

    def __post_init__(self):
        if not self.compartment_id:
            raise ValueError("metric query is missing 'compartment_id'")
        if not self.namespace:
            raise ValueError(f"metric query for {self.compartment_id} is missing 'namespace'")
        if not self.metric_names:
            raise ValueError(f"metric query for namespace '{self.namespace}' has no 'metric_names'")


@dataclass
class Config:
    """Exporter configuration from environment variables + the YAML query file."""

    # OTLP — the exporter's *own* observability (poll counts, errors, OCI API
    # latency). Distinct from the Prometheus metrics it re-exposes on /metrics.
    otlp_endpoint: str
    otlp_insecure: bool
    otlp_metrics_enabled: bool
    otlp_logs_enabled: bool

    # HTTP server exposing /metrics + /healthz.
    metrics_addr: str
    metrics_port: int

    # Polling cadence (OCI Monitoring aggregates to a 1-minute minimum).
    poll_interval_seconds: int

    # OCI auth (traditional user + API key — see DEVELOPMENT.md). The SDK reads
    # the config file itself; we only point it at the right file/profile/region.
    oci_config_file: str
    oci_profile: str
    oci_region: str

    # Path to the YAML query file, plus the parsed queries.
    queries_file: str

    # When False (default) the chatty third-party HTTP loggers (urllib3 — every
    # OTLP export POST + OCI API call) are quieted to WARNING so they don't drown
    # the exporter's own DEBUG logs or echo back through OTLP. Flip to True to
    # restore them for debugging the HTTP/OTLP path.
    third_party_debug_logs: bool = False

    queries: list[MetricQuery] = field(default_factory=list)

    def __post_init__(self):
        if self.poll_interval_seconds <= 0:
            raise ValueError("POLL_INTERVAL_SECONDS must be a positive integer")
        if not 1 <= self.metrics_port <= 65535:
            raise ValueError("METRICS_PORT must be between 1 and 65535")

    @classmethod
    def from_env(cls) -> "Config":
        """Load configuration from environment variables (and the YAML query file)."""
        queries_file = os.getenv("QUERIES_FILE", "/etc/oci-monitoring-exporter/queries.yaml")
        return cls(
            otlp_endpoint=os.getenv("OTLP_ENDPOINT", "http://localhost:4318"),
            otlp_insecure=os.getenv("OTLP_INSECURE", "true").lower() == "true",
            otlp_metrics_enabled=os.getenv("OTLP_METRICS_ENABLED", "false").lower() == "true",
            otlp_logs_enabled=os.getenv("OTLP_LOGS_ENABLED", "false").lower() == "true",
            # Binds all interfaces by design — the exporter exists to be scraped.
            metrics_addr=os.getenv("METRICS_ADDR", "0.0.0.0"),  # nosec B104
            metrics_port=int(os.getenv("METRICS_PORT", "9090")),
            poll_interval_seconds=int(os.getenv("POLL_INTERVAL_SECONDS", "60")),
            oci_config_file=os.getenv("OCI_CONFIG_FILE", "~/.oci/config"),
            oci_profile=os.getenv("OCI_PROFILE", "DEFAULT"),
            oci_region=os.getenv("OCI_REGION", ""),
            queries_file=queries_file,
            third_party_debug_logs=os.getenv("THIRD_PARTY_DEBUG_LOGS", "false").lower() == "true",
            queries=load_queries(queries_file),
        )


def load_queries(path: str) -> list[MetricQuery]:
    """Parse the YAML query file into :class:`MetricQuery` objects.

    Expected shape::

        queries:
          - compartment_id: ocid1.compartment.oc1..aaaa
            namespace: oci_computeagent
            metric_names: [CpuUtilization, MemoryUtilization]
            resource_group: null
            statistic: mean
            interval: 1m

    A missing file yields an empty list (the exporter starts, serves an empty
    ``/metrics``, and logs the gap) rather than crash-looping. Malformed
    contents fail fast.
    """
    expanded = os.path.expanduser(path)
    if not os.path.exists(expanded):
        return []
    with open(expanded, "r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}
    entries = raw.get("queries", [])
    if not isinstance(entries, list):
        raise ValueError("'queries' must be a list in the YAML config")
    queries = []
    for entry in entries:
        queries.append(
            MetricQuery(
                compartment_id=entry.get("compartment_id", ""),
                namespace=entry.get("namespace", ""),
                metric_names=entry.get("metric_names", []) or [],
                resource_group=entry.get("resource_group") or None,
                statistic=entry.get("statistic", "mean"),
                interval=entry.get("interval", "1m"),
            )
        )
    return queries
