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

테스트: `uv run python -m pytest scripts/data/tests`
