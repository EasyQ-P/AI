"""EasyQ 공용 검색 패키지 (설계서 6.1.5).

서비스 worker와 학과 서버의 학습서버가 같은 패키지 · 같은 검색 설정 버전을 쓴다.
backend 레포에서는 git 태그로 고정해 설치한다.
"""

from retrieval.config import RetrievalConfig
from retrieval.overlap import check_overlap, is_eval_lecture, overlap_ratio

__all__ = ["RetrievalConfig", "check_overlap", "is_eval_lecture", "overlap_ratio"]
__version__ = "0.1.0"
