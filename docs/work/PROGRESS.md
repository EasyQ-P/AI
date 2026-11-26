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
| `trainer/app/api/*` 기본 API(7.4.1~4 · 7.4.24~25) | Codex (DB 다음, 작업 설명은 그때 적는다) |
| `docs/work/PROGRESS.md` | 둘 다 (자기 칸만) |

### 단계
- [ ] 1. 레지스트리 DB: `reg_` 테이블 10개(8.2.38) 모델 · 첫 마이그레이션 · SQLite 테스트 (Claude, 브랜치 `feature/registry-db`)
- [ ] 2. 작업 실행기: 202 + job_id, GPU 잠금(609), 중단, 재시작 후 정리, 자기 프로세스만 관리 (Claude)
- [ ] 3. 기본 API: 7.4.1~4 · 7.4.24~25 (Codex)
- [ ] 4. 학과 서버 1차 올리기: `pip --user`, API 실행, SSH 터널로 상태 확인 (최의찬 + Claude)
- [ ] 5. 판정 추론 서버(:8001): 사전학습 bge-reranker fp16, 적재 · 해제, 800 ms 측정 (Claude)
- [ ] 6. 학습 한 바퀴: 학습 → 평가 → fp16 변환 → 등록 → 서빙 전환 · 롤백 (Claude, 테스트 Codex)
- [ ] 7. 백엔드 연동: EC2 → SSH 터널 → 판정 호출, 시간 초과 대체 (최의찬 + 조현준 + Claude)

## 끝난 작업: 검색 모듈(retrieval, rc-v1) — PR #5 · #6 머지
- 같은 강의 안 벡터 20(gemini-embedding-2, 768) + Kiwi BM25 20 → RRF(k=60) 상위 20. 교안 slides-v4 규칙 청킹, 발화 30초 청킹.
- `scripts/search/`: 검증 후보 20 · 어려운 오답(이웃 제외, 최대 3). 실행은 `uv run --env-file .env ... --embedder gemini`.
- Gemini 실행 결과(11/26, `data/interim/search/rc-v1/`, 엄윤종 전달용 zip 있음): 검증 480 × 20, synth 근거 포함률 98.8%(상위 5 90.8%), 오답 2100(발화 1719 · 교안 381), 정답 근거 포함률 97.7%.
- 남은 것: 엄윤종 slides-v4 코드 받으면 `chunk_slides` 결과 비교, 실제 bge 토크나이저로 청킹 실행.

## 질문 (답이 필요한 것)
- 팀 합의: 레지스트리 DB SQLite, 판정 모델 강연 중에만 적재(백엔드가 강연 시작 · 종료를 알려야 함). `docs/work/design-changes.md` 참고.
- 서버 관리자: 로컬 API 상시 실행, SQLite 파일, 강연 중 GPU 0번 사용, `/data/easyq` 사용 가능 여부.

## 다음 할 일
- Claude: 단계 1(레지스트리 DB) → 2(작업 실행기).
- Codex: 단계 3(기본 API), 단계 1 끝난 뒤.
- 사람(최의찬): rc-v1 zip 엄윤종에게 전달, 검증 480 검수, 설계 변경 팀 공유, 관리자 문의, 서비스용 Gemini 키 · 결제 주체 결정.

## 나중에 (Should, v1.0 이후)
- 교안 멀티모달(rc-v2): 교안을 올릴 때 쪽 이미지를 비전 모델로 글로 바꿔(그림 설명 · 표 → 마크다운 · 수식 → LaTeX) 쪽 텍스트 뒤에 붙인다. 이후 검색 · 판정 · 답변은 그대로.
  학습용 OCW 교안도 같은 방식으로 다시 만들고 후보 · 오답 재생성, rc-v1과 정답 근거 포함률 비교. 설계 6.1.5 · 3장 변경이라 팀 합의 먼저(2026-11-26 피드백, 우선순위 Should).
