def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok", "service": "test-service"}


def test_ready_ok_without_checks(client):
    assert client.get("/ready").status_code == 200


def test_ready_reports_failing_dependency(app, client):
    def broken():
        raise RuntimeError("db down")

    app.state.readiness_checks["database"] = broken
    r = client.get("/ready")
    assert r.status_code == 503
    assert r.json()["failures"]["database"] == "db down"


def test_metrics_exposed_and_ignore_operational_endpoints(client):
    client.get("/health")
    client.get("/ready")
    r = client.get("/metrics")
    assert r.status_code == 200
    assert "http_requests_total" in r.text
    for noisy in ("/health", "/ready", "/metrics"):
        assert f'handler="{noisy}"' not in r.text  # probes would drown out real traffic


def test_request_id_header_is_returned(client):
    r = client.get("/health", headers={"X-Request-ID": "abc123"})
    assert r.headers["X-Request-ID"] == "abc123"
    assert client.get("/health").headers["X-Request-ID"]
