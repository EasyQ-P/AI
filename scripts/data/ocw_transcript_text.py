"""MIT OCW 전사본 PDF에서 강사 발화 텍스트를 뽑는다 (설계서 3.2.2 (1) 2단계 '전사본 정리').

extract_ocw_transcripts.py로 정리한 transcripts/*.pdf와 transcripts_manifest.csv를 읽어서
  - 쪽 머리말(MITOCW | …), Creative Commons 안내 문단, 쪽 맨 위의 글자 조각을 지우고
  - 효과음 태그([LAUGHTER], [INAUDIBLE] 등)를 지우고, 불확실 표기 [? word ?]는 word만 남기고
  - 화자 이름을 역할(INSTRUCTOR / STUDENT / OTHER)로 바꾼 뒤
  - 강사 발화만 이어 붙인 텍스트를 강의마다 한 줄씩 쓴다.
발화 청크 나누기(3단계)와 한국어 변환(4단계)은 다음 스크립트에서 한다. 발화 시각(start_ms)은 쓰지 않는다.

출력 (data/ 아래, 커밋 금지):
  <out>/transcripts/<course_id>.jsonl  강의마다 1행: lecture_id, course_id, text, turns, 단어 수
  <out>/lectures.jsonl                 강의 메타 테이블(3.3.3): lecture_id, course_id, title, source_site,
                                       source_url, license, materials, split + 영상 길이 · 화자 정보

사용:
    uv sync --all-packages --group dev --group data
    uv run python scripts/data/ocw_transcript_text.py                      # 강의 · 리시테이션 등 (extras 제외)
    uv run python scripts/data/ocw_transcript_text.py --include-extras     # 짧은 클립 · 인터뷰까지
"""

import argparse
import csv
import json
import re
import sys
import zipfile
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

# 강좌 폴더 → course_id · 분할 (설계서 3.3.1 표: 학습 3 · 검증 1 · 시험 1)
COURSES = {
    "6-006-introduction-to-algorithms-spring-2020": ("6.006_S20", "TRAIN"),
    "6-046j-design-and-analysis-of-algorithms-spring-2015": ("6.046J_S15", "TRAIN"),
    "6-034-artificial-intelligence-fall-2010": ("6.034_F10", "TRAIN"),
    "6-0001-introduction-to-computer-science-and-programming-in-python-fall-2016": ("6.0001_F16", "VALIDATION"),
    "6-172-performance-engineering-of-software-systems-fall-2018": ("6.172_F18", "TEST"),
}

INSTRUCTOR, STUDENT, OTHER = "INSTRUCTOR", "STUDENT", "OTHER"
UNLABELED = "(UNLABELED)"
STUDENT_WORDS = ("AUDIENCE", "STUDENT")
OTHER_LABELS = {"VOICEOVER", "ANNOUNCER", "SYSTEM", "NARRATOR", "APPLE WATCH"}
INSTRUCTOR_WORDS = ("PROFESSOR", "INSTRUCTOR", "LECTURER")
# 이름표가 있는 화자 중 이 비율 이상을 말한 사람은 강사(교수 · 조교 · 초청 강연자)로 본다. 나머지는 학생.
INSTRUCTOR_MIN_SHARE = 0.05
# 학생 발화가 이보다 길면 강사 이름표가 빠진 것으로 본다(전사본에서 학생 질문 뒤 강사 이름표 없이 이어지는 경우).
STUDENT_MAX_WORDS = 60

HEADER_RE = re.compile(r"^MITOCW \|")
# 끝맺음이 'ocw.mit.edu.' · 'ocw.mit.edu' · 'fsae@mit.edu.' 등으로 강의마다 조금씩 다르다.
CC_NOTICE_RE = re.compile(
    r"The following content is provided under a Creative Commons license.{0,400}?(?:ocw\.mit\.edu|\S+@mit\.edu)\.?",
    re.DOTALL,
)
JUNK_LINE_RE = re.compile(r"^[a-z,.;' ]{1,5}$")
# 화자 이름: 대문자 단어 1~4개. 첫 단어는 두 글자 이상이고 마침표가 없다('OK. JASON KU', 'A. PROFESSOR' 같은 오인 방지).
NAME = r"[A-Z][A-Z0-9'\-]+(?: [A-Z0-9][A-Z0-9.'\-]*){0,3}"
LABEL_RE = re.compile(rf"^({NAME}):$")
INLINE_LABEL_RE = re.compile(rf"^({NAME}):\s*(\S.*)$")
# 두 줄로 나뉜 이름의 앞부분('CHARLES E.' + 'LEISERSON:'). 첫 단어는 세 글자 이상.
NAME_PART_RE = re.compile(r"^[A-Z]{3,}(?: [A-Z][A-Z.'\-]*){0,2}$")
SOUND_TAG_RE = re.compile(r"\[(?!\?)[A-Z][A-Z ,'\-]*\]")
UNSURE_RE = re.compile(r"\[\?\s*(.*?)\s*\?\]")


