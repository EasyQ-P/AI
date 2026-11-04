"""7.4 API 목록(28개)이 경로 · 메서드 그대로 등록됐는지 확인한다."""

from app.main import app

EXPECTED = {
    ("GET", "/health"),                                    # 7.4.1
    ("POST", "/datasets"),                                 # 7.4.2
    ("GET", "/datasets"),                                  # 7.4.3
    ("GET", "/datasets/{dataset_version}"),                # 7.4.4
    ("POST", "/datasets/{dataset_version}/reviewed-labels"),  # 7.4.5
    ("POST", "/collection-jobs"),                          # 7.4.6
    ("POST", "/train-jobs"),                               # 7.4.7
    ("GET", "/train-jobs/{job_id}"),                       # 7.4.8
    ("DELETE", "/train-jobs/{job_id}"),                    # 7.4.9
    ("GET", "/train-configs/default"),                     # 7.4.10
    ("PUT", "/train-configs/default"),                     # 7.4.11
    ("POST", "/evaluations"),                              # 7.4.12
    ("GET", "/evaluations/{evaluation_id}"),               # 7.4.13
    ("POST", "/comparisons"),                              # 7.4.14
    ("POST", "/export-jobs"),                              # 7.4.15
    ("POST", "/models"),                                   # 7.4.16
    ("GET", "/models"),                                    # 7.4.17
    ("GET", "/models/{model_version}"),                    # 7.4.18
    ("PATCH", "/models/{model_version}"),                  # 7.4.19
    ("DELETE", "/models/{model_version}"),                 # 7.4.20
    ("GET", "/deployment"),                                # 7.4.21
    ("PUT", "/deployment"),                                # 7.4.22
    ("POST", "/rollbacks"),                                # 7.4.23
    ("GET", "/jobs"),                                      # 7.4.24
    ("GET", "/jobs/{job_id}"),                             # 7.4.25
    ("POST", "/judgments"),                                # 7.4.26
    ("GET", "/faults"),                                    # 7.4.27
    ("GET", "/eval-slide-chunks"),                         # 7.4.28
}


def test_all_7_4_routes_registered():
    # 포함된 라우터는 app.routes에 펼쳐지지 않을 수 있어 OpenAPI 스키마로 확인한다
    actual = {
        (method.upper(), path.removeprefix("/api/v1"))
        for path, ops in app.openapi()["paths"].items()
        for method in ops
    }
    assert actual == EXPECTED
