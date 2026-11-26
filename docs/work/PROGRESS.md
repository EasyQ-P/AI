# 작업 진행 기록

> Claude Code · Codex 공통. 작업을 시작할 때 먼저 읽고, 단계를 끝낼 때마다 갱신한다(AGENTS.md "에이전트 작업 규칙").
> 체크: `[ ]` 할 일 · `[~]` 진행 중 · `[x]` 끝. 담당 표에 없는 파일은 고치기 전에 "질문"에 적는다.

## 지금 작업: 검색 모듈(retrieval) — 브랜치 `feature/retrieval-search`

목표(11/27 금): 엄윤종에게 검색 모듈 전달 → 검증 480문항 후보 20개, 학습 OCW 답변 가능 700문항 어려운 오답.
입력 데이터: `data/raw/easyq_ai2_search_pack/` (엄윤종 2026-11-25, AI Hub 없음, README.md에 형식 설명). **내용 출력 금지, 구조만 확인.**

### 정해진 결정
| 항목 | 결정 | 근거 |
|---|---|---|
| Python | trainer · retrieval은 3.9 문법(`Optional[X]`, `list[...]` OK, `X \| None` · `zip(strict=)` · `match` 금지) | 학과 서버 3.9 (PR #4) |
| 교안 청킹 | slides-v4 규칙: 1쪽 = 1조각, 최대 400토큰(bge-reranker-v2-m3, 특수 토큰 제외), 넘으면 50토큰 겹쳐 나눔, 20자 미만 · 내용어 3개 미만 · 깨진 글 쪽 제외 | 백엔드 합의안, `es-draft-3/meta.json` |
| 발화 검색 텍스트 | `evidence_text_ko`(한국어 변환본). 교안은 영어 원문 `text` | 엄윤종 README 권고, 서비스 STT도 한국어 |
| 검색 | 같은 강의 안에서만. 벡터 20 + 키워드 20 → RRF(k=60) 상위 20 | 설계 6.1.5 |
| 임베딩 | gemini-embedding-2, 768차원, 파일 캐시. 키 `GEMINI_API_KEY`(.env). 키 없으면 FakeEmbedder로 개발 | 설계 3장 |
| 선택 설치 | `retrieval[keyword]` kiwipiepy · `[embedding]` google-genai(3.10+만) · `[tokenizer]` tokenizers | 서버 3.9에 SDK 불필요 |
| 어려운 오답 | 정답 근거와 그 이웃(같은 강의 발화 T±1, 같은 교안 쪽의 다른 조각)은 제외, 상위에서 최대 3개 | 이웃은 답이 이어질 가능성 큼 |
| AI Hub | 어떤 스크립트도 `contains_aihub=true` 행을 받으면 바로 멈춘다 | 3.1.3 |

### 담당 (같은 파일을 동시에 고치지 않는다)
| 파일 | 담당 |
|---|---|
| `retrieval/src/retrieval/config.py` · `search.py` · `chunking.py` | Claude |
| `retrieval/src/retrieval/keyword.py` · `embedding.py` | Codex (C1 · C2) |
| `retrieval/tests/test_keyword.py` · `test_embedding.py` | Codex |
| `scripts/search/*` · `scripts/search/tests/*` | Codex (C3) |
| `.github/workflows/ci.yml` | Codex (C1에서 keyword extra 설치 추가) |
| `docs/work/PROGRESS.md` | 둘 다 (자기 칸만) |

### 단계
- [x] 0. 지침 통일(AGENTS.md 원본, CLAUDE.md는 `@AGENTS.md`), 이 파일
- [x] 1. 뼈대 · 인터페이스: config(rc-v1) · keyword · embedding · chunking · search(HybridSearcher 구현 완료)
- [x] 2. C1 키워드 검색 (Codex)
- [x] 3. C2 임베딩 (Codex)
- [x] 4. 교안 청킹 `chunk_slides` · `bge_token_spans` · 발화 `chunk_utterances` (Claude, 실제 bge 토크나이저 실행은 아직)
- [x] 5. C3 스크립트: 검증 후보 · 어려운 오답 (Codex, C1 · C2 다음)
- [~] 6. 리뷰 · 통합 · 실제 데이터로 실행 · PR (Claude)
  - 리뷰 끝: meta 파일 이름 분리(`validation_meta.json` · `hard_negatives_meta.json`), 오답 행 `label_source=HARD_NEGATIVE`, pytest `pythonpath=["."]`
  - fake 임베더 실행(11/26): 검증 480 × 후보 20, 오답 2100(700 × 3, 발화 1668 · 교안 432), 정답 근거 후보 포함률 92.6%
  - 남은 것: Gemini 키로 실제 실행, push · PR
- [ ] 7. 엄윤종 slides-v4 코드 받으면 `chunk_slides` 결과 비교 (push 요청 중)

## Codex 작업 설명

공통: Python 3.9 문법, 새 의존성 추가 금지(아래 명시한 것 제외), 네트워크가 필요한 테스트 금지, docstring에 적힌 동작을 그대로 구현.
끝나면 `uv run ruff check .` · `uv run pytest` 통과 → 커밋(`feat: ...`) → 이 파일 체크 · "Codex 메모"에 한 줄.

### C1. 키워드 검색 — `retrieval/src/retrieval/keyword.py`
- `tokenize_keywords`, `BM25Index`를 docstring대로 구현. kiwipiepy는 함수 안에서 지연 import(모듈 import만으로는 필요 없게).
- 품사는 `config.keyword_tags`. Kiwi 태그 이름이 버전마다 다르면(예: `VV-R`) 앞부분으로 비교.
- 테스트 `retrieval/tests/test_keyword.py`: BM25는 손으로 만든 토큰으로(정렬 · 동점 · allowed_ids · 점수 0 제외), 토크나이저는 `pytest.importorskip("kiwipiepy")` 후 한국어 · 영어 섞인 문장 1~2개.
- CI(`.github/workflows/ci.yml`)의 빠른 검사 두 개(3.12 · 3.9)에서 설치를 `uv sync --all-packages --group dev --extra keyword`로 바꿔 Kiwi 테스트가 실제로 돌게 한다.

### C2. 임베딩 — `retrieval/src/retrieval/embedding.py`
- `FakeEmbedder`, `CachedEmbedder`, `cosine_top_k`, `GeminiEmbedder`를 docstring대로 구현.
- `GeminiEmbedder`: `from google import genai`를 `__init__` 안에서. `client.models.embed_content(model=..., contents=[...], config=types.EmbedContentConfig(task_type=..., output_dimensionality=dim))`. 응답 `.embeddings[i].values`. 키는 `os.environ["GEMINI_API_KEY"]`, 예외 · 로그에 키를 넣지 않는다.
- 테스트 `retrieval/tests/test_embedding.py`: Fake 결정성 · 단위 길이, Cached(tmp_path, 두 번째 호출은 inner를 안 부름 · 순서 유지 · 일부만 캐시된 경우), cosine 정렬. Gemini는 실제 호출 없이 SDK가 없을 때 친절한 오류만(가능하면).

### C3. 스크립트 — `scripts/search/` (로컬 3.12 전용, ruff py312)
공통 입력: `--pack data/raw/easyq_ai2_search_pack`. 검색 문서(`SearchDoc`):
- 발화: `index/transcripts/*.jsonl` → doc_id=`evidence_id`, text=`evidence_text_ko`, evidence_type=TRANSCRIPT
- 교안: `index/slides-v4/*.jsonl`(6.172 제외) → doc_id=`source_key`, text=`text`, evidence_type=DOCUMENT
- 임베더: `--embedder fake|gemini`(기본 fake), gemini는 `CachedEmbedder(GeminiEmbedder(), data/interim/search/emb_cache.jsonl)`
- 화면에는 개수 · 통계만 찍는다(질문 · 근거 원문 출력 금지). 입력에 `contains_aihub=true`가 있으면 즉시 종료.

1) `scripts/search/build_val_candidates.py`
   - `dataset/validation.jsonl` 480문항 → `HybridSearcher.search_many([(question_text, lecture_id)])`
   - 출력 `data/interim/search/<이름>/validation.jsonl`: 입력 필드 그대로 + `candidates`(근거 ID 20개, 검색 순위) + `retrieval_config_version`
   - `validation_meta.json`: `RetrievalConfig.to_dict()`, 임베더 이름, 문항 수, 후보 수 분포, 진단용으로 `synth_evidence_id`가 후보 안에 든 비율(전체 · 상위 5 · 상위 10)
