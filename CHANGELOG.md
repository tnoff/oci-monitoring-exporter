# Changelog

All notable changes to the OCI Monitoring exporter will be documented in this
file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] - 2026-06-18

### Added

- Step 2 — the OCI read path. `OCIMonitoringClient.summarize` now calls
  `summarize_metrics_data` for each metric in a query (over a 15-minute
  window), keeps the newest aggregated datapoint per series, and flattens it
  into a `Datapoint` carrying the OCI dimensions (`resourceId`, `region`, …)
  as Prometheus labels. The exporter now serves live OCI metrics on
  `/metrics` instead of an empty registry.

### Changed

- `OCIMetricsCollector` now builds each gauge family from the *union* of its
  series' dimension keys (filling missing keys with `""`), so series of the
  same metric with differing OCI dimensions no longer break exposition.

## [0.1.0] - 2026-06-17

### Added

- Initial repo skeleton (Step 1b). Runs end-to-end and serves an empty
  `/metrics`; the OCI read path lands in Step 2.
  - `src/oci_monitoring_exporter/` package: `config` (env vars + YAML query
    loader), `telemetry` (OTLP logs + metrics for the exporter's own
    observability), `oci_client` (Monitoring SDK wrapper + MQL builder;
    `summarize()` stubbed), `exporter` (Prometheus collector + poll cycle),
    `main` (HTTP server for `/metrics` + `/healthz`, poll loop, signal
    handling).
  - Two-stage `Dockerfile` (`python:3.14-slim`, non-root `exporter` user,
    `build-essential` confined to the builder for `crc32c`).
  - `.gitlab-ci.yml` with the shared tag / docker-push / renovate / trufflehog
    / bump-version / trigger-bump / tox-pipeline templates.
  - `pyproject.toml` (`oci`, `prometheus-client`, `PyYAML`, `opentelemetry-*`)
    + `tox.ini` (py3.13 / py3.14) + `renovate.json`.
  - Test suite covering config loading/validation, telemetry setup, the MQL
    builder, the Prometheus collector, and the HTTP/poll-loop wiring.
  - `config.example.yaml`, `README.md`, `DEVELOPMENT.md`.
