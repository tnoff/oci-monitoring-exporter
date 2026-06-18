"""Tests for the HTTP app, poll loop, and main wiring."""

import socket
import threading
import urllib.request

from prometheus_client import CollectorRegistry, Gauge

from src.oci_monitoring_exporter import main as main_mod


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _call(app, path):
    """Invoke a WSGI app for a GET on ``path``; return (status, body bytes)."""
    captured = {}

    def start_response(status, headers):
        captured["status"] = status

    body = b"".join(app({"PATH_INFO": path, "REQUEST_METHOD": "GET"}, start_response))
    return captured["status"], body


def test_healthz_returns_ok():
    app = main_mod.build_wsgi_app(CollectorRegistry())
    status, body = _call(app, "/healthz")
    assert status == "200 OK"
    assert body == b"ok\n"


def test_metrics_path_serves_exposition():
    registry = CollectorRegistry()
    Gauge("demo_metric", "demo", registry=registry).set(3)
    app = main_mod.build_wsgi_app(registry)
    status, body = _call(app, "/metrics")
    assert status.startswith("200")
    assert b"demo_metric 3.0" in body


def test_run_poll_loop_stops_on_event():
    stop = threading.Event()
    calls = {"n": 0}

    class _Exporter:
        def poll(self):
            calls["n"] += 1
            stop.set()  # stop after one cycle

    main_mod.run_poll_loop(_Exporter(), interval_seconds=0, stop=stop)
    assert calls["n"] == 1


def test_run_poll_loop_continues_through_error():
    stop = threading.Event()
    calls = {"n": 0}

    class _Exporter:
        def poll(self):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RuntimeError("transient")
            stop.set()

    main_mod.run_poll_loop(_Exporter(), interval_seconds=0, stop=stop)
    assert calls["n"] == 2


def test_serve_starts_and_serves(make_config):
    cfg = make_config(metrics_addr="127.0.0.1", metrics_port=_free_port())
    httpd = main_mod.serve(cfg, registry=CollectorRegistry())
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{cfg.metrics_port}/healthz", timeout=5) as r:
            assert r.status == 200
            assert r.read() == b"ok\n"
    finally:
        httpd.shutdown()
        httpd.server_close()


def _patch_main_deps(monkeypatch, cfg, oci_client_factory):
    monkeypatch.setattr(main_mod.Config, "from_env", staticmethod(lambda: cfg))
    monkeypatch.setattr(main_mod, "setup_telemetry", lambda c: (None, None))
    monkeypatch.setattr(main_mod, "create_metrics", lambda mp: None)
    monkeypatch.setattr(main_mod, "OCIMonitoringClient", oci_client_factory)


def test_main_success_path(monkeypatch, make_config):
    cfg = make_config(queries=[])

    class _FakeHTTPD:
        def __init__(self):
            self.shut = False

        def shutdown(self):
            self.shut = True

    fake = _FakeHTTPD()
    _patch_main_deps(monkeypatch, cfg, lambda c: object())
    monkeypatch.setattr(main_mod, "serve", lambda c: fake)
    monkeypatch.setattr(main_mod, "run_poll_loop", lambda exporter, interval, stop: None)

    assert main_mod.main() == 0
    assert fake.shut is True  # finally block ran


def test_main_returns_1_on_oci_client_error(monkeypatch, make_config):
    def _boom(_cfg):
        raise RuntimeError("no ~/.oci/config")

    _patch_main_deps(monkeypatch, make_config(queries=[]), _boom)
    assert main_mod.main() == 1


def test_main_returns_1_on_config_error(monkeypatch):
    def _raise():
        raise ValueError("bad config")

    monkeypatch.setattr(main_mod.Config, "from_env", staticmethod(_raise))
    assert main_mod.main() == 1
