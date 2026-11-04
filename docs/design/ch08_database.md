# 8장 데이터 설계 — 수정본

> 표 · 그림 번호는 통합 때 매긴다. 백엔드 v0.8의 8장을 바탕으로 확정 결정(기준표)을 반영했다. ERD는 이 명세에 맞춰 다시 그린다.

## 8.1 ERD 다이어그램

EasyQ의 데이터는 두 DB에 나뉜다.

- **서비스 DB** (DB명 easyq, 스키마 public, AWS RDS for PostgreSQL 16 + pgvector): 회원 · 인증 · 강연 · 질문 · 답변 · 필기 · 후보 · 작업 · 실시간 이벤트, 교안 · 발화 벡터와 키워드 색인, 학습서버 레지스트리 복사본을 둔다. 교안 원본 파일은 S3에 둔다.
- **학습서버 레지스트리 DB** (학과 서버, PostgreSQL): 데이터셋 · 작업 · 평가 · 모델 · 서빙 상태 · 학습 설정 · 평가용 교안 조각 · 장애 기록의 원본을 둔다. 학습 · 검증 · 시험 JSONL, 체크포인트, 모델 패키지는 학과 서버 파일(7.4.29)로 둔다.

서비스 DB의 ERD는 업무 영역 다섯 개로 나누고, 한 그림이 본문 폭에 맞도록 영역마다 1~3장으로 그린다. 영역 경계의 테이블은 여러 그림에 함께 나오며 별도 DB를 뜻하지 않는다. 선은 주요 FK 관계이고, 선택 FK는 빈 원, 다중 관계는 까마귀발로 표기한다. 모든 컬럼과 제약은 8.2에서 정의한다.

[그림: 서비스 DB ERD (1-a) 회원 · 인증 — users, auth_sessions, email_verifications, password_resets, auth_rate_limits — 다시 그림]

[그림: 서비스 DB ERD (1-b) 강연 · 참가 · 동의 — lecture_sessions, participants, consents — 다시 그림]

[그림: 서비스 DB ERD (2-a) 교안 · 검색 · 요약 — documents, knowledge_chunks, eval_reference_chunks, summary_notes — 다시 그림]

[그림: 서비스 DB ERD (2-b) 질문 · 답변 · 인용 — questions, answers, answer_citations — 다시 그림]

[그림: 서비스 DB ERD (2-c) 공감 · 필기 · 평가 — votes, question_notes, answer_feedback — 새로 그림]

[그림: 서비스 DB ERD (3) 후보 · 검수 — feedback_candidates, label_reviews, candidate_provenance — 다시 그림]

[그림: 서비스 DB ERD (4) 학습서버 복사본 · 배포 — datasets, training_runs, model_versions, evaluation_runs, deployments — 다시 그림]

[그림: 서비스 DB ERD (5-a) 작업 · 실시간 이벤트 — jobs, ws_events — 다시 그림]

[그림: 서비스 DB ERD (5-b) 사용량 · 감사 — api_usage, audit_events — 다시 그림]

[그림: 서비스 DB ERD (5-c) 공지 · 문의 · 설정 — notices, inquiries, app_settings — 새로 그림]

[그림: 학습서버 레지스트리 DB ERD (a) 데이터 · 학습 · 평가 — reg_datasets, reg_test_sets, reg_train_configs, reg_jobs, reg_evaluations, reg_merge_requests, reg_faults — 새로 그림]

[그림: 학습서버 레지스트리 DB ERD (b) 모델 · 배포 — reg_models, reg_deployments, reg_eval_slide_chunks — 새로 그림]

## 8.2 논리적 설계: 테이블 명세서

### 8.2.1 공통 규칙

- NN은 NOT NULL, PK는 기본키, FK는 외래키이며 O는 적용, -는 미적용이다.
- 식별자는 서버가 발급하는 UUID다. users.email은 소문자로 정규화해 유일하게 둔다.
- 시각은 TIMESTAMPTZ로 저장하고 API는 UTC ISO 8601로 응답하며, 화면은 Asia/Seoul로 표시한다.
- 상태 필드는 표에 적은 값만 허용하도록 CHECK 제약을 둔다. 판정 점수는 0~1이고, LLM_ONLY 점수와 τ_LLM(llm_only_threshold)만 0~100이다(τ_LLM = 101은 모든 질문 이관). 개수 · 시간 · 비용은 0 이상이다.
- 강연에 속한 행은 항상 session_id 조건으로 접근한다. 참가자 · 교안 · 조각 · 질문 사이에 다른 강연을 참조하지 못하도록 복합 FK 또는 트랜잭션 검증으로 막는다.
- FK는 접근 권한을 대신하지 않는다. 개인 답변 · 필기 · 관리자 응답은 각각 별도 응답 스키마로 직렬화한다.
- created_at은 생성 시각, updated_at은 변경 시각이며 서버가 기록한다.
- DB 계정은 실행 단위별로 나눈다. auth 계정만 비밀번호 해시 · 인증 코드 · 재설정 토큰 검증값을 읽고 쓴다. backend는 인증 확인용 조회 뷰(auth_session_view: 세션 해시 · 만료 · 폐기, 회원 상태 · 역할 · 이메일 인증 여부, 게스트 참가 상태)만 읽는다.

### 8.2.2 users — 회원

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | user_id | UUID | O | O | - | 회원 ID |
| 2 | email | VARCHAR(254) | O | - | - | 로그인 이메일(소문자 정규화), UNIQUE |
| 3 | password_hash | TEXT | O | - | - | 비밀번호 단방향 해시(auth 계정만 접근) |
| 4 | display_name | VARCHAR(50) | O | - | - | 표시 이름 |
| 5 | role | VARCHAR(10) | O | - | - | MEMBER / ADMIN. 가입은 MEMBER 고정, ADMIN은 서버 초기 생성 명령으로만 생성 |
| 6 | status | VARCHAR(24) | O | - | - | PENDING_VERIFICATION / ACTIVE / SUSPENDED / DELETING |
| 7 | email_verified_at | TIMESTAMPTZ | - | - | - | 가입 이메일 인증을 마친 시각. 로그인마다 갱신하지 않음 |
| 8 | suspension_reason | VARCHAR(500) | - | - | - | 정지 사유. SUSPENDED일 때만 값이 있고 로그인 거부 응답에 담음. 복구하면 NULL |
| 9 | created_at | TIMESTAMPTZ | O | - | - | 가입 시각 |
| 10 | updated_at | TIMESTAMPTZ | O | - | - | 변경 시각 |

PENDING_VERIFICATION이면 email_verified_at이 NULL이고, ACTIVE이면 반드시 값이 있다. 이메일 변경은 지원하지 않는다. 정지를 풀어도 인증 시각은 그대로 둔다. 가입 후 24시간 안에 인증하지 않은 계정은 동의 · 인증 기록 · 메일 작업과 함께 삭제하며, 이 정리와 인증 완료는 같은 회원 행 잠금으로 순서를 맞춘다.

### 8.2.3 auth_sessions — 회원 · 게스트 인증 세션

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | auth_session_id | UUID | O | O | - | 인증 세션 ID |
| 2 | user_id | UUID | - | - | O | 회원 인증이면 users |
| 3 | participant_id | UUID | - | - | O | 게스트 인증이면 participants |
| 4 | token_hash | CHAR(64) | O | - | - | 쿠키 토큰의 해시, UNIQUE |
| 5 | csrf_token_hash | CHAR(64) | O | - | - | CSRF 토큰 해시 |
| 6 | expires_at | TIMESTAMPTZ | O | - | - | 회원 발급 후 12시간, 게스트 입장 후 24시간과 강연 종료 중 빠른 시각 |
| 7 | revoked_at | TIMESTAMPTZ | - | - | - | 로그아웃 · 정지 · 비밀번호 변경 · 재설정 · 강연 종료 때 폐기 시각 |
| 8 | created_at | TIMESTAMPTZ | O | - | - | 발급 시각 |

user_id와 participant_id 중 정확히 하나만 채운다. 게스트 세션은 GUEST 참가자만 참조하며, 같은 게스트의 활성 세션은 하나다. 회원 세션은 ACTIVE이고 이메일 인증을 마친 회원에게만 발급한다. 발급 · 폐기는 auth가 하고, 폐기하면 session.revoked 이벤트(ws_events)를 같은 트랜잭션으로 남긴다. 쿠키 원문은 DB와 로그에 저장하지 않는다.

### 8.2.4 email_verifications — 가입 이메일 인증

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | verification_id | UUID | O | O | - | 인증 기록 ID |
| 2 | user_id | UUID | O | - | O | users, ON DELETE CASCADE |
| 3 | code_hash | CHAR(64) | O | - | - | HMAC-SHA256(verification_id + 6자리 코드). 코드 원문 아님 |
| 4 | key_id | VARCHAR(50) | O | - | - | HMAC · 발송 암호화 키 버전 |
| 5 | delivery_ciphertext | BYTEA | - | - | - | 발송 대기 중인 코드의 암호화 봉투. 발송 완료 · 만료 · 폐기 즉시 제거 |
| 6 | expires_at | TIMESTAMPTZ | O | - | - | 발급 후 10분 |
| 7 | attempt_count | SMALLINT | O | - | - | 틀린 횟수 0~5 |
| 8 | sent_at | TIMESTAMPTZ | - | - | - | SMTP 접수 시각(인증 완료와 다름) |
| 9 | consumed_at | TIMESTAMPTZ | - | - | - | 인증 성공 시각 |
| 10 | revoked_at | TIMESTAMPTZ | - | - | - | 재발송 · 5회 실패 · 취소로 폐기한 시각 |
| 11 | created_at | TIMESTAMPTZ | O | - | - | 생성 시각 |

(user_id) WHERE consumed_at IS NULL AND revoked_at IS NULL에 UNIQUE를 둔다. 재발송은 회원 행을 잠그고 이전 기록을 폐기한 뒤 새 기록을 만든다. 메일 작업의 payload에는 verification_id만 넣고, worker는 최신 유효 기록인지 다시 확인한 뒤 봉투를 풀어 fastapi-mail로 보낸다. SMTP 일시 오류는 만료 전까지 최대 3회 다시 시도한다. 사용 · 폐기 · 만료된 기록은 24시간 안에 지운다. HMAC 키와 봉투 암호화 키는 DB 밖의 비밀 설정으로 관리한다.

