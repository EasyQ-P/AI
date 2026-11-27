"""단계 3a: 학습서버 기본 조회 API."""

from datetime import datetime, timezone

import pytest

from app.api import health as health_api
from app.core.config import get_settings
from app.db.models import (
    RegDataset,
    RegDeployment,
    RegEvaluation,
    RegFault,
    RegJob,
    RegModel,
    RegTestSet,
)
from modules.inference import ServingState

KEY = {"X-API-Key": get_settings().trainer_api_key}
UTC = timezone.utc


def add_dataset(session, version: str, test_version: str, created_at: datetime) -> RegDataset:
    session.add(RegTestSet(test_set_version=test_version, test_use_count=int(version.rsplit("v", 1)[1])))
    session.flush()
    dataset = RegDataset(
        dataset_version=version,
        status="READY",
        contains_aihub=version == "ds-v2",
        statistics={"TRAIN": {"questions": 2, "pairs": 3}},
        courses_by_split={"TRAIN": ["6.006"], "VALIDATION": ["6.0001"], "TEST": ["6.172"]},
        gold_in_candidates_rate={"VALIDATION": 0.9, "TEST": 0.8},
        script_version="build-dataset@1.0.0",
        retrieval_config_version="rc-v1",
        validation_set_version=f"val-v{version[-1]}",
        test_set_version=test_version,
        eval_slide_version=f"es-v{version[-1]}",
        storage_uri=f"/data/easyq/datasets/{version}/",
        change_note=f"dataset {version}",
        created_at=created_at,
    )
    session.add(dataset)
    session.flush()
    return dataset


def test_empty_database_lists_and_health(api, monkeypatch):
    client, _ = api
    monkeypatch.setattr(health_api, "serving_state", lambda: ServingState(loaded=False))

    health = client.get("/api/v1/health", headers=KEY)
    assert health.status_code == 200
    assert health.json()["data"] == {
        "status": "ok",
        "mode": "LLM_ONLY",
        "serving_version": None,
        "threshold": None,
        "gpu_busy": False,
        "model_loaded": False,
    }
    assert client.get("/api/v1/datasets", headers=KEY).json()["data"] == {
        "datasets": [],
        "total_count": 0,
    }
    assert client.get("/api/v1/jobs", headers=KEY).json()["data"] == {"jobs": [], "total_count": 0}
    assert client.get("/api/v1/faults", headers=KEY).json()["data"] == {"faults": [], "total_count": 0}


def test_datasets_are_newest_first_paginated_and_detailed(api):
    client, factory = api
    with factory() as session:
        add_dataset(session, "ds-v1", "test-v1", datetime(2026, 11, 25, 1, 0, tzinfo=UTC))
        add_dataset(session, "ds-v2", "test-v2", datetime(2026, 11, 26, 9, 30, tzinfo=UTC))
        session.commit()

    response = client.get("/api/v1/datasets", params={"page": 1, "size": 1}, headers=KEY)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["total_count"] == 2
    assert [row["dataset_version"] for row in data["datasets"]] == ["ds-v2"]
    assert data["datasets"][0]["test_use_count"] == 2
    assert data["datasets"][0]["created_at"] == "2026-11-26T18:30:00+09:00"

    detail = client.get("/api/v1/datasets/ds-v2", headers=KEY).json()["data"]
    assert detail["dataset_version"] == "ds-v2"
    assert detail["courses_by_split"]["TEST"] == ["6.172"]
    assert detail["gold_in_candidates_rate"]["TEST"] == 0.8
    assert detail["test_use_count"] == 2
    assert detail["storage_uri"].endswith("/ds-v2/")


def test_dataset_and_job_missing_are_613(api):
    client, _ = api
    for path in ("/api/v1/datasets/ds-v99", "/api/v1/jobs/train-9999"):
        response = client.get(path, headers=KEY)
        assert response.status_code == 404
        assert response.json()["result_code"] == 613


def test_jobs_support_filters_pagination_detail_and_time_format(api):
    client, factory = api
    with factory() as session:
        session.add_all([
            RegJob(
                job_id="collect-0001",
                type="collect",
                status="SUCCEEDED",
                progress=1.0,
                result={"collected": 10},
                created_at=datetime(2026, 11, 24, 0, 0, tzinfo=UTC),
                finished_at=datetime(2026, 11, 24, 0, 5, tzinfo=UTC),
            ),
            RegJob(
                job_id="train-0001",
                type="train",
                status="RUNNING",
                stage="train",
                progress=0.4,
                created_at=datetime(2026, 11, 26, 3, 0, tzinfo=UTC),
            ),
            RegJob(
                job_id="train-0002",
                type="train",
                status="HELD",
                stage="register",
                hold_reason="below_target",
                progress=1.0,
                result={"registered": False},
                created_at=datetime(2026, 11, 26, 4, 0, tzinfo=UTC),
            ),
        ])
        session.commit()

    response = client.get(
        "/api/v1/jobs",
        params={"type": "train", "page": 1, "size": 1},
        headers=KEY,
    )
    data = response.json()["data"]
    assert data["total_count"] == 2
    assert [row["job_id"] for row in data["jobs"]] == ["train-0002"]
    assert data["jobs"][0]["created_at"] == "2026-11-26T13:00:00+09:00"
    assert data["jobs"][0]["finished_at"] is None

    running = client.get("/api/v1/jobs", params={"status": "RUNNING"}, headers=KEY).json()["data"]
    assert [row["job_id"] for row in running["jobs"]] == ["train-0001"]
    detail = client.get("/api/v1/jobs/train-0002", headers=KEY).json()["data"]
    assert detail == {
        "job_id": "train-0002",
        "type": "train",
        "status": "HELD",
        "progress": 1.0,
        "stage": "register",
        "hold_reason": "below_target",
        "result": {"registered": False},
        "fault_id": None,
    }


