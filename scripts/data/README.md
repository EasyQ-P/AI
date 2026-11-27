# 학습 데이터 구축 스크립트 (L1, 설계서 3장)

담당: 엄윤종, 최의찬

- 공개 강의 자료 수집(MIT OCW 등) · 출처 · 라이선스 기록
- 질문-근거 쌍 생성(LLM 합성 초안) → 2인 교차 검수
- 데이터 분석 · 강좌 단위 분할(학습 · 검증 · 시험)
- 결과는 `/home/t26112/easyq-data/upload/<폴더>/`(학과 서버에 /data 없음, 2026-11-26 변경)에 train.jsonl · validation.jsonl · test.jsonl로 두고 7.4.2로 등록한다

스크립트만 이 폴더에 두고, 만들어진 데이터는 레포에 올리지 않는다.

## 스크립트
- `extract_ocw_transcripts.py`: `data/raw/mit_ocw/<강좌>/<강좌>.zip`에서 영상 전사본 PDF를 꺼내 `transcripts/`에 강의 번호 순(L01 · PS3 · QR1 …)으로 정리하고 `transcripts_manifest.csv`(출처 · 라이선스)를 만든다. `--apply` 없이 돌리면 미리보기.
- `ocw_transcript_text.py`: 정리한 전사본 PDF에서 머리말 · CC 안내문 · 효과음 태그를 지우고 화자를 역할(강사/학생)로 바꿔 강사 발화만 뽑는다(3.2.2 (1) 2단계). 결과는 `data/interim/mit_ocw/transcripts/<course_id>.jsonl`과 강의 메타 `lectures.jsonl`(3.3.3). PyMuPDF가 필요하므로 먼저 `uv sync --all-packages --group dev --group data`.
- `ocw_transcript_chunks.py`: 강사 발화를 강의별 말하는 속도(전체 단어 수 ÷ 영상 길이)로 정한 30초 분량 단어 수에 맞춰 문장 경계에서 자른다(3.2.2 (1) 3단계). 결과는 `data/interim/mit_ocw/chunks/<course_id>.jsonl`, 근거 ID는 `<lecture_id>_T0001` 형식.
- `synth_batch.py` + `prompts/`: Sonnet 합성 배치 준비(`prepare`: 청크 선택 · 목표 질문 유형 배정) · 검증(`ingest`: 형식 · 길이 검사, 3.3.3 학습 쌍 변환, 라벨별 길이 · 단어 겹침 · 유형 분포를 `meta.json`에 기록). 프롬프트: `ko_rewrite_v1`(한국어 구어체 변환), `question_synth_v1`/`v2`/`v3`/`v3_1`(질문 합성, 기본값은 v3_1). LLM 호출은 스크립트 밖에서 하고 모델 ID를 `--model`로 남긴다. AI Hub 데이터에는 쓰지 않는다.
  `--source slides`(B안, 2026-11-25): 교안 조각(slides-v4)에서 질문을 합성한다. 번역하지 않고 영어 원문을 근거로(`DOCUMENT`, `page_no`, `evidence_id` = source_key), 질문 프롬프트 기본값은 `question_synth_slides_v1`, 배치 폴더에 작업 지시 `TASK.md`도 만든다. 예: `prepare --source slides --batch train-slides-v1 --courses 6.006_S20 6.034_F10 6.046J_S15 --n 200 --part-size 50`