### 8.2.5 password_resets — 비밀번호 재설정

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | reset_id | UUID | O | O | - | 재설정 기록 ID |
| 2 | user_id | UUID | O | - | O | users, ON DELETE CASCADE |
| 3 | token_hash | CHAR(64) | O | - | - | HMAC-SHA256(재설정 토큰). 토큰 원문 아님 |
| 4 | key_id | VARCHAR(50) | O | - | - | HMAC 키 버전 |
| 5 | delivery_ciphertext | BYTEA | - | - | - | 발송 대기 중인 링크의 암호화 봉투. 발송 후 즉시 제거 |
| 6 | expires_at | TIMESTAMPTZ | O | - | - | 발급 후 30분 |
| 7 | consumed_at | TIMESTAMPTZ | - | - | - | 재설정 완료 시각(1회용) |
| 8 | revoked_at | TIMESTAMPTZ | - | - | - | 새 요청으로 폐기한 시각 |
| 9 | created_at | TIMESTAMPTZ | O | - | - | 생성 시각 |

ACTIVE이고 이메일 인증을 마친 회원에게만 만든다. 회원당 유효 기록은 하나이며(email_verifications와 같은 부분 UNIQUE), 재설정이 끝나면 그 회원의 auth_sessions를 모두 폐기한다. 사용 · 폐기 · 만료된 기록은 24시간 안에 지운다.

### 8.2.6 auth_rate_limits — 인증 · 입장 요청 공유 제한

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | bucket_key | CHAR(64) | O | O | - | 범위(scope)와 정규화 이메일 또는 IP의 HMAC. 원문 없음 |
| 2 | window_start | TIMESTAMPTZ | O | O | - | 제한 구간 시작. bucket_key와 복합 PK |
| 3 | request_count | INTEGER | O | - | - | 원자 증가 카운터 |
| 4 | last_request_at | TIMESTAMPTZ | O | - | - | 마지막 요청 시각(60초 간격 확인) |
| 5 | expires_at | TIMESTAMPTZ | O | - | - | 구간 종료 후 24시간 안에 삭제 |

가입 · 로그인 · 인증 메일 · 인증 코드 확인 · 재설정 메일 · 입장 코드 실패를 서로 다른 범위로 센다. 입장 코드 실패(같은 IP 15분 20회)는 backend가 JOIN_CODE 범위 행에만 쓰며, backend DB 계정은 이 범위 행만 읽고 쓴다. 메일 발송(가입 첫 발송 포함)은 같은 이메일 시간당 5회 · 60초 간격, 같은 IP 시간당 20회다. 로그인 실패는 이메일당 15분 10회, IP당 15분 100회다. 코드 확인은 기록당 5회, IP당 15분 100회다. RDS의 원자 UPSERT로 여러 auth 프로세스에서도 같은 한도를 적용한다. 질문 API에는 적용하지 않는다.

### 8.2.7 lecture_sessions — 강연

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | session_id | UUID | O | O | - | 강연 ID |
| 2 | host_user_id | UUID | - | - | O | users, 강연 소유자. 강연자 탈퇴 시 SET NULL |
| 3 | host_display_name | VARCHAR(50) | O | - | - | 강연 기록에 남는 강연자 표시명(생성 시 복사) |
| 4 | title | VARCHAR(100) | O | - | - | 강연명 |
| 5 | description | VARCHAR(500) | - | - | - | 강연 설명(대기 화면 표시) |
| 6 | scheduled_at | TIMESTAMPTZ | O | - | - | 시작 예정 일시. 표시용이며 자동 시작하지 않음 |
| 7 | join_code | CHAR(5) | O | - | - | 입장 코드(영문 대문자 · 숫자 5자리, 혼동되는 0 · O · 1 · I 제외), UNIQUE. QR 주소에 들어감. 재발급 시 교체 |
| 8 | previous_join_code | CHAR(5) | - | - | - | 바로 전 입장 코드. 이 코드로 들어오면 JOIN_CODE_REVOKED |
| 9 | terms | JSONB | O | - | - | 전문용어 사전(문자열 배열, 최대 100개, 각 1~40자), STT 용어 힌트. 기본 [] |
| 10 | removed_terms | JSONB | O | - | - | 강연자가 지운 자동 추출 용어. 교안 용어를 더할 때 다시 넣지 않음. 기본 [] |
| 11 | status | VARCHAR(12) | O | - | - | DRAFT / LIVE / ENDED / PURGED / DELETING |
| 12 | stt_status | VARCHAR(16) | O | - | - | STOPPED / CONNECTING / RUNNING / PAUSED / DEGRADED |
| 13 | end_reason | VARCHAR(16) | - | - | - | HOST / AUTO_TIMEOUT / ADMIN |
| 14 | started_at | TIMESTAMPTZ | - | - | - | LIVE 전환 시각. 자동 종료 기준(+12시간) |
| 15 | ended_at | TIMESTAMPTZ | - | - | - | 종료 시각 |
| 16 | raw_data_expires_at | TIMESTAMPTZ | - | - | - | 강연 원자료 파기 시각 = ended_at + 90일 |
| 17 | host_deleted_at | TIMESTAMPTZ | - | - | - | 강연자가 삭제한 시각. 강연자 목록에서 빼고 원자료를 즉시 파기 |
| 18 | is_eval_lecture | BOOLEAN | O | - | - | 기본 false. 자동 검사 또는 ADMIN 표시의 OR. true면 후보 생성 금지 |
| 19 | eval_detection | JSONB | O | - | - | manual_marked, auto_detected, matched_chunks, total_chunks, match_ratio, eval_slide_version, retrieval_config_version, checked_at, check_status(PENDING / DONE). 기본 {} |
| 20 | course_id | VARCHAR(100) | O | - | - | 강좌 그룹 식별자. 병합 때 학습 전용 ID로 바뀜 |
| 21 | version | INTEGER | O | - | - | 상태 변경 낙관적 잠금, 초기 1 |
| 22 | statistics | JSONB | - | - | - | 종료 처리 때 한 번 집계한 강연 통계(API-39 Statistics). 종료 전 NULL |
| 23 | created_at | TIMESTAMPTZ | O | - | - | 생성 시각 |

입장 코드는 강연장 화면에 크게 띄워 공개하는 값이므로 원문으로 저장하고 HOST에게는 언제든 돌려준다(QR 크게 보기 화면). 새 코드는 지금 코드와 이전 코드 모두와 겹치지 않게 만들고 한 번 쓴 코드는 다시 발급하지 않는다. 무작위 대입은 입장 코드 요청 한도(7.1.2)로 막는다. QR은 화면에서 만든다. 정원 50명은 상수이며 활성 참가자 수로 확인한다(컬럼을 두지 않음). 강연 정보(제목 · 설명 · 예정 일시)와 전문용어는 DRAFT에서만 바꾼다. 입장 코드는 청중 입장에만 쓰며 소유자 인증 수단이 아니다. PURGED는 원자료 파기가 끝나 강연 기록(제목 · 날짜 · 강연자 표시명 · 요약 노트 · 공개 질문)만 남은 상태다. 보관함에 이 강연을 남긴 회원이 없고 강연자도 목록에서 지웠거나 탈퇴했으면 행을 삭제한다.

### 8.2.8 participants — 강연 참가자

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | participant_id | UUID | O | O | - | 참가 ID |
| 2 | session_id | UUID | O | - | O | lecture_sessions |
| 3 | user_id | UUID | - | - | O | 회원 참가이면 users. 탈퇴 시 행 삭제 |
| 4 | kind | VARCHAR(10) | O | - | - | MEMBER / GUEST |
| 5 | nickname | VARCHAR(20) | - | - | - | 게스트 닉네임(본인 화면에만 표시). 강연 종료 정리 때 NULL |
| 6 | status | VARCHAR(10) | O | - | - | ACTIVE / REVOKED(서비스 동의 철회 · 강제 퇴장) |
| 7 | archived | BOOLEAN | O | - | - | 회원 보관함에 이 강연이 있는지. 기본 true, 보관함 삭제 시 false. 게스트는 false |
| 8 | joined_at | TIMESTAMPTZ | O | - | - | 입장 시각 |

MEMBER는 user_id가 필수이고 GUEST는 NULL이다. 회원은 (session_id, user_id)에 부분 UNIQUE를 둔다. 게스트 쿠키를 잃으면 이전 질문의 소유권을 되살리지 않으며, 게스트 기록을 회원 계정으로 옮기지 않는다. 게스트 참가 행은 강연 원자료와 함께 90일에 지우고, 그때 게스트가 쓴 공개 질문의 participant_id는 NULL이 된다.

### 8.2.9 consents — 계정 · 강연 동의 이력

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | consent_id | UUID | O | O | - | 동의 ID |
| 2 | session_id | UUID | - | - | O | lecture_sessions. NULL이면 계정 단위 |
| 3 | user_id | UUID | - | - | O | 회원 주체(회원 참가 · 강연자) |
| 4 | participant_id | UUID | - | - | O | 게스트 주체 |
| 5 | purpose | VARCHAR(16) | O | - | - | SERVICE / TRAINING / STT |
| 6 | policy_version | VARCHAR(30) | O | - | - | 동의문 버전 |
| 7 | granted | BOOLEAN | O | - | - | 동의 true / 미동의 · 철회 false |
| 8 | recorded_at | TIMESTAMPTZ | O | - | - | 의사표시 시각 |

user_id와 participant_id 중 정확히 하나만 채운다. 계정 단위는 user_id가 필수이고, STT는 강연 단위 · 강연자만 허용한다. 같은 범위 · 주체 · 목적의 최신 이력을 적용하되, 계정 TRAINING 철회는 그 회원의 강연 단위 동의보다 우선한다. 동의 안내문에는 "철회하면 이후 학습에서 빠지며, 이미 익명화되어 학습에 반영된 데이터는 삭제되지 않습니다."를 넣는다.

### 8.2.10 documents — 교안

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | document_id | UUID | O | O | - | 교안 ID |
| 2 | session_id | UUID | O | - | O | lecture_sessions |
| 3 | file_name | VARCHAR(255) | O | - | - | 표시용 파일명 |
| 4 | object_key | TEXT | O | - | - | 비공개 S3 객체 키, UNIQUE |
| 5 | media_type | VARCHAR(100) | O | - | - | PDF 또는 PPTX MIME |
| 6 | size_bytes | BIGINT | O | - | - | 파일 크기(최대 50 MiB) |
| 7 | sha256 | CHAR(64) | O | - | - | 파일 내용 해시 |
| 8 | status | VARCHAR(12) | O | - | - | PENDING / PROCESSING / READY / FAILED / DELETING |
| 9 | stage | VARCHAR(12) | - | - | - | PROCESSING일 때 단계: UPLOADED / EXTRACTING / INDEXING / TERMS |
| 10 | page_count | INTEGER | - | - | - | PDF 페이지 수 또는 PPTX 슬라이드 수 |
| 11 | chunk_count | INTEGER | - | - | - | READY일 때 검색 조각 수 |
| 12 | terms | JSONB | O | - | - | 이 교안에서 뽑은 용어 배열(강연 전문용어 사전에 더할 후보), 기본 [] |
| 13 | error_code | VARCHAR(40) | - | - | - | 실패 시 8.4 코드 |
| 14 | attempt_count | INTEGER | O | - | - | 처리 시도 횟수(재시도 API 포함), 기본 0 |
| 15 | created_at | TIMESTAMPTZ | O | - | - | 업로드 시각 |

