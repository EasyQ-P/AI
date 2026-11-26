from fastapi.testclient import TestClient

from app.core.config import get_settings
from app.main import app

client = TestClient(app)


def test_health_requires_api_key():
    r = client.get("/api/v1/health")
    assert r.status_code == 401
    assert r.json()["result_code"] == 612


def test_health_ok_with_key(api):
    client, _ = api
    r = client.get("/api/v1/health", headers={"X-API-Key": get_settings().trainer_api_key})
    assert r.status_code == 200
    body = r.json()
    assert body["result_code"] == 200
    assert body["data"]["mode"] in ("CUSTOM", "LLM_ONLY")