- `ocw_slide_chunks.py`: 강좌 zip 안의 강의 교안(슬라이드 · 노트 PDF, PPTX도 같은 규칙)을 쪽 단위 교안 조각으로 나눈다(3.2.3, 회의안건 B4). 규칙은 백엔드와 합의(2026-11-24): 1쪽 = 1조각 단위, 쪽을 넘겨 붙이지 않음, 최대 400토큰(bge-reranker-v2-m3), 넘으면 문단 → 문장 → 토큰 순으로 분할하고 같은 쪽 안 이웃 조각만 약 50토큰 겹침(쪽 사이 겹침 없음), 내용 적은 쪽(20자 미만 또는 내용어 3개 미만, 내용어 = Kiwi 명사 NNG · NNP + 라틴 문자 단어)은 제외하고 개수 기록(다음 쪽에 붙이지 않음), 제3자 저작물(All rights reserved) 표시 문단 제외, 발표자 노트 제외. 6.172 저작권 줄(© 2008–2018 by the MIT 6.172 Lecturers)과 깨진 글 줄(괄호 · = · 따옴표 · 쉼표 · 콜론을 뺀 글자 중 글자 · 숫자 0.5 미만 또는 단어 같은 토큰 절반 미만, `--min-word-char-ratio` · `--min-wordlike-token-ratio`)은 내용 적은 쪽 판정 전에 지우고 개수를 `garbled_blocks`로 기록. 결과는 `data/interim/mit_ocw/slides-v4/<course_id>.jsonl`(lecture_id, source_key, page_no, chunk_index, text)과 `stats.json`(이전 결과 `slides/` · `slides-v2/` · `slides-v3/`는 그대로). 6.172(시험)는 lecN PDF만. 6.046J 필기 노트(writtenlec)는 스캔 이미지라 쓰지 않는다.
- `squad_sample.py`: SQuAD 2.0 train에서 답 있음 250 + 답 없음 250을 뽑는다(지문당 1문항, 문서당 라벨별 최대 2문항). 정답(답 없음은 plausible_answers) 문장을 가운데 두고 약 148단어(교안 조각 중앙값, B5 추천)까지 문장 단위로 늘려 자르고, 350토큰을 넘지 않는다. 결과는 `data/interim/squad2/<이름>/pairs.jsonl`(3.3.3 필드) · `meta.json`.
- `aihub_sample.py`: AI Hub 「기계독해」 표준(정답 있음) 250 + 정답 없음 250을 SQuAD와 같은 방식으로 뽑는다(지문당 1문항, 문서당 라벨별 최대 2문항, `contains_aihub=true`). 정답 있음은 정답 문장 주변을 148어절 · 350토큰 이내로, 정답 없음은 지문을 같은 길이 조각으로 나눠 질문과 BM25 최상위 조각을 근거로 쓴다(임베딩 · 외부 API 없음, BM25 토큰은 kiwipiepy가 있으면 형태소, 없으면 글자 2-gram). 화면에는 개수 · 통계만 찍는다. 먼저 `--inspect`로 값 없이 키 구조만 확인한다. 결과는 `data/interim/aihub/<이름>/pairs.jsonl` · `meta.json`이고, `build_splits.py --aihub`로 합친다.
- 위 스크립트들은 bge-m3 토크나이저(`tokenizers`)를 쓴다. 처음 실행할 때 Hugging Face에서 `BAAI/bge-m3`의 tokenizer.json을 받는다(`--tokenizer`로 로컬 경로 지정 가능).
- `synth_batch.py prepare --lectures ... --part-size 50`: 고른 강의의 청크 전부를 배치로 만들고 50청크 묶음 파일(`parts/in_NN.jsonl`)도 만든다(B3). 강의 선정 기준은 프로젝트 노트 `학습강의_선정안.md`.
- `sample_pairs.py`: 합성 쌍(`pairs.jsonl`)에서 라벨 비율(기본 168/168/144)을 맞춰 청크당 1문항, 강의 비율대로 seed로 뽑는다. 예: `uv run python scripts/data/sample_pairs.py --batch val-6.0001-v3_1 --name val-480`
- `build_eval_slides.py`: `slides-v4`에서 평가 강좌(6.0001 검증 · 6.172 시험) 조각만 골라 평가용 교안 조각 파일 `data/processed/<이름>/eval_reference_chunks.jsonl`(lecture_id, source_key, page_no, chunk_index, text)과 `meta.json`(청킹 규칙 · 일치 판정 기준 5단어 shingle · 조각 80% · 강의 30%)을 만든다(es-vN 초안, 7.4.2 등록용).
- `build_splits.py`: OCW 합성 쌍(700/700/600으로 seed 추출) + SQuAD 500을 3.3.3 학습 필드의 `train.jsonl`로, 검증 480을 평가 필드의 `validation.jsonl`(후보 20개 · gold_in_candidates는 검색 모듈 뒤에 채움)로 합쳐 `data/processed/<이름>/`에 둔다. 7.4.2 등록 전 단계. `--ocw`에 발화 · 교안 쌍 파일을 함께 주고 `--ocw-counts`를 근거 종류별(`{"TRANSCRIPT": {...}, "DOCUMENT": {...}}`)로 주면 B안 구성으로 뽑는다. `--aihub`로 AI Hub 쌍도 넣을 수 있고, 이때 결과물도 AI Hub 데이터로 다룬다. AI Hub 행이 다른 입력에 섞이거나 검증셋에 AI Hub · SQuAD 행이 있으면 멈춘다. `--hard-negatives`(검색 모듈 결과) · `--hn-max`(질문당, 기본 2) · `--hn-recheck`(재확인 결과)를 주면 재확인을 통과한 어려운 오답만 순위대로 붙이고, 라벨별 근거 종류 비율 · 길이를 `meta.json`에 남긴다.
- `recheck_batch.py` + `prompts/hn_recheck_v1.md`: 어려운 오답 Sonnet 재확인("이 근거로 답할 수 있나", 3.3.4 5단계). `prepare`는 질문당 통과 개수가 `--hn-max`가 되도록 확인 안 한 오답을 순위대로 고르고(`--checked`로 이전 결과를 주면 빠진 자리 보충), `ingest`는 `result.jsonl`(pair_id, answerable, reason)로 모은다. 결과는 `data/interim/recheck/<이름>/`.
- `review_sample.py`: 학습셋 무작위 10% 사람 검수표(OCW 합성 쌍, 근거 종류 × 라벨별 비율 유지, CSV)를 만들고(`make`), 채운 표로 라벨 오류율을 센다(`summary`). 결과는 `data/interim/review/<이름>/`.
- `build_search_pack.py`: `scripts/search/hard_negatives.py`가 읽는 검색 묶음(train 답변 가능 쌍 + 한국어 발화 · 교안 색인)을 만든다. 어려운 오답을 다시 뽑아야 할 때 쓴다.

