# 학과 서버에 학습서버 올리기 (PROGRESS 단계 4)

> 학과 서버(ceprj, Rocky Linux, Python 3.9, 가상환경 · docker 없음)에 학습서버 API를 처음 올리고, 내 PC에서 SSH 터널로 닿는지 확인한다.
> 이번에는 **GPU를 쓰지 않는다**(판정 추론 · 학습은 단계 5 · 6). 명령은 서버에 `t26112`로 접속해서 친다.

| 위치 | 경로 |
|---|---|
| 코드 | `/home/t26112/easyq-ai` (git clone) |
| 파이썬 패키지 | `/home/t26112/easyq-ai/.pylib` (`pip --target`, 아래 이유) |
| 데이터 · 장부 · 로그 | `/home/t26112/easyq-data` (`DATA_ROOT`, design-changes 4번) |

**왜 `pip --user`가 아니라 `--target`인가:** `--user`는 `~/.local`에 깔려 같은 계정의 모든 파이썬에 적용된다. 팀 공용 계정이라 다른 사람 코드의 fastapi · pydantic 버전이 바뀔 수 있다. `--target`은 우리 폴더에만 깔리고 `PYTHONPATH`로 우리 프로세스만 쓴다. 서버에 있는 torch는 그대로 보인다.

---

## 0. 먼저 확인 (아무것도 바꾸지 않음)

```bash
python3 --version                    # 3.9.x
python3 -m pip --version
python3 -c "import torch; print(torch.__version__, torch.cuda.is_available())"   # 2.1.2 True (단계 5부터 필요)
ss -ltn | grep -E ':(8000|8001)\b'   # 아무것도 안 나와야 한다. 나오면 다른 사람이 쓰는 포트 → 멈추고 알려주기
df -h /home                          # 여유 공간
```

## 1. 코드 받기

```bash
cd /home/t26112
git clone https://github.com/EasyQ-P/AI.git easyq-ai   # 비공개 레포면 GitHub 토큰 · SSH 키 필요
cd easyq-ai
git checkout dev
```

이미 있으면 `cd /home/t26112/easyq-ai && git pull`.

## 2. 패키지 설치

```bash
cd /home/t26112/easyq-ai
python3 -m pip install --target .pylib -r trainer/requirements-server.txt
```

## 3. 데이터 폴더 · 설정

```bash
mkdir -p /home/t26112/easyq-data/{registry,jobs,logs,upload,datasets,checkpoints,exports,models,evaluations}
chmod 700 /home/t26112/easyq-data

cd /home/t26112/easyq-ai
cp .env.example .env
chmod 600 .env
```

`.env`를 열어(`vi .env`) 이렇게 맞춘다.

```
TRAINER_ENV=prod
REGISTRY_DB_URL=
DATA_ROOT=/home/t26112/easyq-data
GPU_DEVICE=0
```

API 키는 화면에 찍지 않고 바로 파일에 넣는다(원래 있던 `TRAINER_API_KEY=` 줄은 지운다).

```bash
sed -i '/^TRAINER_API_KEY=/d' .env
printf 'TRAINER_API_KEY=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> .env
```

`GEMINI_API_KEY`는 서버에 넣지 않는다(학과 서버에서는 Gemini를 쓰지 않는다).

## 4. 실행 환경 변수 (접속할 때마다)

```bash
cd /home/t26112/easyq-ai
export PYTHONPATH=/home/t26112/easyq-ai/.pylib:/home/t26112/easyq-ai/trainer:/home/t26112/easyq-ai/retrieval/src
```

매번 치기 싫으면 `~/.bashrc`에 넣지 말고(공용 계정) `easyq-env.sh` 파일로 두고 `source easyq-env.sh`.

## 5. 레지스트리 DB 만들기

```bash
python3 -m alembic -c trainer/alembic.ini upgrade head
python3 -m alembic -c trainer/alembic.ini current     # 4d5f3a7aaa3d (head)
ls -l /home/t26112/easyq-data/registry/                # registry.db
```