@dataclass
class Turn:
    speaker: str
    text: str
    role: str = ""
    repaired: bool = False  # 이름표가 빠져 학생 발화에서 떼어 강사에게 돌려준 덩어리


def clean_page_lines(lines: list[str]) -> list[str]:
    """한 쪽의 줄에서 머리말과 쪽 맨 위 글자 조각(PDF 숨은 글자)을 지운다."""
    out = []
    leading = True
    for line in lines:
        s = line.strip()
        if not s or HEADER_RE.match(s):
            continue
        if leading and JUNK_LINE_RE.match(s):
            continue
        leading = False
        out.append(s)
    return out


def drop_cc_notice(text: str) -> str:
    """맨 앞의 Creative Commons 안내 문단을 지운다."""
    m = CC_NOTICE_RE.search(text)
    if not m or m.start() > 400:
        return text
    return text[: m.start()] + text[m.end() :]


def clean_text(text: str) -> str:
    """효과음 태그를 지우고 [? word ?]는 word만 남긴 뒤 공백을 정리한다."""
    text = UNSURE_RE.sub(r"\1", text)
    text = SOUND_TAG_RE.sub(" ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return re.sub(r"\s+([,.?!;:])", r"\1", text)


def split_mid_line_labels(lines: list[str]) -> list[str]:
    """줄 맨 앞에서 이름표로 쓰인 이름이 줄 가운데에 또 나오면 거기서 줄을 나눈다.

    예: 'AUDIENCE: [INAUDIBLE] SPEAKER 1: The …' → 'AUDIENCE: [INAUDIBLE]', 'SPEAKER 1: The …'
    """
    known = set()
    for line in lines:
        if m := (LABEL_RE.match(line) or INLINE_LABEL_RE.match(line)):
            known.add(m.group(1))
    multi = sorted((k for k in known if " " in k or k in ("AUDIENCE", "STUDENT", "PROFESSOR")), key=len, reverse=True)
    if not multi:
        return lines
    pat = re.compile(r"(?<=\S) (?=(?:" + "|".join(re.escape(k) for k in multi) + r"):)")
    out = []
    for line in lines:
        out.extend(pat.split(line))
    return out


def split_turns(lines: list[str]) -> list[Turn]:
    """줄 목록을 화자 이름표 기준으로 발화 덩어리로 나눈다.

    이름표 형식: 'JASON KU:' 한 줄, 'PATRICK WINSTON: 본문' 한 줄, 'CHARLES E.' + 'LEISERSON:' 두 줄.
    첫 이름표 앞의 글은 UNLABELED 화자로 둔다(대부분 강사 혼자 말하는 강의).
    """
    lines = split_mid_line_labels(lines)
    turns: list[Turn] = []
    speaker, buf = UNLABELED, []

    def flush():
        if buf:
            turns.append(Turn(speaker, "\n".join(buf)))

    i = 0
    while i < len(lines):
        line = lines[i]
        nxt = lines[i + 1] if i + 1 < len(lines) else ""
        m = LABEL_RE.match(line)
        if not m and NAME_PART_RE.match(line) and LABEL_RE.match(nxt) and len(line) <= 20:
            flush()
            speaker, buf = f"{line} {nxt[:-1]}", []
            i += 2
            continue
        if m:
            flush()
            speaker, buf = m.group(1), []
        elif mi := INLINE_LABEL_RE.match(line):
            flush()
            speaker, buf = mi.group(1), [mi.group(2)]
        else:
            buf.append(line)
        i += 1
    flush()
    return turns


def last_name(speaker: str) -> str:
    return speaker.split()[-1].strip(".") if speaker.split() else ""


def assign_roles(turns: list[Turn], known_instructors: set[str] | None = None) -> dict[str, str]:
    """화자 이름표를 역할로 바꾼다. 반환값은 화자 → 역할.

    known_instructors: 같은 강좌 다른 강의에서 강사로 판정된 사람의 성(LEISERSON 등).
    이 강의에서 적게 말했어도 강사로 본다.
    """
    known_instructors = known_instructors or set()
    words = Counter()
    for t in turns:
        words[t.speaker] += len(t.text.split())
    total = sum(words.values()) or 1
    roles = {}
    for spk, n in words.items():
        upper = spk.upper()
        if spk == UNLABELED:
            roles[spk] = INSTRUCTOR
        elif any(w in upper for w in STUDENT_WORDS):
            roles[spk] = STUDENT
        elif upper in OTHER_LABELS:
            roles[spk] = OTHER
        elif (
            any(w in upper for w in INSTRUCTOR_WORDS)
            or n / total >= INSTRUCTOR_MIN_SHARE
            or last_name(upper) in known_instructors
        ):
            roles[spk] = INSTRUCTOR
        else:
            roles[spk] = STUDENT
    for t in turns:
        t.role = roles[t.speaker]
    return roles


def repair_missing_labels(turns: list[Turn]) -> list[Turn]:
    """긴 학생 발화를 첫 문장 줄까지만 학생으로 두고, 나머지는 바로 앞 강사 발화로 돌린다."""
    out: list[Turn] = []
    last_instructor = UNLABELED
    for t in turns:
        lines = t.text.splitlines()
        if t.role == STUDENT and len(t.text.split()) > STUDENT_MAX_WORDS and len(lines) > 1:
            cut = next((i + 1 for i, ln in enumerate(lines[:3]) if ln.rstrip().endswith(("?", ".", "!"))), 1)
            out.append(Turn(t.speaker, "\n".join(lines[:cut]), t.role))
            out.append(Turn(last_instructor, "\n".join(lines[cut:]), INSTRUCTOR, repaired=True))
            continue
        if t.role == INSTRUCTOR:
            last_instructor = t.speaker
        out.append(t)
    return out


def process_pages(pages: list[str], known_instructors: set[str] | None = None) -> list[Turn]:
    """PDF 쪽 텍스트 목록 → 정리된 발화 덩어리(역할 포함)."""
    lines: list[str] = []
    for page in pages:
        lines.extend(clean_page_lines(page.splitlines()))
    joined = "\n".join(lines)
    lines = drop_cc_notice(joined).splitlines()
    turns = split_turns([s.strip() for s in lines if s.strip()])
    assign_roles(turns, known_instructors)
    turns = repair_missing_labels(turns)
    for t in turns:
        t.text = clean_text(t.text)
    return [t for t in turns if t.text]


def lecture_code(file_name: str) -> str:
    """'L12A_Neural_Nets.pdf' → 'L12A', 'extras/X03_Branching.pdf' → 'X03'."""
    return Path(file_name).name.split("_", 1)[0]


def video_kind(code: str) -> str:
    for prefix, kind in (
        ("MR", "MEGA_RECITATION"),
        ("PS", "PROBLEM_SESSION"),
        ("QR", "QUIZ_REVIEW"),
        ("L", "LECTURE"),
        ("R", "RECITATION"),
        ("T", "TUTORIAL"),
    ):
        if code.startswith(prefix):
            return kind
    return "EXTRA"


def caption_duration_sec(z: zipfile.ZipFile, youtube_id: str, pdf_zip_path: str) -> int | None:
    """zip 안 자막(VTT/SRT)의 마지막 시각으로 영상 길이(초)를 구한다. 30초 청크 단어 수 계산용(3.2.2 3단계)."""
    stem = Path(pdf_zip_path).stem
    keys = [k for k in (youtube_id, stem.split("_", 1)[-1], stem.removesuffix("_transcript")) if k and len(k) >= 6]
    caps = [n for n in z.namelist() if n.lower().endswith((".vtt", ".srt", ".webvtt")) and any(k in n for k in keys)]
    best = None
    for name in caps:
        text = z.read(name).decode("utf-8", errors="ignore")
        stamps = re.findall(r"(\d+):(\d{2}):(\d{2})[.,]\d{3}", text)
        if stamps:
            h, m, s = map(int, stamps[-1])
            sec = h * 3600 + m * 60 + s
            best = max(best or 0, sec)
    return best


def read_pdf_pages(path: Path) -> list[str]:
    import pymupdf  # data 그룹 의존성. 테스트에서는 불러오지 않는다.

    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def process_course(course_dir: Path, include_extras: bool) -> tuple[list[dict], list[dict]]:
    course_id, split = COURSES[course_dir.name]
    manifest = course_dir / "transcripts_manifest.csv"
    if not manifest.exists():
        sys.exit(f"{manifest}가 없습니다. 먼저 extract_ocw_transcripts.py --apply를 돌리세요.")
    zip_path = next(course_dir.glob("*.zip"), None)
    z = zipfile.ZipFile(zip_path) if zip_path else None
    texts, metas = [], []
    with open(manifest, encoding="utf-8") as fh:
        rows = [r for r in csv.DictReader(fh) if r["file"]]
    if not include_extras:
        rows = [r for r in rows if video_kind(lecture_code(r["file"])) != "EXTRA"]
    pages = {r["file"]: read_pdf_pages(course_dir / "transcripts" / r["file"]) for r in rows}
    # 1차: 강의마다 판정한 강사의 성을 모아, 2차에서 같은 사람이 적게 말한 강의에서도 강사로 본다.
    known = set()
    for r in rows:
        for t in process_pages(pages[r["file"]]):
            if t.role == INSTRUCTOR and t.speaker != UNLABELED and not t.speaker.startswith("SPEAKER"):
                if len(name := last_name(t.speaker)) >= 2:
                    known.add(name)
    for row in rows:
        code = lecture_code(row["file"])
        kind = video_kind(code)
        lecture_id = f"{course_id}_{code}"
        turns = process_pages(pages[row["file"]], known)
        instructor = [t for t in turns if t.role == INSTRUCTOR]
        text = " ".join(t.text for t in instructor)
        speakers = Counter()
        for t in turns:
            speakers[(t.speaker, t.role)] += len(t.text.split())
        words_by_role = Counter()
        for (_, role), n in speakers.items():
            words_by_role[role] += n
        duration = caption_duration_sec(z, row["youtube_id"], row["zip_path"]) if z else None
        texts.append(
            {
                "lecture_id": lecture_id,
                "course_id": course_id,
                "source": "MIT_OCW",
                "evidence_lang": "en",
                "text": text,
                "instructor_words": len(text.split()),
                "repaired_turns": sum(t.repaired for t in turns),
                "turns": [{"speaker": t.speaker, "role": t.role, "text": t.text} for t in turns],
            }
        )
        metas.append(
            {
                "lecture_id": lecture_id,
                "course_id": course_id,
                "title": row["title"],
                "source_site": "MIT OpenCourseWare",
                "source_url": row["source_url"],
                "license": row["license"],
                "materials": ["transcript_pdf"],
                "split": split,
                "video_kind": kind,
                "youtube_id": row["youtube_id"],
                "transcript_file": row["file"],
                "duration_sec": duration,
                "words_by_role": dict(words_by_role),
                "speakers": [{"speaker": s, "role": r, "words": n} for (s, r), n in speakers.most_common()],
            }
        )
    if z:
        z.close()
    return texts, metas


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/raw/mit_ocw"))
    parser.add_argument("--out", type=Path, default=Path("data/interim/mit_ocw"))
    parser.add_argument("--include-extras", action="store_true", help="extras/의 짧은 클립 · 인터뷰도 포함")
    args = parser.parse_args()

    all_meta = []
    for course_dir in sorted(p for p in args.root.iterdir() if p.is_dir()):
        if course_dir.name not in COURSES:
            print(f"건너뜀(강좌 목록에 없음): {course_dir.name}")
            continue
        texts, metas = process_course(course_dir, args.include_extras)
        course_id = COURSES[course_dir.name][0]
        write_jsonl(args.out / "transcripts" / f"{course_id}.jsonl", texts)
        all_meta.extend(metas)
        words = sum(t["instructor_words"] for t in texts)
        print(f"{course_id:12} 강의 {len(texts):3}개  강사 발화 {words:>9,}단어")
    write_jsonl(args.out / "lectures.jsonl", all_meta)
    print(f"강의 메타 {len(all_meta)}개 → {args.out / 'lectures.jsonl'}")


if __name__ == "__main__":
    main()
