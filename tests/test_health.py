from fastapi.testclient import TestClient

from app.main import app


def test_health_ok() -> None:
    client = TestClient(app)
    resp = client.get("/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["provider"] in {"mock", "openai"}
    # the request-logging middleware tags every response with a request id
    assert resp.headers.get("X-Request-ID")