교안은 DRAFT · LIVE에서 올리고 DRAFT · ENDED에서만 지운다. 텍스트가 없는 스캔 교안은 FAILED로 두고 교체를 안내한다. DOCUMENT_PARSE_FAILED처럼 원본 때문에 실패한 교안은 재시도하지 않고, INDEX_BUILD_FAILED처럼 처리 중 실패한 교안만 재시도(API-23)를 받는다.

### 8.2.11 knowledge_chunks — 교안 · 발화 검색 조각

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | chunk_id | UUID | O | O | - | 조각 ID(= 판정 · 학습의 evidence_id) |
| 2 | session_id | UUID | O | - | O | lecture_sessions, 검색 격리 기준 |
| 3 | document_id | UUID | - | - | O | DOCUMENT이면 documents |
| 4 | source_type | VARCHAR(12) | O | - | - | DOCUMENT / TRANSCRIPT |
| 5 | source_key | VARCHAR(100) | O | - | - | 교안 · 페이지 · 순번 또는 음성 스트림 · 구간의 멱등 키 |
| 6 | page_no | INTEGER | - | - | - | 교안 페이지, 1부터 |
| 7 | start_ms | BIGINT | - | - | - | 강연 시작 기준 발화 시작 ms |
| 8 | end_ms | BIGINT | - | - | - | 발화 끝 ms(start_ms보다 큼) |
| 9 | content | TEXT | O | - | - | 확정된 교안 텍스트 또는 발화 텍스트 |
| 10 | embedding | VECTOR(768) | - | - | - | Gemini Embedding 2 벡터 |
| 11 | search_vector | TSVECTOR | O | - | - | Kiwi 형태소 분석 결과를 simple 설정으로 색인 |
| 12 | retrieval_config_version | VARCHAR(50) | O | - | - | 검색 설정 버전(rc-vN) |
| 13 | index_status | VARCHAR(10) | O | - | - | PENDING / READY / FAILED |
| 14 | captured_at | TIMESTAMPTZ | O | - | - | 교안 수신 또는 발화 종료 시각 |
| 15 | indexed_at | TIMESTAMPTZ | - | - | - | 검색 가능해진 시각 |

(session_id, source_key)에 UNIQUE를 둔다. DOCUMENT는 document_id · page_no가 필수이고 발화 시각이 NULL이며, TRANSCRIPT는 그 반대다. READY는 embedding과 indexed_at이 필수다. STT 중간 결과는 넣지 않는다. 한국어는 Kiwi로 형태소를 나누고 영어 용어는 소문자로 그대로 둔 결과를 search_vector에 넣는다.

### 8.2.12 eval_reference_chunks — 평가용 교안 조각

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | eval_slide_version | VARCHAR(20) | O | O | - | 목록 버전(es-vN) |
| 2 | chunk_key | VARCHAR(100) | O | O | - | 학습서버 조각 키 |
| 3 | course_id | VARCHAR(30) | O | - | - | 평가용 강좌(6.0001 · 6.172 · 자체 녹음) |
| 4 | page_no | INTEGER | - | - | - | 교안 페이지 |
| 5 | ngram_hashes | BIGINT[] | O | - | - | 정규화 텍스트의 연속 5단어 묶음 해시 집합 |
| 6 | normalized_text | TEXT | O | - | - | 정규화한 텍스트(5단어 미만 조각의 전체 문장 비교용) |
| 7 | received_at | TIMESTAMPTZ | O | - | - | 7.4.28로 받은 시각 |

worker만 쓰고 backend는 읽기만 한다. 새 버전을 받으면 이전 버전 행을 지운다. 평가용 강의의 교안 조각만 담고 AI Hub 데이터 · 평가 질문은 담지 않는다.

### 8.2.13 questions — 질문과 판정

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | question_id | UUID | O | O | - | 질문 ID |
| 2 | session_id | UUID | O | - | O | lecture_sessions |
| 3 | participant_id | UUID | - | - | O | 질문자. 작성자 연결을 끊으면 NULL(공개 질문만) |
| 4 | document_id | UUID | - | - | O | 질문자가 고른 교안 |
| 5 | page_no | INTEGER | - | - | - | 질문 관련 페이지 |
| 6 | content | VARCHAR(200) | - | - | - | 질문 원문(1~200자). 게스트 개인 질문 정리 · 원자료 파기 때 NULL |
| 7 | status | VARCHAR(16) | O | - | - | QUEUED / PROCESSING / AI_ANSWERED / ESCALATED / COMPLETED / FAILED |
| 8 | escalation_reason | VARCHAR(30) | - | - | - | INSUFFICIENT_EVIDENCE / LOW_CONFIDENCE / SECOND_STAGE_INSUFFICIENT / PROVIDER_FAILURE / RETRACTED / FINALIZE_TIMEOUT |
| 9 | decision_score | NUMERIC(6,5) | - | - | - | 판정 점수(CUSTOM 0~1, LLM_ONLY는 0~100을 snapshot에) |
| 10 | vote_count | INTEGER | O | - | - | 공감 수, 기본 0. 공감 · 취소와 같은 트랜잭션으로 갱신하고 강연 종료 후 고정 |
| 11 | model_version_id | UUID | - | - | O | 실제 쓴 model_versions. LLM_ONLY면 NULL |
| 12 | decision_snapshot | JSONB | O | - | - | 8.2.36의 판정 기록, 기본 {} |
| 13 | idempotency_key | UUID | O | - | - | 중복 제출 방지 키 |
| 14 | version | INTEGER | O | - | - | 낙관적 잠금, 초기 1 |
| 15 | created_at | TIMESTAMPTZ | O | - | - | 제출 시각 |
| 16 | first_token_at | TIMESTAMPTZ | - | - | - | 답변 첫 글자 전달 시각 |
| 17 | finalized_at | TIMESTAMPTZ | - | - | - | 답변 확정 또는 이관 확정 시각 |
| 18 | completed_at | TIMESTAMPTZ | - | - | - | 강연자 답변 완료 시각 |
| 19 | content_purged_at | TIMESTAMPTZ | - | - | - | 내용을 지운 시각(행은 운영 지표용으로 남음) |
| 20 | deleted_at | TIMESTAMPTZ | - | - | - | 삭제 접수 시각. 이후 조회 차단 |

(participant_id, idempotency_key)에 UNIQUE를 둔다. 공개 여부는 따로 표시하지 않고 ESCALATED · COMPLETED 상태로 정한다. 개인 질문은 작성자와 그 강연의 강연자만 보며, 공개 질문은 누구에게도 작성자를 보여주지 않는다. 조회는 deleted_at · content_purged_at이 NULL인 행만 대상으로 한다(운영 지표 집계는 예외). 자동 이관은 확정된 정답 라벨이 아니며, 낮은 점수만으로 의견 질문이라고 단정하지 않고 LOW_CONFIDENCE로 기록한다.

### 8.2.14 answers — AI 답변

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | answer_id | UUID | O | O | - | 답변 ID |
| 2 | question_id | UUID | O | - | O | questions, UNIQUE(질문당 최종 답변 1개) |
| 3 | content | TEXT | - | - | - | 인용 검증을 통과한 답변(최대 4문장). 내용 정리 시 NULL |
| 4 | provider_model | VARCHAR(100) | O | - | - | 실제 생성 모델 ID |
| 5 | status | VARCHAR(12) | O | - | - | ACTIVE / RETRACTED |
| 6 | retraction_reason | VARCHAR(32) | - | - | - | WRONG_OR_INSUFFICIENT / EXPLAIN_AGAIN |
| 7 | retraction_detail | VARCHAR(500) | - | - | - | 철회 사유 상세(선택) |
| 8 | created_at | TIMESTAMPTZ | O | - | - | 답변 확정 시각 |
| 9 | retracted_at | TIMESTAMPTZ | - | - | - | 철회 시각 |

강연자의 구두 답변은 녹음 · 저장하지 않고 questions의 완료 여부만 남긴다. 철회된 답변은 본문을 숨기고 철회 상태만 보여준다.

### 8.2.15 answer_citations — 답변 근거 위치

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | answer_id | UUID | O | O | O | answers |
| 2 | citation_no | SMALLINT | O | O | - | 답변 본문 인용 번호, 1부터 |
| 3 | chunk_id | UUID | - | - | O | knowledge_chunks. 원자료 파기 · 교안 삭제 시 SET NULL |
| 4 | source_type | VARCHAR(12) | O | - | - | DOCUMENT / TRANSCRIPT |
| 5 | location_label | VARCHAR(50) | O | - | - | 위치 텍스트("교안 p.9", "발화 21:05") |
| 6 | page_no | INTEGER | - | - | - | 교안 페이지 |
| 7 | start_ms | BIGINT | - | - | - | 발화 시작 ms |
| 8 | end_ms | BIGINT | - | - | - | 발화 끝 ms |
| 9 | excerpt | TEXT | O | - | - | 실제 조각에서 확인한 인용 구절 |

복합 PK (answer_id, citation_no). 생성 모델이 준 페이지 번호나 URL을 믿지 않고, 서버가 조각 ID로 위치를 만들어 저장한다. ACTIVE 답변에는 근거가 하나 이상 있어야 한다. 위치 텍스트와 인용 구절을 함께 저장해, 원자료가 파기돼도 회원 보관함에서 근거 위치가 보인다.

### 8.2.16 votes — 공감

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | question_id | UUID | O | O | O | questions |
| 2 | participant_id | UUID | O | O | O | participants |
| 3 | created_at | TIMESTAMPTZ | O | - | - | 공감 시각 |

복합 PK로 참가자당 질문별 공감 1회를 보장한다. 공감 · 취소는 LIVE 강연의 ESCALATED 질문에만 받고, questions.vote_count를 같은 트랜잭션으로 갱신한다. 강연이 끝나면 vote_count가 강연 기록으로 고정되며, 회원의 votes 행은 보관함의 내가 공감한 질문 배지(voted_by_me)에 쓰이므로 회원 개인 기록으로 남기고, 게스트의 votes 행은 원자료 파기 때 지운다. 게스트가 브라우저를 바꿔 다시 공감하는 경우는 막지 않는다(참가자 단위 제한).