2) `scripts/search/hard_negatives.py`
   - 대상: `dataset/train.jsonl` 중 `source == MIT_OCW` · `label == ANSWERABLE` (700)
   - 같은 강의 검색 → 정답 `evidence_id`와 이웃(발화 T±1, 같은 쪽 다른 조각) 제외 → 순위대로 `--max-neg`(기본 3)개
   - 출력 `data/interim/search/<이름>/hard_negatives.jsonl`: 학습 필드 형식(README 2장) 그대로, 원 쌍에서 질문 쪽 필드 복사 + 근거 쪽은 고른 조각(`evidence_text`는 발화면 ko, 교안이면 영어 원문, `evidence_lang`도 맞춤) + `label=INSUFFICIENT_EVIDENCE`, `target=0`, `is_hard_negative=true`, `gen_method=HARD_NEGATIVE`, `pair_id=<원 pair_id>:hn<순번>`, `retrieval_config_version`
   - `recheck.jsonl`: Sonnet 재확인용 `{pair_id, question_text, evidence_text}` (파일로만, 화면 출력 금지)
   - `hard_negatives_meta.json`: 설정, 대상 수, 붙은 오답 수 분포(0~3개), 오답 출처 TRANSCRIPT/DOCUMENT 분포, 정답 근거가 후보 안에 있던 비율
- 테스트 `scripts/search/tests/`: 작은 가짜 pack(tmp_path)과 FakeEmbedder로 두 스크립트의 출력 형식 · 이웃 제외 · AI Hub 거부.
  루트 `pyproject.toml`의 `testpaths`에 `scripts/search/tests` 추가(3.9 CI는 경로를 직접 주므로 영향 없음). 이 한 줄은 Codex가 고쳐도 된다.

## 질문 (답이 필요한 것)
- (없음)

## Codex 메모
- C1: Kiwi 지연 생성 키워드 토큰화와 Okapi BM25 색인·필터·결정적 정렬을 구현하고, 빠른 CI에 keyword extra를 연결했다.
- C2: 결정적 단위 Fake 임베딩, Gemini 배치·재시도, JSONL 파일 캐시, 순수 Python 코사인 검색을 구현했다.
- C3: 검증 후보·어려운 오답 생성 스크립트와 통계 메타, 이웃 제외·AI Hub 거부 가짜 pack 테스트를 구현했다.

## 다음 할 일
- Codex: C1 · C2 · C3 끝(Claude가 리뷰 후 커밋).
- Claude: Gemini 키 받으면 실제 실행 → PR.
- 사람(최의찬): Gemini API 키 정하기, 엄윤종에게 slides-v4 코드 push 요청, 검증 480 검수.
