"""MIT OCW 강좌 zip에서 강의 영상 전사본 PDF를 꺼내 정리한다 (설계서 3.1 · 3.3.1 수집 단계).

OCW "Download Course" zip에는 영상마다 전사본 PDF가 들어 있지만 파일 이름이 영상 ID라
몇 강인지 알 수 없다. 이 스크립트는 zip 안의 resources/*/data.json으로 영상 제목을 찾아
전사본을 강의 번호 순 이름으로 꺼내고, 출처 기록(D-07)용 manifest를 만든다.

입력:  <root>/<강좌 폴더>/<강좌>.zip
출력:  <root>/<강좌 폴더>/transcripts/L01_<제목>.pdf ...
       <root>/<강좌 폴더>/transcripts/extras/  (강의 · 리시테이션이 아닌 영상: 짧은 클립, 인터뷰)
       <root>/<강좌 폴더>/transcripts_manifest.csv

파일 이름 접두어: L(강의) · PS(문제 풀이) · QR(퀴즈 리뷰) · R(리시테이션) · MR(메가 리시테이션) · T(튜토리얼) · X(그 밖)

사용:
    uv run python scripts/data/extract_ocw_transcripts.py            # 미리보기
    uv run python scripts/data/extract_ocw_transcripts.py --apply    # 실제로 꺼내기

--apply는 transcripts/ 폴더의 기존 파일을 지우고 다시 만든다. 결과물은 data/ 아래에만 두고 커밋하지 않는다.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import zipfile
from pathlib import Path

LICENSE = "CC BY-NC-SA 4.0"
OCW_COURSE_URL = "https://ocw.mit.edu/courses/"

CODE_PATTERNS = [
    (r"^Lecture (\d+)([A-Za-z]?)\b", "L{:02d}{}"),
    (r"^Quiz (\d+) Review", "QR{}"),
    (r"^Problem Session (\d+)", "PS{}"),
    (r"^Mega-Recitation (\d+)", "MR{}"),
    (r"^Recitation (\d+)", "R{:02d}"),
    (r"^Tutorial (\d+)", "T{:02d}"),
]
TITLE_PREFIX = r"^(Lecture|Quiz \d+ Review|Problem Session|Recitation|Tutorial)\s*\d*[A-Za-z]?\s*:?\s*"
MANIFEST_FIELDS = [
    "file",
    "title",
    "youtube_id",
    "zip_path",
    "course",
    "course_number",
    "term",
    "license",
    "source_url",
]


def code_for(title: str) -> str | None:
    """영상 제목에서 정렬용 코드(L01, PS3, QR1 …)를 만든다. 해당 없으면 None."""
    for pattern, fmt in CODE_PATTERNS:
        m = re.match(pattern, title.strip(), re.IGNORECASE)
        if m:
            return fmt.format(int(m.group(1)), *[g.upper() for g in m.groups()[1:]])
    return None


def slug(title: str) -> str:
    """제목에서 'Lecture 3:' 같은 머리를 떼고 파일 이름에 쓸 수 있게 바꾼다."""
    body = re.sub(TITLE_PREFIX, "", title, flags=re.IGNORECASE) or title
    return re.sub(r"[^A-Za-z0-9]+", "_", body).strip("_")[:80]


def find_videos(z: zipfile.ZipFile) -> list[dict]:
    """zip 안의 영상 리소스마다 제목 · 영상 ID · 전사본 PDF 경로를 찾는다. 같은 PDF는 한 번만 남긴다."""
    names = z.namelist()
    pdfs = {n.rsplit("/", 1)[-1]: n for n in names if n.lower().endswith(".pdf")}
    videos, seen = [], set()
    for name in names:
        if not (name.startswith("resources/") and name.endswith("data.json")):
            continue
        meta = json.loads(z.read(name))
        if meta.get("resourcetype") != "Video":
            continue
        files = meta.get("video_files") or {}
        youtube_id = (meta.get("video_metadata") or {}).get("youtube_id") or ""
        candidates = [r.get("file", "") for r in files.get("video_transcript_resources") or []]
        candidates.append(files.get("video_transcript_file") or "")
        src = next((pdfs[b] for c in candidates if (b := c.rsplit("/", 1)[-1]) and b in pdfs), None)
        if not src and youtube_id:
            src = next((n for b, n in pdfs.items() if youtube_id in b), None)
        key = hashlib.md5(z.read(src)).hexdigest() if src else (youtube_id or meta.get("title", ""))
        if key in seen:
            continue
        seen.add(key)
        videos.append(
            {
                "title": meta.get("title", ""),
                "youtube_id": youtube_id,
                "src": src,
                "page": name.rsplit("/", 2)[-2],
            }
        )
    return videos


def assign_names(videos: list[dict]) -> None:
    """영상마다 출력 파일 이름(file)을 정한다. 강의가 아닌 영상은 extras/로 보낸다."""
    other, used = 0, set()
    for v in sorted(videos, key=lambda v: v["title"]):
        code = code_for(v["title"])
        if not code:
            other += 1
            code = f"X{other:02d}"
        base = f"{code}_{slug(v['title'])}"
        while base in used:
            base += "_b"
        used.add(base)
        prefix = "extras/" if code.startswith("X") else ""
        v["file"] = f"{prefix}{base}.pdf" if v["src"] else ""
    videos.sort(key=lambda v: v["file"] or "~")


def write_outputs(course_dir: Path, z: zipfile.ZipFile, videos: list[dict]) -> None:
    out = course_dir / "transcripts"
    if out.exists():
        for f in sorted(out.rglob("*"), reverse=True):
            f.unlink() if f.is_file() else f.rmdir()
    out.mkdir(exist_ok=True)
    for v in videos:
        if v["src"]:
            target = out / v["file"]
            target.parent.mkdir(exist_ok=True)
            target.write_bytes(z.read(v["src"]))

    root = json.loads(z.read("data.json"))
    url = f"{OCW_COURSE_URL}{course_dir.name}/"
    with open(course_dir / "transcripts_manifest.csv", "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(MANIFEST_FIELDS)
        for v in videos:
            w.writerow(
                [
                    v["file"],
                    v["title"],
                    v["youtube_id"],
                    v["src"] or "",
                    root.get("course_title"),
                    root.get("primary_course_number"),
                    f"{root.get('term')} {root.get('year')}",
                    LICENSE,
                    f"{url}resources/{v['page']}/",
                ]
            )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--root", type=Path, default=Path("data/raw/mit_ocw"), help="강좌 폴더들이 있는 곳")
    parser.add_argument("--apply", action="store_true", help="미리보기만 하지 않고 실제로 파일을 쓴다")
    args = parser.parse_args()

    zips = sorted(args.root.glob("*/*.zip"))
    if not zips:
        sys.exit(f"zip이 없습니다: {args.root}/<강좌 폴더>/*.zip")
    for zip_path in zips:
        with zipfile.ZipFile(zip_path) as z:
            videos = find_videos(z)
            assign_names(videos)
            missing = sum(1 for v in videos if not v["src"])
            print(f"== {zip_path.parent.name}: 영상 {len(videos)}개, 전사본 없음 {missing}개")
            for v in videos:
                print(f"   {v['file'] or '(전사본 없음)'} | {v['title']}")
            if args.apply:
                write_outputs(zip_path.parent, z, videos)
    if not args.apply:
        print("\n미리보기입니다. 실제로 꺼내려면 --apply를 붙이세요.")


if __name__ == "__main__":
    main()
