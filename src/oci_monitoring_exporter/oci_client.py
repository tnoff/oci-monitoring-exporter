"""Thin wrapper over the OCI Monitoring ``SummarizeMetricsData`` API."""

import datetime
import logging
import os
from dataclasses import dataclass, field

import oci
from oci.monitoring.models import SummarizeMetricsDataDetails

from .config import AUTH_RESOURCE_PRINCIPAL, Config, MetricQuery

logger = logging.getLogger(__name__)

# How far back to ask OCI for datapoints. OCI Monitoring aggregates to a
# 1-minute minimum and a query window must be wider than the metric interval,
# so a few minutes covers a [1m]/[5m] window with margin; we keep only the
# newest datapoint per series regardless.
_LOOKBACK_MINUTES = 15


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
        self._client = client
        if client is not None:
            # Injected for tests.
            return
        if cfg.oci_auth == AUTH_RESOURCE_PRINCIPAL:
            logger.info("OCI auth mode: resource_principal (sidecar-provided session token)")
            # The sidecar may not have written its token/key files yet (or may
            # be retrying after an IAM change), so a failure here is not fatal:
            # the signer is built lazily and retried on every poll until it works.
            try:
                self._client = self._build_resource_principal_client()
            except Exception as e:
                self._warn_not_ready(e)
            return
        logger.info("OCI auth mode: api_key (config file %s, profile %s)", cfg.oci_config_file, cfg.oci_profile)
        oci_config = oci.config.from_file(
            file_location=os.path.expanduser(cfg.oci_config_file),
            profile_name=cfg.oci_profile,
        )
        if cfg.oci_region:
            oci_config["region"] = cfg.oci_region
        self._client = oci.monitoring.MonitoringClient(oci_config)

    def _build_resource_principal_client(self):
        """Build the signer + client once; the SDK re-reads the token file itself."""
        signer = oci.auth.signers.get_resource_principals_signer()
        config = {"region": self._cfg.oci_region} if self._cfg.oci_region else {}
        return oci.monitoring.MonitoringClient(config=config, signer=signer)

    @staticmethod
    def _warn_not_ready(exc: Exception) -> None:
        # Only the exception text is logged, never token or key contents.
        logger.warning(
            "Resource principal signer not ready (%s: %s); will retry on the next poll",
            type(exc).__name__, exc,
        )

    def _get_client(self):
        """Return the cached client, building the resource principal one if needed."""
        if self._client is None:
            try:
                self._client = self._build_resource_principal_client()
            except Exception as e:
                self._warn_not_ready(e)
                raise
        return self._client

    def summarize(self, query: MetricQuery) -> list[Datapoint]:
        """Return the latest datapoint per resource/dimension set for a query.

        For each ``metric_name`` builds the MQL via :func:`build_mql`, calls
        ``summarize_metrics_data`` for ``query.compartment_id``, and flattens
        each returned series' newest aggregated datapoint into a
        :class:`Datapoint` carrying the OCI dimensions (``resourceId``,
        ``region``, …) as labels.
        """
        end = datetime.datetime.now(datetime.timezone.utc)
        start = end - datetime.timedelta(minutes=_LOOKBACK_MINUTES)
        results: list[Datapoint] = []
        for metric_name in query.metric_names:
            mql = build_mql(metric_name, query)
            details = SummarizeMetricsDataDetails(
                namespace=query.namespace,
                query=mql,
                start_time=start,
                end_time=end,
                resource_group=query.resource_group or None,
            )
            resp = self._get_client().summarize_metrics_data(
                compartment_id=query.compartment_id,
                summarize_metrics_data_details=details,
            )
            for series in resp.data:
                if not series.aggregated_datapoints:
                    continue
                latest = max(series.aggregated_datapoints, key=lambda dp: dp.timestamp)
                results.append(
                    Datapoint(
                        metric_name=series.name,
                        namespace=series.namespace,
                        value=float(latest.value),
                        dimensions=dict(series.dimensions or {}),
                    )
                )
            logger.debug("summarize %s -> %d series", mql, len(resp.data))
        return results
