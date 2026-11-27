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

    @probe.get("/api/v1/jobs")
    async def jobs(page: int) -> dict:
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


def test_dataset_body_validation_is_601():
    r = probe_client.post("/api/v1/datasets", json={})
    assert r.status_code == 400
    body = r.json()
    assert body["result_code"] == 601
    assert set(body) == {"result_code", "result_msg", "data"}


def test_other_validation_is_603():
    # 데이터셋과 무관한 입력 오류를 601(→ DATASET_NOT_READY)로 돌려주면 백엔드 화면이 원인을 잘못 보여 준다
    r = probe_client.get("/api/v1/jobs", params={"page": "x"})
    assert r.status_code == 400
    assert r.json()["result_code"] == 603


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


def test_docs_only_in_dev_and_relative_data_root_is_repo_based():
    from app.core.config import REPO_ROOT

    assert Settings(trainer_env="dev").docs_enabled is True
    assert Settings(trainer_env="prod", trainer_api_key="real-key").docs_enabled is False
    # 작업 프로세스(cwd=trainer/)와 API가 같은 폴더를 보도록 상대 경로는 레포 루트 기준
    assert Settings(trainer_env="dev", data_root="data/local").data_root == (REPO_ROOT / "data" / "local").resolve()
    assert (REPO_ROOT / "trainer" / "app" / "core" / "config.py").is_file()
