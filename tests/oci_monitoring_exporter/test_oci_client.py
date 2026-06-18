"""Tests for the OCI Monitoring client wrapper."""

from src.oci_monitoring_exporter import oci_client as oci_client_mod
from src.oci_monitoring_exporter.config import MetricQuery
from src.oci_monitoring_exporter.oci_client import (
    Datapoint,
    OCIMonitoringClient,
    build_mql,
)


def test_build_mql_basic():
    q = MetricQuery(compartment_id="c", namespace="oci_computeagent", metric_names=["X"])
    assert build_mql("CpuUtilization", q) == "CpuUtilization[1m].mean()"


def test_build_mql_with_resource_group_and_stat():
    q = MetricQuery(
        compartment_id="c", namespace="oci_lbaas", metric_names=["X"],
        resource_group="web", statistic="sum", interval="5m",
    )
    assert build_mql("HttpResponses5xx", q) == 'HttpResponses5xx[5m]{resourceGroup = "web"}.sum()'


def test_summarize_stub_returns_empty(make_config):
    cfg = make_config()
    client = OCIMonitoringClient(cfg, client=object())  # injected — no real SDK
    q = MetricQuery(compartment_id="c", namespace="oci_oke", metric_names=["A", "B"])
    assert client.summarize(q) == []


def test_datapoint_defaults():
    dp = Datapoint(metric_name="CpuUtilization", namespace="oci_computeagent", value=1.5)
    assert dp.dimensions == {}


def test_init_builds_real_client_from_config(make_config, monkeypatch):
    """The non-injected path reads ~/.oci/config and constructs the SDK client."""
    captured = {}

    def fake_from_file(file_location, profile_name):
        captured["file_location"] = file_location
        captured["profile_name"] = profile_name
        return {"region": "placeholder"}

    def fake_monitoring_client(oci_config):
        captured["oci_config"] = oci_config
        return "SDK_CLIENT"

    monkeypatch.setattr(oci_client_mod.oci.config, "from_file", fake_from_file)
    monkeypatch.setattr(oci_client_mod.oci.monitoring, "MonitoringClient", fake_monitoring_client)

    cfg = make_config(oci_config_file="~/.oci/config", oci_profile="san-jose", oci_region="us-sanjose-1")
    client = OCIMonitoringClient(cfg)

    assert client._client == "SDK_CLIENT"
    assert captured["profile_name"] == "san-jose"
    # Region override from config is applied over the profile's region.
    assert captured["oci_config"]["region"] == "us-sanjose-1"
    # ~ is expanded before handing the path to the SDK.
    assert "~" not in captured["file_location"]
