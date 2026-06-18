"""Prometheus exposition side of the exporter.

A custom collector holds the latest datapoints pulled from OCI Monitoring and
yields them on each Prometheus scrape; :class:`Exporter` runs the poll cycle
that refreshes that collector and records the exporter's own OTLP metrics.
"""

import logging
import re
import time
from threading import Lock

from prometheus_client.core import GaugeMetricFamily
from prometheus_client.registry import Collector

from .config import Config
from .oci_client import OCIMonitoringClient, Datapoint
from .telemetry import Metrics

logger = logging.getLogger(__name__)

# Prometheus metric-name prefix for everything this exporter re-publishes.
METRIC_PREFIX = "oci_monitoring"

_CAMEL_BOUNDARY = re.compile(r"(?<!^)(?=[A-Z])")


def _to_snake(name: str) -> str:
    """CpuUtilization → cpu_utilization."""
    return _CAMEL_BOUNDARY.sub("_", name).lower()


def metric_name(namespace: str, metric: str) -> str:
    """Map an OCI ``(namespace, metric)`` to a Prometheus metric name.

    ``oci_computeagent`` / ``CpuUtilization`` → ``oci_monitoring_computeagent_cpu_utilization``.
    The redundant ``oci_`` namespace prefix is stripped before joining.
    """
    ns = namespace[4:] if namespace.startswith("oci_") else namespace
    return f"{METRIC_PREFIX}_{_to_snake(ns)}_{_to_snake(metric)}"


class OCIMetricsCollector(Collector):
    """Holds the latest OCI datapoints and yields them on each scrape.

    Thread-safe: :meth:`update` is called from the poll loop while
    :meth:`collect` is called from the HTTP server thread.
    """

    def __init__(self):
        self._lock = Lock()
        self._latest: list[Datapoint] = []

    def update(self, datapoints: list[Datapoint]) -> None:
        with self._lock:
            self._latest = list(datapoints)

    def collect(self):
        with self._lock:
            datapoints = list(self._latest)

        families: dict[str, GaugeMetricFamily] = {}
        for dp in datapoints:
            name = metric_name(dp.namespace, dp.metric_name)
            family = families.get(name)
            if family is None:
                family = GaugeMetricFamily(
                    name,
                    f"OCI Monitoring {dp.namespace}/{dp.metric_name}",
                    labels=sorted(dp.dimensions.keys()),
                )
                families[name] = family
            labels = [dp.dimensions[k] for k in sorted(dp.dimensions.keys())]
            family.add_metric(labels, dp.value)
        yield from families.values()


class Exporter:
    """Runs one poll cycle: query OCI for every configured query, refresh gauges."""

    def __init__(
        self,
        cfg: Config,
        oci_client: OCIMonitoringClient,
        collector: OCIMetricsCollector,
        app_metrics: Metrics | None = None,
    ):
        self._cfg = cfg
        self._oci = oci_client
        self._collector = collector
        self._metrics = app_metrics

    def poll(self) -> list[Datapoint]:
        """Query OCI for every configured query and refresh the collector."""
        collected: list[Datapoint] = []
        for query in self._cfg.queries:
            start = time.monotonic()
            outcome = "ok"
            try:
                collected.extend(self._oci.summarize(query))
            except Exception as e:
                outcome = "error"
                logger.error("poll failed for namespace %s: %s", query.namespace, e)
            finally:
                if self._metrics:
                    self._metrics.poll_total.add(1, {"namespace": query.namespace, "outcome": outcome})
                    self._metrics.poll_duration.record(
                        time.monotonic() - start, {"namespace": query.namespace}
                    )
        self._collector.update(collected)
        logger.info(
            "poll cycle complete: %d datapoint(s) from %d query(ies)",
            len(collected), len(self._cfg.queries),
        )
        return collected
