"""Thin wrapper over the OCI Monitoring ``SummarizeMetricsData`` API.

The skeleton wires up the SDK client and the MQL statement builder; the actual
``summarize_metrics_data`` call + response flattening is the Step 2 deliverable
(see ``docs/projects/oci-monitoring-exporter.md``).
"""

import logging
import os
from dataclasses import dataclass, field

import oci

from .config import Config, MetricQuery

logger = logging.getLogger(__name__)


@dataclass
class Datapoint:
    """One metric datapoint flattened to a Prometheus-ready shape."""

    metric_name: str
    namespace: str
    value: float
    # OCI dimensions (resourceId, region, …) → Prometheus labels.
    dimensions: dict[str, str] = field(default_factory=dict)


def build_mql(metric_name: str, query: MetricQuery) -> str:
    """Build the OCI MQL statement for one metric of a query.

    ``CpuUtilization`` with ``interval=1m`` / ``statistic=mean`` and no
    resource group → ``CpuUtilization[1m].mean()``. With a resource group →
    ``CpuUtilization[1m]{resourceGroup = "web"}.mean()``.
    """
    selector = ""
    if query.resource_group:
        selector = f'{{resourceGroup = "{query.resource_group}"}}'
    return f"{metric_name}[{query.interval}]{selector}.{query.statistic}()"


class OCIMonitoringClient:
    """Wraps ``oci.monitoring.MonitoringClient`` for SummarizeMetricsData reads."""

    def __init__(self, cfg: Config, client=None):
        self._cfg = cfg
        if client is not None:
            # Injected for tests, or to swap in instance-principal auth later.
            self._client = client
            return
        oci_config = oci.config.from_file(
            file_location=os.path.expanduser(cfg.oci_config_file),
            profile_name=cfg.oci_profile,
        )
        if cfg.oci_region:
            oci_config["region"] = cfg.oci_region
        self._client = oci.monitoring.MonitoringClient(oci_config)

    def summarize(self, query: MetricQuery) -> list[Datapoint]:
        """Return the latest datapoint per resource/dimension set for a query.

        Step 2 deliverable: for each ``metric_name`` build the MQL via
        :func:`build_mql`, call ``self._client.summarize_metrics_data`` against
        ``query.compartment_id``, and flatten each returned ``MetricData``
        series' newest aggregated datapoint into a :class:`Datapoint` carrying
        ``resourceId``/``region`` (and any other OCI dimensions) as labels.

        Stubbed in the skeleton: returns an empty list and logs at debug so the
        exporter runs end-to-end (serves an empty ``/metrics``) before the OCI
        read path lands.
        """
        for metric_name in query.metric_names:
            logger.debug(
                "summarize stub — would query MQL %r in compartment %s",
                build_mql(metric_name, query),
                query.compartment_id,
            )
        return []
