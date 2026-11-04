"""작업 실행기 (7.4 공통 규칙). 수집 · 학습 · 평가 · 변환을 API 서버와 분리된 작업 프로세스에서 돌린다.

- 요청은 즉시 202 + job_id(train-NNNN · eval-NNNN · export-NNNN · collect-NNNN)로 답하고 reg_jobs에 QUEUED로 남긴다.
- 학습 · 평가 · 변환은 GPU에서 한 번에 하나만 실행한다(이미 실행 중이면 609).
- 상태: QUEUED → RUNNING → SUCCEEDED / FAILED / CANCELLED / HELD
- 작업 프로세스가 죽어도 API 서버와 추론 프로세스(8001)는 계속 응답한다.
"""