## 6. API 켜기 · 끄기

켜기(접속을 끊어도 돈다):

```bash
nohup python3 -m uvicorn app.main:app --app-dir trainer --host 127.0.0.1 --port 8000 \
  >> /home/t26112/easyq-data/logs/api.log 2>&1 &
echo $! > /home/t26112/easyq-data/api.pid
```

서버 안에서 확인(키 없이 → 401이면 정상, 키를 찍지 않는 확인법):

```bash
curl -s -o /dev/null -w '%{http_code}\n' http://127.0.0.1:8000/api/v1/health    # 401
```

키를 넣은 확인. 키를 `curl` 명령줄에 붙이지 않는다. 공용 계정이라 실행 중인 명령줄은 같은 계정의 다른 프로세스가 `ps`로 볼 수 있기 때문이다. `printf`는 셸 내장 명령이라 명령줄에 남지 않고, `curl -H @-`가 헤더를 표준 입력에서 읽는다.

```bash
grep '^TRAINER_API_KEY=' .env | cut -d= -f2- | { read -r KEY; printf 'X-API-Key: %s\n' "$KEY"; } \
  | curl -s -H @- http://127.0.0.1:8000/api/v1/health; echo
# {"result_code":200,...,"data":{"status":"ok","mode":"LLM_ONLY","serving_version":null,"threshold":null,"gpu_busy":false,"model_loaded":false}}
```

끄기(우리가 띄운 프로세스만):

```bash
kill "$(cat /home/t26112/easyq-data/api.pid)" && rm /home/t26112/easyq-data/api.pid
```

`pkill python` · `killall` 같은 건 쓰지 않는다(공용 계정의 다른 프로세스까지 죽는다).

## 7. 내 PC에서 SSH 터널로 확인

내 PC PowerShell에서(서버 주소 · 포트는 학과 서버 안내대로):

```powershell
ssh -N -L 8000:127.0.0.1:8000 t26112@<학과 서버 주소>
```

다른 PowerShell 창에서:

```powershell
curl.exe -s -o NUL -w "%{http_code}`n" http://127.0.0.1:8000/api/v1/health
```

`401`이 나오면 터널 · API 모두 정상이다(키 없이 확인). 내 PC에서 로컬 API를 8000으로 켜 두었다면 먼저 끈다.

## 8. 끝나면 PROGRESS에 적을 것

- python · pip · torch 버전, `cuda.is_available()` 결과
- 8000 · 8001 포트가 비어 있었는지
- 설치 중 오류(있었다면 메시지 앞부분)
- 서버 안 401 · 200 확인, PC 터널 401 확인

## 문제가 생기면

| 증상 | 원인 · 조치 |
|---|---|
| `TRAINER_API_KEY가 없거나 기본값` 으로 시작 안 함 | 3번의 키 넣기를 안 했다 |
| `no such table: reg_jobs` | 5번 `alembic upgrade head`를 안 했다 |
| `ModuleNotFoundError: app` · `fastapi` | 4번 `PYTHONPATH`를 안 넣었다 |
| `address already in use` | 8000을 누가 쓴다. 0번의 `ss` 확인 후 알려주기 (포트를 바꾸면 백엔드 터널도 바뀐다) |
| pip가 버전을 못 찾음 · wheel 빌드 실패 | 서버 pip가 오래돼 새 wheel 형식을 못 읽을 수 있다. 오류 앞부분을 알려주기(pip를 `--user`로 올리면 계정 전체에 영향이 있어 같이 정한다) |

> 이 순서는 11/26 로컬에서 Python 3.9 · `--target` · `TRAINER_ENV=prod`로 그대로 돌려 봤다(alembic → API → 키 없이 401 · 키 넣고 200). 서버에서 다른 건 OS(Rocky)와 서버 pip 버전뿐이다.
