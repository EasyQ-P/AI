import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel

from app.core.config import Settings, check_settings, get_settings
from app.core.errors import register_error_handlers
from app.main import app

KEY = {"X-API-Key": get_settings().trainer_api_key}


class _Body(BaseModel):
    epochs: int


def _probe_app() -> FastAPI:
    probe = FastAPI()
    register_error_handlers(probe)

    @probe.put("/api/v1/train-configs/default")
    async def param(body: _Body) -> dict:
        return {}

    @probe.post("/api/v1/datasets")
    async def dataset(body: _Body) -> dict:
        return {}

    @probe.get("/boom")
    async def boom() -> dict:
        raise ValueError("secret detail")

    return probe


probe_client = TestClient(_probe_app(), raise_server_exceptions=False)


def test_param_validation_is_603():
    r = probe_client.put("/api/v1/train-configs/default", json={"epochs": "many"})
    assert r.status_code == 400
    assert r.json()["result_code"] == 603


def test_other_validation_is_601():
    r = probe_client.post("/api/v1/datasets", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["result_code"] == 601
    assert set(body) == {"result_code", "result_msg", "data"}


def test_unexpected_error_is_600_without_detail():
    r = probe_client.get("/boom")
    assert r.status_code == 500
    assert r.json() == {"result_code": 600, "result_msg": "internal error", "data": None}


def test_unknown_route_is_common_format():
    r = TestClient(app).get("/api/v1/nope", headers=KEY)
    assert r.status_code == 404
    assert r.json()["result_code"] == 613


def test_stub_api_answers_600():
    r = TestClient(app).post("/api/v1/train-jobs", headers=KEY)
    assert r.status_code == 500
    assert r.json()["result_code"] == 600


@pytest.mark.parametrize("key", ["", "change-me"])
def test_prod_rejects_missing_or_placeholder_key(key):
    with pytest.raises(RuntimeError):
        check_settings(Settings(trainer_env="prod", trainer_api_key=key))


def test_prod_accepts_real_key_and_dev_allows_placeholder():
    check_settings(Settings(trainer_env="prod", trainer_api_key="real-key"))
    check_settings(Settings(trainer_env="dev", trainer_api_key="change-me"))
