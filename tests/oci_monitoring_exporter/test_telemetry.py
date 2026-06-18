"""Tests for OTLP telemetry setup."""

from src.oci_monitoring_exporter import telemetry


def test_setup_telemetry_disabled(make_config):
    cfg = make_config(otlp_metrics_enabled=False, otlp_logs_enabled=False)
    meter_provider, logger_provider = telemetry.setup_telemetry(cfg)
    assert meter_provider is None
    assert logger_provider is None


def test_setup_telemetry_enabled(make_config):
    cfg = make_config(otlp_metrics_enabled=True, otlp_logs_enabled=True)
    meter_provider, logger_provider = telemetry.setup_telemetry(cfg)
    try:
        assert meter_provider is not None
        assert logger_provider is not None
    finally:
        telemetry.shutdown_telemetry(meter_provider, logger_provider)


def test_create_metrics_none_without_provider():
    assert telemetry.create_metrics(None) is None


def test_create_metrics_builds_instruments(make_config):
    cfg = make_config(otlp_metrics_enabled=True)
    meter_provider, _ = telemetry.setup_telemetry(cfg)
    try:
        metrics = telemetry.create_metrics(meter_provider)
        assert metrics is not None
        assert metrics.poll_total is not None
        assert metrics.poll_duration is not None
    finally:
        telemetry.shutdown_telemetry(meter_provider, None)


def test_shutdown_telemetry_handles_none():
    # Should be a no-op, not raise.
    telemetry.shutdown_telemetry(None, None)
