import sys
from pathlib import Path

# scripts/data/의 스크립트를 모듈로 불러오기 위해 경로에 넣는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
