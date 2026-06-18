"""Shared fixtures for the exporter test suite."""

import pytest

from src.oci_monitoring_exporter.config import Config, MetricQuery


@pytest.fixture
def sample_query():
    return MetricQuery(
        compartment_id="ocid1.compartment.oc1..aaaa",
        namespace="oci_computeagent",
        metric_names=["CpuUtilization", "MemoryUtilization"],
    )


@pytest.fixture
def make_config(sample_query):
    """Factory for a valid Config; pass overrides as kwargs."""

    def _make(**overrides):
        base = dict(
            otlp_endpoint="http://localhost:4318",
            otlp_insecure=True,
            otlp_metrics_enabled=False,
            otlp_logs_enabled=False,
            metrics_addr="127.0.0.1",
            metrics_port=9090,
            poll_interval_seconds=60,
            oci_config_file="~/.oci/config",
            oci_profile="DEFAULT",
            oci_region="us-ashburn-1",
            queries_file="/nonexistent/queries.yaml",
            queries=[sample_query],
        )
        base.update(overrides)
        return Config(**base)

    return _make