### 8.2.17 question_notes — 필기

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | question_id | UUID | O | O | O | questions(공개 질문). ON DELETE CASCADE |
| 2 | user_id | UUID | O | O | O | users(필기한 회원). ON DELETE CASCADE |
| 3 | question_text | VARCHAR(200) | O | - | - | 처음 저장할 때 복사한 질문 문장 |
| 4 | content | VARCHAR(1000) | O | - | - | 필기 본문(1~1,000자, 일반 텍스트) |
| 5 | created_at | TIMESTAMPTZ | O | - | - | 최초 작성 시각 |
| 6 | updated_at | TIMESTAMPTZ | O | - | - | 최종 수정 시각 |

복합 PK (question_id, user_id)로 질문 하나에 회원당 필기 하나를 둔다. 공개 질문(ESCALATED · COMPLETED)에만 만들며 게스트는 쓸 수 없다. 필기는 작성자에게만 보이고 강연자 · 관리자 응답, 공개 WebSocket, 요약, 학습 후보에 넣지 않는다. 회원이 보관함에서 그 강연을 지우거나 탈퇴하면 필기를 지운다. 화면은 본문을 HTML로 실행하지 않고 텍스트로 표시하며, 로그에는 본문을 남기지 않는다.

### 8.2.18 answer_feedback — 청중의 AI 답변 평가

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | answer_id | UUID | O | O | O | answers |
| 2 | participant_id | UUID | O | O | O | 질문 작성자 participants |
| 3 | rating | VARCHAR(16) | O | - | - | HELPFUL / UNHELPFUL |
| 4 | version | INTEGER | O | - | - | 평가 변경 순번, 초기 1 |
| 5 | updated_at | TIMESTAMPTZ | O | - | - | 평가 시각 |

질문 작성자만 ACTIVE 답변을 평가한다. 같은 평가를 다시 보내면 그대로 두고, 바꾸면 순번을 올린다. 평가는 학습 동의와 관계없이 저장하며, 후보 생성만 동의 조건을 다시 확인한다. 평가만으로 답변을 공개하거나 철회하지 않는다.

### 8.2.19 summary_notes — 요약 노트

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | summary_id | UUID | O | O | - | 요약 ID |
| 2 | session_id | UUID | O | - | O | lecture_sessions, UNIQUE |
| 3 | status | VARCHAR(12) | O | - | - | QUEUED / RUNNING / READY / FAILED / SKIPPED(확정 발화 1,000자 미만) |
| 4 | content | JSONB | - | - | - | READY일 때 {one_line, key_concepts[{term, description}], emphases[], keywords[]} |
| 5 | source_refs | JSONB | O | - | - | 인용 위치 배열(location_label · excerpt · chunk_id), 기본 [] |
| 6 | provider_model | VARCHAR(100) | - | - | - | 생성 모델 ID |
| 7 | generated_at | TIMESTAMPTZ | - | - | - | 완료 시각 |

강연마다 한 번 확정한다. 개인 질문 · 개인 답변 · 필기는 입력에 넣지 않는다. 실패하면 정해진 횟수까지 다시 시도하되 READY 노트를 다시 만들지 않는다. 요약 노트는 강연 기록이므로 원자료 파기 · 강연자 삭제 뒤에도 남고, 강연 기록이 지워질 때 함께 지운다. 원자료 파기 때 source_refs의 chunk_id는 지우고 위치 텍스트와 구절은 남긴다.

### 8.2.20 feedback_candidates — 미병합 라벨 후보

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | candidate_id | UUID | O | O | - | 후보 ID |
| 2 | event_type | VARCHAR(32) | O | - | - | AUTO_ESCALATED / RETRACTED / AUDIENCE_HELPFUL / AUDIENCE_UNHELPFUL / SECOND_STAGE_INSUFFICIENT |
| 3 | default_label | VARCHAR(24) | - | - | - | 기본 라벨(확정 정답 아님, 3.3.4) |
| 4 | reason_code | VARCHAR(32) | - | - | - | RETRACTED이면 WRONG_OR_INSUFFICIENT / EXPLAIN_AGAIN 필수 |
| 5 | sanitized_pair | JSONB | O | - | - | question_text, evidence_id, evidence_type, evidence_text, page_no, start_ms, end_ms, course_id(1차 마스킹) |
| 6 | retrieved_evidence | JSONB | O | - | - | 검수용 검색 후보 최대 20개(조각 ID · 위치 · 정제 본문 · 순위) |
| 7 | judgment_snapshot | JSONB | O | - | - | mode, model_version, score, threshold, margin, selected_evidence_ids(당시 값) |
| 8 | review_status | VARCHAR(16) | O | - | - | PENDING / DISAGREEMENT / APPROVED / REJECTED / MERGING |
| 9 | final_label | VARCHAR(24) | - | - | - | 2인 검수 확정 라벨 |
| 10 | merge_request_id | UUID | - | - | - | 병합 요청 번호 |
| 11 | review_started_at | TIMESTAMPTZ | - | - | - | 첫 검수 시작 시각(미검수 정리와 경합 방지) |
| 12 | created_at | TIMESTAMPTZ | O | - | - | 생성 시각 |

질문자와 그 강연의 강연자가 지금 모두 TRAINING에 동의했고 평가용 강의가 아닐 때만 만든다. LLM_ONLY의 자동 이관은 후보로 만들지 않는다. LLM_ONLY의 철회 · 청중 평가 · 2차 근거 부족 사건은 같은 조건이면 후보로 만들며, 근거는 Sonnet이 고른 근거 중 첫 번째를 쓴다. 고른 근거가 없거나 검색 후보가 없으면 질문-근거 쌍을 만들 수 없으므로 후보를 만들지 않는다. 한 사건에 인용이 여럿이면 근거마다 후보를 나눈다. 병합이 끝나면 후보 · 검수 · 출처 연결을 지우고 통계만 남긴다.

### 8.2.21 label_reviews — 2인 교차 검수

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | candidate_id | UUID | O | O | O | feedback_candidates |
| 2 | reviewer_user_id | UUID | O | O | O | ADMIN users |
| 3 | label | VARCHAR(24) | O | - | - | ANSWERABLE / INSUFFICIENT_EVIDENCE / OPINION / REJECT |
| 4 | evidence_id | UUID | - | - | - | 고른 정답 근거(retrieved_evidence 안의 조각 ID). AUTO_ESCALATED를 ANSWERABLE로 고르면 필수 |
| 5 | comment | VARCHAR(1000) | - | - | - | 검수 메모 |
| 6 | reviewed_at | TIMESTAMPTZ | O | - | - | 검수 시각 |

서로 다른 두 관리자가 각자 검수하며, 자기 결과를 내기 전에는 다른 사람의 결과를 보지 않는다. 라벨과 근거가 모두 같아야 APPROVED다. evidence_id는 retrieved_evidence에 담긴 값으로 검증하며, 원자료가 파기돼도 후보 안의 정제본으로 검수할 수 있게 FK를 두지 않는다.

### 8.2.22 candidate_provenance — 후보 출처 추적

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | candidate_id | UUID | O | O | O | feedback_candidates |
| 2 | question_id | UUID | O | - | O | questions |
| 3 | answer_id | UUID | - | - | O | answers |
| 4 | actor_user_id | UUID | - | - | O | 철회한 강연자 users |
| 5 | actor_participant_id | UUID | - | - | O | 평가한 청중 participants |
| 6 | source_revision | INTEGER | O | - | - | 평가 순번 또는 사건 순번 |
| 7 | consent_snapshot | JSONB | O | - | - | 질문자 · 강연자의 동의 ID · 버전 |
| 8 | event_key | CHAR(64) | O | - | - | 사건 종류 · 질문 · 답변 · 근거 · 주체 · 순번의 SHA-256, UNIQUE |
| 9 | created_at | TIMESTAMPTZ | O | - | - | 생성 시각 |

검수 응답에는 넣지 않고 삭제 작업용 DB 역할만 읽는다. 원천 삭제 · 동의 철회 때 이 연결로 미병합 후보를 찾아 지우며, 병합이 끝나면 연결을 지운다. MERGING 후보는 merge_request_id로 학습서버의 실제 병합 여부를 확인한 뒤 처리한다. 병합 뒤에는 새 버전과 건수만 남기고 서비스 대응표를 남기지 않는다.

### 8.2.23 datasets — 데이터셋 복사본

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | dataset_id | UUID | O | O | - | 서비스 내부 ID |
| 2 | version_name | VARCHAR(20) | O | - | - | ds-vN, UNIQUE |
| 3 | parent_version | VARCHAR(20) | - | - | - | 기준 버전(최초면 NULL) |
| 4 | status | VARCHAR(20) | O | - | - | 학습서버 상태 복사 |
| 5 | contains_aihub | BOOLEAN | O | - | - | AI Hub 포함 여부 |
| 6 | statistics | JSONB | O | - | - | 출처 · 라벨 · 분할별 질문 · 쌍 수 |
| 7 | script_version | VARCHAR(100) | O | - | - | 생성 스크립트 버전 |
| 8 | retrieval_config_version | VARCHAR(20) | O | - | - | rc-vN |
| 9 | validation_set_version | VARCHAR(20) | O | - | - | val-vN |
| 10 | test_set_version | VARCHAR(20) | O | - | - | test-vN |
| 11 | eval_slide_version | VARCHAR(20) | O | - | - | es-vN |
| 12 | test_use_count | INTEGER | - | - | - | 시험셋 버전 누적 사용 횟수 |
| 13 | change_note | TEXT | O | - | - | 원문 없는 변경 설명 |
| 14 | created_at | TIMESTAMPTZ | O | - | - | 학습서버 생성 시각 |
| 15 | synced_at | TIMESTAMPTZ | O | - | - | 동기화 시각 |

7.4.3 · 7.4.4의 복사본이며 값이 다르면 학습서버를 따른다. 데이터셋 본문, 강좌 분할 목록, 다운로드 경로는 서비스 DB에 두지 않는다.

### 8.2.24 training_runs — 학습 작업 복사본

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | training_run_id | UUID | O | O | - | 서비스 요청 ID(= 학습서버 request_id) |
| 2 | dataset_id | UUID | O | - | O | datasets |
| 3 | requested_by | UUID | - | - | O | ADMIN users |
| 4 | job_id | VARCHAR(20) | - | - | - | 학습서버 train-NNNN |
| 5 | status | VARCHAR(16) | O | - | - | QUEUED / RUNNING / SUCCEEDED / FAILED / HELD / CANCELLED |
| 6 | stage | VARCHAR(16) | - | - | - | train / export / eval / register |
| 7 | hold_reason | VARCHAR(24) | - | - | - | precision_drop / below_target |
| 8 | progress | NUMERIC(4,3) | - | - | - | 진행률 0~1 |
| 9 | config | JSONB | O | - | - | 요청 설정(epochs · batch_size · learning_rate) |
| 10 | learning_curve | JSONB | O | - | - | 에폭별 손실 · 검증 AUC |
| 11 | metrics | JSONB | O | - | - | roc_auc · false_answer_rate · tpr · threshold · precision_auc_drop · latency_p95_ms · baselines · 검색 성공률 · 근거 적중률 |
| 12 | model_version | VARCHAR(20) | - | - | - | 등록된 judge-vN |
| 13 | deployable | BOOLEAN | - | - | - | 등록 당시 비교 결과 |
| 14 | error_code | VARCHAR(40) | - | - | - | 실패 코드 |
| 15 | started_at · finished_at | TIMESTAMPTZ | - | - | - | 학습서버 시작 · 완료 시각 |
| 16 | synced_at | TIMESTAMPTZ | - | - | - | 7.4.8 동기화 시각 |
| 17 | created_at | TIMESTAMPTZ | O | - | - | 요청 시각 |

