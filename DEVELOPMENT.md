# Development

## Local setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e '.[dev]'
```

Run the full check suite (matches CI):

```bash
tox            # pytest + pylint + bandit across py3.13 / py3.14
tox -e pytest  # tests + HTML coverage only
tox -e pylint  # lint only
tox -e bandit  # security lint only
```

Run the exporter locally (needs a `~/.oci/config` profile and a query file):

```bash
export QUERIES_FILE=$(pwd)/config.example.yaml   # edit the compartment OCIDs first
export METRICS_PORT=9090
python -m src.oci_monitoring_exporter
# then: curl localhost:9090/metrics  and  curl localhost:9090/healthz
```

## Authentication

The exporter uses a traditional OCI user + API key (instance principals are a
later add). The SDK reads a standard `~/.oci/config` profile; in production the
profile + PEM key are mounted into the Pod from a Kubernetes Secret
(`oci-monitoring-exporter-creds`), the same shape as `security-scanner-read-bot`.
The reader user needs `read metrics` on the compartments it polls.

## Environment variables

| Variable                | Default                                       | Purpose                                                      |
|-------------------------|-----------------------------------------------|--------------------------------------------------------------|
| `QUERIES_FILE`          | `/etc/oci-monitoring-exporter/queries.yaml`   | Path to the YAML query config (mounted as a ConfigMap).      |
| `METRICS_ADDR`          | `0.0.0.0`                                      | Bind address for the HTTP server.                            |
| `METRICS_PORT`          | `9090`                                         | Port for `/metrics` + `/healthz`.                            |
| `POLL_INTERVAL_SECONDS` | `60`                                           | Seconds between OCI poll cycles (OCI aggregates to 1m min).  |
| `OCI_CONFIG_FILE`       | `~/.oci/config`                                | OCI SDK config file location.                                |
| `OCI_PROFILE`           | `DEFAULT`                                      | Profile within the OCI config file.                          |
| `OCI_REGION`            | _(unset → profile's region)_                   | Override the region for the Monitoring client.               |
| `OTLP_ENDPOINT`         | `http://localhost:4318`                        | OTLP HTTP endpoint for the exporter's own telemetry.         |
| `OTLP_INSECURE`         | `true`                                         | Whether the OTLP exporter skips TLS.                         |
| `OTLP_METRICS_ENABLED`  | `false`                                        | Emit the exporter's own OTLP metrics.                        |
| `OTLP_LOGS_ENABLED`     | `false`                                        | Ship Python logs to OTLP via the OTel `LoggingHandler`.      |

## Query config

See [`config.example.yaml`](config.example.yaml). Each entry is one
`(compartment, namespace, metric_names)` tuple with optional `resource_group`,
`statistic` (default `mean`), and `interval` (default `1m`). A missing file
starts the exporter with no queries (empty `/metrics`) rather than crash-looping.

## Layout

```
src/oci_monitoring_exporter/
  config.py      env vars + YAML query loader
  telemetry.py   OTLP setup for the exporter's own observability
  oci_client.py  OCI Monitoring SDK wrapper + MQL builder (summarize() is Step 2)
  exporter.py    Prometheus collector + poll cycle
  main.py        HTTP server (/metrics + /healthz), poll loop, signal handling
```
