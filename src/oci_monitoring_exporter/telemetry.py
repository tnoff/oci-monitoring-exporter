"""OpenTelemetry configuration for the exporter's own logs and metrics.

This is the exporter observing *itself* (poll counts, errors, OCI API
latency) and shipping to the LGTM stack via OTLP — distinct from the
Prometheus metrics it re-exposes on ``/metrics`` (see :mod:`.exporter`).
"""

import logging
from dataclasses import dataclass
from typing import Any, Optional

from opentelemetry import metrics
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
from opentelemetry.sdk.resources import get_aggregated_resources, OTELResourceDetector
from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk._logs import LoggerProvider
from opentelemetry._logs import set_logger_provider
from opentelemetry.instrumentation.logging.handler import LoggingHandler

from .config import Config


@dataclass
class Metrics:
    """The exporter's internal-observability instruments (not the OCI data)."""

    poll_total: Any  # Counter — poll cycles run, labelled by namespace + outcome
    poll_duration: Any  # Histogram — seconds per OCI SummarizeMetricsData call


def setup_telemetry(cfg: Config) -> tuple[Optional[MeterProvider], Optional[LoggerProvider]]:
    """Initialize OpenTelemetry with OTLP exporters based on configuration."""

    resource = get_aggregated_resources(detectors=[OTELResourceDetector()])

    meter_provider = None
    logger_provider = None

    # Metrics
    if cfg.otlp_metrics_enabled:
        metric_reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(),
        )
        meter_provider = MeterProvider(resource=resource, metric_readers=[metric_reader])
        metrics.set_meter_provider(meter_provider)
        logging.info("OTLP metrics enabled")
    else:
        logging.info("OTLP metrics disabled")

    # Logs
    if cfg.otlp_logs_enabled:
        logger_provider = LoggerProvider()
        set_logger_provider(logger_provider)
        log_exporter = OTLPLogExporter()
        logger_provider.add_log_record_processor(BatchLogRecordProcessor(log_exporter))
        handler = LoggingHandler(level=logging.NOTSET, logger_provider=logger_provider)
        logging.getLogger().addHandler(handler)
        logging.info("OTLP logs enabled")
    else:
        logging.info("OTLP logs disabled")

    return meter_provider, logger_provider


def create_metrics(meter_provider: Optional[MeterProvider]) -> Optional[Metrics]:
    """Create the exporter's internal-observability instruments.

    Returns ``None`` when ``meter_provider`` is ``None`` (OTLP metrics off).
    """
    if not meter_provider:
        return None

    meter = meter_provider.get_meter(__name__)
    return Metrics(
        poll_total=meter.create_counter(
            "oci_exporter_poll_total",
            description="OCI Monitoring poll cycles run, by namespace and outcome",
            unit="1",
        ),
        poll_duration=meter.create_histogram(
            "oci_exporter_poll_duration_seconds",
            description="Wall-clock seconds per OCI SummarizeMetricsData call",
            unit="s",
        ),
    )


def shutdown_telemetry(
    meter_provider: Optional[MeterProvider],
    logger_provider: Optional[LoggerProvider],
) -> None:
    """Flush and shut down the OTLP providers so nothing is lost on exit."""
    if meter_provider:
        logging.debug("Flushing metrics...")
        meter_provider.force_flush(timeout_millis=30000)
        meter_provider.shutdown()
    if logger_provider:
        logging.debug("Flushing logs...")
        logger_provider.force_flush(timeout_millis=30000)
        logger_provider.shutdown()