학습서버 작업 상태가 원본이며 worker는 7.4.8만 주기적으로 조회한다.

### 8.2.25 model_versions — 모델 버전 복사본

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | model_version_id | UUID | O | O | - | 서비스 ID |
| 2 | training_run_id | UUID | - | - | O | training_runs(수동 등록이면 NULL) |
| 3 | version_name | VARCHAR(20) | O | - | - | judge-vN, UNIQUE |
| 4 | artifact_uri | TEXT | O | - | - | 학과 서버 모델 패키지 경로 |
| 5 | artifact_sha256 | CHAR(64) | O | - | - | model.safetensors 해시(검증은 학습서버) |
| 6 | threshold | NUMERIC(8,5) | O | - | - | τ |
| 7 | status | VARCHAR(16) | O | - | - | REGISTERED / DELETED |
| 8 | deployable | BOOLEAN | O | - | - | 등록 당시 서빙 대비 비교 결과 |
| 9 | compared_with | VARCHAR(20) | - | - | - | 비교한 서빙 버전 |
| 10 | serving | BOOLEAN | O | - | - | 현재 서빙 여부 |
| 11 | served_before | BOOLEAN | O | - | - | 서빙 이력. true인 버전만 롤백 대상 |
| 12 | metrics | JSONB | O | - | - | roc_auc · false_answer_rate · tpr · precision_auc_drop · latency_p95_ms · baselines |
| 13 | evaluation_contract | JSONB | O | - | - | format = pytorch-fp16, validation_set_version, test_set_version, threshold_rule, evaluation_id |
| 14 | memo | VARCHAR(500) | - | - | - | 버전 메모 |
| 15 | synced_at | TIMESTAMPTZ | O | - | - | 동기화 시각 |

7.4.17 · 7.4.18이 원본이다. 사용자 데이터 삭제로 모델을 막거나 지우지 않는다.

### 8.2.26 evaluation_runs — 평가 결과 복사본

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | evaluation_id | UUID | O | O | - | 서비스 ID |
| 2 | external_evaluation_id | VARCHAR(20) | O | - | - | 학습서버 eval-NNNN |
| 3 | model_version_id | UUID | - | - | O | model_versions(베이스라인이면 NULL) |
| 4 | dataset_id | UUID | O | - | O | datasets |
| 5 | evaluator | VARCHAR(16) | O | - | - | CUSTOM / SIMILARITY / PRETRAINED / SONNET_ONLY |
| 6 | scope | VARCHAR(10) | O | - | - | QUESTION / PAIR / SERVICE |
| 7 | split | VARCHAR(10) | O | - | - | VALIDATION / TEST |
| 8 | config | JSONB | O | - | - | model_format(fp16 / fp32), retrieval_config_version, llm_model_id, llm_prompt_version, 후보 20 |
| 9 | metrics | JSONB | O | - | - | 8.2.36의 평가 지표 |
| 10 | test_use_count | INTEGER | - | - | - | 평가 시점의 시험셋 사용 횟수 |
| 11 | synced_at | TIMESTAMPTZ | O | - | - | 동기화 시각 |

평가 실행과 τ 선정은 학습서버가 한다(6.4.8). QUESTION 지표와 PAIR 지표를 섞어 쓰지 않는다.

### 8.2.27 deployments — 서빙 전환 요청 이력

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | deployment_id | UUID | O | O | - | 요청 이력 ID |
| 2 | model_version_id | UUID | - | - | O | 요청한 model_versions(LLM_ONLY면 NULL) |
| 3 | mode | VARCHAR(12) | O | - | - | CUSTOM / LLM_ONLY |
| 4 | operation | VARCHAR(12) | O | - | - | SWITCH(7.4.22) / ROLLBACK(7.4.23) |
| 5 | requested_by | UUID | O | - | O | ADMIN users |
| 6 | previous_deployment_id | UUID | - | - | O | 직전 이력 |
| 7 | status | VARCHAR(16) | O | - | - | PENDING / ACTIVE / SUPERSEDED / FAILED |
| 8 | reason | VARCHAR(500) | O | - | - | 전환 · 롤백 사유 |
| 9 | serving_snapshot | JSONB | O | - | - | 7.4.21의 mode · 버전 · τ · τ_LLM · llm_model_id · llm_prompt_version · deployed_at |
| 10 | error_code | VARCHAR(40) | - | - | - | 실패 코드 |
| 11 | synced_at | TIMESTAMPTZ | - | - | - | 실제 설정 확인 시각 |
| 12 | created_at | TIMESTAMPTZ | O | - | - | 요청 시각 |

요청 이력은 서비스 DB가 원본이고 실제 서빙 설정은 7.4.21이 원본이다. ACTIVE는 하나만 허용한다(부분 UNIQUE). AI 담당자가 학과 서버에서 직접 바꾼 설정을 발견하면 serving_snapshot을 갱신하고 감사 기록을 남긴다.

### 8.2.28 jobs — 비동기 작업

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | job_id | UUID | O | O | - | 작업 ID |
| 2 | session_id | UUID | - | - | O | lecture_sessions, 삭제 후 SET NULL |
| 3 | requested_by | UUID | - | - | O | 요청 회원, 삭제 후 SET NULL |
| 4 | participant_id | UUID | - | - | O | 요청 게스트, 삭제 후 SET NULL |
| 5 | job_type | VARCHAR(24) | O | - | - | INGEST / TRANSCRIPT_INDEX / QA / FINALIZE / SUMMARY / AUTO_END / PURGE / CLEANUP / DATASET / TRAIN / DEPLOY / SYNC / EMAIL_VERIFICATION / PASSWORD_RESET / AUTH_REVOKE |
| 6 | target_id | UUID | O | - | - | 유형별 대상 ID |
| 7 | status | VARCHAR(12) | O | - | - | QUEUED / RUNNING / SUCCEEDED / FAILED / CANCELLED / HELD |
| 8 | idempotency_key | VARCHAR(200) | O | - | - | 작업 종류 · 대상 · 버전 조합, UNIQUE |
| 9 | payload | JSONB | O | - | - | 대상 ID · 요청 해시 · 삭제 범위 등. 원문 · 코드 · 비밀번호 제외 |
| 10 | attempts | SMALLINT | O | - | - | 시도 횟수 |
| 11 | available_at | TIMESTAMPTZ | O | - | - | 실행 가능 시각(AUTO_END는 started_at + 12시간) |
| 12 | lease_until | TIMESTAMPTZ | - | - | - | 점유 만료 시각 |
| 13 | lease_token | UUID | - | - | - | 현재 점유 표식. 만료된 점유의 늦은 저장 차단 |
| 14 | error_code | VARCHAR(40) | - | - | - | 최종 실패 코드 |
| 15 | result | JSONB | - | - | - | 원문 없는 결과(병합 새 버전 · 건수 등) |
| 16 | created_at | TIMESTAMPTZ | O | - | - | 생성 시각 |
| 17 | finished_at | TIMESTAMPTZ | - | - | - | 완료 시각 |

질문과 질문 작업은 한 트랜잭션으로 만든다. 결과는 lease_token이 일치할 때만 저장한다. FINALIZE는 강연 종료 때 진행 중인 질문 · 마지막 발화를 정리하고, 공감 수를 고정하고, 게스트 닉네임과 학습 미동의 게스트 개인 질문 · 답변 내용을 지우고, 게스트 세션 폐기(AUTH_REVOKE)와 SUMMARY를 한 번 만든다. CLEANUP은 미인증 계정 · 만료된 인증 기록 · 제한 카운터 · 전달 끝난 ws_events를 정리한다. PURGE는 매일 원자료 파기와 삭제 요청을 처리한다.

### 8.2.29 ws_events — 실시간 전달 이벤트

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | event_id | BIGSERIAL | O | O | - | 재조회 순서 |
| 2 | session_id | UUID | - | - | O | lecture_sessions(session.revoked만 NULL 허용) |
| 3 | question_id | UUID | - | - | O | 질문 관련 이벤트면 필수 |
| 4 | event_type | VARCHAR(40) | O | - | - | question.progress, answer.delta · completed · discarded · retracted, public_question.updated, document.updated, session.updated, summary.updated, auth.csrf_rotated, session.revoked 등 |
| 5 | generation_id | UUID | - | - | - | 답변 생성 시도 구분 |
| 6 | sequence | INTEGER | - | - | - | 생성 시도 안의 조각 순번 |
| 7 | payload | JSONB | O | - | - | 임시 글자 조각 또는 결과 ID. 쿠키 · 키 · 음성 금지 |
| 8 | created_at | TIMESTAMPTZ | O | - | - | 생성 시각 |
| 9 | expires_at | TIMESTAMPTZ | O | - | - | 정리 시각 |

worker는 결과와 이벤트를 함께 커밋하고 NOTIFY로 event_id만 알린다. (generation_id, sequence, event_type)에 UNIQUE를 둔다. 답변이 확정 · 폐기 · 철회되면 관련 answer.delta를 바로 지운다. session.revoked는 auth가 남기는 내부 이벤트로, backend가 해당 연결을 닫는 데만 쓰고 브라우저로 보내지 않는다.

### 8.2.30 audit_events — 감사 기록

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | audit_event_id | UUID | O | O | - | 감사 ID |
| 2 | actor_user_id | UUID | - | - | O | users, 탈퇴 후 SET NULL |
| 3 | action | VARCHAR(50) | O | - | - | USER_SUSPENDED, USER_RESTORED, SESSION_FORCE_ENDED, EVAL_LECTURE_MARKED, ANSWER_RETRACTED, DATASET_MERGED, TRAINING_REQUESTED, DEPLOYMENT_REQUESTED 등 |
| 4 | target_type | VARCHAR(30) | O | - | - | USER / SESSION / ANSWER / DATASET / MODEL / DEPLOYMENT |
| 5 | target_ref | VARCHAR(100) | O | - | - | 가명 처리한 대상 참조 |
| 6 | changes | JSONB | O | - | - | 허용 필드의 이전 · 이후 값. 질문 · 답변 · 필기 원문 제외 |
| 7 | reason | VARCHAR(500) | - | - | - | 사유 |
| 8 | request_id | UUID | O | - | - | 요청 추적 ID |
| 9 | created_at | TIMESTAMPTZ | O | - | - | 발생 시각 |

