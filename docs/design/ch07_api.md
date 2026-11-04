# 7장 인터페이스(API) 설계 — 수정본

> 표 · 그림 번호는 통합 때 매긴다. 서비스 API 번호는 기준표 §7(API-01~65), 학습서버 API 번호는 7.4.1~7.4.28이다. API마다 같은 순서(권한 · 정상 응답 / 입력 / 출력 / 처리 / 오류)로 적는다. 오류 코드의 뜻은 8.4에 한 번만 정의한다.

## 7.1 서버 · 클라이언트 구조

[그림: 서버 · 클라이언트 구조 — 브라우저, EC2(frontend · auth · backend · worker), RDS, S3, EC2 호스트 SSH 터널, 학과 서버 — 다시 그림]

표: 실행 단위와 통신

| 구성 | 실행 내용 | 통신 |
|---|---|---|
| 브라우저 | Next.js 화면 | 서비스 도메인의 /api/v1(REST)과 /api/v1/ws(WebSocket)만 호출 |
| frontend | Caddy, Next.js 서버 | 호스트의 80 · 443만 공개. 경로에 따라 auth:8001 또는 backend:8000으로 프록시(7.1.4) |
| auth | 회원가입 · 가입 이메일 인증 · 로그인 · 로그아웃 · 비밀번호 변경 · 재설정 · 인증 세션 · CSRF | RDS 5432. 내부 API(게스트 세션 발급 · 세션 폐기)를 backend · worker에 제공. 학습서버에 접근하지 않음 |
| backend | 강연 · 참가 · 질문 · 필기 · 관리 REST, WebSocket, 권한 확인, STT 중계 | RDS 5432(인증 정보는 제한된 조회 뷰만), 학습서버는 호스트 터널로 호출 |
| worker | 교안 · 색인 · 판정 · 답변 · 요약 · 메일 발송 · 인증 세션 폐기 재시도 · 병합 · 동기화 · 파기 | RDS 5432, S3, 외부 AI API, Gmail SMTP 587, 학습서버는 호스트 터널로 호출. 수신 포트 없음 |
| RDS | PostgreSQL 16 + pgvector | 같은 VPC의 EC2 보안 그룹에서만 접속. auth · backend · worker가 각각 최소 권한 DB 계정을 가짐 |
| EC2 호스트 | SSH 터널 서비스 | Docker bridge의 호스트 주소:9000 → 학과 서버 localhost:8000 |
| 학과 서버 | AI학습서버(학습 · 평가 · 배포 · 판정 추론) | 터널 안의 HTTP, X-API-Key 인증 |

네 컨테이너는 사용자 정의 bridge 네트워크 easyq-network에 연결하고, auth · backend · worker의 포트는 호스트에 게시하지 않는다. backend와 worker는 같은 이미지에서 실행 명령만 달리하고, auth는 별도 이미지 · 프로세스로 실행한다. 데이터는 같은 RDS에 두되, 비밀번호 해시와 인증 코드 검증값은 auth의 DB 계정만 읽는다. backend와 worker의 학습서버 주소(TRAINING_API_BASE_URL)는 Docker bridge의 호스트 주소 9000번 포트다.

터널은 그 bridge 주소에서만 받고, 호스트 방화벽에서 backend · worker 컨테이너의 접속만 허용한다. 0.0.0.0으로 열지 않으며 EC2 보안 그룹에도 9000번을 열지 않는다. SSH 연결은 EC2에서 학과 서버로 나가며, 호스트 키를 검증하고 개인 키는 호스트의 제한된 경로에만 둔다(이미지에 넣지 않는다). 터널이 끊기면 호스트 서비스가 자동으로 다시 연결한다.

### 7.1.1 권한과 인증

- **인증 서버**: 가입 · 로그인 · 로그아웃 · 비밀번호 · CSRF와 인증 세션의 발급 · 폐기는 auth가 한다. backend는 RDS의 제한된 인증 조회 뷰(세션 해시 · 만료 · 폐기, 회원 상태 · 이메일 인증 여부, 게스트 참가 상태)로 요청마다 현재 인증을 확인하며, 비밀번호 해시와 인증 코드 검증값은 이 뷰에 넣지 않는다. 계정 정지 · 탈퇴 · 게스트 참가 철회는 backend가 업무 상태를 바꾸면 그 즉시 접근이 막히고, 세션 폐기는 auth 내부 API로 따로 처리한다(7.3.11).
- **역할**: 계정 역할은 MEMBER와 ADMIN이다. HOST는 역할이 아니라 본인이 만든 강연의 소유 권한이고, 게스트는 한 강연의 참가자로만 인증된다. ADMIN 계정은 서버의 초기 생성 명령으로만 만들며, 웹 API로 역할을 바꾸지 않는다. 관리자도 일반 로그인 API(API-04)로 로그인하고, backend가 관리자 API마다 현재 계정의 ADMIN 역할을 확인한다.
- **인증 쿠키**: 로그인하면 서버 세션을 만들고 easyq_session 쿠키에 무작위 토큰을 넣는다. 쿠키는 Secure · HttpOnly · SameSite=Lax · Path=/이고, DB에는 토큰의 해시만 저장한다.
- **CSRF**: 화면(Next.js)은 세션 토큰을 읽지 않고 CSRF 토큰만 메모리에 둔다. 새로고침으로 CSRF 토큰이 사라지면 같은 출처 요청으로 다시 받는다(API-06).
- **이메일 인증**: 회원 세션은 가입 이메일 인증을 마친(email_verified_at이 있는) ACTIVE 계정에만 발급한다. 이메일 인증은 가입 때 한 번만 하며 로그인 때 다시 하지 않는다.
- **만료**: 회원 인증은 12시간 절대 만료다. 게스트 인증은 입장 후 24시간과 강연 종료 중 빠른 시각에 끝난다. 로그아웃 · 계정 정지 · 비밀번호 변경 · 비밀번호 재설정 때는 인증 세션과 연결된 WebSocket을 폐기한다.
- **권한 확인**: backend는 모든 REST 요청과 WebSocket 연결에서 최신 권한(계정 상태 · 강연 소유 · 참가 · 보관함 보유)을 DB로 확인한다. 학습서버에는 브라우저 쿠키 대신 서비스 X-API-Key를 쓴다.

### 7.1.2 공통 규칙

표: 서비스 API 공통 규칙

| 항목 | 규칙 |
|---|---|
| Base URL | /api/v1. JSON 요청 · 응답, 교안 업로드만 multipart |
| 응답 형식 | 성공 {request_id, data}, 목록은 data에 items · next_cursor · total_count. 오류 {request_id, error:{code, message, details, retryable}} (8.4) |
| 변경 요청 | 인증 쿠키 + Origin 검사 + X-CSRF-Token. 가입 · 인증 메일 · 인증 확인 · 로그인 · 입장 · 비밀번호 재설정 · CSRF 재발급은 Origin 검사만 |
| 비동기 처리 | 202 Accepted와 {resource_id, job_id, status}, Location: /api/v1/jobs/{job_id} |
| 중복 요청 | 비동기 POST는 Idempotency-Key 필수. 같은 주체 · 작업 · 키에 같은 본문이면 같은 결과, 다른 본문이면 409 IDEMPOTENCY_CONFLICT |
| 버전 확인 | 강연 · 질문 상태 변경은 If-Match(리소스 version). 서빙 전환은 expected_active_deployment_id |
| 목록 조회 | cursor 방식, limit 기본 20 · 최대 100. 목록 응답에 같은 조건의 전체 개수(total_count)를 함께 줌(내 정보 화면의 참여 강연 · 내 질문 · 만든 강연 수 등). GET은 본문 없음 |
| 요청 한도 | 가입 · 로그인 · 인증 메일 · 인증 코드 확인 · 재설정 메일 · 입장 코드 확인에만 적용(429 RATE_LIMITED, Retry-After). 질문 API에는 적용하지 않음. 메일 발송(가입 첫 발송 포함)은 같은 이메일 60초 간격 · 시간당 5회, 같은 IP 시간당 20회. 로그인 실패는 이메일당 15분 10회, IP당 15분 100회. 코드 확인은 인증 기록당 5회, IP당 15분 100회. 입장 코드는 없는 코드 · 폐기된 코드로 실패한 요청이 같은 IP에서 15분 20회를 넘으면 그 IP의 입장 코드 확인 · 입장을 15분 동안 거부. 카운터는 프로세스 메모리가 아닌 RDS(auth_rate_limits, 입장 코드는 backend가 JOIN_CODE 범위로 기록)에 둠 |
| 시각 | ISO 8601 UTC |
| 입력 규칙 | 비밀번호 8~20자, 영문과 숫자를 각각 1자 이상 포함. 표시명 1~50자, 게스트 닉네임 1~20자, 강연명 1~100자, 강연 설명 ≤ 500자, 질문 1~200자, 필기 ≤ 1,000자, 전문용어 1~40자 · 강연당 100개 |

### 7.1.3 동의

동의는 세 가지다.

- **SERVICE(필수)**: 질문 처리 · 실시간 기능에 필요한 정보 처리
- **TRAINING(선택)**: 질문과 근거를 비식별 처리해 판정 모델 학습에 쓰는 것
- **STT(강연자만, 강연마다)**: 강연자 음성을 외부 STT로 처리하는 것

회원은 가입 때 SERVICE(필수)와 TRAINING(선택)을 계정 단위로 남기고, 강연 생성 · 입장 때는 계정 동의를 쓴다. 계정에 TRAINING 동의가 없을 때만 선택 항목을 다시 보여주고, 그때 고른 값은 그 강연 단위로 남긴다. 게스트는 입장할 때마다 SERVICE와 TRAINING을 모두 기록하고, 고르지 않은 TRAINING은 false다. 같은 대상 · 범위 · 목적에서는 가장 최근 기록을 적용하고, 계정 TRAINING 철회는 그 회원의 모든 강연 단위 동의보다 우선한다.

라벨 후보는 질문자와 그 강연의 강연자가 모두 TRAINING에 동의했고 평가용 강의가 아닐 때만 만든다. 후보 조회 · 검수 · 병합 때도 이 조건을 다시 확인한다.

### 7.1.4 공개 경로 분기와 인증 서버 장애

브라우저는 같은 도메인으로만 요청하고, Caddy가 경로로 대상을 나눈다. 쿠키 계약(Secure · HttpOnly · SameSite=Lax · Path=/)은 auth와 backend가 같이 쓴다.

표: 공개 경로 분기

