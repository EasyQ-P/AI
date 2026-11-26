# 작업 진행 기록

> Claude Code · Codex 공통. 작업을 시작할 때 먼저 읽고, 단계를 끝낼 때마다 갱신한다(AGENTS.md "에이전트 작업 규칙").
> 체크: `[ ]` 할 일 · `[~]` 진행 중 · `[x]` 끝. 담당 표에 없는 파일은 고치기 전에 "질문"에 적는다.

## 지금 작업: 학습서버 본체(trainer) — 목표 12/1(화), 점검 v0.3 12/2

설계서와 달라지는 점은 `docs/work/design-changes.md`에 모은다(팀 공유용).

### 정해진 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| Python | trainer · retrieval은 3.9 문법(`Optional[X]`, `list[...]` OK, `X \| None` · `zip(strict=)` · `match` 금지) | 학과 서버 3.9 (PR #4) |
| 레지스트리 DB | **SQLite 파일**(학과 서버, DB 서버 미사용). SQLAlchemy · Alembic, PostgreSQL 전용 기능 금지 → `REGISTRY_DB_URL`만 바꾸면 RDS로 이전 가능. DB에 쓰는 건 API 프로세스만(작업은 진행 상황을 파일로) | 학과 서버 규칙 "웹/DB는 AWS" (2026-11-26 결정, 팀 합의 대기) |
| 학습서버 API | 학과 서버 `127.0.0.1:8000`, SSH 터널 전용, 상시 실행(GPU 미사용) | 설계 7.4 그대로 |
| 판정 추론 | `127.0.0.1:8001`, **강연 중에만 GPU에 적재**, 없으면 서비스가 LLM_ONLY | GPU 독점 금지 (제안, 팀 합의 대기) |
| GPU | 0번만(`CUDA_VISIBLE_DEVICES=0`), GPU 작업은 한 번에 하나(609) | 서버 가이드 · 설계 |

### 담당
| 파일 | 담당 |
|---|---|
| `trainer/app/db/*` · `trainer/migrations/*` · `trainer/app/jobs/*` | Claude |
| `trainer/app/api/health.py` · `datasets.py` · `jobs.py` · `faults.py`, `trainer/app/core/timefmt.py`(새로), `trainer/modules/dataset/*`, 해당 테스트 | Codex (아래 "단계 3 작업 설명") |
| `docs/work/PROGRESS.md` | 둘 다 (자기 칸만) |

### 단계
- [x] 1. 레지스트리 DB: `reg_` 테이블 10개(8.2.38) 모델 · 첫 마이그레이션 · SQLite 테스트 (Claude, 브랜치 `feature/registry-db`)
  - `trainer/app/db/models.py`(JSON은 PG에서만 JSONB, 상태는 CHECK, 시각은 UTC aware), 마이그레이션 `20261126_4d5f3a7aaa3d`(upgrade · check · downgrade 확인), 테스트 `trainer/tests/test_registry_db.py`
  - 기본 주소: `REGISTRY_DB_URL`이 비면 `{DATA_ROOT}/registry/registry.db`. SQLite는 접속마다 foreign_keys · WAL · busy_timeout
  - 주의: 테이블 간 relationship을 두지 않아 한 세션에서 부모 · 자식을 같이 넣을 때는 부모를 먼저 flush