관리자 변경과 감사 기록은 같은 트랜잭션으로 저장하며, 감사 기록이 실패하면 변경도 되돌린다.

### 8.2.31 api_usage — 외부 API 호출량 · 비용

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | usage_id | UUID | O | O | - | 호출 ID |
| 2 | session_id | UUID | - | - | O | lecture_sessions, 삭제 후 SET NULL |
| 3 | question_id | UUID | - | - | O | questions, 삭제 후 SET NULL |
| 4 | provider | VARCHAR(30) | O | - | - | 외부 제공자 |
| 5 | model_name | VARCHAR(100) | O | - | - | 실제 호출 모델 |
| 6 | operation | VARCHAR(20) | O | - | - | STT / EMBEDDING / JUDGE_LLM / ANSWER / SUMMARY / EMAIL |
| 7 | input_tokens · output_tokens | BIGINT | - | - | - | 제공자가 보고한 토큰 |
| 8 | audio_ms | BIGINT | - | - | - | 처리 음성 길이 |
| 9 | estimated_cost | NUMERIC(18,8) | - | - | - | 추정 비용(가격 미확인이면 NULL) |
| 10 | currency | CHAR(3) | O | - | - | 통화, 기본 USD |
| 11 | price_version | VARCHAR(50) | - | - | - | 적용 가격표 버전 |
| 12 | latency_ms | INTEGER | O | - | - | 호출 소요 시간 |
| 13 | outcome | VARCHAR(10) | O | - | - | SUCCESS / TIMEOUT / ERROR |
| 14 | request_id | UUID | O | - | - | 추적 ID |
| 15 | created_at | TIMESTAMPTZ | O | - | - | 호출 시각 |

### 8.2.32 notices — 공지

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | notice_id | UUID | O | O | - | 공지 ID |
| 2 | author_user_id | UUID | - | - | O | users(ADMIN), 탈퇴 · 삭제 시 SET NULL |
| 3 | title | VARCHAR(100) | O | - | - | 제목 |
| 4 | content | TEXT | O | - | - | 내용(≤ 2,000자) |
| 5 | version | INTEGER | O | - | - | 수정 낙관적 잠금, 초기 1 |
| 6 | deleted_at | TIMESTAMPTZ | - | - | - | 삭제 시각. 값이 있으면 목록에서 뺌 |
| 7 | created_at · updated_at | TIMESTAMPTZ | O | - | - | 게시 · 수정 시각 |

공지 · 문의는 F13-1(Should)이다. 공지는 회원 전체에 같은 내용을 보이며 개인정보를 담지 않는다.

### 8.2.33 inquiries — 1:1 문의

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | inquiry_id | UUID | O | O | - | 문의 ID |
| 2 | user_id | UUID | O | - | O | users, 회원 탈퇴 시 CASCADE 삭제 |
| 3 | title | VARCHAR(100) | O | - | - | 제목 |
| 4 | content | TEXT | O | - | - | 내용(≤ 2,000자) |
| 5 | status | VARCHAR(10) | O | - | - | WAITING / ANSWERED |
| 6 | reply | TEXT | - | - | - | 관리자 답변(≤ 2,000자) |
| 7 | replied_by | UUID | - | - | O | users(ADMIN), SET NULL |
| 8 | replied_at | TIMESTAMPTZ | - | - | - | 답변 시각 |
| 9 | created_at | TIMESTAMPTZ | O | - | - | 문의 시각 |

문의는 회원 본인과 ADMIN만 본다. 학습 · 요약 · 운영 지표에 쓰지 않는다.

### 8.2.34 app_settings — 운영 설정

| NO | Attribute | Data Type | NN | PK | FK | Description |
|---|---|---|---|---|---|---|
| 1 | setting_key | VARCHAR(40) | O | O | - | 설정 이름. 현재 MONTHLY_API_BUDGET 하나 |
| 2 | value | JSONB | O | - | - | {monthly_budget_krw, usd_krw_rate} |
| 3 | updated_by | UUID | - | - | O | users(ADMIN), SET NULL |
| 4 | updated_at | TIMESTAMPTZ | O | - | - | 변경 시각 |

월 사용액은 api_usage의 이번 달 estimated_cost를 통화별로 합해 usd_krw_rate로 원화로 바꿔 계산하고 저장하지 않는다. 사용률 80% 이상이면 운영 지표에 경고를 표시한다. 예산을 넘어도 서비스 동작은 바꾸지 않는다.

### 8.2.35 주요 인덱스와 무결성

| 대상 | 인덱스 · 제약 | 목적 |
|---|---|---|
| lecture_sessions | (host_user_id, status, scheduled_at), (raw_data_expires_at), (status, started_at), join_code UNIQUE, previous_join_code UNIQUE | 내 강연 목록(예정 · 진행 중 · 지난), 90일 파기, 12시간 자동 종료, 입장 코드 확인 |
| participants (정원) | (session_id, status) | 활성 참가자 수 확인(정원 50) |
| notices · inquiries | notices (deleted_at, created_at DESC), inquiries (user_id, created_at DESC) · (status, created_at) | 공지 목록, 내 문의 · 답변 대기 목록 |
| participants | 회원 (session_id, user_id) 부분 UNIQUE, (user_id, archived) | 중복 참가 방지, 보관함 목록 |
| knowledge_chunks | (session_id, source_type, index_status), embedding HNSW, search_vector GIN, (session_id, source_key) UNIQUE | 강연별 벡터 · 키워드 검색, 발화 중복 방지 |
| questions | (session_id, status, vote_count DESC, created_at), (participant_id, created_at), (participant_id, idempotency_key) UNIQUE | 공개 목록 · 내 질문 · 중복 제출 방지 |
| question_notes | (question_id, user_id) PK, (user_id) | 필기 1개 보장, 회원 삭제 |
| votes · label_reviews · answer_feedback | 복합 PK | 중복 공감 · 표결 · 평가 방지 |
| email_verifications · password_resets | (user_id) 부분 UNIQUE(미사용 · 미폐기) | 유효 기록 1개 |
| deployments | ACTIVE 부분 UNIQUE | 동시 활성 충돌 방지 |
| jobs | idempotency_key UNIQUE, (status, available_at) | 중복 작업 방지 · 재처리 |
| api_usage | (created_at, operation), (session_id, created_at) | 일별 · 강연별 지표 |

벡터 · 키워드 검색은 모두 같은 강연 · READY 상태로 제한하고, 결과가 모자라도 다른 강연의 조각으로 채우지 않는다.

### 8.2.36 판정 · 평가 기록 형식

- **questions.decision_snapshot**: mode(CUSTOM / LLM_ONLY), route(CUSTOM / FALLBACK_LLM_ONLY / FIXED_LLM_ONLY), fallback_reason, model_version, threshold, llm_model_id, llm_prompt_version, llm_only_threshold, candidate_scores(조각 ID · 점수 · 순위), top_evidence_id, selected_evidence_ids, retrieval_config_version, second_stage_escalated, judge_ms, progress_ms(접수부터 첫 진행 상태 전달까지), first_token_ms, final_ms. CUSTOM과 LLM_ONLY의 점수 범위는 구분해서 기록한다.
- **evaluation_runs.metrics**: 질문 단위 ROC-AUC · 오답 즉답률 · TPR(95% 오차 범위), valid_auc_fp32 · valid_auc_fp16 · precision_auc_drop, latency_p95_ms, 라벨별 이관율(의견 질문 이관율), 질문 출처별 결과, 쌍 단위 ROC-AUC, 검색 성공률, 검색 실패 시 즉답률, 근거 적중률(top-1), 표본 수. QUESTION 평가는 정답 근거가 후보에 든 답변 가능 질문과 이관 대상 질문을, SERVICE 평가는 시험셋 전체를 쓴다.
- **검색 설정 버전(retrieval_config_version)**: 청킹 규칙(교안 조각 · 발화 30초), 임베딩 모델 · 차원, Kiwi 버전, RRF 결합, 후보 수 20, 코드 버전을 묶은 불변 버전이다. 설정 파일은 코드와 함께 버전 관리한다.

### 8.2.37 보관 · 삭제 · 동의 철회

| 대상 | 처리 |
|---|---|
| 강연자 음성 | STT 중계용 메모리만 쓰며 디스크 · S3 · 로그에 저장하지 않음 |
| 게스트 닉네임, 학습 미동의 게스트의 개인 질문 · 답변 내용 | 강연 종료 정리(FINALIZE) 때 삭제. 질문 · 답변 행은 내용 없이 상태 · 시간만 남김 |
| 강연 원자료(교안 원본 · 조각 · 발화 · 벡터 · 색인, 학습 동의 게스트의 개인 질문 · 답변, 게스트 참가 행과 게스트 공감 행, 미병합 후보) | 종료 후 90일 또는 강연자 삭제 때 파기, 강연은 PURGED. 인용의 chunk_id는 NULL |
| 강연 기록(제목 · 날짜 · 강연자 표시명 · 요약 노트 · 공개 질문과 공감 수 · 완료 여부) | 보관함에 남긴 회원이 있는 동안 유지. 마지막 회원이 지우거나 탈퇴하고 강연자도 지웠거나 탈퇴하면 삭제 |
| 회원 개인 기록(내 질문 · 내 답변 · 인용 위치 · 필기 · 내 공감 표시) | 회원이 지우거나(질문 · 보관함 강연) 탈퇴할 때까지 보관. 공개 질문은 작성자 연결만 끊고 강연 기록에 남김 |
| 미병합 후보 | 원천 삭제 · 학습 동의 철회 · 원자료 파기 때 후보 · 검수 · 출처 연결 삭제 |
| 병합 중 후보 | merge_request_id로 실제 병합 여부를 확인한 뒤 미병합이면 삭제, 병합됐으면 완료 정리 |
| 병합된 데이터셋 · 학습된 모델 | 원래 질문과 연결이 끊긴 익명 데이터라 삭제 · 철회의 대상이 아님 |
| 1:1 문의 | 회원 탈퇴 때 삭제 |
| 공지 | 관리자가 삭제할 때까지 보관(삭제는 deleted_at 표시) |
| 인증 기록 · 제한 카운터 · ws_events | 사용 · 만료 후 24시간 안에 정리 |

파기 순서는 접근 차단 → 진행 중 작업 결과 저장 차단 → 미병합 후보 · 임시 이벤트 정리 → S3 객체 삭제 → DB 행 · 벡터 · 색인 삭제 → 확인이다. S3 삭제가 실패하면 접근을 막은 채 다시 시도한다.

### 8.2.38 학습서버 레지스트리 DB

