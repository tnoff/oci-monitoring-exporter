"""Tests for the OCI Monitoring client wrapper."""

import datetime
from types import SimpleNamespace

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


def _dp(value, minute):
    return SimpleNamespace(
        value=value,
        timestamp=datetime.datetime(2026, 6, 18, 0, minute, tzinfo=datetime.timezone.utc),
    )


class _FakeMonitoringClient:
    """Returns one queued response per summarize_metrics_data call; records queries."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.calls = []

    def summarize_metrics_data(self, compartment_id, summarize_metrics_data_details):
        d = summarize_metrics_data_details
        self.calls.append(SimpleNamespace(compartment_id=compartment_id, query=d.query, namespace=d.namespace))
        data = self._responses.pop(0) if self._responses else []
        return SimpleNamespace(data=data)


def test_summarize_flattens_newest_datapoint(make_config):
    series = [
        SimpleNamespace(
            name="CpuUtilization", namespace="oci_computeagent",
            dimensions={"resourceId": "vm-1", "region": "sjc"},
            aggregated_datapoints=[_dp(10.0, 1), _dp(42.0, 5), _dp(20.0, 3)],
        ),
        SimpleNamespace(
            name="CpuUtilization", namespace="oci_computeagent",
            dimensions={"resourceId": "vm-2", "region": "sjc"},
            aggregated_datapoints=[_dp(7.0, 2)],
        ),
    ]
    fake = _FakeMonitoringClient([series])
    client = OCIMonitoringClient(make_config(), client=fake)
    q = MetricQuery(compartment_id="ocid.c", namespace="oci_computeagent", metric_names=["CPUUtilization"])

    out = client.summarize(q)

    assert {dp.dimensions["resourceId"]: dp.value for dp in out} == {"vm-1": 42.0, "vm-2": 7.0}
    assert out[0].metric_name == "CpuUtilization"  # OCI's returned name, not the queried casing
    assert fake.calls[0].compartment_id == "ocid.c"
    assert fake.calls[0].query == "CPUUtilization[1m].mean()"


def test_summarize_iterates_metrics_and_skips_empty_series(make_config):
    s_cpu = [SimpleNamespace(
        name="CpuUtilization", namespace="oci_computeagent",
        dimensions={"resourceId": "vm-1"}, aggregated_datapoints=[_dp(5.0, 1)],
    )]
    s_mem = [
        SimpleNamespace(
            name="MemoryUtilization", namespace="oci_computeagent",
            dimensions={"resourceId": "vm-1"}, aggregated_datapoints=[],  # no data -> skipped
        ),
        SimpleNamespace(
            name="MemoryUtilization", namespace="oci_computeagent",
            dimensions={"resourceId": "vm-2"}, aggregated_datapoints=[_dp(50.0, 2)],
        ),
    ]
    fake = _FakeMonitoringClient([s_cpu, s_mem])
    client = OCIMonitoringClient(make_config(), client=fake)
    q = MetricQuery(
        compartment_id="ocid.c", namespace="oci_computeagent",
        metric_names=["CPUUtilization", "MemoryUtilization"],
    )

    out = client.summarize(q)

    assert [c.query for c in fake.calls] == ["CPUUtilization[1m].mean()", "MemoryUtilization[1m].mean()"]
    assert {dp.value for dp in out} == {5.0, 50.0}  # empty memory series dropped


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