- [x] 2. 작업 실행기: 202 + job_id, GPU 잠금(609), 중단, 재시작 후 정리, 자기 프로세스만 관리 (Claude, 브랜치 `feature/job-runner`, #7 위에 쌓음)
  - `app/jobs/runner.py` `JobRunner.submit/cancel/poll/start/stop`, 모듈 함수 `submit_job` · `cancel_job` · `start` · `stop`(main.py lifespan에서 시작 · 종료)
  - 작업마다 자식 프로세스 `python -m app.jobs.worker <job_dir> <모듈:함수>`. 핸들러는 `JobContext`를 받아 `check_cancel()` · `report(...)`, 보류는 `raise JobHeld("below_target")`
  - 파일: `{DATA_ROOT}/jobs/{job_id}/` payload.json · status.json · cancel · pid · worker.log. DB 반영은 API의 poll(기본 2초)만
  - 실패하면 종류별 장애 코드(수집 602 · 학습 606 · 평가 607 · 변환 604)로 `modules.fault.record_fault`(reg_faults + `logs/fault-날짜.jsonl`)
  - `DEFAULT_HANDLERS`는 비어 있다 → 지금 제출하면 600. 단계 6에서 학습 · 평가 · 변환 모듈을 여기에 넣는다. 시험용 핸들러는 `app/jobs/sample.py`
  - 서버를 켜려면 먼저 `alembic upgrade head`(reg_jobs가 없으면 시작 때 실패)
- [~] A. slides-v4 비교: 엄윤종 `scripts/data/ocw_slide_chunks.py`(`origin/feature/dataset`) ↔ `retrieval.chunk_slides` 조각 수 · 경계 (Claude, 브랜치 `feature/slides-v4-compare`, 3a · 4와 동시에)
  - 결과(11/26, 코드 읽기 + slides-v4 결과 2377쪽 · 2634조각으로 측정, 원본 PDF · bge 토크나이저 없이):
    - **rc-v1 데이터는 다시 만들 필요 없음.** 검증 후보 · 어려운 오답은 `scripts/search/common.py`가 엄윤종 slides-v4 결과 파일(`search_pack/index/slides-v4/*.jsonl`)을 그대로 읽어 만들었다. `chunk_slides`는 쓰지 않았다.
    - **서비스 쪽 `retrieval.chunk_slides`가 slides-v4와 다르다**(학습 · 서비스 조각 불일치): ① 깨진 줄 판정에서 2글자 이하 기호 토큰(=, +, {)을 빼지 않아 slides-v4가 남긴 줄 92개(80쪽)를 더 지움 ② 긴 쪽(192쪽, 8%)을 문단 → 문장 → 토큰이 아니라 토큰 400개 창으로 자르고 겹침도 단어 경계를 안 봄 ③ 글상자 줄 잇기 · 줄 끝 하이픈 잇기 · 쪽 번호 · OCW 안내문 · 저작권 줄 · 제3자 표시 제거가 없음(지금은 "호출하는 쪽이 한다") ④ 최소 글자 수를 공백 정리 전에 셈
    - 할 일: `chunk_slides`를 slides-v4 규칙에 맞춘다(입력을 쪽별 글상자 목록으로). 맞춘 뒤 bge 토크나이저로 slides-v4 결과와 조각이 같은지 확인. 그 뒤 엄윤종 스크립트가 `retrieval`을 불러 쓰도록 제안(규칙 한 곳)
  - A-2. ~~다르면 검증 후보 · 어려운 오답 다시 만들기~~ → 필요 없음(위)
  - A-3. 검증 480 검수(2인 교차) — **지금 시작 가능**(후보가 slides-v4 기준이라 바뀌지 않음) (최의찬 + 엄윤종)
- [ ] 3. 기본 API: 3a 조회(7.4.1 · 7.4.3 · 7.4.4 · 7.4.24 · 7.4.25 · 7.4.27) → 3b 데이터셋 등록(7.4.2) (Codex, 브랜치 `feature/basic-api`, 바로 시작 가능)
- [ ] 4. 학과 서버 1차 올리기: `docs/work/server-setup.md`(`pip --target`, API 실행, SSH 터널 확인) (최의찬 + Claude, 바로 시작 가능)
- [ ] 5. 판정 추론 서버(:8001): 사전학습 bge-reranker fp16, 강연 중 적재 · 해제, 800 ms 측정 (Claude, 4 · 관리자 · 팀 답변 후)
  - 5-1. LLM_ONLY 판정 프롬프트 `llm-only-v1` 확정: 서비스 대체 판정과 베이스라인 ③이 같은 프롬프트(τ_LLM). 원본 위치 제안 `retrieval` 패키지 (Claude + 팀)
- [ ] 6. 학습 한 바퀴: 학습 → 평가 → fp16 변환 → 등록 → 서빙 전환 · 롤백 (Claude, 테스트 Codex) — **엄윤종 최종 데이터셋** · 3b · 5 · 5-1 필요
- [ ] 7. 백엔드 연동: EC2 → SSH 터널 → 판정 호출, 시간 초과 대체 (최의찬 + 조현준 + Claude) — 6 · 조현준 합의 필요
- 나중(Should, v1.0 이후): 교안 멀티모달 rc-v2 (아래 "나중에")

```
지금 동시에: A · 3a · 4
A-3 검수 → 엄윤종 최종 데이터셋 ┐  (A chunk_slides 맞추기는 5 전까지)
3a → 3b                                      ├→ 6 → 7
4 → 5 (+ 5-1)                                ┘
```

### 엄윤종에게 받을 것
| 받을 것 | 받아서 할 일 | 상태 |
|---|---|---|
| slides-v4 청킹 코드 | A 비교 | push됨(`origin/feature/dataset`, dev PR 없음 → PR 요청) |
| es-vN 파일 형식 | 3b | `build_eval_slides.py` → `eval_reference_chunks.jsonl`(lecture_id · source_key · page_no · chunk_index · text) + `meta.json` |
| 어려운 오답 · 재확인 라벨 | 학습셋 반영 | 대기 |
| 최종 train · validation · test.jsonl | 서버 `/home/t26112/easyq-data/upload/<폴더>/`에 두면 7.4.2 등록 → 6 | **일정 확인 필요** |
| 시험셋 자체 녹음 강의 | 시험셋 포함 | 대기 |

### 단계 3 작업 설명 (Codex)
> 설계 원문: `docs/design/ch07_api.md` 7.4 머리말 표(공통 규칙) · 각 절, `ch06_process.md` 6.4.1 · 6.4.2, `ch03_data.md` 3.3.3(필드). 이 설명에 없는 설계 결정이 필요하면 구현하지 말고 "질문"에 적고 멈춘다.

**쓸 것 (이미 있음, 고치지 말 것)**
- DB: `from app.db import get_session`(FastAPI `Depends(get_session)`), 모델 `app.db.models`(RegDataset · RegTestSet · RegJob · RegFault · RegDeployment). 테이블을 바꿔야 하면 멈추고 질문.
- 작업: `from app.jobs.runner import get_runner` → `get_runner().gpu_job(session)`(GPU 작업 job_id 또는 None). 작업 제출 · 중단 API(7.4.6~9 등)는 이번 범위 아님.
- 오류: `raise TrainerError(Code.NOT_FOUND, ...)` 등, 성공은 `ok(data)`. 응답 형식 `{result_code, result_msg, data}`.
- 담당이 Claude인 `app/db/*` · `migrations/*` · `app/jobs/*` · `modules/fault/*`, 그리고 `app/main.py`는 건드리지 않는다.

**공통**
- 시각은 ISO 8601 **+09:00**로 내보낸다(DB는 UTC). `app/core/timefmt.py`에 `to_kst_iso(dt) -> Optional[str]` 하나 만들어 모든 API가 쓴다.
- 목록 API의 `page` · `size`: 설계서에 기본값이 없어 **page=1부터, size 기본 20 · 최대 100**으로 한다. 응답에 `total_count`.
- 없는 항목은 613. 목록 필터 값이 허용 목록 밖이면 422 → 기존 핸들러가 601로 바꾼다(손대지 않음).

**3a. 조회 API (먼저, 작은 PR 하나)**
| API | 구현 |
|---|---|
| 7.4.1 GET /health | `mode` · `serving_version` · `threshold`: reg_deployments에서 `deployment_seq` 가장 큰 행. 행이 없으면 LLM_ONLY · null · null. `gpu_busy`: `gpu_job(session) is not None`. `status`: 판정 모델 적재 여부는 5단계에서 붙으므로 지금은 `modules.inference.serving_state().loaded`를 그대로 쓰고, CUSTOM인데 미적재면 degraded. worker가 10초마다 부르므로 DB가 비어 있어도 200이어야 한다 |
| 7.4.3 GET /datasets | reg_datasets 최신순(created_at desc). 항목 필드는 7.4.3 그대로, `test_use_count`는 reg_test_sets에서 |
| 7.4.4 GET /datasets/{v} | 7.4.4 필드 그대로. 없으면 613 |
| 7.4.24 GET /jobs | `type` · `status` 필터(값은 `JOB_TYPES` · `JOB_STATUSES`), 최신순. 항목: job_id · type · status · progress · created_at · finished_at |
| 7.4.25 GET /jobs/{id} | type · status · progress · stage · hold_reason · result · fault_id. 없으면 613 |
| 7.4.27 GET /faults | `from` · `to`(ISO 8601) · `code` · `job_id` 필터, 최신순 |

테스트: 임시 SQLite에 `alembic upgrade head` 후 `app.dependency_overrides[get_session]`로 바꿔 끼운다(`trainer/tests/test_registry_db.py` · `test_job_runner.py`의 fixture 참고). X-API-Key 헤더는 conftest의 `test-key`. 빈 DB · 행 있음 · 필터 · 613 · +09:00 형식을 확인.

**3b. 7.4.2 데이터셋 등록 (3a 머지 뒤)**
- `modules/dataset.validate_dataset(source_dir)`에 6.4.1 검사: 3.3.3 필드, 검증 · 시험 후보 ≤ 20 · 정답 근거가 후보 안, 강좌가 두 분할에 겹치지 않음, 검증 · 시험에 AI Hub 행 없음, 시험셋은 사람 라벨만. 어긋나면 601 + `errors`(파일 · 행 번호 · 사유, **행 내용은 넣지 않음**) + `record_fault(601, "dataset", None, 요약)`.
- `source_dir`는 `{DATA_ROOT}/upload/` 아래만 받는다(`..`나 밖 경로는 601). 통과하면 `{DATA_ROOT}/datasets/ds-vN/`로 복사하고 reg_datasets에 등록. 검증 · 시험셋 내용이 이전 버전과 같으면 val/test 버전을 이어 쓰고, 다르면 새 번호(내용 해시로 비교).
- `reg_datasets.status`는 값 목록이 아직 없다(질문 1번). **임시로 `READY`** 를 넣고 코드에 TODO를 남긴다.
- 평가용 교안 조각(es-vN, reg_eval_slide_chunks): 엄윤종 `scripts/data/build_eval_slides.py`가 만드는 `eval_reference_chunks.jsonl`(lecture_id · source_key · page_no · chunk_index · text)을 `source_dir`에서 읽어 저장한다. 파일이 이 형식과 다르면 멈추고 질문.
- 테스트 데이터는 테스트 안에서 만든 가짜 JSONL만 쓴다. `data/` 아래 실제 파일 · AI Hub 파일은 열지 않는다.

**끝 기준**: `uv run ruff check .` · `uv run pytest` 통과, Python 3.9 문법, `test_routes.py`의 28개 경로 그대로, PROGRESS 단계 3에 체크와 메모.

## 끝난 작업: 검색 모듈(retrieval, rc-v1) — PR #5 · #6 머지
- 같은 강의 안 벡터 20(gemini-embedding-2, 768) + Kiwi BM25 20 → RRF(k=60) 상위 20. 교안 slides-v4 규칙 청킹, 발화 30초 청킹.
- `scripts/search/`: 검증 후보 20 · 어려운 오답(이웃 제외, 최대 3). 실행은 `uv run --env-file .env ... --embedder gemini`.
- Gemini 실행 결과(11/26, `data/interim/search/rc-v1/`, 엄윤종 전달용 zip 있음): 검증 480 × 20, synth 근거 포함률 98.8%(상위 5 90.8%), 오답 2100(발화 1719 · 교안 381), 정답 근거 포함률 97.7%.
- 남은 것: 엄윤종 slides-v4 코드 받으면 `chunk_slides` 결과 비교, 실제 bge 토크나이저로 청킹 실행.

## 질문 (답이 필요한 것)
- `reg_datasets.status` 값 목록이 설계서(8.2.38 · 7.4.3)에 없다. 지금은 제약 없이 문자열. 예: READY / ARCHIVED 중 무엇을 쓸지 정하면 CHECK 추가.
- 팀 합의: 레지스트리 DB SQLite, 판정 모델 강연 중에만 적재(백엔드가 강연 시작 · 종료를 알려야 함). `docs/work/design-changes.md` 참고.
- 서버 관리자(11/26 문의함, 답변 대기): 로컬 API 상시 실행, SQLite 파일, 강연 중 GPU 0번 사용. (`/data` 없음 → `DATA_ROOT=/home/t26112/easyq-data`로 확정, design-changes 4번)

## 다음 할 일
- Claude: 단계 1 · 2 끝(PR #7 · #8). 단계 3 작업 설명 작성함. 단계 4 서버 올리기 안내 `docs/work/server-setup.md`.
- Codex: 단계 3 시작 가능(3a 조회 API부터, 위 "단계 3 작업 설명").
- 사람(최의찬): 끝 — rc-v1 zip 엄윤종 전달, slides-v4 코드 요청, 관리자 문의(답변 대기), 로컬 .env를 SQLite · ./data/local로, Gemini 키는 지금 키 · 본인 결제 하나로 개발 · 시연 모두 사용(실배포 없음, 11/26 결정), 설계 변경(design-changes.md) 팀 공유(11/26, 합의 답변 대기 — 특히 3번 강연 중 GPU 적재는 백엔드 호출 필요). 남음 — 검증 480 검수.

## 나중에 (Should, v1.0 이후)
- 교안 멀티모달(rc-v2): 교안을 올릴 때 쪽 이미지를 비전 모델로 글로 바꿔(그림 설명 · 표 → 마크다운 · 수식 → LaTeX) 쪽 텍스트 뒤에 붙인다. 이후 검색 · 판정 · 답변은 그대로.
  학습용 OCW 교안도 같은 방식으로 다시 만들고 후보 · 오답 재생성, rc-v1과 정답 근거 포함률 비교. 설계 6.1.5 · 3장 변경이라 팀 합의 먼저(2026-11-26 피드백, 우선순위 Should).