학과 서버의 학습서버가 쓰는 DB다. 서비스 DB 복사본의 원본이며, 7.4 API의 필드 이름을 그대로 쓴다.

표: 학습서버 레지스트리 테이블

| 테이블 | 주요 컬럼 | 설명 |
|---|---|---|
| reg_datasets | dataset_version(PK), parent_version, status, contains_aihub, statistics, courses_by_split, gold_in_candidates_rate, script_version, retrieval_config_version, validation_set_version, test_set_version, eval_slide_version, storage_uri, change_note, created_at | 데이터셋 버전. 등록 후 수정하지 않음 |
| reg_test_sets | test_set_version(PK), test_use_count, created_at | 시험셋 버전별 사용 횟수 |
| reg_train_configs | config_id(PK), config(JSONB), is_default, created_at | 기본 학습 파라미터와 변경 이력 |
| reg_jobs | job_id(PK, train · eval · export · collect-NNNN), type, request_id(UNIQUE), status, stage, hold_reason, progress, config, curve, best_epoch, checkpoint_uri, export_job_id, evaluation_id, model_version, result, fault_id, created_at, finished_at | 수집 · 학습 · 변환 · 평가 작업 |
| reg_evaluations | evaluation_id(PK), target, dataset_version, validation_set_version, test_set_version, retrieval_config_version, threshold, metrics(JSONB), baselines(JSONB), llm_only(JSONB), roc_points, test_use_count, created_at | 평가 결과(7.4.13) |
| reg_models | model_version(PK), dataset_version, evaluation_id, artifact_uri, manifest(JSONB), threshold, status, deployable, compared_with, served_before, memo, created_at | 모델 버전 레지스트리 |
| reg_deployments | deployment_seq(PK), mode, serving_version, previous_version, threshold, llm_only_threshold, llm_model_id, llm_prompt_version, operation(SWITCH / ROLLBACK), reason, deployed_at | 서빙 설정 이력. 마지막 행이 현재 설정 |
| reg_eval_slide_chunks | (eval_slide_version, chunk_key)(PK), course_id, page_no, text | 평가용 교안 조각 목록(7.4.28) |
| reg_merge_requests | request_id(PK), base_version, result_version, added, excluded_overlap, masked, skipped, created_at | 병합 요청 멱등 처리(7.4.5) |
| reg_faults | fault_id(PK), occurred_at, code, module, job_id, message | 장애 기록(7.4.27) |

reg_models.served_before는 서빙된 적이 있으면 true가 되고 되돌리지 않는다. 서빙 중 버전과 직전 서빙 버전은 DELETED로 바꿀 수 없다. 레지스트리 DB에는 AI Hub 원문을 두지 않고, 데이터셋 본문은 /data/easyq/datasets/의 파일로만 둔다.

## 8.3 로그 파일 설계

### 8.3.1 파일 종류와 로그 레벨

UTF-8 JSON Lines로 한 줄에 한 이벤트를 기록한다. 운영 환경은 INFO 이상만 기록하고 DEBUG는 개발 환경에서만 쓴다. {date}는 UTC YYYY-MM-DD, {instance}는 프로세스 식별자다.

표: 로그 파일

| 파일 | 위치 | 레벨 | 기록 내용 | 보관 기간 |
|---|---|---|---|---|
| access-{date}-{instance}.jsonl | EC2 | INFO · WARN | HTTP 메서드, 경로 템플릿, 상태 코드, 응답 시간 | 14일 |
| application-{date}-{instance}.jsonl | EC2 | INFO · WARN · ERROR | 인증 · 강연 · 교안 · 작업 상태 변화 | 30일 |
| realtime-{date}-{instance}.jsonl | EC2 | INFO · WARN · ERROR | WebSocket 연결 · 종료, STT 상태, 마지막 정상 수신 시각 | 14일 |
| rag-{date}-{instance}.jsonl | EC2 | INFO · WARN · ERROR | 검색 건수, 점수, 임계값, 판정 경로, 이관 사유, 단계별 시간 | 30일 |
| usage-{date}-{instance}.jsonl | EC2 | INFO · WARN | 외부 호출 단위 · 토큰 · 시간 · 추정 비용 | 90일 |
| audit-{date}-{instance}.jsonl | EC2 | INFO · WARN | 계정 정지 · 복구, 철회, 강제 종료, 병합 · 학습 · 배포 요청, 삭제 | 90일 |
| error-{date}-{instance}.jsonl | EC2 | WARN · ERROR · CRITICAL | 사용자 처리 실패와 내부 예외(8.4.3 형식) | 30일 |
| trainer-{date}.jsonl | 학과 서버 /data/easyq/logs | INFO · WARN · ERROR | 학습서버 작업 시작 · 단계 전환 · 완료(service = training) | 90일 |
| fault-{date}.jsonl | 학과 서버 /data/easyq/logs | ERROR · CRITICAL | 학습서버 수집 · 학습 · 변환 · 평가 · 서빙 · 추론 오류(reg_faults와 같은 내용) | 90일 |

표: 로그 레벨

| 레벨 | 의미 | 예시 |
|---|---|---|
| DEBUG | 개발 중 원문 없는 상세 진단 | 검색 단계별 후보 수 |
| INFO | 정상 동작 · 상태 변화 | 질문 접수, AI 답변 확정, 근거 부족 이관 |
| WARN | 처리 가능한 실패 · 품질 저하 | 요청 한도 초과, STT 재연결, 질문별 LLM_ONLY |
| ERROR | 해당 작업의 실패 | 교안 파싱 실패, 요약 최종 실패 |
| CRITICAL | 서비스 지속에 영향을 주는 장애 | RDS 연결 불가, 파기 작업 계속 실패 |

인증 로그는 service = auth, 메일 작업은 service = worker로 구분한다. 인증 관련 이벤트(email.verification_queued · sent · failed · completed, password_reset.requested · completed, auth.session_created · revoked)와 필기 이벤트(note.saved · deleted)를 남긴다. 인증 완료는 가입 때 한 번만 기록하며 로그인 성공을 인증 완료로 기록하지 않는다.

### 8.3.2 공통 로그 필드

| 필드 | 형식 | 필수 | 설명 |
|---|---|---|---|
| timestamp | datetime | O | UTC 발생 시각 |
| level | string | O | 로그 레벨 |
| service | string | O | auth / api / worker / training |
| event | string | O | question.decided 같은 고정 이벤트 이름 |
| request_id | UUID | O | 요청 · 작업 연결 ID |
| trace_id | UUID | O | 외부 호출까지 묶는 처리 흐름 ID |
| actor_ref | string | - | 회원 · 게스트 ID의 HMAC 가명 |
| session_ref · question_ref · job_ref | string | - | 대상별 가명 참조 |
| duration_ms | integer | - | 단계 소요 시간 |
| code | string | O | OK 또는 8.4 오류 코드 |
| message | string | O | 고정 템플릿의 짧은 설명 |
| meta | object | O | 이벤트별 허용 필드, 기본 {} |

질문 · 답변 · 필기 · 교안 · 발화 원문, 비밀번호, 인증 코드 · 재설정 토큰과 그 검증값, 발송 암호화 봉투, 쿠키, Authorization 헤더, QR 토큰, 사전 서명 URL, 외부 API 키 · SMTP 자격 증명은 기록하지 않는다. 이메일 · IP는 원문 대신 HMAC 참조를 쓰고, 경로는 실제 UUID 대신 템플릿(/sessions/{session_id}/questions)으로 남긴다. 제어 문자는 JSON 인코더로 이스케이프한다.

```
{"timestamp":"2026-11-17T05:30:02.400Z","level":"INFO","service":"worker","event":"question.decided",
 "request_id":"0000…0101","trace_id":"0000…0102","session_ref":"hmac:s1","question_ref":"hmac:q1",
 "duration_ms":1520,"code":"OK","message":"AI 답변 경로 확정",
 "meta":{"route":"CUSTOM","model_version":"judge-v1","score":0.91,"threshold":0.83,"retrieved_count":20,"judge_ms":95}}
```

### 8.3.3 회전 · 수집 · 운영

파일은 UTC 날짜가 바뀌거나 100 MiB가 되면 회전하고 닫힌 파일을 압축한다. 여러 프로세스가 같은 파일에 쓰지 않도록 프로세스별로 나눈다. 운영 로그는 허용된 운영자만 읽고, 애플리케이션은 추가 기록만 한다. 보관 기간이 지난 파일은 매일 지운다.

지표 · 감사의 기준은 DB의 api_usage와 audit_events이고, 파일은 진단 · 추적에 쓴다. 로그 파일 장애는 원문 없이 stderr로 알린다. 평가용 강의 검사 로그에는 eval_slide_version · retrieval_config_version · matched_chunks · total_chunks · match_ratio와 결과만 남기고 교안 본문은 남기지 않는다. 후보 정리 로그는 기준 시각 · 삭제 건수 · 제외 건수만 남긴다. 판정 · 철회 · 청중 평가 로그는 같은 HMAC 질문 참조로 원문 없이 연결한다. 학습 · 평가 로그에는 model_format(pytorch-fp16), test_set_version, test_use_count, hold_reason을 넣는다.

## 8.4 오류 코드 및 오류 파일 설계

### 8.4.1 오류 응답 원칙

HTTP 상태 코드는 통신 결과를, error.code는 업무 원인을 나타낸다. 근거 부족 · 의견 질문으로 인한 이관은 정상 처리이며 오류가 아니다.

```
{ "request_id": "0000…0101",
  "error": { "code": "SESSION_NOT_LIVE", "message": "질문을 등록할 수 있는 강연 상태가 아닙니다.",
             "details": { "status": "ENDED" }, "retryable": false } }
```

비동기 작업의 실패는 처음 응답한 202를 바꾸지 않는다. 작업 조회(API-41)의 200 응답에 status = FAILED와 error_code를 담고, WebSocket이 열린 뒤의 오류는 error 이벤트로 보낸다.

### 8.4.2 서비스 오류 코드