| 경로 · 메서드 | 대상 | 내용 |
|---|---|---|
| POST /api/v1/users | auth | 회원가입 · 첫 인증 메일 |
| /api/v1/auth/* | auth | 인증 메일 · 인증 확인 · 로그인 · 로그아웃 · CSRF · 비밀번호 재설정 |
| GET · PATCH /api/v1/me (정확히 이 경로) | auth | 내 계정 · 표시명 · 비밀번호 변경 |
| /api/v1/me/questions, POST /api/v1/me/consents | backend | 내 질문 기록, 계정 동의 |
| 나머지 /api/v1, /api/v1/ws | backend | 강연 · 참가 · 질문 · 필기 · 관리 · 실시간 |
| 그 밖의 경로(화면) | frontend(Next.js 서버) | 강연자 · 청중 · 관리자 화면. 화면 서버는 API를 대신 호출하지 않고 브라우저가 /api/v1을 직접 호출 |
| /internal/v1/* | 외부 비공개 | Caddy가 프록시하지 않음(7.3.11) |

auth가 응답하지 않으면 새 가입 · 인증 확인 · 로그인 · 게스트 입장은 503 AUTH_SERVICE_UNAVAILABLE로 실패한다. 이미 발급된 세션은 backend가 RDS에서 확인하므로 강연 · 질문 기능은 계속 동작한다. RDS 확인이 실패하면 인증을 허용하지 않는다. SMTP 장애는 메일 작업의 재시도로 처리하며, 인증되지 않은 계정을 활성화하지 않는다.

## 7.2 서비스 REST API 정의

서비스 REST API는 65개이며, 모든 URI 앞에 /api/v1이 붙는다. 실시간 전달은 WebSocket(7.3.10), auth 내부 API 2개는 7.3.11에서 따로 정의한다. 처리 서버가 auth인 API는 API-01~10이다.

표: 서비스 REST API 목록

| ID | Method | URI | 기능 | 권한 | 정상 |
|---|---|---|---|---|---|
| API-01 | POST | /users | 회원가입(인증 대기 계정 · 인증 메일) | 방문자 | 201 |
| API-02 | POST | /auth/email-verifications | 가입 인증 메일 재발송 | 방문자 | 202 |
| API-03 | POST | /auth/email-verifications/confirm | 가입 이메일 인증 완료 | 방문자 | 200 |
| API-04 | POST | /auth/sessions | 로그인 | 방문자 | 201 |
| API-05 | DELETE | /auth/sessions/current | 로그아웃 | 인증 사용자 | 204 |
| API-06 | POST | /auth/csrf-tokens | CSRF 토큰 재발급 | 회원 · 게스트 | 200 |
| API-07 | POST | /auth/password-reset-requests | 비밀번호 재설정 메일 요청 | 방문자 | 202 |
| API-08 | POST | /auth/password-resets | 비밀번호 재설정 | 방문자 | 204 |
| API-09 | GET | /me | 내 계정 정보 | MEMBER · ADMIN | 200 |
| API-10 | PATCH | /me | 표시명 · 비밀번호 변경 | MEMBER · ADMIN | 200 |
| API-11 | POST | /me/consents | 계정 단위 동의 변경 | MEMBER | 201 |
| API-12 | GET | /me/questions | 내 질문 기록 | MEMBER | 200 |
| API-13 | POST | /sessions | 강연 생성 · 입장 정보 발급 | MEMBER | 201 |
| API-14 | GET | /sessions | 내 강연 · 보관함 강연 목록 | MEMBER | 200 |
| API-15 | GET | /sessions/{sid} | 강연 상태 · 내 권한 | HOST · 참가자 · 보관함 회원 | 200 |
| API-16 | PATCH | /sessions/{sid} | 강연 정보 수정 · 시작 · 종료 · 음성 인식 상태 변경 | HOST | 200 |
| API-17 | POST | /sessions/{sid}/join-links | 입장 QR 재발급 | HOST | 201 |
| API-18 | GET | /join-codes/{code} | 입장 전 강연 확인 | 방문자 · MEMBER | 200 |
| API-19 | POST | /participations | QR 입장 | 방문자 · MEMBER | 201 · 200 |
| API-20 | POST | /sessions/{sid}/consents | 강연 단위 동의 · 철회 | HOST · 본인 참가자 | 201 |
| API-21 | POST | /sessions/{sid}/documents | 교안 업로드 | HOST | 202 |
| API-22 | GET | /sessions/{sid}/documents | 교안 처리 상태 | HOST | 200 |
| API-23 | POST | /sessions/{sid}/documents/{did}/retries | 교안 처리 재시도 | HOST | 202 |
| API-24 | DELETE | /sessions/{sid}/documents/{did} | 교안 삭제 | HOST | 202 |
| API-25 | PUT | /sessions/{sid}/terms | 전문용어 사전 저장 | HOST | 200 |
| API-26 | POST | /sessions/{sid}/similar-question-searches | 유사 공개 질문 검색 | 참가자 | 200 |
| API-27 | POST | /sessions/{sid}/questions | 질문 등록 | 참가자 | 202 |
| API-28 | GET | /sessions/{sid}/questions | 공개 · 내 질문 · 검토 목록 | HOST · 참가자 · 보관함 회원 | 200 |
| API-29 | GET | /sessions/{sid}/questions/{qid} | 질문 · 답변 조회 | HOST · 참가자 · 보관함 회원 | 200 |
| API-30 | PUT | /sessions/{sid}/questions/{qid}/votes/me | 공감 | 참가자 | 200 |
| API-31 | DELETE | /sessions/{sid}/questions/{qid}/votes/me | 공감 취소 | 참가자 | 204 |
| API-32 | PATCH | /sessions/{sid}/questions/{qid} | 이관 질문 답변 완료 · 완료 취소 | HOST | 200 |
| API-33 | POST | /sessions/{sid}/questions/{qid}/answer-retractions | AI 답변 철회 | HOST | 201 |
| API-34 | PUT | /sessions/{sid}/questions/{qid}/answer-ratings/me | AI 답변 평가 | 질문 작성자 | 200 |
| API-35 | PUT | /sessions/{sid}/questions/{qid}/notes/me | 필기 저장 · 수정 | 회원 참가자 · 보관함 회원 | 200 |
| API-36 | DELETE | /sessions/{sid}/questions/{qid}/notes/me | 필기 삭제 | 회원 참가자 · 보관함 회원 | 204 |
| API-37 | GET | /sessions/{sid}/summary | 요약 노트 | HOST · 보관함 회원 | 200 |
| API-38 | GET | /sessions/{sid}/sources/{chunk_id} | 인용 근거 원문 | HOST · 권한 있는 참가자 | 200 |
| API-39 | GET | /sessions/{sid}/statistics | 강연 통계 | HOST | 200 |
| API-40 | POST | /deletion-requests | 삭제 접수 | 대상 소유자 | 202 |
| API-41 | GET | /jobs/{job_id} | 작업 상태 | 요청자 · ADMIN | 200 |
| API-42 | GET | /notices | 공지 목록 | MEMBER · ADMIN | 200 |
| API-43 | POST | /inquiries | 1:1 문의 등록 | MEMBER | 201 |
| API-44 | GET | /inquiries | 문의 목록(회원은 본인 것) | MEMBER · ADMIN | 200 |
| API-45 | GET | /admin/users | 회원 목록 | ADMIN | 200 |
| API-46 | PATCH | /admin/users/{user_id} | 계정 정지 · 복구 | ADMIN | 200 |
| API-47 | GET | /admin/sessions | 강연 목록 | ADMIN | 200 |
| API-48 | PATCH | /admin/sessions/{sid} | 평가용 강의 표시 · 강제 종료 | ADMIN | 200 |
| API-49 | POST | /admin/notices | 공지 등록 | ADMIN | 201 |
| API-50 | PATCH | /admin/notices/{notice_id} | 공지 수정 | ADMIN | 200 |
| API-51 | DELETE | /admin/notices/{notice_id} | 공지 삭제 | ADMIN | 204 |
| API-52 | PUT | /admin/inquiries/{inquiry_id}/reply | 문의 답변 | ADMIN | 200 |
| API-53 | GET | /admin/feedback-candidates | 라벨 후보 목록 | ADMIN | 200 |
| API-54 | PUT | /admin/feedback-candidates/{cid}/reviews/me | 검수 결과 저장 | ADMIN | 200 |
| API-55 | POST | /admin/datasets | 승인 후보 병합(새 데이터셋 버전) | ADMIN | 202 |
| API-56 | GET | /admin/datasets | 데이터셋 버전 · 분포 | ADMIN | 200 |
| API-57 | POST | /admin/training-runs | 학습 · 재학습 요청 | ADMIN | 202 |
| API-58 | GET | /admin/training-runs/{run_id} | 학습 진행 · 결과 | ADMIN | 200 |
| API-59 | DELETE | /admin/training-runs/{run_id} | 학습 중단 | ADMIN | 202 |
| API-60 | GET | /admin/model-versions | 모델 버전 목록 | ADMIN | 200 |
| API-61 | GET | /admin/evaluation-runs | 평가 결과 | ADMIN | 200 |
| API-62 | POST | /admin/deployments | 서빙 전환 · 롤백 · LLM_ONLY | ADMIN | 202 |
| API-63 | GET | /admin/deployments | 현재 서빙 설정 · 전환 이력 | ADMIN | 200 |
| API-64 | GET | /admin/metrics | 운영 지표 · 예산 사용률 | ADMIN | 200 |
| API-65 | PUT | /admin/budget-settings | 월 API 예산 설정 | ADMIN | 200 |

### 7.2.1 HTTP 메서드별 분류

표: HTTP 메서드별 API

| Method | 개수 | API |
|---|---|---|
| GET | 23 | API-09 · 12 · 14 · 15 · 18 · 22 · 28 · 29 · 37 · 38 · 39 · 41 · 42 · 44 · 45 · 47 · 53 · 56 · 58 · 60 · 61 · 63 · 64 |
| POST | 23 | API-01 · 02 · 03 · 04 · 06 · 07 · 08 · 11 · 13 · 17 · 19 · 20 · 21 · 23 · 26 · 27 · 33 · 40 · 43 · 49 · 55 · 57 · 62 |
| PUT | 7 | API-25 · 30 · 34 · 35 · 52 · 54 · 65 |
| PATCH | 6 | API-10 · 16 · 32 · 46 · 48 · 50 |
| DELETE | 6 | API-05 · 24 · 31 · 36 · 51 · 59 |
| WebSocket | — | /api/v1/ws/sessions/{sid} (7.3.10) |

## 7.3 서비스 REST API 설계

### 7.3.1 공통 응답 객체

각 API의 출력에서 참조하는 객체다. 목록 응답은 이 객체의 배열이다. 내부 외래 키 · 토큰 해시 · S3 키는 응답하지 않는다. ?는 null 가능, []는 배열이다.

표: 공통 응답 객체

| 객체 | 필드 |
|---|---|
| User | user_id:uuid, email:string, display_name:string, role:MEMBER/ADMIN, status:PENDING_VERIFICATION/ACTIVE/SUSPENDED/DELETING, email_verified_at:datetime?, consents:{SERVICE, TRAINING}. 관리자 목록에서만 suspension_reason:string? · joined_count:int(청중으로 참여한 강연 수) · hosted_count:int · question_count:int · created_at |
| Auth | user:User, expires_at:datetime, csrf_token:string (+ Set-Cookie. 토큰 원문은 본문에 넣지 않음) |
| Session | session_id:uuid, title:string, description:string?, scheduled_at:datetime, host_display_name:string, status:DRAFT/LIVE/ENDED/PURGED, stt_status:enum, end_reason:enum?, my_role:HOST/AUDIENCE, version:int, started_at?, ended_at?, raw_data_expires_at?, is_eval_lecture:bool, my_consents:object, has_summary:bool, participant_count:int, capacity:int(50). HOST에게만 join_code · join_url · terms:string[] |
| JoinPreview | title, host_display_name, scheduled_at, description?, status:DRAFT/LIVE, participant_count, capacity, is_full:bool, already_joined:bool(회원) |
| Participation | participant_id:uuid, session_id:uuid, kind:MEMBER/GUEST, nickname:string(게스트) · 회원은 display_name, session_status:enum, expires_at:datetime, csrf_token:string? (게스트 첫 입장은 Set-Cookie 포함) |
| Consent | consent_id:uuid, purpose:SERVICE/TRAINING/STT, policy_version:string, granted:bool, recorded_at:datetime |
| Document | document_id:uuid, file_name:string, status:PENDING/PROCESSING/READY/FAILED, stage:UPLOADED/EXTRACTING/INDEXING/TERMS?(PROCESSING일 때), page_count:int?, chunk_count:int?, error_code:string?, retryable:bool(FAILED일 때) |
| Accepted | resource_id:uuid, job_id:uuid, status:QUEUED |
| QuestionPublic | question_id, content, status:ESCALATED/COMPLETED, document_id?, page_no?, vote_count:int, voted_by_me:bool, my_note:Note?, version:int, created_at. 작성자 · 개인 답변은 넣지 않음 |
| QuestionPrivate | QuestionPublic 필드 + status:질문 전체 상태, escalation_reason:string?, answer:Answer?, processing_error:string? (본인 · HOST만) |
| Answer | answer_id, status:ACTIVE/RETRACTED, content:string?, citations:Citation[], my_rating:HELPFUL/UNHELPFUL? (철회되면 content = null, citations = []) |
| Citation | citation_no:int, chunk_id:uuid?, source_type:DOCUMENT/TRANSCRIPT, location_label:string("교안 p.9" · "발화 21:05"), page_no?, start_ms?, end_ms?, excerpt:string. 강연 원자료 파기 후 chunk_id = null |
| Note | content:string, question_text:string, updated_at:datetime |
| SimilarQuestion | question:QuestionPublic, similarity:float |
| Retraction | question_id, answer_status:RETRACTED, question_status:ESCALATED, reason_code:enum, question_version:int |
| Summary | summary_id, status:QUEUED/RUNNING/READY/FAILED/SKIPPED, content:{one_line:string, key_concepts:{term, description}[], emphases:string[], keywords:string[]}?, sources:Citation[], generated_at? |
| Statistics | question_count, ai_answer_count, escalated_count, completed_count, retracted_count, vote_total, participant_count:{member, guest}, ai_answer_share:float?, questions_by_page:{document_id, file_name, page_no, count}[], general_question_count(교안 페이지 없는 질문), computed_at |
| Notice | notice_id, title, content, created_at, updated_at |
| Inquiry | inquiry_id, title, content, status:WAITING/ANSWERED, reply:string?, replied_at?, created_at. ADMIN 응답에만 author_display_name |
| Job | job_id, job_type:enum, status:enum, resource_id, attempts:int, error_code?, finished_at?, result:object? |
| Candidate | candidate_id, event_type:enum, session_title:string(병합 전까지만), default_label:enum?, sanitized_pair:object, retrieved_evidence:Evidence[], judgment_snapshot:object, review_status:enum, final_label:enum?, reviews:Review[] |
| Review | reviewer_ref:string, label:enum, evidence_id:uuid?, comment:string?, reviewed_at |
| Dataset | dataset_id, version_name(ds-vN), status, contains_aihub:bool, statistics:object, script_version, retrieval_config_version, test_set_version, test_use_count:int, change_note, synced_at |
| TrainingRun | training_run_id, dataset_id, job_id(train-NNNN)?, status:QUEUED/RUNNING/SUCCEEDED/FAILED/HELD/CANCELLED, stage:train/export/eval/register?, hold_reason:precision_drop/below_target?, progress:float, learning_curve:object, metrics:object, model_version:string?, deployable:bool?, error_code?, synced_at |
| ModelVersion | model_version_id, version_name(judge-vN), status:REGISTERED/DELETED, threshold:number, metrics:object(roc_auc · false_answer_rate · tpr · precision_auc_drop · latency_p95_ms), deployable:bool, compared_with:string?, serving:bool, served_before:bool, memo, synced_at |
| Evaluation | evaluation_id, dataset_id, model_version_id?, evaluator:CUSTOM/SIMILARITY/PRETRAINED/SONNET_ONLY, scope:QUESTION/PAIR/SERVICE, split:VALIDATION/TEST, metrics:object, config:object, synced_at |
| Deployment | deployment_id, requested_by, requested_mode:CUSTOM/LLM_ONLY, requested_model_version?, route:SWITCH/ROLLBACK, status:PENDING/ACTIVE/SUPERSEDED/FAILED, reason, error_code?, created_at, synced_at? |
| ServingConfig | mode, model_version?, threshold?, llm_only_threshold, llm_model_id, llm_prompt_version, deployed_at, synced_at, stale:bool |
| Metrics | period:object, group_by, groups:object[] (필드는 7.3.8), budget:{month, monthly_budget_krw, month_to_date_krw, usage_ratio, warning:bool}, data_as_of |

### 7.3.2 계정 · 인증 API

#### API-01 POST /users — 회원가입

- 처리 서버 · 권한 · 정상: auth · 방문자 · 201
- 입력: email · password(8~20자, 영문 · 숫자 각 1자 이상) · display_name(1~50자)(Body, 필수), consents(Body, {SERVICE:{policy_version, granted:true}, TRAINING:{policy_version, granted}}, SERVICE 필수). 가입 화면의 필수 동의 3개(이용약관 · 개인정보 수집 · 이용 · 질문 · 답변 기록 보관)는 SERVICE 하나의 policy_version으로 묶어 보내며, 셋 중 하나라도 빠지면 화면에서 가입 버튼을 막는다
- 출력: Registration {user_id, status:PENDING_VERIFICATION, resend_available_at}. Set-Cookie 없음
- 처리: 이메일을 소문자로 정규화해 중복을 확인하고, 회원(role = MEMBER, status = PENDING_VERIFICATION, email_verified_at = null) · 비밀번호 해시 · 계정 단위 동의 이력 · 인증 기록(6자리 코드의 HMAC, 10분 만료) · 메일 발송 작업(EMAIL_VERIFICATION)을 한 트랜잭션으로 저장한다. TRAINING이 없으면 false로 기록한다. worker가 인증 메일을 보낸다. 201은 접수를 뜻하며 메일 도착을 보장하지 않는다. 인증 전에 같은 이메일로 다시 가입하면 저장된 비밀번호를 덮어쓰지 않고 재발송(API-02)을 안내한다. 24시간 안에 인증하지 않은 계정은 동의 · 인증 기록 · 메일 작업과 함께 정리한다.
- 오류: 409 EMAIL_ALREADY_EXISTS, 422 VALIDATION_ERROR · CONSENT_REQUIRED, 429 RATE_LIMITED

#### API-02 POST /auth/email-verifications — 가입 인증 메일 재발송

- 처리 서버 · 권한 · 정상: auth · 방문자 · 202
- 입력: email(Body, 필수)
- 출력: {message:"인증이 필요한 계정이면 메일을 발송합니다."} (계정 유무 · 상태와 관계없이 같은 응답)
- 처리: PENDING_VERIFICATION 계정만 이전 인증 기록과 미발송 작업을 폐기하고 새 기록 · 작업을 만든다. 계정 정보와 비밀번호는 바꾸지 않는다. 같은 이메일 60초 간격 · 시간당 5회, 같은 IP 시간당 20회로 제한한다.
- 오류: 422 VALIDATION_ERROR, 429 RATE_LIMITED

#### API-03 POST /auth/email-verifications/confirm — 가입 이메일 인증 완료

- 처리 서버 · 권한 · 정상: auth · 방문자 · 200
- 입력: email · code(6자리, Body, 필수)
- 출력: {email_verified:true, next_action:"LOGIN"}. Set-Cookie 없음(자동 로그인하지 않음)
- 처리: 현재 유효한 인증 기록과 회원을 잠그고 검증값 · 만료 · 사용 여부 · 실패 횟수를 확인한다. 성공하면 consumed_at · email_verified_at을 기록하고 PENDING_VERIFICATION을 ACTIVE로 바꾼다. 실패 횟수는 오류 응답에서도 저장하며, 5번 틀리면 그 기록을 폐기한다.
- 오류: 422 EMAIL_VERIFICATION_INVALID, 429 EMAIL_VERIFICATION_ATTEMPTS_EXCEEDED · RATE_LIMITED

#### API-04 POST /auth/sessions — 로그인

- 처리 서버 · 권한 · 정상: auth · 방문자 · 201
- 입력: email · password(Body, 필수)
- 출력: Auth
- 처리: 비밀번호를 확인한 뒤 ACTIVE 상태와 email_verified_at을 확인하고 인증 세션과 CSRF 토큰을 발급한다. 로그인 때 인증 메일을 보내지 않는다. 비밀번호가 틀리면 인증 상태를 드러내지 않는다. 비밀번호가 맞고 정지된 계정이면 ACCOUNT_SUSPENDED의 details에 관리자가 남긴 정지 사유(suspension_reason)를 담아 화면이 "이용이 정지된 계정이에요. 사유: …"로 보여준다. 관리자도 이 API로 로그인한다.
- 오류: 401 AUTH_INVALID_CREDENTIALS(이메일 존재 여부를 구분하지 않음), 403 EMAIL_NOT_VERIFIED · ACCOUNT_SUSPENDED, 429 RATE_LIMITED, 503 AUTH_SERVICE_UNAVAILABLE

#### API-05 DELETE /auth/sessions/current — 로그아웃

- 처리 서버 · 권한 · 정상: auth · 인증 사용자 · 204
- 처리: 인증 세션의 revoked_at과 폐기 이벤트(session.revoked)를 같은 트랜잭션으로 저장하고 쿠키를 만료시킨다. backend가 이벤트를 받아 연결된 WebSocket을 닫는다. 이미 폐기된 세션에 다시 요청해도 204다.

#### API-06 POST /auth/csrf-tokens — CSRF 토큰 재발급

- 처리 서버 · 권한 · 정상: auth · 회원 · 게스트 · 200
- 입력: 인증 쿠키, Origin, X-EasyQ-Client 헤더
- 출력: {csrf_token}
- 처리: 새로고침으로 메모리의 CSRF 토큰이 사라졌을 때 쓴다. 정확히 같은 출처만 받고 교차 출처 CORS를 허용하지 않으며 no-store로 응답한다. 인증 세션의 CSRF 해시를 새 값으로 바꾸고, 열린 다른 탭에는 WebSocket으로 갱신을 알린다.
- 오류: 401 AUTH_REQUIRED, 403 FORBIDDEN

#### API-07 POST /auth/password-reset-requests — 비밀번호 재설정 메일 요청

- 처리 서버 · 권한 · 정상: auth · 방문자 · 202
- 입력: email(Body, 필수)
- 출력: 빈 data
- 처리: 가입 여부와 관계없이 같은 응답을 준다. 인증을 마친 ACTIVE 계정이면 1회용 재설정 토큰의 HMAC과 만료 시각(30분)을 password_resets에 저장하고 메일 발송 작업(PASSWORD_RESET)을 등록한다. 발송 한도는 가입 인증 메일과 같다. 새 토큰을 만들면 이전 토큰은 무효다.
- 오류: 422 VALIDATION_ERROR, 429 RATE_LIMITED

#### API-08 POST /auth/password-resets — 비밀번호 재설정

- 처리 서버 · 권한 · 정상: auth · 방문자 · 204
- 입력: token · new_password(Body, 8~20자, 영문 · 숫자 각 1자 이상, 필수)
- 처리: 토큰 해시 · 만료 · 사용 여부를 확인하고 비밀번호를 바꾼 뒤 토큰을 사용 처리한다. 그 계정의 모든 인증 세션과 WebSocket을 폐기한다.
- 오류: 422 RESET_TOKEN_INVALID · VALIDATION_ERROR

#### API-09 GET /me — 내 계정 정보

- 처리 서버 · 권한 · 정상: auth · MEMBER · ADMIN · 200
- 출력: User
- 처리: 쿠키의 현재 계정을 DB에서 다시 확인해 돌려준다(no-store). 화면은 새로고침 때 API-06과 함께 불러 로그인 상태를 복구한다. 게스트는 403이다.

#### API-10 PATCH /me — 표시명 · 비밀번호 변경

- 처리 서버 · 권한 · 정상: auth · MEMBER · ADMIN · 200
- 입력: display_name(1~50자), current_password(비밀번호 변경 시 필수), new_password(8~20자, 영문 · 숫자 각 1자 이상) — 최소 1개
- 출력: User
- 처리: 비밀번호를 바꾸면 현재 비밀번호를 확인하고 다른 인증 세션과 WebSocket을 모두 폐기한 뒤, 현재 브라우저에는 새 세션과 CSRF 토큰을 준다. 이메일은 바꿀 수 없다. 탈퇴는 API-40(ACCOUNT)로 한다.
- 오류: 401 AUTH_INVALID_CREDENTIALS, 422 VALIDATION_ERROR

#### API-11 POST /me/consents — 계정 단위 동의 변경

- 권한 · 정상: MEMBER · 201
- 입력: purpose(SERVICE/TRAINING) · policy_version · granted(Body, 필수)
- 출력: Consent (+ 후보 삭제 작업이 생기면 deletion_job_id)
- 처리: 계정 단위 이력을 추가한다. TRAINING 철회는 그 회원의 강연 단위 동의보다 우선하며, 이후 후보를 만들지 않고 미병합 후보를 지운다. 병합된 데이터와 모델은 바꾸지 않는다. SERVICE는 철회할 수 없고 탈퇴(API-40)로 안내한다.
- 오류: 422 VALIDATION_ERROR

#### API-12 GET /me/questions — 내 질문 기록

- 권한 · 정상: MEMBER · 200
- 입력: session_id(Query, 선택), cursor · limit
- 출력: QuestionPrivate[] + 항목마다 session_id · session_title
- 처리: 현재 회원이 쓴 질문만 돌려준다. 회원 개인 기록이므로 강연 원자료가 파기된 뒤에도 질문 · 답변 · 근거 위치(location_label · excerpt)를 보여주며, 회원이 지운 질문과 보관함에서 지운 강연의 질문은 빠진다.

### 7.3.3 강연 · 입장 · 동의 API

#### API-13 POST /sessions — 강연 생성

- 권한 · 정상: MEMBER · 201
- 입력: title(Body, 1~100자, 필수), scheduled_at(Body, 시작 예정 일시, 필수), description(Body, ≤ 500자, 선택), training_consent(Body, {policy_version, granted}, 계정 TRAINING 동의가 없을 때만)
- 출력: Session(join_code · join_url 포함)
- 처리: 계정 SERVICE 동의를 확인하고 DRAFT 강연을 만든다. scheduled_at은 내 강연의 예정 탭과 청중 대기 화면에 보여주는 값이며, 그 시각에 자동으로 시작하지 않는다(시작은 API-16). 선택 동의를 받으면 강연 단위로 남긴다. is_eval_lecture는 false로 시작하며 일반 회원이 바꿀 수 없다. 강연 원자료 보관 기간은 종료 후 90일로 고정이다.
- 오류: 403 CONSENT_REQUIRED, 422 VALIDATION_ERROR

#### API-14 GET /sessions — 내 강연 · 보관함 강연 목록

- 권한 · 정상: MEMBER · 200
- 입력: scope(Query, hosted 또는 joined, 필수), status(선택, hosted는 DRAFT · LIVE · ENDED로 예정 · 진행 중 · 지난 강연 탭을 나눔), q(Query, 1~50자, joined에서 강연명 · 강연자 표시명 검색), cursor · limit
- 출력: Session[] (joined는 항목마다 my_question_count 포함)
- 처리: hosted는 본인이 만든 강연 중 삭제하지 않은 것, joined는 회원으로 청중 참여한 강연 중 보관함에서 지우지 않은 것이다. 본인이 HOST인 강연은 joined에 넣지 않는다. joined는 강연 원자료가 파기된(PURGED) 강연도 포함한다. q는 대소문자를 구분하지 않는 부분 일치이며, 결과가 없으면 빈 목록이다. hosted의 DRAFT는 scheduled_at, LIVE는 started_at, ENDED는 ended_at의 최근 순이다.

#### API-15 GET /sessions/{sid} — 강연 상태 · 내 권한

- 권한 · 정상: HOST · 참가자 · 보관함 회원 · 200
- 출력: Session (ETag = version)
- 처리: 대기 화면(DRAFT) · 질문 화면(LIVE) · 보관함 상세(ENDED · PURGED)가 같은 API로 상태를 받는다.
- 오류: 404 RESOURCE_NOT_FOUND

#### API-16 PATCH /sessions/{sid} — 강연 정보 수정 · 시작 · 종료 · 음성 인식 상태

- 권한 · 정상: HOST · 200
- 입력: If-Match(필수), title · scheduled_at · description(DRAFT에서만), status(LIVE 또는 ENDED), stt_status(RUNNING 또는 PAUSED) — 최소 1개
- 출력: Session, 새 ETag
- 처리: 강연 정보는 DRAFT에서만 고친다. 상태는 DRAFT → LIVE → ENDED만 허용한다. 시작은 SERVICE 동의만 확인하며 교안이 없어도 된다. 시작하면 started_at을 기록하고 12시간 뒤 자동 종료 작업을 예약한다. 종료하면 end_reason = HOST로 6.2.9의 종료 처리를 한다. stt_status를 RUNNING으로 바꾸려면 이 강연의 STT 동의(API-20)가 있어야 하며, CONNECTING을 거쳐 audio.start가 승인되면 RUNNING이 된다. 종료와 음성 인식 시작을 한 요청에 함께 보내면 422다. 상태 · 정보가 바뀌면 참가자 모두에게 session.updated를 보낸다.
- 오류: 403 CONSENT_REQUIRED, 409 VERSION_CONFLICT · SESSION_STATE_CONFLICT, 422 VALIDATION_ERROR

#### API-17 POST /sessions/{sid}/join-links — 입장 QR 재발급

- 권한 · 정상: HOST · 201
- 입력: If-Match(필수)
- 출력: {join_url, join_code, version}
- 처리: DRAFT · LIVE에서만 한다. 새 입장 코드(영문 대문자 · 숫자 5자리)를 만들고, 바로 전 코드는 previous_join_code로 옮겨 이전 QR · 코드 · 링크를 바로 무효로 한다. 이전 코드로 들어오면 404가 아니라 410 JOIN_CODE_REVOKED로 "강연자가 입장 QR을 새로 발급했어요"를 보여준다. 이미 입장한 참가자는 그대로 둔다.
- 오류: 409 SESSION_STATE_CONFLICT · VERSION_CONFLICT

#### API-18 GET /join-codes/{code} — 입장 전 강연 확인

- 권한 · 정상: 방문자 · MEMBER · 200
- 출력: JoinPreview
- 처리: QR · 코드 입력 직후 회원 · 게스트 선택 화면에 강연명 · 강연자 · 예정 일시 · 설명 · 정원 상태를 보여주기 위해 부른다. 참가를 만들거나 세션을 발급하지 않는다. 코드는 대문자로 바꿔 찾는다. 입장 코드 요청 한도(7.1.2)를 함께 센다.
- 오류: 404 JOIN_CODE_INVALID, 410 JOIN_CODE_REVOKED, 409 SESSION_ENDED, 429 RATE_LIMITED

#### API-19 POST /participations — QR 입장

- 권한 · 정상: 방문자 · MEMBER · 201(새 참가) 또는 200(기존 참가)
- 입력: join_code(Body, 필수), nickname(Body, 1~20자, 게스트 필수), service_consent(게스트 필수), training_consent(선택)
- 출력: Participation
- 처리: 강연 상태에 따라 처리한다. DRAFT · LIVE는 입장을 받고, ENDED · PURGED는 409 SESSION_ENDED로 거부한다(화면은 회원에게 보관함을 안내). 정원은 강연당 청중 50명(활성 참가자 수, 강연자 제외)이며, 다 찼으면 새 참가를 409 SESSION_FULL로 거부한다. 이미 참가한 사람이 다시 들어오는 것(200)은 정원과 관계없이 받는다. 참가자 수가 바뀌면 session.updated로 participant_count를 보낸다. 회원은 계정 SERVICE 동의를 쓰고 계정 TRAINING 동의가 없을 때만 선택값을 받는다. 게스트는 입장마다 닉네임과 SERVICE = true, TRAINING 선택 결과를 저장한다. 이어서 backend가 auth 내부 API(INT-01)로 그 강연 전용 게스트 세션을 받아 Set-Cookie로 전달한다. auth가 응답하지 않으면 503 AUTH_SERVICE_UNAVAILABLE이며, 다시 요청하면 같은 참가자를 재사용해 참가자가 중복되지 않는다. 닉네임은 게스트 본인 화면에만 쓰며 질문 목록 · 강연자 화면에는 표시하지 않는다. 학습 활용에 동의하지 않아도 입장한다. 게스트로 쓴 기록은 회원 계정으로 옮기지 않으며, 강연 중에 로그인해 다시 입장하면 새 회원 참가로 처리한다.
- 오류: 404 JOIN_CODE_INVALID, 410 JOIN_CODE_REVOKED, 409 SESSION_ENDED · SESSION_FULL, 403 CONSENT_REQUIRED, 429 RATE_LIMITED, 503 AUTH_SERVICE_UNAVAILABLE

#### API-20 POST /sessions/{sid}/consents — 강연 단위 동의 · 철회

- 권한 · 정상: HOST · 본인 참가자 · 201
- 입력: purpose(SERVICE/TRAINING/STT) · policy_version · granted(Body, 필수)
- 출력: Consent (+ 필요하면 deletion_job_id)
- 처리: 강연 단위 이력을 추가한다. STT는 그 강연의 HOST만 기록한다. TRAINING 철회는 후보 생성을 막고 미병합 후보를 지운다. SERVICE 철회는 참가자면 참가 권한을 폐기하고, HOST면 강연을 종료한다. STT 철회는 음성 중계를 멈춘다.
- 오류: 403 FORBIDDEN, 422 VALIDATION_ERROR

### 7.3.4 교안 · 전문용어 API

#### API-21 POST /sessions/{sid}/documents — 교안 업로드

- 권한 · 정상: HOST · 202
- 입력: file(multipart, PDF · PPTX, 50 MiB 이하, 필수), Idempotency-Key
- 출력: Accepted
- 처리: DRAFT · LIVE에서 받는다. 확장자 · MIME · 실제 파일 형식 · 압축 해제 크기를 확인하고 S3에 저장한 뒤 교안 처리 작업(INGEST)을 등록한다. 처리 상태는 document.updated 이벤트로 알린다. LIVE 중 추가된 교안은 READY가 되면 검색에 포함되고 평가용 강의 검사를 다시 한다.
- 오류: 409 SESSION_STATE_CONFLICT, 413 FILE_TOO_LARGE, 415 FILE_TYPE_UNSUPPORTED

#### API-22 GET /sessions/{sid}/documents — 교안 처리 상태

- 권한 · 정상: HOST · 200
- 출력: Document[]
- 처리: 처리 상태 · 단계(업로드 → 텍스트 추출 · 청킹 → 임베딩 · 색인 → 용어 추출) · 쪽수 · 검색 조각 수와 화면에 보여도 되는 오류 코드만 돌려준다. 단계가 바뀔 때마다 document.updated를 보낸다.

#### API-23 POST /sessions/{sid}/documents/{did}/retries — 교안 처리 재시도

- 권한 · 정상: HOST · 202
- 입력: Idempotency-Key
- 출력: Accepted
- 처리: DRAFT · LIVE에서 FAILED 교안만 받는다. S3에 남은 같은 원본으로 교안 처리 작업(INGEST)을 다시 등록하고, 앞선 시도에서 만든 조각 · 벡터는 지운 뒤 처음 단계부터 다시 한다. 손상된 파일 · 텍스트 없는 스캔 PDF처럼 원본 때문에 실패한 교안은 retryable = false이며, 화면은 재시도 대신 삭제 후 새 파일 업로드를 안내한다.
- 오류: 404 RESOURCE_NOT_FOUND, 409 SESSION_STATE_CONFLICT · DOCUMENT_NOT_RETRYABLE

#### API-24 DELETE /sessions/{sid}/documents/{did} — 교안 삭제

- 권한 · 정상: HOST · 202
- 입력: Idempotency-Key
- 출력: Accepted
- 처리: DRAFT · ENDED에서만 받는다. 접근을 먼저 막고 S3 원본 · 교안 조각 · 벡터 · 색인을 지운다. 이 교안을 인용한 답변과 요약은 그대로 두고, 인용의 chunk_id만 비운다(위치 텍스트 · 인용 구절은 남는다).
- 오류: 404 RESOURCE_NOT_FOUND, 409 SESSION_STATE_CONFLICT

#### API-25 PUT /sessions/{sid}/terms — 전문용어 사전 저장

- 권한 · 정상: HOST · 200
- 입력: terms(Body, 문자열 배열, 각 1~40자, 최대 100개, 필수), If-Match
- 출력: {terms, version}
- 처리: DRAFT에서만 받고, 보낸 목록으로 전체를 바꾼다. 앞뒤 공백을 지우고 대소문자를 구분하지 않고 중복을 하나로 합친다. 교안이 READY가 되면 worker가 그 교안에서 뽑은 용어(documents.terms)를 남은 자리만큼 목록에 한 번 더한다. 강연자가 지운 용어는 다시 넣지 않는다. 강연을 시작하면 목록을 고정하고, STT 연결마다 이 목록을 용어 힌트로 보낸다. LIVE 중 추가된 교안의 용어는 남은 자리만큼 더해져 다음 STT 연결부터 쓰인다.
- 오류: 409 SESSION_STATE_CONFLICT · VERSION_CONFLICT, 422 VALIDATION_ERROR

### 7.3.5 질문 · 공감 · 답변 · 필기 · 리포트 API

#### API-26 POST /sessions/{sid}/similar-question-searches — 유사 공개 질문 검색

- 권한 · 정상: 참가자 · 200
- 입력: content(Body, 1~200자, 필수), document_id · page_no(선택)
- 출력: {items: SimilarQuestion[] (최대 3개)}
- 처리: 같은 강연의 ESCALATED 질문만 찾는다. 검색 문장은 저장하거나 로그에 남기지 않는다.

#### API-27 POST /sessions/{sid}/questions — 질문 등록

- 권한 · 정상: 참가자 · 202
- 입력: content(Body, 1~200자, 필수), document_id · page_no(선택), Idempotency-Key
- 출력: Accepted
- 처리: 참가 권한 · SERVICE 동의 · LIVE 상태를 확인하고 질문(QUEUED)과 질문 작업(QA)을 한 트랜잭션으로 저장한다. 이후 진행은 question.progress · answer.* 이벤트로 받는다.
- 오류: 403 CONSENT_REQUIRED, 409 SESSION_NOT_LIVE, 422 VALIDATION_ERROR

#### API-28 GET /sessions/{sid}/questions — 질문 목록

- 권한 · 정상: HOST · 참가자 · 보관함 회원 · 200
- 입력: scope(Query, public · mine · review, 필수), document_id · page_no(선택), sort(votes 또는 latest), cursor · limit
- 출력: public은 QuestionPublic[], mine · review는 QuestionPrivate[]
- 처리: public은 ESCALATED · COMPLETED 질문이며, 참가자 · 보관함 회원에게 voted_by_me를, 회원에게 my_note를 채운다(게스트는 my_note = null). mine은 본인 질문, review는 HOST만 쓰며 이관 질문과 AI 답변 검토 목록을 준다. 어느 목록에도 작성자를 넣지 않는다. 보관함 회원은 ENDED · PURGED 강연에서 public · mine을 조회한다. votes 정렬의 동률은 생성 시각 순이다.
- 오류: 403 FORBIDDEN

#### API-29 GET /sessions/{sid}/questions/{qid} — 질문 · 답변 조회

- 권한 · 정상: HOST · 참가자 · 보관함 회원 · 200
- 출력: 본인 · HOST는 QuestionPrivate, 그 밖에는 공개 질문일 때만 QuestionPublic
- 처리: 다른 사람의 개인 질문은 존재 여부를 숨기고 404로 응답한다.

#### API-30 PUT /sessions/{sid}/questions/{qid}/votes/me — 공감

- 권한 · 정상: 참가자 · 200
- 출력: {question_id, voted:true, vote_count}
- 처리: LIVE 강연의 ESCALATED 질문만 받는다. 참가자는 인증 세션으로 정하며, 반복 요청해도 한 번만 센다. 바뀐 공감 수는 public_question.updated로 보낸다.
- 오류: 409 QUESTION_NOT_PUBLIC · SESSION_NOT_LIVE

#### API-31 DELETE /sessions/{sid}/questions/{qid}/votes/me — 공감 취소

- 권한 · 정상: 참가자 · 204
- 처리: LIVE 강연에서 본인 공감만 지운다. 이미 없으면 그대로 204다. 강연이 끝난 뒤의 공감 수는 강연 기록으로 고정한다.
- 오류: 409 SESSION_NOT_LIVE

#### API-32 PATCH /sessions/{sid}/questions/{qid} — 이관 질문 답변 완료 · 완료 취소

- 권한 · 정상: HOST · 200
- 입력: status(COMPLETED 또는 ESCALATED, 필수), If-Match
- 출력: QuestionPrivate
- 처리: ESCALATED → COMPLETED(답변 완료)와 COMPLETED → ESCALATED(잘못 누른 완료 취소)만 허용한다. 강연자가 강연 중에 구두로 답한 질문을 표시하는 기능이므로 LIVE에서만 받는다. 바뀐 상태는 public_question.updated로 보낸다. 강연이 끝날 때 ESCALATED로 남은 질문은 그대로 강연 기록에 남는다.
- 오류: 409 VERSION_CONFLICT · SESSION_NOT_LIVE · SESSION_STATE_CONFLICT

#### API-33 POST /sessions/{sid}/questions/{qid}/answer-retractions — AI 답변 철회

- 권한 · 정상: HOST · 201
- 입력: reason_code(WRONG_OR_INSUFFICIENT 또는 EXPLAIN_AGAIN, 필수), reason_detail(≤ 500자, 선택), If-Match
- 출력: Retraction
- 처리: ACTIVE 답변만 철회한다. 답변 숨김, 질문 ESCALATED 전환, 감사 기록을 한 트랜잭션으로 저장하고 질문자에게 answer.retracted를 보낸다. 철회한 질문은 강연자가 강연 중에 구두로 다시 답하는 대상이므로 LIVE에서만 받는다. 질문자와 강연자가 모두 TRAINING에 동의했고 평가용 강의가 아니면 RETRACTED 후보를 만든다(기본 라벨은 사유별로 3.3.4).
- 오류: 409 ANSWER_NOT_ACTIVE · VERSION_CONFLICT · SESSION_NOT_LIVE, 422 VALIDATION_ERROR

#### API-34 PUT /sessions/{sid}/questions/{qid}/answer-ratings/me — AI 답변 평가

- 권한 · 정상: 질문 작성자 · 200
- 입력: answer_id(필수), rating(HELPFUL 또는 UNHELPFUL, 필수)
- 출력: {answer_id, rating, version}
- 처리: 본인 질문의 ACTIVE 답변만 평가한다. 평가는 학습 동의와 관계없이 저장한다. 양측 TRAINING 동의 · 평가용 강의 아님이면 AUDIENCE_HELPFUL 또는 AUDIENCE_UNHELPFUL 후보를 하나만 만들고, 평가를 바꾸면 미병합 후보의 사건 종류도 바꾼다. 답변을 자동으로 공개하거나 철회하지 않는다.
- 오류: 409 ANSWER_NOT_ACTIVE

#### API-35 PUT /sessions/{sid}/questions/{qid}/notes/me — 필기 저장 · 수정

- 권한 · 정상: 회원 참가자 · 보관함 회원 · 200
- 입력: content(Body, 1~1,000자, 필수)
- 출력: Note
- 처리: 공개 질문(ESCALATED · COMPLETED)에만 쓴다. 회원 · 질문당 하나이며 다시 보내면 덮어쓴다. 처음 저장할 때 질문 문장을 함께 복사해 둔다. 게스트는 쓸 수 없다. 필기는 본인에게만 보이며 요약 · 학습 · 강연자 화면에 쓰지 않는다.
- 오류: 403 FORBIDDEN, 409 QUESTION_NOT_PUBLIC, 422 VALIDATION_ERROR

#### API-36 DELETE /sessions/{sid}/questions/{qid}/notes/me — 필기 삭제

- 권한 · 정상: 회원 참가자 · 보관함 회원 · 204
- 처리: 본인 필기를 지운다. 없으면 그대로 204다.

#### API-37 GET /sessions/{sid}/summary — 요약 노트

- 권한 · 정상: HOST · 보관함 회원 · 200
- 출력: Summary
- 처리: ENDED · PURGED에서 조회한다. 요약 노트는 한 줄 요약 · 핵심 개념(용어와 설명) · 강조한 점 · 키워드로 나눠 저장한 JSON이다. 생성 중이면 상태만 돌려준다. 확정 발화가 1,000자 미만이면 만들지 않고 SKIPPED로 둔다(화면 "요약 노트가 만들어지지 않았어요"). 게스트는 403이다. 강연 원자료가 파기돼도 요약 노트는 강연 기록으로 남는다.
- 오류: 403 FORBIDDEN, 409 SESSION_STATE_CONFLICT

#### API-38 GET /sessions/{sid}/sources/{chunk_id} — 인용 근거 원문

- 권한 · 정상: HOST · 권한 있는 참가자 · 200
- 출력: Citation + content
- 처리: HOST, 또는 본인의 ACTIVE 답변이나 요약 노트가 인용한 조각만 돌려준다. 교안 전체에 대한 접근권은 주지 않는다. 강연 원자료가 파기되면 404이며, 화면은 Citation의 위치 텍스트와 인용 구절을 보여준다.
- 오류: 403 FORBIDDEN, 404 RESOURCE_NOT_FOUND

#### API-39 GET /sessions/{sid}/statistics — 강연 통계

- 권한 · 정상: HOST · 200
- 출력: Statistics
- 처리: 강연 리포트의 통계 탭이다(F11-1, Should). 강연이 끝날 때 종료 처리(6.2.9)에서 한 번 집계해 lecture_sessions.statistics에 저장하고, 조회는 저장된 값을 돌려준다. 그래서 게스트 질문 내용 정리 · 90일 파기 뒤에도 숫자가 바뀌지 않는다. 질문 수 · AI 답변 수 · 이관 수 · 답변 완료 수 · 철회 수 · 공감 합계 · 회원 · 게스트 참가자 수 · AI 답변 비중과 교안 페이지별 질문 수를 준다. 질문 원문과 작성자는 넣지 않는다.
- 오류: 403 FORBIDDEN, 409 SESSION_STATE_CONFLICT(종료 전)

### 7.3.6 삭제 · 작업 · 공지 · 문의 API

#### API-40 POST /deletion-requests — 삭제 접수

- 권한 · 정상: 대상 소유자 · 202
- 입력: target_type(QUESTION · ARCHIVE · SESSION · ACCOUNT, 필수), target_id(uuid, 필수), reason(≤ 500자, 선택), Idempotency-Key
- 출력: Accepted
- 처리: 접근을 먼저 막고 삭제 작업(PURGE)을 등록한다.
  - QUESTION: 작성자가 자기 질문을 지운다. 개인 질문이면 질문 · 답변을 지우고, 공개 질문이면 작성자 연결만 끊어 강연 기록에 남긴다.
  - ARCHIVE: 회원이 보관함에서 강연 하나를 지운다(target_id = 강연). 그 강연의 내 질문 · 내 답변 · 내 필기를 지운다. 마지막 보관 회원이면 강연 기록도 지운다.
  - SESSION: HOST가 강연 원자료를 즉시 지운다. 강연 기록은 보관함 회원이 있으면 남긴다.
  - ACCOUNT: 본인 탈퇴. 최근 10분 안에 로그인한 상태여야 한다. 본인이 HOST인 LIVE 강연이 있으면 409 HOSTING_LIVE_SESSION으로 거부하고 화면은 강연 종료를 먼저 안내한다. 계정 단위 처리 순서는 6.2.11을 따른다.
- 오류: 403 FORBIDDEN · RECENT_LOGIN_REQUIRED, 404 RESOURCE_NOT_FOUND, 409 HOSTING_LIVE_SESSION

탈퇴하면 인증 세션도 폐기되므로 이후 작업 조회는 할 수 없다. 삭제가 끝나기 전에도 대상 데이터는 다시 조회되지 않는다.

#### API-41 GET /jobs/{job_id} — 작업 상태

- 권한 · 정상: 작업 요청자 · ADMIN · 200
- 출력: Job
- 처리: 요청자와 그 강연의 HOST가 조회한다. ADMIN은 운영 · 학습 작업만 본다. 질문 작업의 개인 내용은 넣지 않는다.

#### API-42 GET /notices — 공지 목록

- 권한 · 정상: MEMBER · ADMIN · 200
- 입력: cursor · limit
- 출력: Notice[]
- 처리: 공지 · 문의는 F13-1(Should)이다. 삭제되지 않은 공지를 최근 순으로 준다. 회원의 내 정보 화면은 마지막으로 본 공지 이후 새 공지가 있으면 표시를 붙인다(마지막 확인 시각은 브라우저에만 둔다).

#### API-43 POST /inquiries — 1:1 문의 등록

- 권한 · 정상: MEMBER · 201
- 입력: title(Body, 1~100자, 필수), content(Body, 1~2,000자, 필수)
- 출력: Inquiry
- 처리: WAITING 상태로 저장한다. 첨부 파일은 받지 않는다. 문의 내용은 학습 · 요약에 쓰지 않는다.
- 오류: 422 VALIDATION_ERROR

#### API-44 GET /inquiries — 문의 목록

- 권한 · 정상: MEMBER · ADMIN · 200
- 입력: status(WAITING · ANSWERED, 선택), cursor · limit
- 출력: Inquiry[]
- 처리: 회원은 본인 문의만, ADMIN은 전체 문의를 받는다. ADMIN 응답에만 작성자 표시명을 넣고 이메일은 넣지 않는다. 탈퇴한 회원의 문의는 탈퇴 처리에서 함께 지운다.

### 7.3.7 관리자 API

모든 관리자 API는 현재 계정의 ADMIN 역할을 확인하고, 상태를 바꾸는 요청은 사유와 함께 감사 기록(audit_events)을 같은 트랜잭션으로 남긴다. 브라우저는 학습서버를 직접 부르지 않으며, backend · worker가 7.4의 API로 전달한다.

#### API-45 GET /admin/users — 회원 목록

- 정상: 200 / 입력: status, q(이름 · 이메일 부분 일치, 1~50자), cursor · limit / 출력: User[]
- 처리: 비밀번호 · 인증 세션 정보는 넣지 않는다. 상태별 개수는 status마다 total_count로 받는다.

#### API-46 PATCH /admin/users/{user_id} — 계정 정지 · 복구

- 정상: 200 / 입력: status(ACTIVE 또는 SUSPENDED, 필수), reason(필수) / 출력: User
- 처리: 정지하면 사유를 suspension_reason에 저장하고(로그인 화면에 보여줌, API-04) 그 계정의 인증 세션과 WebSocket을 폐기한다. 그 회원이 HOST인 LIVE 강연은 end_reason = ADMIN으로 강제 종료하고, 청중으로 참가 중이던 강연에서는 세션 폐기로 바로 나가진다(강연은 계속된다). DRAFT 강연은 그대로 둔다. 복구하면 사유를 지우고 복구 사유는 감사 기록에만 남긴다. 마지막 활성 관리자는 정지할 수 없다. 역할은 바꾸지 않는다.
- 오류: 409 SESSION_STATE_CONFLICT(마지막 관리자)

#### API-47 GET /admin/sessions — 강연 목록

- 정상: 200 / 입력: status, from · to, cursor · limit
- 출력: {session_id, host_user_id, host_display_name, title, join_code, status, end_reason, is_eval_lecture, scheduled_at, started_at, ended_at, participant_count, question_count, created_at, version}[]
- 처리: 질문 원문은 넣지 않는다. 일시는 DRAFT면 scheduled_at, 그 밖에는 started_at을 보여준다.

#### API-48 PATCH /admin/sessions/{sid} — 평가용 강의 표시 · 강제 종료

- 정상: 200 / 입력: status(ENDED), is_eval_lecture(true), reason(필수), If-Match — status · is_eval_lecture 중 최소 1개
- 출력: {session_id, status, is_eval_lecture, version}
- 처리: is_eval_lecture는 DRAFT에서 true로만 바꾼다(교안 없이 진행할 평가용 강의). 한 번 true가 되면 false로 되돌리지 않는다(자동 판정된 평가용 강의도 같다). status = ENDED(강제 종료)는 LIVE에서만 받으며 end_reason = ADMIN으로 종료 처리를 한다. 아직 시작하지 않은 DRAFT 강연은 강제 종료 대상이 아니다.
- 오류: 409 SESSION_STATE_CONFLICT · VERSION_CONFLICT

#### API-49 POST /admin/notices — 공지 등록

- 정상: 201 / 입력: title(1~100자, 필수), content(1~2,000자, 필수) / 출력: Notice
- 처리: 바로 게시한다. 예약 게시는 하지 않는다.

#### API-50 PATCH /admin/notices/{notice_id} — 공지 수정

- 정상: 200 / 입력: title · content(최소 1개), If-Match / 출력: Notice
- 오류: 404 RESOURCE_NOT_FOUND, 409 VERSION_CONFLICT

#### API-51 DELETE /admin/notices/{notice_id} — 공지 삭제

- 정상: 204
- 처리: deleted_at을 기록해 목록에서 내린다. 이미 지운 공지는 그대로 204다.

#### API-52 PUT /admin/inquiries/{inquiry_id}/reply — 문의 답변

- 정상: 200 / 입력: reply(1~2,000자, 필수) / 출력: Inquiry
- 처리: 답변을 저장하고 ANSWERED로 바꾼다. 다시 보내면 답변을 고치고 replied_at을 갱신한다. 회원은 내 정보의 1:1 문의 화면에서 답변을 본다. 메일로 알리지 않는다.
- 오류: 404 RESOURCE_NOT_FOUND, 422 VALIDATION_ERROR

#### API-53 GET /admin/feedback-candidates — 라벨 후보 목록

- 정상: 200 / 입력: review_status, event_type, sort(CREATED_AT 또는 NEAR_THRESHOLD), model_version(NEAR_THRESHOLD 때 필수), cursor · limit
- 출력: Candidate[]
- 처리: 지금 시점에 양측 TRAINING 동의 · 평가용 강의 아님을 만족하는 미병합 후보만 정제본으로 보여준다. retrieved_evidence에는 판정 당시 검색 후보(evidence_id · evidence_type · evidence_text · location_label)를 담는다. NEAR_THRESHOLD는 판정 모델이 이관한 후보를 한 모델 버전 안에서 τ와 최고 점수의 차이가 작은 순으로 보여준다. 검수 맥락을 위해 강연명(session_title)을 함께 주되, 계정 식별자는 넣지 않는다. 강연명은 후보와 원래 강연의 연결로 읽으므로 병합 · 정리로 연결이 지워지면 함께 사라지고, 학습서버로 보내는 정제본에는 넣지 않는다.

#### API-54 PUT /admin/feedback-candidates/{cid}/reviews/me — 검수 결과 저장

- 정상: 200 / 입력: label(ANSWERABLE · INSUFFICIENT_EVIDENCE · OPINION · REJECT, 필수), evidence_id(조건부 필수), comment / 출력: Candidate
- 처리: AUTO_ESCALATED 후보를 ANSWERABLE로 고르면 검색 후보 중 정답 근거를 반드시 고른다. 두 검수자의 라벨과 근거가 같으면 APPROVED, 다르면 DISAGREEMENT다. 다른 검수자의 결과는 자기 검수 전에 보여주지 않는다. 병합 요청에 들어간 후보는 고칠 수 없다.
- 오류: 409 REVIEW_CONFLICT · CANDIDATE_NOT_ELIGIBLE, 422 VALIDATION_ERROR

#### API-55 POST /admin/datasets — 승인 후보 병합

- 정상: 202 / 입력: base_dataset_version(ds-vN, 필수), candidate_ids(필수), description, Idempotency-Key / 출력: Accepted
- 처리: 승인 · 양측 동의 · 평가용 강의 아님을 다시 확인하고 병합 요청 번호(merge_request_id)와 정리 기준 시각(cleanup_cutoff_at)을 고정한다. worker가 정제본을 7.4.5로 보낸다. 완료가 확인되면 후보와 원래 질문의 연결 · 검수자 대응 · 전송 대응표를 지우고, 기준 시각 이전에 생긴 검수 전 AUTO_ESCALATED 후보를 지운다(검수 중 · 병합 중 · 이후 생성 후보는 남김). 임의 파일 경로 · 분할 시드 입력은 받지 않는다.
- 오류: 409 CANDIDATE_NOT_ELIGIBLE · DATASET_NOT_READY

#### API-56 GET /admin/datasets — 데이터셋 버전 · 분포

- 정상: 200 / 입력: status, cursor · limit / 출력: Dataset[]
- 처리: 7.4.3 · 7.4.4에서 동기화한 복사본을 돌려준다. 원문과 다운로드 경로는 넣지 않는다.

#### API-57 POST /admin/training-runs — 학습 · 재학습 요청

- 정상: 202 / 입력: dataset_id(필수), config({epochs 1~10, batch_size 8 · 16, learning_rate 1e-6~1e-4}, 선택), Idempotency-Key / 출력: Accepted
- 처리: 진행 중(LIVE)인 강연이 있으면 409 LIVE_SESSION_IN_PROGRESS로 거부한다. 학습은 판정 추론과 같은 학과 서버 GPU를 쓰므로 강연 중의 판정 지연을 막기 위해서다. 통과하면 training_run_id를 만들고, worker가 이 값을 request_id로 7.4.7(auto_pipeline = true)을 부른다. 학습 시작 가중치는 원본 모델이며, 지정하지 않은 설정은 학습서버 기본값을 쓴다. 학습서버가 603으로 거부하면 422 VALIDATION_ERROR, 609면 409 TRAINER_BUSY로 바꿔 작업 결과에 남긴다. 이후 worker는 7.4.8만 주기적으로 조회한다.
- 오류: 409 LIVE_SESSION_IN_PROGRESS · TRAINER_BUSY, 422 VALIDATION_ERROR

#### API-58 GET /admin/training-runs/{run_id} — 학습 진행 · 결과

- 정상: 200 / 출력: TrainingRun
- 처리: 7.4.8에서 동기화한 상태 · 단계 · 진행률 · 학습 곡선 · 지표 · 등록 버전 · 배포 가능 여부를 돌려준다. HELD는 사유(precision_drop · below_target)를 함께 보여주고 자동으로 다시 실행하지 않는다.

#### API-59 DELETE /admin/training-runs/{run_id} — 학습 중단

- 정상: 202 / 출력: Accepted
- 처리: 7.4.9로 중단을 요청해 남은 변환 · 평가 · 등록까지 취소한다. 실제 CANCELLED는 7.4.8 결과로 동기화한다.
- 오류: 409 TRAINING_ALREADY_FINISHED

#### API-60 GET /admin/model-versions — 모델 버전 목록

- 정상: 200 / 입력: status(REGISTERED · DELETED), cursor · limit / 출력: ModelVersion[]
- 처리: 7.4.17 · 7.4.18 복사본이다. 화면은 served_before = false인 버전에만 전환 버튼을 deployable로 켜고, served_before = true인 버전과 LLM_ONLY만 롤백 목록에 보여준다.

#### API-61 GET /admin/evaluation-runs — 평가 결과

- 정상: 200 / 입력: dataset_id(필수), scope, split, model_version_ids / 출력: Evaluation[]
- 처리: 학습서버 평가(7.4.13)의 복사본만 조회한다. 이 API로 평가를 실행하지 않는다.

#### API-62 POST /admin/deployments — 서빙 전환 · 롤백 · LLM_ONLY

- 정상: 202 / 입력: mode(CUSTOM 또는 LLM_ONLY, 필수), model_version_id(CUSTOM 필수), expected_active_deployment_id(필수), reason(필수), Idempotency-Key / 출력: Accepted
- 처리: backend가 현재 서빙 상태와 요청 이력을 확인하고 경로를 정한다.
  - 서빙한 적 없는 버전: deployable = true만 받으며 7.4.22(전환)로 보낸다.
  - 서빙한 적 있는 버전 또는 LLM_ONLY: 7.4.23(롤백)으로 보낸다.
  모델 파일 · 임계값은 보내지 않는다. 학습서버가 바로 거부하면(614 · 610) 409로 응답하고 실패 이력을 남긴다. 접수 뒤 worker가 7.4.21로 실제 설정을 확인해 ACTIVE로 바꾼다.
- 오류: 409 DEPLOY_CRITERIA_NOT_MET · MODEL_NOT_DEPLOYABLE · VERSION_CONFLICT

#### API-63 GET /admin/deployments — 현재 서빙 설정 · 전환 이력

- 정상: 200 / 입력: cursor · limit / 출력: {active: ServingConfig, items: Deployment[], next_cursor}
- 처리: active는 7.4.21의 값이며, 학습서버에 닿지 않으면 마지막 동기화 값과 stale = true를 준다. 요청 이력과 실제 서빙 상태를 구분해 보여준다.

#### API-64 GET /admin/metrics — 운영 지표 · 예산 사용률

- 정상: 200 / 입력: from · to(필수, 최대 90일), group_by(day 또는 session, 필수), session_id / 출력: Metrics
- 처리: from은 포함, to는 제외한다. 표본이 없으면 비율과 분위수는 null이다. 필드는 7.3.8을 따른다. budget은 조회 기간과 관계없이 이번 달(Asia/Seoul 기준 1일 0시부터)의 추정 비용을 원화로 바꿔 월 예산과 비교한 값이며, 80% 이상이면 warning = true다. 예산을 정하지 않았으면 budget = null이다.

#### API-65 PUT /admin/budget-settings — 월 API 예산 설정

- 정상: 200 / 입력: monthly_budget_krw(정수, 1~10,000,000, 필수), usd_krw_rate(환산 환율, 필수), reason(필수) / 출력: {monthly_budget_krw, usd_krw_rate, updated_at}
- 처리: 예산과 환율을 저장하고 감사 기록을 남긴다. 사용률이 80%를 넘으면 운영 지표 화면에 경고를 보여준다. 예산을 넘어도 서비스를 자동으로 멈추거나 판정 경로를 바꾸지 않으며, 관리자가 판단해 LIVE 강연 종료나 LLM_ONLY 해제를 한다.
- 오류: 422 VALIDATION_ERROR

### 7.3.8 운영 지표 산출 기준

표: 운영 지표 필드

| 필드 | 형식 | 정의 |
|---|---|---|
| question_count | int | 기간 안에 접수된 질문 수 |
| ai_answer_count | int | AI_ANSWERED이고 답변이 ACTIVE인 질문 수 |
| escalated_count | int | ESCALATED 또는 COMPLETED인 질문 수 |
| ai_answer_share | float? | ai_answer_count / question_count (AI 답변 비중) |
| escalation_rate | float? | escalated_count / question_count |
| progress_max_ms · progress_p95_ms | number? | 질문 접수부터 첫 진행 상태(SEARCHING) 전달까지 |
| first_token_p50_ms | number? | 질문 접수부터 답변 첫 글자 전달까지(AI 답변 질문만) |
| final_p50_ms · final_p95_ms | number? | 질문 접수부터 답변 확정 또는 이관 확정까지 |
| stt_ingest_p95_ms | number? | 발화 시점부터 검색 가능(READY)까지. 30초 묶음 대기 포함 |
| fallback_count | int | 판정 추론 시간 초과 · 오류로 질문별 LLM_ONLY를 쓴 수(관리자 고정 LLM_ONLY와 구분) |
| second_stage_escalated_count | int | 판정은 통과했지만 Sonnet이 근거 부족으로 이관한 수 |
| retracted_count | int | 철회된 답변 수 |
| feedback_counts | object | 철회 사유별, 청중 HELPFUL · UNHELPFUL 수 |
| failed_jobs | int | 최종 실패한 작업 수 |
| external_calls | int | 외부 API 호출 수(재시도 포함) |
| estimated_cost_by_currency | object | 통화별 추정 비용 합계 |

운영 질문에는 검수된 정답이 없으므로 AI 처리율 · 오답 즉답률 · ROC-AUC는 운영 지표로 내지 않는다. 이 지표는 평가셋 결과(API-61)로만 본다.

### 7.3.9 요청 · 응답 예시

예시의 UUID와 버전 이름은 자리표시자이며, 응답은 data 부분만 적는다.

**질문 등록(API-27)**

```
POST /api/v1/sessions/{sid}/questions
Content-Type: application/json / 인증 쿠키 / X-CSRF-Token / Idempotency-Key: 0000…0301

{ "content": "방금 설명한 하이브리드 검색은 벡터 검색과 어떻게 달라요?", "document_id": "0000…0401", "page_no": 12 }

202 Accepted
{ "resource_id": "0000…0501", "job_id": "0000…0601", "status": "QUEUED" }
```

**질문자의 최종 결과(API-29)**

```
{ "question_id": "0000…0501", "content": "방금 설명한 하이브리드 검색은 벡터 검색과 어떻게 달라요?",
  "status": "AI_ANSWERED", "document_id": "0000…0401", "page_no": 12,
  "vote_count": 0, "voted_by_me": false, "my_note": null, "version": 3,
  "created_at": "2026-11-17T05:30:00Z", "escalation_reason": null, "processing_error": null,
  "answer": { "answer_id": "0000…0701", "status": "ACTIVE", "my_rating": null,
    "content": "하이브리드 검색은 의미가 비슷한 문장을 찾는 벡터 검색에 용어가 일치하는 문장을 찾는 키워드 검색을 더한 방식입니다.[1]",
    "citations": [ { "citation_no": 1, "chunk_id": "0000…0801", "source_type": "TRANSCRIPT",
      "location_label": "발화 14:32", "page_no": null, "start_ms": 872000, "end_ms": 902000,
      "excerpt": "의미가 비슷한 문장을 찾는 벡터 검색과 용어가 일치하는 문장을 찾는 키워드 검색을 함께 사용합니다." } ] } }
```

다른 참가자가 이 URI를 요청하면 개인 질문이므로 404를 받는다.

표: 주요 변경 요청 예시

| API | 요청 | 응답 · 학습서버 전달 |
|---|---|---|
| API-01 | {email:"member@example.com", password, display_name, consents:{SERVICE:{policy_version:"service-v1", granted:true}, TRAINING:{policy_version:"training-v1", granted:false}}} | 201 {status:"PENDING_VERIFICATION", resend_available_at} |
| API-03 | {email:"member@example.com", code:"482913"} | 200 {email_verified:true, next_action:"LOGIN"} |
| API-33 | {reason_code:"WRONG_OR_INSUFFICIENT"}, If-Match:"3" | 201 {question_id, answer_status:"RETRACTED", question_status:"ESCALATED", question_version:4} |
| API-35 | {content:"시험 범위. 3장 예제 다시 보기"} | 200 {content, question_text, updated_at} |
| API-40 | {target_type:"ARCHIVE", target_id:"<강연 UUID>"} | 202 {resource_id, job_id, status:"QUEUED"} |
| API-48 | {is_eval_lecture:true, reason:"검증 강좌 시연"}, If-Match:"1" | 200 {status:"DRAFT", is_eval_lecture:true, version:2} |
| API-54 | {label:"ANSWERABLE", evidence_id:"<조각 UUID>"} | 200 Candidate(review_status:"APPROVED") |
| API-55 | {base_dataset_version:"ds-v3", candidate_ids:["<UUID>"], description:"승인 후보 병합"} | 학습서버 7.4.5에 {request_id:"<merge_request_id>", items:[…]} |
| API-57 | {dataset_id:"<UUID>", config:{epochs:3}} | 학습서버 7.4.7에 {request_id:"<training_run_id>", dataset_version:"ds-v4", config_override:{epochs:3}, auto_pipeline:true} |
| API-58 | GET /admin/training-runs/<UUID> | {status:"HELD", stage:"eval", hold_reason:"precision_drop", model_version:null, deployable:null} |
| API-62 | {mode:"CUSTOM", model_version_id:"<judge-v4 UUID>", expected_active_deployment_id:"<UUID>", reason:"재학습 버전 배포"} | 학습서버 7.4.22에 {model_version:"judge-v4"}. 미달이면 409 DEPLOY_CRITERIA_NOT_MET |
| API-62 | {mode:"CUSTOM", model_version_id:"<judge-v3 UUID>", …, reason:"철회 증가"} | judge-v3은 서빙 이력이 있으므로 7.4.23에 {target:"judge-v3", reason} |

### 7.3.10 WebSocket 인터페이스

강연 중 실시간 전달은 REST와 별도로 정의한다.

표: WebSocket 연결 규칙

| 항목 | 규칙 |
|---|---|
| 연결 URI | wss://{서비스 도메인}/api/v1/ws/sessions/{sid} |
| 인증 | 같은 사이트의 HttpOnly 쿠키. 연결 때 Origin · 인증 · 강연 권한 확인 |
| 연결 단위 | 브라우저 탭당 강연 1개. 음성은 HOST의 활성 스트림 연결 1개만 |
| JSON 메시지 | {type, event_id, session_id, request_id, resource_version, data}. event_id는 서버가 발급 |
| 음성 프레임 | audio.start 승인 후 binary. 헤더: stream UUID 16바이트 + sequence uint32 + start_ms uint64(network byte order). 본문: 16 kHz · mono · PCM16 little-endian, 100 ms 단위 |
| 음성 한도 | 프레임 최대 32 KiB, 서버 메모리 버퍼 최대 5초. 넘치면 누락 구간을 알림 |
| 수신 확인 | audio.ack로 마지막 수신 sequence. 클라이언트는 확인되지 않은 프레임만 잠시 보관 |
| 재연결 | 1 · 2 · 4초 지수 대기(최대 15초, 무작위 지연 포함). 재연결 후 REST로 최신 상태를 다시 조회 |
| 중복 처리 | stream_id · sequence로 프레임 중복 제거, 확정 발화는 source_key로 중복 저장 방지 |
| 연결 유지 | 20초 간격 ping/pong, 60초 응답 없으면 종료 |
| 종료 코드 | 1000 정상, 1008 인증 · 권한 위반, 1009 프레임 초과, 1011 서버 오류 |

표: WebSocket 이벤트

| type | 방향 | 받는 대상 | data |
|---|---|---|---|
| connection.ready | 서버 → 클라이언트 | 현재 연결 | participant_id 또는 HOST 표시, 강연 version |
| audio.start | 클라이언트 → 서버 | HOST | stream_id, sample_rate = 16000, channels = 1. LIVE · STT 동의 · 활성 스트림 확인 |
| audio.accepted · audio.ack | 서버 → 클라이언트 | HOST | stream_id, next_sequence · sequence |
| audio.stop | 클라이언트 → 서버 | HOST | stream_id. 남은 발화 확정 후 입력 중단 |
| stt.status | 서버 → 클라이언트 | HOST | status, indexed_until_ms, ingest_lag_ms, error_code? |
| transcript.final | 서버 → 클라이언트 | HOST | start_ms, end_ms, text. 청중에게는 보내지 않음 |
| document.updated | 서버 → 클라이언트 | HOST | document_id, status, stage?, chunk_count?, error_code? |
| question.progress | 서버 → 클라이언트 | 질문자 | question_id, stage(SEARCHING "근거를 찾는 중" / WRITING "답변을 작성하는 중") |
| question.updated | 서버 → 클라이언트 | 질문자 · HOST | question_id, status (상세는 REST로 조회) |
| answer.delta | 서버 → 클라이언트 | 질문자 | question_id, generation_id, sequence, text, provisional = true |
| answer.completed | 서버 → 클라이언트 | 질문자 · HOST | question_id, answer_id (인용 검증을 마친 뒤) |
| answer.discarded | 서버 → 클라이언트 | 질문자 | question_id, generation_id, reason (임시 글자 제거) |
| answer.retracted | 서버 → 클라이언트 | 질문자 · HOST | question_id, answer_id |
| public_question.updated | 서버 → 클라이언트 | 참가자 · HOST | QuestionPublic 필드(voted_by_me · my_note 제외). 이관 · 공감 수 · 완료 변경 |
| session.updated | 서버 → 클라이언트 | 참가자(대기 중 포함) · HOST | status, stt_status, participant_count, version. DRAFT 대기 화면이 LIVE로 바뀌는 신호, 참가자 수 변경(5초에 한 번까지 묶어 보냄) |
| summary.updated | 서버 → 클라이언트 | 회원 참가자 · HOST | summary_id, status |
| auth.csrf_rotated | 서버 → 클라이언트 | 같은 인증 세션의 다른 탭 | 없음(탭은 API-06로 다시 받음) |
| error | 서버 → 클라이언트 | 현재 연결 | code, message, retryable |
| ping · pong | 양방향 | 현재 연결 | timestamp |

**개인 · 공개 이벤트 분리.** 질문자 채널은 서버가 인증 주체와 참가자 ID로 정한다. 클라이언트가 다른 participant_id를 보내 다른 사람 채널을 받을 수 없다. HOST는 자기 강연의 AI 답변 검토 이벤트만 받는다.

**답변 글자 전달.** 작성 중인 답변은 provisional = true인 임시 내용으로 보내고, 화면은 이를 작성 중으로 표시한다. 인용 검증까지 끝난 뒤에만 ACTIVE 답변을 저장하고 answer.completed를 보낸다. 근거 부족 · 검증 실패 · 중단이면 answer.discarded로 지우고 이관한다. 재연결한 화면은 임시 내용을 복원하지 않고 확정된 상태를 REST로 받는다.

**권한 재확인.** 로그아웃 · 정지 · 비밀번호 변경으로 인증 세션이 폐기되면 backend가 그 세션의 WebSocket을 닫는다. 폐기 알림이 빠지는 경우에 대비해, 연결 중에도 클라이언트 메시지를 받을 때 · 보호 데이터를 보낼 때 · 최대 30초마다 인증 세션과 참가 상태를 다시 확인하고, 폐기된 세션에는 새 데이터를 보내지 않는다.

**전달 보장.** 이벤트는 DB 커밋 뒤에 보낸다. 알림에는 대상 ID만 담고 backend가 받는 사람 권한에 맞는 최신 데이터를 읽어 보낸다. 알림이 빠지는 경우에 대비해, 재연결할 때 REST로 다시 조회하고 연결 중에는 15초마다 진행 중인 질문 상태를 맞춘다. 공감순 목록은 실시간으로 바뀌므로 화면이 페이지 사이의 중복 ID를 지우고 첫 페이지를 주기적으로 갱신한다.

### 7.3.11 auth 내부 API

auth가 backend · worker에게만 제공하는 API다. 경로는 /internal/v1이고 호출자별 서비스 키로 인증하며, Caddy가 외부로 프록시하지 않고 auth 포트도 호스트에 게시하지 않는다. 공개 API 65개에는 넣지 않는다. 상태 확인용 /health/live(프로세스) · /health/ready(DB 접근)를 함께 둔다.

표: auth 내부 API

| ID | Method · URI | 호출자 | 입출력 · 처리 |
|---|---|---|---|
| INT-01 | POST /internal/v1/guest-sessions | backend → auth | participant_id · request_id를 받아 GUEST · ACTIVE 참가와 강연 상태(DRAFT · LIVE) · 유효 기간을 RDS에서 다시 확인하고, 세션 쿠키 · CSRF 토큰 · expires_at을 돌려준다. 같은 게스트의 활성 세션은 하나이며, 다시 요청하면 기존 세션을 폐기하고 새로 발급한다 |
| INT-02 | POST /internal/v1/session-revocations | backend · worker → auth | user_id 또는 participant_id 중 하나와 reason · request_id를 받아 해당 세션을 모두 폐기하고 session.revoked 이벤트를 남긴다. 응답 {revoked_count}. 이미 폐기된 세션은 성공으로 본다 |

계정 정지 · 탈퇴 · 게스트 참가 철회 · 강연 종료에 따른 게스트 세션 정리는 backend가 업무 상태와 세션 폐기 작업(AUTH_REVOKE)을 한 트랜잭션으로 저장한다. 업무 상태가 바뀌는 즉시 backend의 권한 확인에서 접근이 막히므로, INT-02가 실패해도 worker가 재시도하는 동안 접근이 허용되지 않는다. 정지를 풀 때는 남은 기존 세션을 모두 폐기한 뒤 ACTIVE로 바꾼다.

## 7.4 AI학습서버 REST API 설계

AI학습서버는 서비스 서버와 따로 실행되는 FastAPI 서버이며, 데이터셋 등록부터 학습 · 평가 · fp16 변환 · 등록 · 서빙 전환 · 롤백 · 데이터 재수집 · 판정 추론 · 평가용 교안 조각 제공까지 28개 REST API로 제어한다. 기능 번호(T-xx)는 2.3 · 6.4와 같다.

### 학습서버 API 공통 규칙

표: 학습서버 API 공통 규칙

| 항목 | 규칙 |
|---|---|
| Base URL | 학과 서버 안: http://localhost:8000/api/v1. EC2 backend · worker: http://{Docker bridge 호스트 주소}:9000/api/v1(SSH 터널) |
| 호출하는 쪽 | ① backend · worker: 관리자 기능(7.4.3~7.4.5, 7.4.7~7.4.9, 7.4.13, 7.4.17 · 7.4.18, 7.4.21~7.4.25)과 교안 처리(7.4.28) ② worker 판정 어댑터: 7.4.1, 7.4.26 ③ AI 담당자: 학과 서버에서 localhost로 모든 API. ①②에 없는 API는 이 경로로만 씀 |
| 인증 | X-API-Key(backend · worker와 학습서버만 아는 키, 로그에 남기지 않음). 틀리면 401 · 612 |
| 형식 | 요청 · 응답 JSON, 시각은 ISO 8601(+09:00) |
| 공통 응답 | {result_code(int, 200 성공 · 6xx 오류), result_msg(String), data(Object)}. 6xx 코드는 8.4에 정의 |
| 오래 걸리는 작업 | 수집 · 학습 · 평가 · 변환은 202와 job_id를 바로 돌려주고, 상태는 작업 조회로 확인 |
| 작업 상태 | QUEUED → RUNNING → SUCCEEDED / FAILED / CANCELLED / HELD |
| 학습 단계 | stage: train → export(fp16 변환) → eval → register. hold_reason: precision_drop(fp16 하락 > 0.01) · below_target(등록 조건 미달) |
| 값 표기 | 라벨 ANSWERABLE · INSUFFICIENT_EVIDENCE · OPINION, 분할 TRAIN · VALIDATION · TEST, 모델 상태 REGISTERED · DELETED, 서빙 모드 CUSTOM · LLM_ONLY, 평가자 CUSTOM · SIMILARITY · PRETRAINED · SONNET_ONLY, 평가 범위 QUESTION · PAIR · SERVICE |
| 버전 이름 | ds-vN, val-vN, test-vN, rc-vN, es-vN, judge-vN, 작업 train-NNNN · eval-NNNN · export-NNNN · collect-NNNN |
| 저장 위치 | 데이터셋 · 체크포인트 · 모델 패키지 · 평가 리포트는 학과 서버 /data/easyq/ 아래에만 둠(7.4.29). 경로를 받는 API는 이 아래 경로만 받음 |
| 학습 레지스트리 | 데이터셋 · 작업 · 평가 · 모델 · 서빙 상태의 원본은 학습서버 레지스트리 DB(8.2). 서비스 DB는 조회한 복사본만 두고, 값이 다르면 학습서버 값을 따름 |

표: 학습서버 REST API 목록

| 번호 | Method | URI | 기능 | T |
|---|---|---|---|---|
| 7.4.1 | GET | /health | 서버 · 서빙 상태 확인 | T-19 |
| 7.4.2 | POST | /datasets | 데이터셋 버전 등록 | T-01 |
| 7.4.3 | GET | /datasets | 데이터셋 버전 목록 | T-02 |
| 7.4.4 | GET | /datasets/{dataset_version} | 데이터셋 상세 | T-02 |
| 7.4.5 | POST | /datasets/{dataset_version}/reviewed-labels | 검수 라벨 병합 | T-03 |
| 7.4.6 | POST | /collection-jobs | 데이터 재수집 | T-04 |
| 7.4.7 | POST | /train-jobs | 학습 · 재학습 | T-05 |
| 7.4.8 | GET | /train-jobs/{job_id} | 학습 진행 · 학습 곡선 | T-06 |
| 7.4.9 | DELETE | /train-jobs/{job_id} | 학습 중단 | T-07 |
| 7.4.10 | GET | /train-configs/default | 기본 학습 파라미터 조회 | T-08 |
| 7.4.11 | PUT | /train-configs/default | 기본 학습 파라미터 수정 | T-08 |
| 7.4.12 | POST | /evaluations | 모델 평가 | T-09 |
| 7.4.13 | GET | /evaluations/{evaluation_id} | 평가 결과 | T-09 |
| 7.4.14 | POST | /comparisons | 두 버전 비교 | T-10 |
| 7.4.15 | POST | /export-jobs | fp16 변환 | T-11 |
| 7.4.16 | POST | /models | 모델 버전 등록 | T-12 |
| 7.4.17 | GET | /models | 모델 버전 목록 | T-15 |
| 7.4.18 | GET | /models/{model_version} | 모델 버전 상세 | T-15 |
| 7.4.19 | PATCH | /models/{model_version} | 버전 메모 수정 | T-16 |
| 7.4.20 | DELETE | /models/{model_version} | 버전 삭제 | T-16 |
| 7.4.21 | GET | /deployment | 현재 서빙 설정 | T-13 |
| 7.4.22 | PUT | /deployment | 서빙 버전 전환 | T-13 |
| 7.4.23 | POST | /rollbacks | 롤백 | T-14 |
| 7.4.24 | GET | /jobs | 작업 목록 | T-17 |
| 7.4.25 | GET | /jobs/{job_id} | 작업 상태 | T-17 |
| 7.4.26 | POST | /judgments | 판정 추론 | T-18 |
| 7.4.27 | GET | /faults | 장애 기록 조회 | T-21 |
| 7.4.28 | GET | /eval-slide-chunks | 평가용 교안 조각 목록 | T-22 |

T-20(장애 기록)은 내부 함수(record_fault)로 처리하며 API가 없다.

### 7.4.1 서버 상태 확인 (T-19)

- GET /health · 호출: worker 판정 어댑터(10초마다)
- 출력: status(ok / degraded = 모델 미적재), mode(CUSTOM / LLM_ONLY), serving_version(LLM_ONLY면 null), threshold, gpu_busy(학습 · 평가 · 변환 실행 여부)

```
{ "result_code": 200, "result_msg": "",
  "data": { "status": "ok", "mode": "CUSTOM", "serving_version": "judge-v2", "threshold": 0.62, "gpu_busy": false } }
```

### 7.4.2 데이터셋 버전 등록 (T-01)

- POST /datasets · 호출: AI 담당자
- 입력: source_dir(/data/easyq/upload/ 아래 폴더, train.jsonl · validation.jsonl · test.jsonl과 평가용 강의 교안 조각 파일), script_version, retrieval_config_version(rc-vN), change_note
- 출력: dataset_version, validation_set_version · test_set_version(내용이 같으면 이전 버전을 이어 씀), eval_slide_version(es-vN), contains_aihub, storage_uri, statistics(분할별 질문 · 쌍 수, 라벨 · 출처별 건수), errors(검증 실패 시 파일 · 행 번호 · 사유)
- 처리: 6.4.1의 검사를 하고, 하나라도 어긋나면 601과 오류 행을 돌려준다. 평가용 교안 조각은 레지스트리 DB(reg_eval_slide_chunks)에 버전으로 저장한다.

```
IN  { "source_dir": "/data/easyq/upload/ds-1105/", "script_version": "build-dataset@1.2.0",
      "retrieval_config_version": "rc-v1", "change_note": "OCW 합성 + SQuAD 2.0 + AI Hub 기계독해, 시험셋 2인 교차 검수" }
OUT { "dataset_version": "ds-v1", "validation_set_version": "val-v1", "test_set_version": "test-v1",
      "eval_slide_version": "es-v1", "contains_aihub": true, "storage_uri": "/data/easyq/datasets/ds-v1/",
      "statistics": { "TRAIN": { "questions": 3000, "pairs": 4400,
                                 "label": { "ANSWERABLE": 1200, "INSUFFICIENT_EVIDENCE": 1200, "OPINION": 600 },
                                 "source": { "MIT_OCW": 2000, "SQUAD": 500, "AIHUB": 500 } },
                      "VALIDATION": { "questions": 480, "label": { "ANSWERABLE": 170, "INSUFFICIENT_EVIDENCE": 210, "OPINION": 100 } },
                      "TEST": { "questions": 620, "label": { "ANSWERABLE": 210, "INSUFFICIENT_EVIDENCE": 300, "OPINION": 110 } } },
      "errors": [] }
```

### 7.4.3 데이터셋 버전 목록 (T-02)

- GET /datasets?page&size · 호출: worker(API-56 동기화)
- 출력: datasets[](dataset_version · parent_version · status · contains_aihub · statistics · script_version · retrieval_config_version · test_set_version · test_use_count · change_note · created_at), total_count

### 7.4.4 데이터셋 상세 (T-02)

- GET /datasets/{dataset_version} · 호출: worker(API-56 동기화)
- 출력: statistics(분할별 질문 · 쌍 수, 라벨 · source · question_source별 건수), courses_by_split(분할별 강좌 ID), gold_in_candidates_rate(검증 · 시험셋), validation_set_version · test_set_version · eval_slide_version, test_use_count, contains_aihub · script_version · retrieval_config_version · change_note, storage_uri
- 오류: 613

```
{ "dataset_version": "ds-v1",
  "statistics": { "TRAIN": { "questions": 3000, "pairs": 4400, "source": { "MIT_OCW": 2000, "SQUAD": 500, "AIHUB": 500 } },
                  "VALIDATION": { "questions": 480, "question_source": { "SYNTHETIC": 480 } },
                  "TEST": { "questions": 620, "source": { "MIT_OCW": 400, "SELF_RECORDING": 220 },
                            "question_source": { "SYNTHETIC": 420, "HUMAN": 110, "STUDENT": 90 } } },
  "courses_by_split": { "TRAIN": ["6.006", "6.046J", "6.034"], "VALIDATION": ["6.0001"], "TEST": ["6.172", "SELF-01"] },
  "gold_in_candidates_rate": { "VALIDATION": 0.91, "TEST": 0.88 },
  "validation_set_version": "val-v1", "test_set_version": "test-v1", "eval_slide_version": "es-v1",
  "test_use_count": 0, "contains_aihub": true, "storage_uri": "/data/easyq/datasets/ds-v1/" }
```

### 7.4.5 검수 라벨 병합 (T-03)

- POST /datasets/{dataset_version}/reviewed-labels · 호출: worker(API-55)
- 입력: request_id(merge_request_id, 같은 값이 다시 오면 이전 결과를 돌려줌), items[](question_text · evidence_id · evidence_type · evidence_text · page_no · start_ms · end_ms · course_id + label + event_type, backend에서 1차 마스킹된 정제본), description
- 출력: dataset_version(새 버전), added, excluded_overlap, masked, skipped
- 처리: ① 2차 마스킹 → ② 평가용 강의 겹침 제외(6.4.3) → ③ evidence_id · course_id를 학습 전용 ID로 교체(대응표 미보관) 후 학습셋에만 더한다. 병합된 행은 source = FEEDBACK, question_source = FEEDBACK, label_source = HUMAN이다. 검증 · 시험셋과 test_use_count는 기준 버전 것을 그대로 잇는다.
- 오류: 601, 613

```
IN  { "request_id": "merge-7c1e9a40",
      "items": [ { "question_text": "역전파에서 기울기는 어떻게 전달돼요?", "evidence_id": "0b6f…", "evidence_type": "TRANSCRIPT",
                   "evidence_text": "역전파는 출력층에서 입력층 방향으로 …", "page_no": null, "start_ms": 1265000, "end_ms": 1295000,
                   "course_id": "svc-3f2a…", "label": "ANSWERABLE", "event_type": "AUDIENCE_HELPFUL" } ],
      "description": "11월 3주 시연 피드백 반영" }
OUT { "dataset_version": "ds-v2", "added": 180, "excluded_overlap": 3, "masked": 4, "skipped": 6 }
```

### 7.4.6 데이터 재수집 (T-04)

- POST /collection-jobs · 호출: AI 담당자
- 입력: sources[](name · url · license)
- 출력: job_id(collect-NNNN), status = QUEUED (상태는 7.4.25)
- 처리: 라이선스가 불분명하거나 접속에 실패한 항목은 빼고 장애로 남긴다(602). 결과는 /data/easyq/raw/에만 저장하며, 라벨링을 거쳐 7.4.2로 등록해야 학습에 쓴다. 수집 대상과 라이선스 기준은 3.1과 같다.

### 7.4.7 학습 · 재학습 (T-05)

- POST /train-jobs · 호출: worker(API-57), AI 담당자
- 입력: dataset_version, config_override(이번에만 바꿀 값, 범위는 7.4.11), init_from(시작 가중치, 기본 원본 모델. AI 담당자가 이어 학습할 때만 지정), memo, request_id(같은 값이 다시 오면 기존 job_id), auto_pipeline(기본 true)
- 출력: job_id(train-NNNN), status = QUEUED
- 처리: auto_pipeline이 true면 같은 작업 번호로 ① fp16 변환(7.4.15와 같음) → ② 평가(7.4.12와 같음, fp16 하락 확인 · τ 결정 · 시험셋 지표 · 베이스라인) → ③ 등록 조건 확인(시험셋 사용 횟수 1 증가) → ④ 등록(7.4.16과 같음) → ⑤ 서빙 버전과 비교(7.4.14와 같음, deployable 저장)를 이어서 한다. ②에서 하락이 0.01을 넘으면 precision_drop, ③을 넘지 못하면 below_target으로 HELD가 되고 이후 단계는 실행하지 않는다. 4.3의 격자 탐색처럼 체크포인트만 필요하면 auto_pipeline = false로 보낸다.
- 오류: 603, 609, 613

```
IN  { "dataset_version": "ds-v2", "config_override": { "learning_rate": 1e-5, "epochs": 2 },
      "memo": "피드백 라벨 180건 반영 재학습", "request_id": "3f9a1c2e-…", "auto_pipeline": true }
OUT { "job_id": "train-0007", "status": "QUEUED" }
```

### 7.4.8 학습 진행 · 학습 곡선 (T-06)

- GET /train-jobs/{job_id} · 호출: worker(주기 조회)
- 출력: status, stage, hold_reason, progress(0~1), curve[](epoch · train_loss · valid_loss · valid_auc), best_epoch, checkpoint_uri, config(실제 사용 값), export_job_id · evaluation_id · model_version, metrics(roc_auc · false_answer_rate · tpr · threshold · precision_auc_drop · latency_p95_ms · baselines · pair_roc_auc · retrieval_success_rate · evidence_hit_rate · test_use_count), deployable, error_code
- 처리: auto_pipeline 작업이 끝나면 status = SUCCEEDED, stage = register이고 단계별 결과가 모두 채워진다. backend는 이 API 하나로 training_runs 복사본을 갱신한다.
- 오류: 613

```
{ "job_id": "train-0007", "status": "RUNNING", "stage": "train", "progress": 0.55,
  "curve": [ { "epoch": 1, "train_loss": 0.41, "valid_loss": 0.36, "valid_auc": 0.86 } ],
  "best_epoch": 1, "checkpoint_uri": null,
  "config": { "learning_rate": 1e-5, "epochs": 2, "batch_size": 16, "hard_negatives": 2, "pos_weight": 2.7, "seed": 42 } }
```

### 7.4.9 학습 중단 (T-07)

- DELETE /train-jobs/{job_id} · 호출: worker(API-59)
- 출력: status = CANCELLED
- 처리: 현재 스텝을 마치고 GPU를 해제한다. 남은 변환 · 평가 · 등록은 실행하지 않는다.
- 오류: 608(이미 끝난 작업), 613

### 7.4.10 기본 학습 파라미터 조회 (T-08)

- GET /train-configs/default · 호출: AI 담당자
- 출력: config(base_model · max_length · learning_rate · hard_negatives · pos_weight · batch_size · grad_accum · epochs · patience · weight_decay · warmup_ratio · mixed_precision · seeds), updated_at
- 처리: pos_weight가 auto면 학습셋 쌍의 음성 : 양성 비로 계산하고, 실제 값은 7.4.8의 config에 남긴다. seeds의 각 값으로 학습해 검증셋 AUC가 가장 높은 체크포인트를 쓴다(4.3).

```
{ "config": { "base_model": "BAAI/bge-reranker-v2-m3", "max_length": 512, "learning_rate": 2e-5,
              "hard_negatives": 2, "pos_weight": "auto", "batch_size": 16, "grad_accum": 2, "epochs": 3,
              "patience": 1, "weight_decay": 0.01, "warmup_ratio": 0.1, "mixed_precision": true, "seeds": [42, 43, 44] },
  "updated_at": "2026-10-30T18:20:00+09:00" }
```

### 7.4.11 기본 학습 파라미터 수정 (T-08)

- PUT /train-configs/default · 호출: AI 담당자
- 입력: config(7.4.10과 같은 키). 허용 범위: learning_rate 1e-6~1e-4, epochs 1~10, hard_negatives 1~3, batch_size 8 · 16(실효 배치는 grad_accum으로 조절)
- 출력: 저장된 전체 config
- 처리: 이전 값을 이력으로 남겨 모델 버전별 학습 설정을 추적한다. API-57의 config도 같은 범위로 검사한다.
- 오류: 603(result_msg에 범위를 벗어난 키)

### 7.4.12 모델 평가 (T-09)

- POST /evaluations · 호출: AI 담당자
- 입력: target({export_job_id} 또는 {model_version}), dataset_version, max_fpr(기본 0.04), with_baselines(기본 true)
- 출력: evaluation_id(eval-NNNN), status = QUEUED
- 처리: 판정 모델은 항상 서비스와 같은 fp16 모델로 평가하고, fp32 체크포인트는 검증셋 하락 비교에만 쓴다. 절차는 6.4.8과 같다.
- 오류: 609, 613

### 7.4.13 평가 결과 (T-09)

- GET /evaluations/{evaluation_id} · 호출: worker(API-61 동기화), AI 담당자
- 출력:
  - dataset_version · validation_set_version · test_set_version · retrieval_config_version
  - threshold(τ), valid_auc_fp32 · valid_auc_fp16 · precision_auc_drop, latency_p95_ms(변환 작업에서 잰 값)
  - roc_auc · false_answer_rate · tpr(시험셋 질문 단위 value · ci_low · ci_high, τ 지점)
  - eval_counts(정답 근거가 후보에 든 답변 가능 · 이관 대상 수), escalation_by_label(OPINION = 의견 질문 이관율), by_question_source, pair_roc_auc, roc_points[](fpr · tpr · threshold)
  - service_metrics(retrieval_success_rate · retrieval_fail_answer_rate · evidence_hit_rate)
  - baselines[](evaluator · roc_auc · false_answer_rate · tpr · threshold · reused), llm_only(threshold = τ_LLM · llm_model_id · llm_prompt_version)
  - test_use_count(등록 판단에 처음 쓰인 시점의 값, 아직이면 null)
- 처리: τ와 τ_LLM의 선정 규칙, 베이스라인 재사용 조건은 6.4.8과 같다.
- 오류: 607, 613

```
{ "evaluation_id": "eval-0011", "status": "SUCCEEDED",
  "dataset_version": "ds-v2", "validation_set_version": "val-v1", "test_set_version": "test-v1", "retrieval_config_version": "rc-v1",
  "threshold": 0.62, "valid_auc_fp32": 0.884, "valid_auc_fp16": 0.882, "precision_auc_drop": 0.002, "latency_p95_ms": 180,
  "roc_auc": { "value": 0.88, "ci_low": 0.85, "ci_high": 0.91 },
  "false_answer_rate": { "value": 0.042, "ci_low": 0.025, "ci_high": 0.066 },
  "tpr": { "value": 0.61, "ci_low": 0.54, "ci_high": 0.68 },
  "eval_counts": { "answerable_in_candidates": 185, "escalation_targets": 410 },
  "escalation_by_label": { "ANSWERABLE": 0.39, "INSUFFICIENT_EVIDENCE": 0.95, "OPINION": 0.97 },
  "by_question_source": { "SYNTHETIC": { "roc_auc": 0.89 }, "HUMAN": { "roc_auc": 0.86 }, "STUDENT": { "roc_auc": 0.84 } },
  "pair_roc_auc": 0.91,
  "roc_points": [ { "fpr": 0.0, "tpr": 0.0, "threshold": 1.0 }, { "fpr": 0.042, "tpr": 0.61, "threshold": 0.62 } ],
  "service_metrics": { "retrieval_success_rate": 0.88, "retrieval_fail_answer_rate": 0.20, "evidence_hit_rate": 0.79 },
  "baselines": [ { "evaluator": "SIMILARITY", "roc_auc": 0.71, "false_answer_rate": 0.05, "tpr": 0.22, "reused": true },
                 { "evaluator": "PRETRAINED", "roc_auc": 0.78, "false_answer_rate": 0.05, "tpr": 0.35, "reused": true },
                 { "evaluator": "SONNET_ONLY", "roc_auc": 0.83, "false_answer_rate": 0.06, "tpr": 0.48, "threshold": 70, "reused": true } ],
  "llm_only": { "threshold": 70, "llm_model_id": "claude-sonnet-…", "llm_prompt_version": "llm-only-v1" },
  "test_use_count": 2 }
```

### 7.4.14 두 버전 비교 (T-10)

- POST /comparisons · 호출: AI 담당자(등록 직후에는 학습서버가 자동 실행)
- 입력: base_version(보통 서빙 버전), candidate_version, test_set_version(생략하면 새 버전의 시험셋)
- 출력: base · candidate(roc_auc · false_answer_rate · tpr), deployable, reason
- 처리: 기준 버전에 그 시험셋 버전의 평가가 없으면 먼저 평가한다(시험셋 사용 횟수는 올리지 않음). 새 버전이 등록 조건을 만족하고 질문 단위 ROC-AUC가 기준 버전 이상이면 deployable = true다.
- 오류: 613

### 7.4.15 fp16 변환 (T-11)

- POST /export-jobs · 호출: AI 담당자(자동 연결 학습에서는 학습 작업의 한 단계)
- 입력: train_job_id, precision("fp16")
- 출력: job_id(export-NNNN), status = QUEUED. 완료 후 7.4.25의 result에 model_uri · latency_p95_ms
- 처리: fp32 체크포인트를 fp16으로 바꿔 model.safetensors로 저장하고, 학과 서버 GPU에서 질문 1개의 후보 20쌍 추론 시간을 반복 측정해 p95를 남긴다. fp16 하락은 평가(7.4.12)에서 확인하며, 변환 작업은 임계값을 받지 않는다.
- 오류: 604, 609, 613

### 7.4.16 모델 버전 등록 (T-12)

- POST /models · 호출: AI 담당자(자동 연결 학습에서는 학습 작업의 한 단계)
- 입력: evaluation_id(fp16 변환본을 평가한 SUCCEEDED 평가), memo
- 출력: model_version(judge-vN), artifact_uri, manifest(4.4), status = REGISTERED, deployable · compared_with
- 처리: 등록 조건(fp16 질문 단위 ROC-AUC ≥ 0.85, 시험셋 오답 즉답률 ≤ 5%, 그 지점 TPR ≥ 0.5, 베이스라인 3종보다 ROC-AUC 높음, fp16 하락 ≤ 0.01, 추론 시간 p95 ≤ 500 ms)을 확인한다. 그 평가가 처음 등록 판단에 쓰이면 통과 여부와 관계없이 시험셋 사용 횟수를 1 올린다. 등록 직후 서빙 버전과 비교해 deployable을 저장한다(서빙 중인 모델이 없으면 compared_with = null, 등록 조건으로 판단).
- 오류: 613, 615(result_msg에 미달 항목)

```
IN  { "evaluation_id": "eval-0011", "memo": "ds-v2 재학습, 학습률 1e-5" }
OUT { "model_version": "judge-v2", "artifact_uri": "/data/easyq/models/judge-v2/",
      "manifest": { "dataset_version": "ds-v2", "test_set_version": "test-v1", "format": "pytorch-fp16", "threshold": 0.62,
                    "metrics": { "roc_auc": 0.88, "false_answer_rate": 0.042, "tpr": 0.61,
                                 "precision_auc_drop": 0.002, "latency_p95_ms": 180 }, "test_use_count": 2 },
      "status": "REGISTERED", "deployable": true, "compared_with": "judge-v1" }
```

### 7.4.17 모델 버전 목록 (T-15)

- GET /models?status · 호출: worker(API-60 동기화)
- 출력: models[](model_version · dataset_version · test_set_version · roc_auc · false_answer_rate · tpr · threshold · precision_auc_drop · latency_p95_ms · status · serving · served_before · deployable · compared_with · memo · created_at)

```
{ "models": [ { "model_version": "judge-v2", "dataset_version": "ds-v2", "test_set_version": "test-v1",
                "roc_auc": 0.88, "false_answer_rate": 0.042, "tpr": 0.61, "threshold": 0.62,
                "precision_auc_drop": 0.002, "latency_p95_ms": 180, "status": "REGISTERED",
                "serving": false, "served_before": false, "deployable": true, "compared_with": "judge-v1",
                "memo": "ds-v2 재학습", "created_at": "2026-11-21T09:40:00+09:00" } ] }
```

### 7.4.18 모델 버전 상세 (T-15)

- GET /models/{model_version} · 호출: worker(API-60 동기화)
- 출력: manifest(model.safetensors의 sha256 포함), evaluation_id, roc_points, train_curve, baselines, deployable · compared_with
- 오류: 613

```
{ "manifest": { "model_version": "judge-v2", "base_model": "BAAI/bge-reranker-v2-m3", "dataset_version": "ds-v2",
                "format": "pytorch-fp16", "threshold": 0.62, "artifact_sha256": "9c1f…",
                "metrics": { "roc_auc": 0.88, "false_answer_rate": 0.042, "tpr": 0.61 } },
  "evaluation_id": "eval-0011",
  "roc_points": [ { "fpr": 0.042, "tpr": 0.61, "threshold": 0.62 } ],
  "train_curve": [ { "epoch": 1, "valid_auc": 0.86 }, { "epoch": 2, "valid_auc": 0.88 } ],
  "baselines": [ { "evaluator": "SIMILARITY", "roc_auc": 0.71 } ],
  "deployable": true, "compared_with": "judge-v1" }
```

### 7.4.19 버전 메모 수정 (T-16)

- PATCH /models/{model_version} · 호출: AI 담당자
- 입력: memo / 출력: model_version, memo
- 오류: 613

### 7.4.20 버전 삭제 (T-16)

- DELETE /models/{model_version} · 호출: AI 담당자
- 출력: status = DELETED
- 처리: 서빙 중인 버전과 직전 서빙 버전은 지울 수 없다. 모델 저장소의 패키지는 지우고 레지스트리의 지표 기록은 남긴다.
- 오류: 610, 613

### 7.4.21 현재 서빙 설정 (T-13)

- GET /deployment · 호출: worker(전환 확인 · 주기 동기화), backend(API-63)
- 출력: mode, serving_version(LLM_ONLY면 null), previous_version, threshold, llm_only_threshold(τ_LLM, 0~101), llm_model_id · llm_prompt_version(날짜가 붙은 고정 모델 ID와 프롬프트 버전), deployed_at
- 처리: 서비스는 이 응답을 실제 서빙 설정의 원본으로 보고, 서비스 DB의 복사본과 다르면 이 값을 따른다. LLM_ONLY 판정은 이 모델 · 프롬프트 · τ_LLM으로 한다.

```
{ "mode": "CUSTOM", "serving_version": "judge-v2", "previous_version": "judge-v1",
  "threshold": 0.62, "llm_only_threshold": 70, "llm_model_id": "claude-sonnet-…",
  "llm_prompt_version": "llm-only-v1", "deployed_at": "2026-11-21T10:05:00+09:00" }
```

### 7.4.22 서빙 버전 전환 (T-13)

- PUT /deployment · 호출: backend(API-62, 서빙한 적 없는 버전)
- 입력: model_version(REGISTERED, 서빙 이력 없음)
- 출력: serving_version(실패 시 기존 버전), threshold · llm_only_threshold · llm_model_id · llm_prompt_version
- 처리: 요청 시점의 서빙 버전과 같은 시험셋 버전으로 비교해(7.4.14 기준) 통과할 때만 전환한다. 서빙 중인 모델이 없으면(첫 배포 · LLM_ONLY 상태) 등록 조건만 본다. 새 모델을 GPU 메모리에 기존 모델과 나란히 올려 시험 질문 5건으로 점검한 뒤 교체하고, 그 버전 평가의 SONNET_ONLY 결과(τ_LLM · 모델 ID · 프롬프트 버전)를 서빙 설정에 넣는다.
- 오류: 605, 610(삭제된 버전 · 서빙 이력이 있는 버전), 614

### 7.4.23 롤백 (T-14)

- POST /rollbacks · 호출: backend(API-62, 서빙한 적 있는 버전 · LLM_ONLY)
- 입력: target(previous / 서빙한 적 있는 버전 이름 / LLM_ONLY), reason
- 출력: mode, serving_version, threshold · llm_only_threshold · llm_model_id · llm_prompt_version
- 처리: 이미 서빙해 검증된 버전이므로 배포 비교 없이 다시 적재하고, 그 버전의 τ와 평가의 τ_LLM을 쓴다. LLM_ONLY로 롤백하면 현재 τ_LLM · 모델 ID · 프롬프트 버전을 그대로 두고 판정 모델을 쓰지 않는다. LLM_ONLY에서 판정 모델로 돌아갈 때도 서빙했던 버전을 target으로 보낸다.
- 오류: 605, 610(서빙 이력 없음 · 삭제된 버전)

```
IN  { "target": "previous", "reason": "강연자 철회 증가" }
OUT { "mode": "CUSTOM", "serving_version": "judge-v1", "threshold": 0.60, "llm_only_threshold": 70,
      "llm_model_id": "claude-sonnet-…", "llm_prompt_version": "llm-only-v1" }
```

### 7.4.24 작업 목록 (T-17)

- GET /jobs?type&status&page&size · 호출: backend(실행 중 작업 표시), AI 담당자
- 입력: type(collect · train · eval · export), status
- 출력: jobs[](job_id · type · status · progress · created_at · finished_at)

### 7.4.25 작업 상태 (T-17)

- GET /jobs/{job_id} · 호출: backend, AI 담당자
- 출력: type · status · progress, result(수집: collected · excluded / 변환: model_uri · latency_p95_ms / 평가: evaluation_id), fault_id(실패 시)
- 오류: 613

```
{ "job_id": "export-0004", "type": "export", "status": "SUCCEEDED", "progress": 1.0,
  "result": { "model_uri": "/data/easyq/exports/export-0004/model.safetensors", "latency_p95_ms": 180 }, "fault_id": null }
```

### 7.4.26 판정 추론 (T-18)

- POST /judgments · 호출: worker 판정 어댑터(질문마다, 타임아웃 800 ms)
- 입력: request_id(질문 처리 번호), question, candidates[](최대 20개: evidence_id · evidence_type(DOCUMENT/TRANSCRIPT) · text), top_k(기본 5)
- 출력: model_version, threshold, decision(ANSWER = 최고 점수 ≥ τ / ESCALATE), max_score, ranked[](evidence_id · score), selected(점수 ≥ τ, 최대 top_k), latency_ms
- 처리: 추론 프로세스는 학습 작업과 분리되어 GPU에 상주하며, 후보 20개를 한 배치로 채점한다. 서빙 모드가 LLM_ONLY이면 611을 돌려준다. 어댑터는 800 ms를 넘기거나 611을 받으면 그 질문만 LLM_ONLY로 판정한다. evidence_id는 서비스 knowledge_chunks의 chunk_id다.
- 오류: 611

```
IN  { "request_id": "q-8f1a2c", "question": "역전파에서 기울기 소실은 왜 생겨요?",
      "candidates": [ { "evidence_id": "c1a9…", "evidence_type": "DOCUMENT", "text": "시그모이드의 미분값은 최대 0.25…" },
                      { "evidence_id": "7e02…", "evidence_type": "TRANSCRIPT", "text": "층이 깊어지면 작은 값이 계속 곱해져…" } ],
      "top_k": 5 }
OUT { "model_version": "judge-v2", "threshold": 0.62, "decision": "ANSWER", "max_score": 0.91,
      "ranked": [ { "evidence_id": "7e02…", "score": 0.91 }, { "evidence_id": "c1a9…", "score": 0.77 } ],
      "selected": [ "7e02…", "c1a9…" ], "latency_ms": 95 }
```

### 7.4.27 장애 기록 조회 (T-21)

- GET /faults?from&to&code&job_id · 호출: AI 담당자
- 출력: faults[](fault_id · occurred_at · code · module · job_id · message)

```
{ "faults": [ { "fault_id": "f-0031", "occurred_at": "2026-11-20T23:14:05+09:00", "code": 604, "module": "export",
                "job_id": "export-0003", "message": "fp16 변환 실패: 체크포인트 파일 누락" } ] }
```

### 7.4.28 평가용 교안 조각 목록 (T-22)

- GET /eval-slide-chunks?since_version · 호출: worker(교안 처리 시작 때)
- 입력: since_version(worker가 가진 목록 버전, 선택)
- 출력: eval_slide_version, match_rule({ngram:5, chunk_overlap:0.8, session_ratio:0.3}), chunks[](chunk_key · course_id · page_no · text). since_version이 최신과 같으면 chunks = []
- 처리: 평가용 강의(6.0001 · 6.172 · 자체 녹음 강의)의 교안 조각만 담는다. worker는 받은 목록을 서비스 DB eval_reference_chunks에 버전과 함께 저장하고 6.1.6대로 검사한다. 목록은 검증 · 시험셋이 바뀔 때만 버전이 오른다.

```
{ "eval_slide_version": "es-v1", "match_rule": { "ngram": 5, "chunk_overlap": 0.8, "session_ratio": 0.3 },
  "chunks": [ { "chunk_key": "6.172-L03-p12", "course_id": "6.172", "page_no": 12, "text": "Cache-oblivious algorithms …" } ] }
```

### 7.4.29 학습서버 내부 인터페이스

REST API 안쪽에서 모듈끼리 주고받는 함수와 파일 형식이다. 함수 이름은 snake_case를 따른다.

표: 학습서버 내부 함수

| 모듈 | 함수 | 입력 | 출력 | 기능 |
|---|---|---|---|---|
| 데이터셋 | validate_dataset(source_dir) | 데이터셋 폴더 | ValidationReport(오류 행 · 통계) | T-01 |
| 데이터셋 | build_eval_slide_chunks(dataset_version) | 데이터셋 버전 | eval_slide_version | T-01, T-22 |
| 데이터셋 | mask_pii(text) | 질문 · 근거 문자열 | 가린 문자열, 가린 항목 수 | T-03 |
| 데이터셋 | check_overlap(items, eval_texts) | 피드백 쌍, 평가용 교안 · 검증 · 시험셋 텍스트 | 통과 쌍, 제외 쌍(공용 검색 모듈의 겹침 함수) | T-03 |
| 데이터셋 | merge_labels(base_version, items, request_id) | 기준 버전, 라벨, 요청 번호 | 새 dataset_version | T-03 |
| 학습 | build_pairs(dataset, hard_negatives) | 데이터셋, 오답 수 | (질문, 근거, 0/1) 쌍, pos_weight | T-05 |
| 학습 | train(config, dataset_version, init_from) | 파라미터, 데이터셋, 시작 가중치 | CheckpointInfo(경로 · best_epoch · curve · seed) | T-05 |
| 변환 | export_fp16(checkpoint) | fp32 체크포인트 | model.safetensors 경로 | T-11 |
| 변환 | measure_latency(model_path, n_pairs = 20) | fp16 모델 | latency_p95_ms | T-11 |
| 평가 | select_threshold(scores, labels, max_fpr) | 질문별 최고 점수, 라벨, FPR 기준 | τ | T-09 |
| 평가 | evaluate(model, dataset_version, max_fpr) | fp16 모델, 데이터셋, FPR 기준 | EvalReport(τ · roc_auc · false_answer_rate · tpr · roc_points · service_metrics) | T-09 |
| 평가 | run_baselines(dataset_version, llm_model_id, prompt_version) | 데이터셋, Sonnet 모델 · 프롬프트 | 베이스라인 3종 결과, τ_LLM(재사용 조건이면 저장값) | T-09 |
| 배포 | register_model(evaluation_id) | 평가 | model_version, manifest | T-12 |
| 추론 | load_model(model_version) | 버전 | GPU에 올린 fp16 모델 | T-13 |
| 추론 | score(question, evidences) | 질문, 근거 목록 | 근거별 점수 | T-18 |
| 장애 | record_fault(code, module, job_id, message) | 오류 정보 | fault_id(레지스트리 DB + 장애 로그) | T-20 |

표: 학습서버 파일

| 파일 | 위치(학과 서버) | 형식 · 내용 |
|---|---|---|
| 학습셋 | /data/easyq/datasets/ds-vN/train.jsonl | 한 줄에 한 쌍. 필드는 3.3.3 학습 필드 |
| 검증 · 시험셋 | /data/easyq/datasets/ds-vN/validation.jsonl, test.jsonl | 한 줄에 질문 하나(후보 최대 20개 포함). 필드는 3.3.3 평가 필드 |
| 체크포인트 | /data/easyq/checkpoints/train-NNNN/ | fp32 가중치 · 토크나이저 · config.json |
| 변환본 | /data/easyq/exports/export-NNNN/ | model.safetensors(fp16) |
| 모델 패키지 | /data/easyq/models/judge-vN/ | model.safetensors · tokenizer/ · manifest.json(4.4) |
| 평가 리포트 | /data/easyq/evaluations/eval-NNNN.json | 7.4.13 응답 + 질문별 최고 점수 |
| 실행 로그 | /data/easyq/logs/trainer-{date}.jsonl | 8.3 공통 필드(service = training) |
| 장애 로그 | /data/easyq/logs/fault-{date}.jsonl | 8.4 오류 파일 형식 |

평가용 교안 조각은 파일이 아니라 레지스트리 DB(reg_eval_slide_chunks)에 버전으로 둔다. 학습서버 레지스트리 DB(reg_datasets · reg_test_sets · reg_jobs · reg_evaluations · reg_models · reg_deployments · reg_train_configs · reg_eval_slide_chunks · reg_merge_requests · reg_faults, 8.2.38)가 학습 쪽 정보의 원본이며, 서비스 DB에는 복사본(datasets · training_runs · model_versions · deployments · evaluation_runs)과 평가용 교안 조각(eval_reference_chunks)만 둔다. 두 DB는 8.1 · 8.2에 나눠 정의한다.

### 7.4.30 서비스 API와 학습서버 API의 대응

표: 서비스 API · 모듈과 학습서버 API

| 서비스 API · 모듈 | 하는 일 | 학습서버 API |
|---|---|---|
| API-53 · API-54 | 라벨 후보 조회 · 검수 | 없음(서비스 DB) |
| API-55 | 승인 후보 병합 | 7.4.5 (request_id = merge_request_id) |
| API-56 | 데이터셋 버전 · 분포 | 7.4.3 · 7.4.4 |
| API-57 | 학습 · 재학습 | 7.4.7 (request_id = training_run_id, auto_pipeline = true) |
| API-58 | 진행 · 결과 | 7.4.8 |
| API-59 | 학습 중단 | 7.4.9 |
| API-60 | 모델 버전 | 7.4.17 · 7.4.18 |
| API-61 | 평가 결과 | 7.4.13 (조회만) |
| API-62 (서빙한 적 없는 버전) | 서빙 전환 | 7.4.22 |
| API-62 (서빙한 적 있는 버전 · LLM_ONLY) | 롤백 | 7.4.23 |
| API-63 | 현재 서빙 설정 | 7.4.21, 실행 중 작업은 7.4.24 |
| worker 교안 처리(R1) | 평가용 강의 판정 | 7.4.28 |
| worker 판정 어댑터(R3) | 질문별 판정 · 상태 확인 | 7.4.26 · 7.4.1 |
| worker LLM 어댑터 | LLM_ONLY 판정 | 없음(7.4.21의 τ_LLM · 모델 ID · 프롬프트 버전 사용) |

나머지 학습서버 API(7.4.2, 7.4.6, 7.4.10~7.4.12, 7.4.14~7.4.16, 7.4.19 · 7.4.20, 7.4.27)는 관리자 웹과 연결하지 않고 AI 담당자가 학과 서버에서 호출한다.
