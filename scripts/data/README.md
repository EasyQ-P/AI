# 학습 데이터 구축 스크립트 (L1, 설계서 3장)

담당: 엄윤종, 최의찬

- 공개 강의 자료 수집(MIT OCW 등) · 출처 · 라이선스 기록
- 질문-근거 쌍 생성(LLM 합성 초안) → 2인 교차 검수
- 데이터 분석 · 강좌 단위 분할(학습 · 검증 · 시험)
- 결과는 `/data/easyq/upload/<폴더>/`에 train.jsonl · validation.jsonl · test.jsonl로 두고 7.4.2로 등록한다

스크립트만 이 폴더에 두고, 만들어진 데이터는 레포에 올리지 않는다.

## 스크립트
- `extract_ocw_transcripts.py`: `data/raw/mit_ocw/<강좌>/<강좌>.zip`에서 영상 전사본 PDF를 꺼내 `transcripts/`에 강의 번호 순(L01 · PS3 · QR1 …)으로 정리하고 `transcripts_manifest.csv`(출처 · 라이선스)를 만든다. `--apply` 없이 돌리면 미리보기.
