import pytest
from fastapi.testclient import TestClient

from tokenledger.api import create_app

KEY = "test-key-" + "a" * 32


def test_production_fails_closed_without_auth(tmp_path):
    with pytest.raises(ValueError, match="at least 32"):
        create_app(tmp_path, "production", "")
    with pytest.raises(ValueError, match="forbidden"):
        create_app(tmp_path, "production", KEY, bootstrap_demo=True)


def test_auth_protects_reads_writes_and_metrics(tmp_path, event):
    with TestClient(create_app(tmp_path, "production", KEY)) as client:
        assert client.get("/healthz").status_code == 200
        assert client.get("/readyz").status_code == 200
        for path in ("/api/v1/report", "/metrics"):
            assert client.get(path).status_code == 401
        assert client.post("/api/v1/events", json={"events": [event]}).status_code == 401
        headers = {"Authorization": f"Bearer {KEY}"}
        response = client.post("/api/v1/events", json={"events": [event]}, headers=headers)
        assert response.json()["accepted"] == 1
        report = client.get("/api/v1/report", headers=headers)
        assert report.json()["overview"]["requests"] == 1
        assert "X-Request-ID" in report.headers
        assert "frame-ancestors 'none'" in report.headers["Content-Security-Policy"]
        assert client.get("/docs").status_code == 404
        assert "tokenledger_events 1" in client.get("/metrics", headers=headers).text


def test_demo_http_ingestion_is_disabled_without_token(tmp_path, event):
    with TestClient(create_app(tmp_path, "demo", "")) as client:
        assert client.get("/api/v1/report").status_code == 200
        assert client.post("/api/v1/events", json={"events": [event]}).status_code == 403
        assert "Every token tells a story." in client.get("/").text
        assert client.get("/static/app.js").status_code == 200


def test_body_limit_applies_to_chunked_and_sized_requests(tmp_path):
    with TestClient(create_app(tmp_path, "demo", "")) as client:
        assert client.post("/api/v1/events", content=b"x" * 2_000_001).status_code == 413
        assert (
            client.post("/api/v1/events", content=iter([b"x" * 1_100_000] * 2)).status_code == 413
        )


def test_cache_invalidates_after_rejection_and_acceptance(tmp_path, event):
    with TestClient(create_app(tmp_path, "demo", KEY)) as client:
        headers = {"Authorization": f"Bearer {KEY}"}
        first = client.get("/api/v1/report", headers=headers).json()
        client.post("/api/v1/events", json={"events": [event]}, headers=headers)
        second = client.get("/api/v1/report", headers=headers).json()
        assert first["dataset_fingerprint"] != second["dataset_fingerprint"]
        client.post(
            "/api/v1/events", json={"events": [event | {"prompt": "reject"}]}, headers=headers
        )
        third = client.get("/api/v1/report", headers=headers).json()
        assert third["overview"]["quality"]["rejected"] == 1
        assert second["dataset_fingerprint"] == third["dataset_fingerprint"]


def test_assistant_cites_evidence_and_does_not_execute_sql(tmp_path, event):
    with TestClient(create_app(tmp_path, "demo", KEY)) as client:
        headers = {"Authorization": f"Bearer {KEY}"}
        client.post("/api/v1/events", json={"events": [event]}, headers=headers)
        answer = client.post(
            "/api/v1/explain", json={"question": "Which team spends most?"}, headers=headers
        ).json()
        assert answer["mode"] == "evidence_router"
        assert answer["evidence"][0]["id"] in answer["answer"]
        unsupported = client.post(
            "/api/v1/explain", json={"question": "DROP TABLE usage_events"}, headers=headers
        ).json()
        assert unsupported["status"] == "unsupported"
        assert client.get("/api/v1/report", headers=headers).json()["overview"]["requests"] == 1
