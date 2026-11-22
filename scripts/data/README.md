# 학습 데이터 구축 스크립트 (L1, 설계서 3장)

담당: 엄윤종, 최의찬

- 공개 강의 자료 수집(MIT OCW 등) · 출처 · 라이선스 기록
- 질문-근거 쌍 생성(LLM 합성 초안) → 2인 교차 검수
- 데이터 분석 · 강좌 단위 분할(학습 · 검증 · 시험)
- 결과는 `/data/easyq/upload/<폴더>/`에 train.jsonl · validation.jsonl · test.jsonl로 두고 7.4.2로 등록한다

스크립트만 이 폴더에 두고, 만들어진 데이터는 레포에 올리지 않는다.

## 스크립트
- `extract_ocw_transcripts.py`: `data/raw/mit_ocw/<강좌>/<강좌>.zip`에서 영상 전사본 PDF를 꺼내 `transcripts/`에 강의 번호 순(L01 · PS3 · QR1 …)으로 정리하고 `transcripts_manifest.csv`(출처 · 라이선스)를 만든다. `--apply` 없이 돌리면 미리보기.
- `ocw_transcript_text.py`: 정리한 전사본 PDF에서 머리말 · CC 안내문 · 효과음 태그를 지우고 화자를 역할(강사/학생)로 바꿔 강사 발화만 뽑는다(3.2.2 (1) 2단계). 결과는 `data/interim/mit_ocw/transcripts/<course_id>.jsonl`과 강의 메타 `lectures.jsonl`(3.3.3). PyMuPDF가 필요하므로 먼저 `uv sync --all-packages --group dev --group data`.
- `ocw_transcript_chunks.py`: 강사 발화를 강의별 말하는 속도(전체 단어 수 ÷ 영상 길이)로 정한 30초 분량 단어 수에 맞춰 문장 경계에서 자른다(3.2.2 (1) 3단계). 결과는 `data/interim/mit_ocw/chunks/<course_id>.jsonl`, 근거 ID는 `<lecture_id>_T0001` 형식.
- `synth_batch.py` + `prompts/`: Sonnet 합성 배치 준비(`prepare`: 청크 선택 · 목표 질문 유형 배정) · 검증(`ingest`: 형식 · 길이 검사, 3.3.3 학습 쌍 변환, 라벨별 길이 · 단어 겹침 · 유형 분포를 `meta.json`에 기록). 프롬프트: `ko_rewrite_v1`(한국어 구어체 변환), `question_synth_v1`/`v2`/`v3`/`v3_1`(질문 합성, 기본값은 v3_1). LLM 호출은 스크립트 밖에서 하고 모델 ID를 `--model`로 남긴다. AI Hub 데이터에는 쓰지 않는다.

