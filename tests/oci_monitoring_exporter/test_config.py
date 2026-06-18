"""Tests for config loading + validation."""

import textwrap

import pytest

from src.oci_monitoring_exporter.config import Config, MetricQuery, load_queries


def test_from_env_defaults(monkeypatch):
    for var in (
        "OTLP_ENDPOINT", "OTLP_METRICS_ENABLED", "OTLP_LOGS_ENABLED", "METRICS_PORT",
        "METRICS_ADDR", "POLL_INTERVAL_SECONDS", "OCI_CONFIG_FILE", "OCI_PROFILE",
        "OCI_REGION", "QUERIES_FILE",
    ):
        monkeypatch.delenv(var, raising=False)

    cfg = Config.from_env()

    assert cfg.metrics_port == 9090
    assert cfg.metrics_addr == "0.0.0.0"
    assert cfg.poll_interval_seconds == 60
    assert cfg.otlp_endpoint == "http://localhost:4318"
    assert cfg.otlp_metrics_enabled is False
    assert cfg.oci_profile == "DEFAULT"
    # Default queries file doesn't exist in the test env → empty list, no crash.
    assert cfg.queries == []


def test_from_env_overrides(monkeypatch):
    monkeypatch.setenv("METRICS_PORT", "8000")
    monkeypatch.setenv("POLL_INTERVAL_SECONDS", "30")
    monkeypatch.setenv("OTLP_METRICS_ENABLED", "TRUE")
    monkeypatch.setenv("OCI_REGION", "us-phoenix-1")
    monkeypatch.setenv("QUERIES_FILE", "/nope.yaml")

    cfg = Config.from_env()

    assert cfg.metrics_port == 8000
    assert cfg.poll_interval_seconds == 30
    assert cfg.otlp_metrics_enabled is True
    assert cfg.oci_region == "us-phoenix-1"


@pytest.mark.parametrize("port", [0, 70000])
def test_invalid_port_rejected(make_config, port):
    with pytest.raises(ValueError, match="METRICS_PORT"):
        make_config(metrics_port=port)


def test_nonpositive_interval_rejected(make_config):
    with pytest.raises(ValueError, match="POLL_INTERVAL_SECONDS"):
        make_config(poll_interval_seconds=0)


def test_metric_query_validation():
    with pytest.raises(ValueError, match="compartment_id"):
        MetricQuery(compartment_id="", namespace="oci_oke", metric_names=["X"])
    with pytest.raises(ValueError, match="namespace"):
        MetricQuery(compartment_id="ocid", namespace="", metric_names=["X"])
    with pytest.raises(ValueError, match="metric_names"):
        MetricQuery(compartment_id="ocid", namespace="oci_oke", metric_names=[])


def test_load_queries_missing_file_returns_empty(tmp_path):
    assert load_queries(str(tmp_path / "absent.yaml")) == []


def test_load_queries_parses_yaml(tmp_path):
    f = tmp_path / "queries.yaml"
    f.write_text(textwrap.dedent("""
        queries:
          - compartment_id: ocid1.compartment.oc1..aaaa
            namespace: oci_computeagent
            metric_names: [CpuUtilization]
          - compartment_id: ocid1.compartment.oc1..bbbb
            namespace: oci_lbaas
            metric_names: [HttpResponses5xx]
            resource_group: web
            statistic: sum
            interval: 5m
    """))

    queries = load_queries(str(f))

    assert len(queries) == 2
    assert queries[0].namespace == "oci_computeagent"
    assert queries[0].resource_group is None
    assert queries[1].resource_group == "web"
    assert queries[1].statistic == "sum"
    assert queries[1].interval == "5m"


def test_load_queries_rejects_non_list(tmp_path):
    f = tmp_path / "queries.yaml"
    f.write_text("queries: not-a-list\n")
    with pytest.raises(ValueError, match="must be a list"):
        load_queries(str(f))


def test_load_queries_empty_file(tmp_path):
    f = tmp_path / "queries.yaml"
    f.write_text("")
    assert load_queries(str(f)) == []
