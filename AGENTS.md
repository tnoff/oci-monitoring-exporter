# AGENTS.md

Orientation for AI agents and new contributors. See
[`docs/projects/oci-monitoring-exporter.md`](https://gitlab.com/tnoff-projects/docs/-/blob/main/projects/oci-monitoring-exporter.md)
for the full project plan and rollout steps.

## What this is

A thin (~200–300 LOC target) long-running service that polls OCI Monitoring's
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
- **No instance principals in v1.** Traditional OCI user + API key, mounted from
  a k8s Secret — mirrors `security-scanner-read-bot`.
- **Bespoke ≠ feature-rich.** Keep it small; resist caching / multi-tenancy /
  auto-discovery in v1.
- **Crib `oke-security-scanner`.** Test layout, OTLP wiring, Dockerfile, and CI
  shape are settled by that sibling — match it rather than reinventing.

## Tests

`tox` runs pytest + pylint + bandit across py3.13 / py3.14. pylint is expected
at 10/10, and CI enforces **100% diff coverage** (`diff-cover --fail-under=100`)
— every changed `src/` line must be tested or `# pragma: no cover`'d.