- `ocw_slide_chunks.py`: 강좌 zip 안의 강의 교안(슬라이드 · 노트 PDF, PPTX도 같은 규칙)을 쪽 단위 교안 조각으로 나눈다(3.2.3, 회의안건 B4). 1쪽 = 1조각, 쪽 넘김 · 겹침 없음, 최대 약 350토큰(bge-m3), 넘으면 문단 → 문장 → 토큰 순으로 분할, 10토큰 미만 쪽은 제외하고 개수 기록, 제3자 저작물(All rights reserved) 표시 문단 제외, 발표자 노트 제외. 결과는 `data/interim/mit_ocw/slides/<course_id>.jsonl`(lecture_id, source_key, page_no, chunk_index, text)과 `stats.json`. 6.046J 필기 노트(writtenlec)는 스캔 이미지라 쓰지 않는다.
- `squad_sample.py`: SQuAD 2.0 train에서 답 있음 250 + 답 없음 250을 뽑는다(지문당 1문항, 문서당 라벨별 최대 2문항). 정답(답 없음은 plausible_answers) 문장을 가운데 두고 약 148단어(교안 조각 중앙값, B5 추천)까지 문장 단위로 늘려 자르고, 350토큰을 넘지 않는다. 결과는 `data/interim/squad2/<이름>/pairs.jsonl`(3.3.3 필드) · `meta.json`.
- `aihub_sample.py`: AI Hub 「기계독해」 표준(정답 있음) 250 + 정답 없음 250을 SQuAD와 같은 방식으로 뽑는다(지문당 1문항, 문서당 라벨별 최대 2문항, `contains_aihub=true`). 정답 있음은 정답 문장 주변을 148어절 · 350토큰 이내로, 정답 없음은 지문을 같은 길이 조각으로 나눠 질문과 BM25 최상위 조각을 근거로 쓴다(임베딩 · 외부 API 없음, BM25 토큰은 kiwipiepy가 있으면 형태소, 없으면 글자 2-gram). 화면에는 개수 · 통계만 찍는다. 먼저 `--inspect`로 값 없이 키 구조만 확인한다. 결과는 `data/interim/aihub/<이름>/pairs.jsonl` · `meta.json`이고, `build_splits.py --aihub`로 합친다.
- 위 스크립트들은 bge-m3 토크나이저(`tokenizers`)를 쓴다. 처음 실행할 때 Hugging Face에서 `BAAI/bge-m3`의 tokenizer.json을 받는다(`--tokenizer`로 로컬 경로 지정 가능).
- `synth_batch.py prepare --lectures ... --part-size 50`: 고른 강의의 청크 전부를 배치로 만들고 50청크 묶음 파일(`parts/in_NN.jsonl`)도 만든다(B3). 강의 선정 기준은 프로젝트 노트 `학습강의_선정안.md`.
- `sample_pairs.py`: 합성 쌍(`pairs.jsonl`)에서 라벨 비율(기본 168/168/144)을 맞춰 청크당 1문항, 강의 비율대로 seed로 뽑는다. 예: `uv run python scripts/data/sample_pairs.py --batch val-6.0001-v3_1 --name val-480`
- `build_splits.py`: OCW 합성 쌍(700/700/600으로 seed 추출) + SQuAD 500을 3.3.3 학습 필드의 `train.jsonl`로, 검증 480을 평가 필드의 `validation.jsonl`(후보 20개 · gold_in_candidates는 검색 모듈 뒤에 채움)로 합쳐 `data/processed/<이름>/`에 둔다. 7.4.2 등록 전 단계. `--aihub`로 AI Hub 쌍도 넣을 수 있고, 이때 결과물도 AI Hub 데이터로 다룬다. AI Hub 행이 다른 입력에 섞이거나 검증셋에 AI Hub · SQuAD 행이 있으면 멈춘다.

## 검증셋 val-6.0001-v3_1 만든 순서 (2026-11-22)
스크립트 하나로 다시 만들 수 없어 순서를 적어 둔다. 자세한 기록은 `data/interim/synth/val-6.0001-v3_1/RESUME.md`.
1. `input.jsonl`은 `measure-6.0001-v2`의 것(6.0001 전체 1,086청크)을 그대로 복사한다.
2. L01–L07 600청크와 L08–L09 앞 250청크(850청크): `measure-6.0001-v2`의 ko_text는 그대로 두고 질문만 `question_synth_v3_1`(말투 섞기 규칙 포함)로 새로 만든다 → `parts/qout_01..09.jsonl`.
3. 나머지 236청크: 한국어 변환과 v3_1 질문을 함께 만든다 → `parts/out31_18..22.jsonl`.
4. `qout_01..09` 다음 `out31_18..22` 순서로 이어 붙여 `output.jsonl`을 만들고(행 순서가 `input.jsonl`과 같음), `meta.json`의 프롬프트를 `ko_rewrite_v1` + `question_synth_v3_1`로 적은 뒤 `synth_batch.py ingest --batch val-6.0001-v3_1 --model claude-sonnet-5-5`.
5. 검증 문항: `sample_pairs.py --batch val-6.0001-v3_1 --name val-480` (seed 20261122).

테스트: `uv run python -m pytest scripts/data/tests`
