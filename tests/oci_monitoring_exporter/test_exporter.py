"""Tests for the Prometheus exposition layer + poll cycle."""

from src.oci_monitoring_exporter.config import MetricQuery
from src.oci_monitoring_exporter.exporter import (
    Exporter,
    OCIMetricsCollector,
    metric_name,
)
from src.oci_monitoring_exporter.oci_client import Datapoint


def test_metric_name_strips_namespace_prefix_and_snakes():
    assert metric_name("oci_computeagent", "CpuUtilization") == \
        "oci_monitoring_computeagent_cpu_utilization"
    # Namespace without the oci_ prefix is left (just snaked).
    assert metric_name("custom", "HttpResponses5xx") == \
        "oci_monitoring_custom_http_responses5xx"


def test_collector_empty_yields_nothing():
    collector = OCIMetricsCollector()
    assert list(collector.collect()) == []


def test_collector_yields_gauge_per_metric():
    collector = OCIMetricsCollector()
    collector.update([
        Datapoint("CpuUtilization", "oci_computeagent", 42.0, {"resource_id": "vm-1", "region": "iad"}),
        Datapoint("CpuUtilization", "oci_computeagent", 7.0, {"resource_id": "vm-2", "region": "iad"}),
    ])
    families = list(collector.collect())
    assert len(families) == 1
    family = families[0]
    assert family.name == "oci_monitoring_computeagent_cpu_utilization"
    values = sorted(s.value for s in family.samples)
    assert values == [7.0, 42.0]
    # Labels come through sorted by dimension key.
    assert family.samples[0].labels == {"region": "iad", "resource_id": "vm-1"}


class _FakeOCI:
    def __init__(self, datapoints, raise_for=None):
        self._datapoints = datapoints
        self._raise_for = raise_for

    def summarize(self, query):
        if self._raise_for and query.namespace == self._raise_for:
            raise RuntimeError("boom")
        return [dp for dp in self._datapoints if dp.namespace == query.namespace]


def test_poll_refreshes_collector(make_config):
    dp = Datapoint("CpuUtilization", "oci_computeagent", 1.0, {"region": "iad"})
    cfg = make_config()
    collector = OCIMetricsCollector()
    exporter = Exporter(cfg, _FakeOCI([dp]), collector)

    collected = exporter.poll()

    assert collected == [dp]
    assert len(list(collector.collect())) == 1


def test_poll_survives_query_error(make_config, sample_query):
    cfg = make_config(queries=[sample_query])
    collector = OCIMetricsCollector()
    exporter = Exporter(cfg, _FakeOCI([], raise_for="oci_computeagent"), collector)

    # The bad query is swallowed; poll returns no datapoints rather than raising.
    assert exporter.poll() == []


class _RecordingMetrics:
    """Minimal stand-in for telemetry.Metrics capturing instrument calls."""

    def __init__(self):
        self.counted = []
        self.recorded = []
        self.poll_total = self
        self.poll_duration = self

    def add(self, value, attrs):
        self.counted.append((value, attrs))

    def record(self, value, attrs):
        self.recorded.append((value, attrs))


def test_poll_records_app_metrics_on_success(make_config, sample_query):
    cfg = make_config(queries=[sample_query])
    metrics = _RecordingMetrics()
    exporter = Exporter(cfg, _FakeOCI([]), OCIMetricsCollector(), app_metrics=metrics)

    exporter.poll()

    assert metrics.counted == [(1, {"namespace": "oci_computeagent", "outcome": "ok"})]
    assert len(metrics.recorded) == 1
    assert metrics.recorded[0][1] == {"namespace": "oci_computeagent"}


def test_poll_records_error_outcome(make_config, sample_query):
    cfg = make_config(queries=[sample_query])
    metrics = _RecordingMetrics()
    exporter = Exporter(
        cfg, _FakeOCI([], raise_for="oci_computeagent"), OCIMetricsCollector(), app_metrics=metrics
    )

    exporter.poll()

    assert metrics.counted == [(1, {"namespace": "oci_computeagent", "outcome": "error"})]
