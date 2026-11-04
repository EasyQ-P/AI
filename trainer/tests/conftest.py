import os

# 설정을 처음 읽기 전에 시험용 값을 넣는다 (get_settings는 캐시된다)
os.environ.setdefault("TRAINER_ENV", "dev")
os.environ.setdefault("TRAINER_API_KEY", "test-key")
