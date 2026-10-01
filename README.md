# OCI Monitoring → Prometheus exporter

A small Python service that polls OCI Monitoring's
[`SummarizeMetricsData`](https://docs.oracle.com/en-us/iaas/api/#/en/monitoring/20180401/MetricData/SummarizeMetricsData)
API and re-exposes the latest datapoints in Prometheus exposition format on
`/metrics`, so the in-cluster Prometheus/Mimir stack can scrape OCI-resource
metrics (instance CPU/network, Object Storage usage, OKE node health, load
balancer 5xx rate, …) that otherwise live only inside OCI Monitoring.

Once the metrics are in Prometheus, alerts are re-authored in Grafana and
delivered through Grafana's existing Discord wiring — no ONS → Discord relay
needed for this class of alarm.

## How it works

```
                 poll every POLL_INTERVAL_SECONDS
   OCI Monitoring  ───────────────────────────────▶  exporter  ──▶  /metrics
   SummarizeMetricsData                               (gauges)        (scraped by
                                                                       Prometheus/Mimir)
```

- Reads a YAML config (mounted as a ConfigMap) describing
  `(compartment_ocid, namespace, metric_names, resource_group)` tuples.
- On each interval, queries OCI for every tuple and stores the latest
  datapoint per resource.
- A custom Prometheus collector re-publishes those datapoints as gauges,
  labelled with the OCI dimensions (`resource_id`, `region`, …).
- Exposes `/healthz` for liveness and `/metrics` for scraping.
- Emits its own OTLP logs + metrics to the LGTM stack (see below) — distinct
  from the Prometheus metrics it re-exposes.

## Metrics

Each OCI series becomes a gauge named
`oci_monitoring_<namespace>_<metric>`, with the leading `oci_` stripped from the
namespace and CamelCase converted to snake_case, taking the metric name OCI
returns. For example `oci_computeagent` / `CpuUtilization` is
`oci_monitoring_computeagent_cpu_utilization`, and `oci_oke` /
`KubernetesNodeCondition` is `oci_monitoring_oke_kubernetes_node_condition`.
Labels are the OCI dimension keys as returned (`resourceId`,
`resourceDisplayName`, `nodePoolId`, `nodeCondition`, …); where series of one
metric carry differing dimensions the label set is their union, with missing
values empty. Only the newest datapoint per series from a 15-minute lookback
window is exposed.

The exporter's own telemetry is sent over OTLP when `OTLP_METRICS_ENABLED` /
`OTLP_LOGS_ENABLED` are on: `oci_exporter_poll_total` (counter, labelled
`namespace` and `outcome` of `ok`/`error`) and `oci_exporter_poll_duration_seconds`
(histogram, per query), plus its logs.

## Endpoints

| Path       | Purpose                                  |
|------------|------------------------------------------|
| `/metrics` | Prometheus exposition of the OCI metrics |
| `/healthz` | Liveness probe (always `200 ok`)         |

## Authentication

Traditional OCI user + API key (a `~/.oci/config` profile + PEM key mounted into
the Pod), matching the `security-scanner-read-bot` pattern; the user needs
`read metrics` on the polled compartments. Instance principals are not
supported. See [DEVELOPMENT.md](DEVELOPMENT.md) for the environment-variable
reference.

## Configuration

Runtime knobs come from environment variables; the metric queries come from a
YAML file (see [`config.example.yaml`](config.example.yaml)). Both are
documented in [DEVELOPMENT.md](DEVELOPMENT.md).

## Deployment

Runs as a single-replica Deployment in the `monitoring` namespace of the OKE
cluster, defined in
[`docker-apps/monitoring/oci-monitoring-exporter/`](https://github.com/tnoff/docker-apps/tree/main/monitoring/oci-monitoring-exporter):

- Image `iad.ocir.io/tnoff/oci-monitoring-exporter`; a release dispatches to
  docker-apps' `bump-image-pin.yml`, which updates the pin.
- The OCI reader key comes from Secret `oci-monitoring-exporter-creds` (files
  `config` and `api_key.pem`, mounted at `/home/exporter/.oci/`; the Deployment
  restarts when it rotates).
- The query list is the ConfigMap `oci-monitoring-exporter-queries`, mounted at
  `/etc/oci-monitoring-exporter/queries.yaml`. Currently `oci_computeagent`
  (CPU, memory), `oci_oke` (node condition) and `oci_objectstorage` (stored
  bytes, object count).
- The monitoring OTel collector scrapes `:9090/metrics` every 60s (job
  `oci-monitoring-exporter`) and forwards to Mimir; a NetworkPolicy allows only
  the collector to reach that port. Grafana alert rules and the
  `oci-monitoring` dashboard in docker-apps are built on these series.

## Development

```bash
pip install -e '.[dev]'
tox                 # pytest + pylint + bandit across py3.13 / py3.14
python -m src.oci_monitoring_exporter
```