@pytest.mark.parametrize("params", [{"type": "deploy"}, {"status": "DONE"}])
def test_invalid_job_filter_is_601(api, params):
    client, _ = api
    response = client.get("/api/v1/jobs", params=params, headers=KEY)
    assert response.status_code == 400
    assert response.json()["result_code"] == 601


def test_fault_filters_pagination_and_time_format(api):
    client, factory = api
    with factory() as session:
        session.add_all([
            RegFault(
                fault_id="f-0001",
                occurred_at=datetime(2026, 11, 25, 1, 0, tzinfo=UTC),
                code=602,
                module="collect",
                job_id="collect-0001",
                message="collection failed",
            ),
            RegFault(
                fault_id="f-0002",
                occurred_at=datetime(2026, 11, 26, 14, 14, 5, tzinfo=UTC),
                code=604,
                module="export",
                job_id="export-0003",
                message="export failed",
            ),
            RegFault(
                fault_id="f-0003",
                occurred_at=datetime(2026, 11, 26, 15, 0, tzinfo=UTC),
                code=604,
                module="export",
                job_id="export-0004",
                message="another export failed",
            ),
        ])
        session.commit()

    response = client.get(
        "/api/v1/faults",
        params={
            "from": "2026-11-26T23:00:00+09:00",
            "to": "2026-11-26T23:59:00+09:00",
            "code": 604,
            "job_id": "export-0003",
        },
        headers=KEY,
    )
    data = response.json()["data"]
    assert data["total_count"] == 1
    assert data["faults"] == [{
        "fault_id": "f-0002",
        "occurred_at": "2026-11-26T23:14:05+09:00",
        "code": 604,
        "module": "export",
        "job_id": "export-0003",
        "message": "export failed",
    }]

    page = client.get("/api/v1/faults", params={"page": 2, "size": 1}, headers=KEY).json()["data"]
    assert page["total_count"] == 3
    assert [fault["fault_id"] for fault in page["faults"]] == ["f-0002"]


def test_health_uses_latest_deployment_loaded_state_and_gpu_job(api, monkeypatch):
    client, factory = api
    with factory() as session:
        dataset = add_dataset(session, "ds-v1", "test-v1", datetime(2026, 11, 25, 1, 0, tzinfo=UTC))
        session.add(
            RegEvaluation(
                evaluation_id="eval-0001",
                target={"export_job_id": "export-0001"},
                dataset_version=dataset.dataset_version,
                validation_set_version=dataset.validation_set_version,
                test_set_version=dataset.test_set_version,
                retrieval_config_version=dataset.retrieval_config_version,
                threshold=0.62,
            )
        )
        session.flush()
        session.add(
            RegModel(
                model_version="judge-v1",
                dataset_version="ds-v1",
                evaluation_id="eval-0001",
                artifact_uri="/data/easyq/models/judge-v1/",
                manifest={"format": "pytorch-fp16"},
                threshold=0.62,
                deployable=True,
            )
        )
        session.flush()
        session.add(RegDeployment(mode="LLM_ONLY", operation="SWITCH"))
        session.add(
            RegDeployment(mode="CUSTOM", serving_version="judge-v1", threshold=0.62, operation="SWITCH")
        )
        session.add(RegJob(job_id="eval-0002", type="eval", status="RUNNING"))
        session.commit()

    monkeypatch.setattr(health_api, "serving_state", lambda: ServingState(loaded=False))
    data = client.get("/api/v1/health", headers=KEY).json()["data"]
    assert data == {
        "status": "ok",
        "mode": "CUSTOM",
        "serving_version": "judge-v1",
        "threshold": 0.62,
        "gpu_busy": True,
        "model_loaded": False,
    }

    monkeypatch.setattr(health_api, "serving_state", lambda: ServingState(loaded=True))
    data = client.get("/api/v1/health", headers=KEY).json()["data"]
    assert (data["status"], data["model_loaded"]) == ("ok", True)


@pytest.mark.parametrize("path", [
    "/api/v1/datasets?page=0",
    "/api/v1/jobs?size=101",
    "/api/v1/faults?from=2026-11-26T10:00:00",
])
def test_invalid_list_query_is_601(api, path):
    client, _ = api
    response = client.get(path, headers=KEY)
    assert response.status_code == 400
    assert response.json()["result_code"] == 601
