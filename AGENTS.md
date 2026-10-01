# AGENTS.md

Orientation for AI agents and new contributors. User-facing behaviour,
metric naming and deployment are in [README.md](README.md); env vars, auth and
test commands are in [DEVELOPMENT.md](DEVELOPMENT.md).

## What this is

A thin long-running service that polls OCI Monitoring's
`SummarizeMetricsData` API and re-exposes the latest datapoints as Prometheus
gauges on `/metrics`. It is **both** a producer of Prometheus exposition metrics
(the point — scraped by the in-cluster Prometheus/Mimir) **and** an OTLP
consumer for its own internal observability. Don't conflate the two:
`exporter.py` handles the former, `telemetry.py` the latter.

## Module map

| Module          | Responsibility                                                              |
|-----------------|-----------------------------------------------------------------------------|
| `config.py`     | `Config.from_env()` (runtime knobs) + `load_queries()` (YAML ConfigMap).    |
| `telemetry.py`  | OTLP setup/teardown + the exporter's own metric instruments.                |
| `oci_client.py` | `OCIMonitoringClient` (SDK wrapper) + `build_mql()` + `summarize()`.|
| `exporter.py`   | `OCIMetricsCollector` (Prometheus collector) + `Exporter.poll()`.           |
| `main.py`       | HTTP server (`/metrics` + `/healthz`), poll loop, SIGTERM handling.         |

## Conventions

- **Config, not code.** The metric queries live in a YAML ConfigMap, never
  hardcoded in the readers. Coverage changes shouldn't require an image rebuild.
- **No instance principals.** Traditional OCI user + API key, mounted from
  a k8s Secret — mirrors `security-scanner-read-bot`.
- **Metric names are derived, not configured.** `exporter.metric_name()` builds
  them from the series OCI returns; renaming that function's output breaks the
  Grafana rules and dashboard in docker-apps that query these series.
- **Bespoke ≠ feature-rich.** Keep it small; resist caching / multi-tenancy /
  auto-discovery.
- **Crib `oke-security-scanner`.** Test layout, OTLP wiring, Dockerfile, and CI
  shape are settled by that sibling — match it rather than reinventing.

## Tests

`tox` runs pytest + pylint + bandit across py3.13 / py3.14. pylint is expected
at 10/10, and CI enforces **100% diff coverage** (`diff-cover --fail-under=100`)
— every changed `src/` line must be tested or `# pragma: no cover`'d.
