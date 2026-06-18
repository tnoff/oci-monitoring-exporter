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

> **Status: serving live metrics (Step 2).** Config, telemetry, HTTP server,
> poll loop, Prometheus collector, and the `SummarizeMetricsData` read path are
> all in place — the exporter polls OCI and re-exposes the latest datapoints on
> `/metrics`. Remaining work is deployment (terraform reader bot + k8s Secret,
> docker-apps Deployment) and Grafana dashboards/alerts. See
> [`docs/projects/oci-monitoring-exporter.md`](https://gitlab.com/tnoff-projects/docs/-/blob/main/projects/oci-monitoring-exporter.md).

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
- Emits its own OTLP logs + metrics (poll counts, errors, OCI API latency) to
  the LGTM stack — distinct from the Prometheus metrics it re-exposes.

## Endpoints

| Path       | Purpose                                  |
|------------|------------------------------------------|
| `/metrics` | Prometheus exposition of the OCI metrics |
| `/healthz` | Liveness probe (always `200 ok`)         |

## Authentication

Traditional OCI user + API key (a `~/.oci/config` profile + PEM key mounted into
the Pod), matching the `security-scanner-read-bot` pattern. Instance principals
are a planned follow-up. See [DEVELOPMENT.md](DEVELOPMENT.md) for the full
environment-variable and auth reference.

## Configuration

Runtime knobs come from environment variables; the metric queries come from a
YAML file (see [`config.example.yaml`](config.example.yaml)). Both are
documented in [DEVELOPMENT.md](DEVELOPMENT.md).

## Development

```bash
pip install -e '.[dev]'
tox                 # pytest + pylint + bandit across py3.13 / py3.14
python -m src.oci_monitoring_exporter
```
