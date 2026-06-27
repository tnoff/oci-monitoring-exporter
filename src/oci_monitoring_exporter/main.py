"""Main entry point for the OCI Monitoring exporter.

Starts an HTTP server exposing ``/metrics`` (Prometheus exposition) and
``/healthz`` (liveness), then polls OCI Monitoring on a fixed interval,
refreshing the gauges between scrapes. Long-running — exits cleanly on
SIGTERM/SIGINT, flushing OTLP telemetry on the way out.
"""

import logging
import signal
import sys
import threading
from socketserver import ThreadingMixIn
from wsgiref.simple_server import make_server, WSGIServer

from prometheus_client import REGISTRY, make_wsgi_app

from .config import Config
from .exporter import Exporter, OCIMetricsCollector
from .oci_client import OCIMonitoringClient
from .telemetry import setup_telemetry, create_metrics, shutdown_telemetry

logger = logging.getLogger(__name__)

# Third-party loggers that are pure noise once the app runs at root DEBUG.
# urllib3 logs a line for *every* HTTP request — including each OTLP export POST
# to the collector (`"POST /v1/logs HTTP/1.1" 200`), which the OTLP LoggingHandler
# then ships straight back out, amplifying the spam. The OCI SDK's own request
# traffic rides the same logger. We keep the exporter's logs at DEBUG; quiet these.
_NOISY_LOGGERS = ("urllib3",)


def quiet_noisy_loggers(level=logging.WARNING):
    """Raise chatty third-party loggers above DEBUG so their per-request output
    doesn't drown the exporter's own logs (or echo back through OTLP)."""
    for name in _NOISY_LOGGERS:
        logging.getLogger(name).setLevel(level)


class _ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
    """Serve scrapes concurrently so a slow client can't block /healthz."""

    daemon_threads = True


def build_wsgi_app(registry=REGISTRY):
    """WSGI app: ``/healthz`` → 200, everything else → Prometheus metrics."""
    metrics_app = make_wsgi_app(registry)

    def app(environ, start_response):
        if environ.get("PATH_INFO") == "/healthz":
            start_response("200 OK", [("Content-Type", "text/plain")])
            return [b"ok\n"]
        return metrics_app(environ, start_response)

    return app


def serve(cfg: Config, registry=REGISTRY):
    """Start the metrics/health HTTP server in a daemon thread; return the server."""
    httpd = make_server(
        cfg.metrics_addr, cfg.metrics_port, build_wsgi_app(registry),
        server_class=_ThreadingWSGIServer,
    )
    thread = threading.Thread(target=httpd.serve_forever, name="metrics-http", daemon=True)
    thread.start()
    logger.info("Serving /metrics + /healthz on %s:%d", cfg.metrics_addr, cfg.metrics_port)
    return httpd


def run_poll_loop(exporter: Exporter, interval_seconds: int, stop: threading.Event) -> None:
    """Poll until ``stop`` is set, waiting ``interval_seconds`` between cycles."""
    while not stop.is_set():
        try:
            exporter.poll()
        except Exception as e:  # a single bad cycle must not kill the loop
            logger.error("poll cycle raised: %s", e)
        stop.wait(interval_seconds)


def main() -> int:
    """Run the exporter."""
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )
    logger.info("Initializing OCI Monitoring exporter")

    try:
        cfg = Config.from_env()
    except ValueError as e:
        logger.error("Configuration error: %s", e)
        return 1

    if not cfg.third_party_debug_logs:
        quiet_noisy_loggers()

    meter_provider, logger_provider = setup_telemetry(cfg)
    app_metrics = create_metrics(meter_provider)

    collector = OCIMetricsCollector()
    REGISTRY.register(collector)

    try:
        oci_client = OCIMonitoringClient(cfg)
    except Exception as e:
        logger.error("Failed to initialize OCI client: %s", e)
        shutdown_telemetry(meter_provider, logger_provider)
        return 1

    exporter = Exporter(cfg, oci_client, collector, app_metrics)

    stop = threading.Event()

    def _handle_signal(signum, _frame):  # pragma: no cover - invoked by the OS on SIGTERM/SIGINT
        logger.info("Received signal %s — shutting down", signum)
        stop.set()

    signal.signal(signal.SIGTERM, _handle_signal)
    signal.signal(signal.SIGINT, _handle_signal)

    httpd = serve(cfg)
    logger.info("Polling %d query(ies) every %ds", len(cfg.queries), cfg.poll_interval_seconds)

    try:
        run_poll_loop(exporter, cfg.poll_interval_seconds, stop)
    finally:
        logger.info("Stopping HTTP server and flushing telemetry...")
        httpd.shutdown()
        shutdown_telemetry(meter_provider, logger_provider)
        logger.info("Shutdown complete")
    return 0
