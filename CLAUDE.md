# EasyQ AI 레포 — 작업 기준

EasyQ: 강연 중 청중 질문에 교안 · 발화 근거로 AI가 답하고, 근거가 부족하면 강연자에게 넘기는 서비스.
이 레포는 **AI학습서버(trainer)** 와 **공용 검색 패키지(retrieval)** 만 담는다.
서비스(auth · backend · worker)는 backend 레포, 화면은 frontend 레포.

## 기준 문서 (docs/design/, 제출한 설계서의 원문)
설계와 다르게 구현해야 하면 코드부터 바꾸지 말고 먼저 알린다. 아래가 주로 볼 곳이다.

| 파일 | 볼 곳 |
|---|---|
| ch07_api.md | 7.4 학습서버 API(7.4.1~7.4.28), 7.4.29 내부 함수 · 파일, 7.4.30 서비스 API 대응 |
| ch08_database.md | 8.1.6 · 8.2.38 레지스트리 DB(reg_ 테이블), 8.3 로그 형식, 8.4 오류 코드(600~615) |
| ch06_process.md | 6.1.5 공용 검색 모듈, 6.1.6 평가용 강의 판정, 6.4 학습서버 기능 흐름 |
| ch03_data.md | 학습 데이터 수집 · 라벨 · 분할, 3.3.3 데이터 필드, AI Hub 처리 규칙(3.1.3) |
| ch04_model.md | 판정 모델 학습 · 평가 · 임계값 · 패키지(4.4) |
| ch09_evaluation.md | 등록 · 배포 조건, 성능 지표와 측정 방법 |
| ch02_requirements.md | 2.3 학습서버 기능 T-01~T-22 |
| ch01_ch10_overview_devenv.md | 개발 조직 · 모듈, 10.1 개발 환경, 10.2 디렉터리, 10.3 명칭 규칙 |

## 구조
- `trainer/app/` 학습서버 API(FastAPI, `/api/v1`), `core/`(설정 · X-API-Key · 오류 코드 · 공통 응답)
  - `api/` 7.4 라우터(파일당 리소스 하나), `db/` 레지스트리 DB 연결, `jobs/` 작업 실행기, `inference_main.py` 판정 추론 프로세스(127.0.0.1:8001 내부 전용)
- `trainer/migrations/` 레지스트리 DB Alembic 마이그레이션(`trainer/alembic.ini`)
- `trainer/modules/` dataset · train · export · evaluate · inference · fault (함수 이름 · 입출력은 7.4.29 그대로)
- `retrieval/src/retrieval/` 청킹 · 키워드 · 하이브리드 검색(RRF) · 겹침 계산 · 검색 설정 버전(rc-vN)
- `scripts/data/` 학습 데이터 구축 스크립트

## 핵심 규칙
- 응답은 항상 `{result_code, result_msg, data}`. 오류는 `TrainerError(Code.X)`로 던진다(600~615, 8.4).
- 모든 API는 X-API-Key 필요. 키는 로그에 남기지 않는다.
- 학습서버는 `127.0.0.1:8000`에만 바인드(외부 미개방, EC2는 SSH 터널로만 접근).
- 장시간 작업(수집 · 학습 · 평가 · 변환)은 즉시 202 + job_id, 상태는 작업 조회로. GPU 작업은 한 번에 하나(609).
- 판정 추론은 학습과 분리된 추론 프로세스가 fp16 서빙 모델을 GPU에 상주시켜 처리. 800 ms 넘으면 서비스가 LLM_ONLY로 대체.
- 레지스트리 DB 테이블은 `reg_` 접두어. 학습 쪽 정보의 원본은 레지스트리 DB.
- **trainer · retrieval은 Python 3.9 문법으로 쓴다.** 학과 서버(ceprj, Rocky Linux)가 Python 3.9이고 가상환경을 쓸 수 없어서다(설계서 10.1의 3.12와 다름, 2026-11-26 결정). `X | None` 대신 `Optional[X]`, `zip(strict=)` · `match` 금지. 로컬 개발은 3.12, CI가 3.9에서도 검사한다. `scripts/data`는 로컬 전용이라 3.12 유지.
- **데이터 · 체크포인트 · 모델 · 로그는 커밋 금지.** 학과 서버 `/data/easyq/`에만 둔다. AI Hub 데이터는 원본 · 재가공본 모두 학과 서버 밖으로 반출 금지, 외부 API로 보내지 않는다.

## 명령
```bash
uv sync --all-packages --group dev            # 로컬
uv sync --all-packages --group dev --extra gpu  # 학과 서버
uv run ruff check .
uv run pytest
uv run uvicorn app.main:app --app-dir trainer --host 127.0.0.1 --port 8000
uv run uvicorn app.inference_main:app --app-dir trainer --host 127.0.0.1 --port 8001  # 판정 추론
docker compose -f docker-compose.dev.yml up -d registry-db  # 로컬 레지스트리 DB(5433)
uv run alembic -c trainer/alembic.ini upgrade head
```
- `.env`의 `TRAINER_ENV=dev`가 아니면 API 키가 없거나 `change-me`일 때 서버가 시작하지 않는다.

## Git
- `main`은 PR로만. 작업은 `dev`에서 `feature/짧은-설명` 브랜치를 따서 PR.
- 커밋: `유형: 요약` (feat · fix · docs · refactor · test).
- 점검일 태그: v0.3(12/2) · v0.4(12/3) · v0.5(12/4) · v0.7(12/7) · v0.9(12/8) · v1.0(12/9).
