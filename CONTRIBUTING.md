# 작업 규칙

## 브랜치
- `main`: 진도 점검 · 시연용. PR로만 합치고 직접 push하지 않는다.
- `dev`: 개발 통합 브랜치. 기능 브랜치는 여기서 따고 여기로 PR한다.
- 기능 브랜치: `유형/짧은-설명` (예: `feature/train-job`, `fix/health-timeout`)
- 점검일마다 `dev` → `main` PR 후 태그: `v0.3`(12/2) · `v0.4`(12/3) · `v0.5`(12/4) · `v0.7`(12/7) · `v0.9`(12/8) · `v1.0`(12/9)

## 커밋 메시지
`유형: 요약` — 유형은 feat · fix · docs · refactor · test (설계서 10.3)

예: `feat: 학습 작업 중단 API 추가`

## 이름 규칙 (설계서 10.3)
- Python 함수 · 변수 snake_case, 클래스 PascalCase, 상수 · 환경 변수 UPPER_SNAKE_CASE
- 레지스트리 DB 테이블은 `reg_` 접두어 (reg_models, reg_jobs …)
- 버전: ds-vN, val-vN, test-vN, rc-vN, es-vN, judge-vN / 작업 번호: train-0001, eval-0001, export-0001

## 커밋하면 안 되는 것
- 학습 데이터 · 체크포인트 · 모델 · 평가 리포트 · 로그 (학과 서버 `/data/easyq/`에만 둔다)
- AI Hub 데이터: 원본 · 재가공본 모두 학과 서버 밖으로 옮기지 않는다 (3.1.3)
- `.env`, API 키, SSH 키
