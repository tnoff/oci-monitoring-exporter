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

Run the exporter locally (needs a `~/.oci/config` profile, or `OCI_AUTH=resource_principal` with the variables below and a query file):

```bash
export QUERIES_FILE=$(pwd)/config.example.yaml   # edit the compartment OCIDs first
export METRICS_PORT=9090
python -m src.oci_monitoring_exporter
# then: curl localhost:9090/metrics  and  curl localhost:9090/healthz
```

## Authentication

Two modes, chosen with `OCI_AUTH` (instance principals are not supported):

- `api_key` (default): a traditional OCI user + API key. The SDK reads a
  standard `~/.oci/config` profile; in production the profile + PEM key are
  mounted into the Pod from a Kubernetes Secret. Production no longer uses this
  mode; it is for local runs.
  The reader user needs `read metrics` on the compartments it polls.
- `resource_principal`: `oci.auth.signers.get_resource_principals_signer()`,
  fed by a sidecar that writes a session token and private key to files. The
  signer is built once (lazily, retried each poll until the files exist) and
  reused. `OCI_CONFIG_FILE` / `OCI_PROFILE` are ignored; `OCI_REGION` is passed
  as the client region when set. The Deployment (not the code) sets the
  `OCI_RESOURCE_PRINCIPAL_*` variables below.

## Environment variables

| Variable                | Default                                       | Purpose                                                      |
|-------------------------|-----------------------------------------------|--------------------------------------------------------------|
| `QUERIES_FILE`          | `/etc/oci-monitoring-exporter/queries.yaml`   | Path to the YAML query config (mounted as a ConfigMap).      |
| `METRICS_ADDR`          | `0.0.0.0`                                      | Bind address for the HTTP server.                            |
| `METRICS_PORT`          | `9090`                                         | Port for `/metrics` + `/healthz`.                            |
| `POLL_INTERVAL_SECONDS` | `60`                                           | Seconds between OCI poll cycles (OCI aggregates to 1m min).  |
| `OCI_AUTH`              | `api_key`                                      | Auth mode: `api_key` or `resource_principal`; anything else fails startup. |
| `OCI_CONFIG_FILE`       | `~/.oci/config`                                | OCI SDK config file location (`api_key` mode only).          |
| `OCI_PROFILE`           | `DEFAULT`                                      | Profile within the OCI config file.                          |
| `OCI_REGION`            | _(unset → profile's region)_                   | Override the region for the Monitoring client.               |
| `OTLP_METRICS_ENABLED`  | `false`                                        | Emit the exporter's own OTLP metrics.                        |
| `OTLP_LOGS_ENABLED`     | `false`                                        | Ship Python logs to OTLP via the OTel `LoggingHandler`.      |
| `THIRD_PARTY_DEBUG_LOGS`| `false`                                        | Keep urllib3's per-request DEBUG lines (every OTLP/OCI HTTP call). Off by default so they don't drown the app's logs or echo back through OTLP. |

In `resource_principal` mode the OCI SDK itself reads these, set by the
Deployment (never by the code):

| Variable                             | Value                                  |
|--------------------------------------|----------------------------------------|
| `OCI_RESOURCE_PRINCIPAL_VERSION`     | `2.2`                                  |
| `OCI_RESOURCE_PRINCIPAL_RPST`        | Path to the session token file         |
| `OCI_RESOURCE_PRINCIPAL_PRIVATE_PEM` | Path to the private key PEM            |
| `OCI_RESOURCE_PRINCIPAL_REGION`      | OCI region                             |

The OTLP exporters are configured through the standard `OTEL_EXPORTER_OTLP_*`
environment variables (the Deployment sets `OTEL_EXPORTER_OTLP_ENDPOINT`,
`OTEL_SERVICE_NAME` and friends). `Config` also parses `OTLP_ENDPOINT` and
`OTLP_INSECURE`, but nothing reads them, so setting them has no effect.

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
  oci_client.py  OCI Monitoring SDK wrapper + MQL builder (`summarize()` reads the latest datapoint per series)
  exporter.py    Prometheus collector + poll cycle
  main.py        HTTP server (/metrics + /healthz), poll loop, signal handling
```