| 오류 코드 | HTTP | 발생 조건 | 처리 |
|---|---|---|---|
| VALIDATION_ERROR | 422 | 형식 · 길이 · 범위 · 필수값 위반 | 필드별 설명 반환 |
| AUTH_REQUIRED | 401 | 쿠키 없음 · 만료 · 폐기 | 다시 로그인 또는 QR 재입장 |
| AUTH_INVALID_CREDENTIALS | 401 | 로그인 · 현재 비밀번호 확인 실패 | 이메일 존재 여부를 구분하지 않음 |
| EMAIL_NOT_VERIFIED | 403 | 비밀번호는 맞지만 가입 이메일 인증 전 | 인증 화면 안내, 세션 발급 안 함 |
| EMAIL_VERIFICATION_INVALID | 422 | 코드 불일치 · 만료 · 사용 · 폐기 · 대상 없음 | 코드 다시 입력 또는 재발송 |
| EMAIL_VERIFICATION_ATTEMPTS_EXCEEDED | 429 | 인증 기록 5회 실패 | 기록 폐기, 한도 안에서 재발송 |
| RESET_TOKEN_INVALID | 422 | 재설정 토큰 불일치 · 만료 · 사용 | 재설정 다시 요청 |
| ACCOUNT_SUSPENDED | 403 | 정지 계정 | 접속 차단, WebSocket 종료. 로그인 응답 details에 정지 사유 |
| RECENT_LOGIN_REQUIRED | 403 | 탈퇴 요청 시 최근 10분 안 로그인이 아님 | 다시 로그인 후 요청 |
| FORBIDDEN | 403 | 역할 · 소유 · CSRF · Origin 확인 실패, 게스트의 회원 전용 기능 | 자동 재시도 안 함 |
| CONSENT_REQUIRED | 403 | 서비스 · 음성 동의 없음 | 해당 동의 요청 |
| RESOURCE_NOT_FOUND | 404 | 대상 없음 또는 숨겨야 하는 타인 개인 데이터 | 존재 여부를 드러내지 않음 |
| JOIN_CODE_INVALID | 404 | 없는 입장 코드 · 토큰 | QR · 코드 확인 |
| JOIN_CODE_REVOKED | 410 | 재발급으로 무효가 된 바로 전 입장 코드 | 새 QR로 입장 안내 |
| EMAIL_ALREADY_EXISTS | 409 | 이미 가입한 이메일 | 로그인 · 재발송 안내 |
| VERSION_CONFLICT | 409 | If-Match 버전 불일치 | 다시 조회 후 요청 |
| IDEMPOTENCY_CONFLICT | 409 | 같은 키로 다른 본문 | 새 작업이면 새 키 |
| SESSION_NOT_LIVE | 409 | LIVE가 아닌 강연에서 질문 · 공감 · 철회 · 완료 | 상태 갱신 |
| SESSION_ENDED | 409 | 종료 · 파기된 강연에 입장 | 회원은 보관함 안내 |
| SESSION_FULL | 409 | 정원 50명이 찬 강연에 새로 입장 | 입장 불가 안내 |
| HOSTING_LIVE_SESSION | 409 | 진행 중인 강연의 강연자가 탈퇴 요청 | 강연 종료 후 탈퇴 안내 |
| DOCUMENT_NOT_RETRYABLE | 409 | FAILED가 아니거나 원본 때문에 실패한 교안의 재시도 | 삭제 후 새 파일 업로드 |
| SESSION_STATE_CONFLICT | 409 | 허용하지 않는 상태 전이(DRAFT 강제 종료, LIVE 중 강연 정보 · 용어 수정 등), 마지막 관리자 정지 | 상태 갱신 |
| QUESTION_NOT_PUBLIC | 409 | 공개 질문이 아닌데 공감 · 필기 | 목록 갱신 |
| ANSWER_NOT_ACTIVE | 409 | 철회 · 삭제된 답변의 철회 · 평가 | 질문 상태 다시 조회 |
| FILE_TOO_LARGE | 413 | 50 MiB 초과 | 파일 크기 줄이기 |
| FILE_TYPE_UNSUPPORTED | 415 | PDF · PPTX가 아닌 파일 | 지원 형식 업로드 |
| RATE_LIMITED | 429 | 가입 · 로그인 · 인증 메일 · 코드 확인 · 재설정 메일 · 입장 코드 실패 한도 초과 | Retry-After 뒤 재시도 |
| REVIEW_CONFLICT | 409 | 두 검수 결과 불일치 상태에서 확정 시도 | 재검수 |
| CANDIDATE_NOT_ELIGIBLE | 409 | 미승인 · 동의 철회 · 평가용 강의 후보 | 후보 제외 |
| DATASET_NOT_READY | 409 | 사용할 수 없는 데이터셋 버전 | 다른 버전 선택 |
| TRAINER_BUSY | 409 | 학습서버 GPU 사용 중(609) | 실행 중 작업이 끝난 뒤 요청 |
| LIVE_SESSION_IN_PROGRESS | 409 | 진행 중(LIVE)인 강연이 있는 동안 학습 요청 | 강연이 끝난 뒤 요청 |
| TRAINING_ALREADY_FINISHED | 409 | 끝난 학습 중단 요청(608) | 현재 상태 조회 |
| MODEL_NOT_DEPLOYABLE | 409 | 배포 불가 버전, 서빙 이력 조건 위반(610) | 다른 버전 선택 |
| DEPLOY_CRITERIA_NOT_MET | 409 | 전환 시점 배포 기준 미달(614) | 기존 서빙 유지 |
| AUTH_SERVICE_UNAVAILABLE | 503 | auth 응답 없음(가입 · 인증 · 로그인 · 게스트 세션 발급) | 새 발급 실패, 기존 세션은 유지 |
| SERVICE_UNAVAILABLE | 503 | RDS · 작업 접수 불가 | 접수 성공으로 표시하지 않음 |
| INTERNAL_ERROR | 500 | 분류되지 않은 예외 | 일반 메시지와 request_id |
| DOCUMENT_PARSE_FAILED | 작업 실패 | 손상 · 암호화 · 텍스트 없음 | 교안 교체 안내 |
| INDEX_BUILD_FAILED | 작업 실패 | 임베딩 · 색인 최종 실패 | 정해진 횟수 재시도 후 실패 표시 |
| EMAIL_DELIVERY_FAILED | 작업 실패 | SMTP 최종 실패 · 만료로 발송 불가 | 재발송 안내 |
| TRAINING_FAILED | 작업 실패 | 학습 · 변환 · 평가 실패(604 · 606 · 607) | 기존 모델 유지 |
| TRAINING_HELD | 작업 상태 | precision_drop / below_target(615) | HELD 표시, 이후 단계 중지 |
| DEPLOYMENT_FAILED | 작업 실패 | 적재 · 점검 실패(605) | 기존 서빙 유지 |
| DELETION_FAILED | 작업 실패 | S3 · DB 삭제 미완료 | 접근 차단 유지, 재시도 |
| EVAL_REFERENCE_UNAVAILABLE | 작업 상태 | 평가용 교안 조각 목록 미수신 · 검색 설정 버전 불일치 | 검사 PENDING, 후보 생성 보류, 7.4.28 재조회 |
| STT_UNAVAILABLE | WS 이벤트 | STT 연결 · 제공자 장애 | 자동 재연결, 인식 지연 표시 |
| MODEL_UNAVAILABLE | 내부 경고 | 판정 추론 800 ms 초과 · 오류(611) | 그 질문만 LLM_ONLY |
| GENERATION_FAILED | 내부 경고 | 답변 생성 · 인용 검증 실패 | AI 답변을 내지 않고 이관 |
| PROVIDER_RATE_LIMITED | 내부 경고 | 외부 API 호출 한도 | 제한 시간 안 재시도, 넘으면 이관 |

### 8.4.3 학습서버 오류 코드

학습서버 오류 코드는 이 표 한 곳에 정의하며, backend는 오른쪽 서비스 코드로 바꿔 관리자 화면 · 작업 결과에 남긴다.

| 코드 | 설명 | HTTP | 서비스 코드 |
|---|---|---|---|
| 200 | 정상 처리 | 200 · 201 · 202 | - |
| 600 | 정의되지 않은 오류 | 500 | INTERNAL_ERROR |
| 601 | 데이터셋 검증 오류(필드 · 라벨 · 분할 · 평가셋 형식 · 허용 경로 밖) | 400 | DATASET_NOT_READY |
| 602 | 데이터 수집 오류 | 500 | - (AI 담당자 전용) |
| 603 | 학습 파라미터 허용 범위 밖 | 400 | VALIDATION_ERROR |
| 604 | fp16 변환 오류 | 500 | TRAINING_FAILED |
| 605 | 서빙 전환 오류(적재 · 점검 실패) | 500 | DEPLOYMENT_FAILED |
| 606 | 학습 실패 | 500 | TRAINING_FAILED |
| 607 | 평가 오류 | 500 | TRAINING_FAILED |
| 608 | 중단할 수 없는 작업 | 409 | TRAINING_ALREADY_FINISHED |
| 609 | GPU 사용 중 | 409 | TRAINER_BUSY |
| 610 | 모델 버전 상태 오류(서빙 중 · 직전 버전 삭제, 서빙 이력 있는 버전의 전환, 이력 없는 버전의 롤백) | 409 | MODEL_NOT_DEPLOYABLE |
| 611 | 판정 추론 오류 · LLM_ONLY 모드 | 500 | MODEL_UNAVAILABLE |
| 612 | API 키 인증 오류 | 401 | INTERNAL_ERROR |
| 613 | 없는 데이터셋 · 모델 · 작업 · 평가 | 404 | RESOURCE_NOT_FOUND |
| 614 | 배포 기준 미달 | 409 | DEPLOY_CRITERIA_NOT_MET |
| 615 | 등록 조건 미달(fp16 평가가 등록 조건 · fp16 하락 · 추론 시간 기준을 넘지 못함) | 409 | TRAINING_HELD |

### 8.4.4 오류 파일 형식

서비스 오류 파일은 error-{date}-{instance}.jsonl, 학습서버 장애 파일은 fault-{date}.jsonl이며, 8.3.2 공통 필드에 아래 필드를 더한다.

| 필드 | 형식 | 설명 |
|---|---|---|
| exception_type | string? | 예외 클래스 이름 |
| stack_trace | string? | 내부 진단용. 지역 변수 · 요청 본문 · 비밀값 제거 |
| retryable | boolean | 같은 작업을 자동 재시도할 수 있는지 |
| attempt | integer | 현재 시도 횟수 |
| dependency | string? | db / s3 / stt / embedding / judge / llm / auth / smtp / trainer |
| recovery | string | retry / fallback / escalate / abort |

```
{"timestamp":"2026-11-17T05:31:00.000Z","level":"WARN","service":"worker","event":"judge.fallback",
 "request_id":"0000…0101","trace_id":"0000…0102","duration_ms":800,"code":"MODEL_UNAVAILABLE",
 "message":"판정 시간 초과로 질문별 LLM_ONLY 사용","meta":{"route":"FALLBACK_LLM_ONLY"},
 "exception_type":"TimeoutError","stack_trace":null,"retryable":false,"attempt":1,"dependency":"judge","recovery":"fallback"}
```

판정 추론이 실패해 LLM_ONLY로 넘어가는 것은 WARN이다. LLM_ONLY와 답변 생성까지 실패하면 PROVIDER_FAILURE 사유로 이관한다. 검색 근거가 없으면 장애 여부와 관계없이 답변을 만들지 않는다.
