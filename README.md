# EasyQ AI

EasyQ의 AI학습서버(trainer)와 공용 검색 패키지(retrieval) 레포.

| 폴더 | 내용 | 실행 위치 |
|---|---|---|
| `trainer/app/` | 학습서버 API(`/api/v1`, 7.4.1~7.4.28), X-API-Key 인증 | 학과 서버 localhost:8000 |
| `trainer/modules/` | dataset · train · export · evaluate · inference · fault 모듈(7.4.29) | 학과 서버 |
| `retrieval/` | 교안 · 발화 청킹, 키워드 색인, 하이브리드 검색, 겹침 계산(6.1.5) | 학과 서버 + backend worker |
| `scripts/data/` | 학습 데이터 구축 스크립트(3장) | 학과 서버 |

서비스(auth · backend · worker)는 backend 레포, 화면은 frontend 레포에 있다.
worker의 STT · 검색 · 판정 · 답변 처리(R2~R4)는 backend 레포에서 작업한다.

## 시작하기

```bash
uv sync --all-packages --group dev          # 로컬(GPU 없이)
uv sync --all-packages --group dev --extra gpu   # 학과 서버(GPU)
cp .env.example .env
docker compose -f docker-compose.dev.yml up -d registry-db   # 레지스트리 DB (로컬)
uv run uvicorn app.main:app --app-dir trainer --host 127.0.0.1 --port 8000
```

확인: `curl -H "X-API-Key: change-me" http://127.0.0.1:8000/api/v1/health`

```bash
uv run ruff check .
uv run pytest
```

## backend 레포에서 retrieval 쓰기

태그로 버전을 고정해서 설치한다.

```bash
uv add "retrieval @ git+https://github.com/EasyQ-P/AI@v0.1.0#subdirectory=retrieval"
```

retrieval을 고치면 태그를 새로 달고 backend 쪽 버전을 올린다.

## 서비스와의 연결

- EC2 backend · worker → SSH 터널(EC2 호스트 Docker bridge 주소:9000 → 학과 서버 localhost:8000) → 이 서버
- 학습서버 레지스트리 DB가 학습 쪽 정보의 원본이고, 서비스 DB는 조회한 복사본만 둔다(7.4).
- 판정 추론(7.4.26)이 800 ms를 넘기거나 실패하면 서비스가 그 질문만 LLM_ONLY로 판정한다.

작업 규칙은 [CONTRIBUTING.md](CONTRIBUTING.md).
