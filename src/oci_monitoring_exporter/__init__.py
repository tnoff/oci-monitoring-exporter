"""OCI Monitoring → Prometheus exporter.

Polls OCI Monitoring's ``SummarizeMetricsData`` API on an interval and
re-exposes the latest datapoints in Prometheus exposition format on
``/metrics`` so the in-cluster Prometheus/Mimir stack can scrape OCI-resource
metrics (instance CPU/network, Object Storage usage, OKE node health, load
balancer 5xx rate, …) that otherwise live only inside OCI Monitoring.

Authenticated via a traditional OCI user + API key (see DEVELOPMENT.md);
instance principals are a later add. The exporter is *both* a producer of
Prometheus metrics (the point) and an OTLP consumer for its own internal
observability — see ``telemetry`` for the latter.

Invoked as ``python -m src.oci_monitoring_exporter``.
"""