## 검증셋 val-6.0001-v3_1 만든 순서 (2026-11-22)
스크립트 하나로 다시 만들 수 없어 순서를 적어 둔다. 자세한 기록은 `data/interim/synth/val-6.0001-v3_1/RESUME.md`.
1. `input.jsonl`은 `measure-6.0001-v2`의 것(6.0001 전체 1,086청크)을 그대로 복사한다.
2. L01–L07 600청크와 L08–L09 앞 250청크(850청크): `measure-6.0001-v2`의 ko_text는 그대로 두고 질문만 `question_synth_v3_1`(말투 섞기 규칙 포함)로 새로 만든다 → `parts/qout_01..09.jsonl`.
3. 나머지 236청크: 한국어 변환과 v3_1 질문을 함께 만든다 → `parts/out31_18..22.jsonl`.
4. `qout_01..09` 다음 `out31_18..22` 순서로 이어 붙여 `output.jsonl`을 만들고(행 순서가 `input.jsonl`과 같음), `meta.json`의 프롬프트를 `ko_rewrite_v1` + `question_synth_v3_1`로 적은 뒤 `synth_batch.py ingest --batch val-6.0001-v3_1 --model claude-sonnet-5-5`.
5. 검증 문항: `sample_pairs.py --batch val-6.0001-v3_1 --name val-480` (seed 20261122).

테스트: `uv run python -m pytest scripts/data/tests`
