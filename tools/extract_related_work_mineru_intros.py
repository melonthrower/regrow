from __future__ import annotations

from pathlib import Path
import csv
import json
import os
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = REPO_ROOT / "research" / "paper" / "generated"
ROOT = Path(os.environ.get(
    "RELATED_WORK_MINERU_ROOT",
    REPO_ROOT / "artifacts" / "scratch" / "related_work_mineru_parsed",
))
MANIFEST = ROOT / "manifest.jsonl"
OUT_JSON = GENERATED_DIR / "related_work_mineru_intros.json"
OUT_CSV = GENERATED_DIR / "related_work_mineru_intro_inventory.csv"

NEXT_HEADINGS = [
    "related work",
    "related works",
    "background",
    "preliminaries",
    "method",
    "methods",
    "approach",
    "dataset",
    "datasets",
    "benchmark",
    "benchmarks",
    "experiments",
    "experiment",
    "evaluation",
    "task",
    "tasks",
    "framework",
    "system",
    "data collection",
    "problem formulation",
    "overview",
    "conclusion",
]


def clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def extract_intro(text: str) -> str | None:
    text = clean(text)
    starts = []
    for pattern in [
        r"(?im)^#{1,4}\s*(?:\d+\.?\s*)?introduction\s*$",
        r"(?im)^\s*(?:\d+\.?\s*)?introduction\s*$",
        r"(?im)^\s*i\.\s*introduction\s*$",
    ]:
        starts.extend((m.start(), m.end()) for m in re.finditer(pattern, text))
    if not starts:
        match = re.search(r"(?i)(?:^|\n)\s*(?:1\.?\s*)?introduction\s+([A-Z][^\n]{20,})", text)
        if match:
            starts.append((match.start(), match.start() + len("Introduction")))
    if not starts:
        return None

    start = min(starts, key=lambda item: item[0])[1]
    rest = text[start:]
    ends = []
    for heading in NEXT_HEADINGS:
        escaped = re.escape(heading)
        pattern = rf"(?im)^#{{1,4}}\s*(?:\d+\.?|[IVX]+\.)?\s*{escaped}\s*$|^\s*(?:\d+\.?|[IVX]+\.)\s*{escaped}\s*$"
        for match in re.finditer(pattern, rest):
            if match.start() > 800:
                ends.append(match.start())
    end = min(ends) if ends else min(len(rest), 14000)
    intro = rest[:end].strip()
    intro = re.sub(r"[ \t]+", " ", intro)
    intro = re.sub(r"\n{2,}", "\n\n", intro)
    return intro


def load_manifest() -> list[dict]:
    rows = []
    if not MANIFEST.is_file():
        return rows
    for line in MANIFEST.read_text(encoding="utf-8", errors="ignore").splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for manifest in load_manifest():
        if manifest.get("status") != "success":
            continue
        out_dir = Path(manifest["out_dir"])
        content_path = out_dir / "content.md"
        if not content_path.is_file():
            continue
        text = content_path.read_text(encoding="utf-8", errors="ignore")
        intro = extract_intro(text) or ""
        meta_path = out_dir / "metadata.json"
        metadata = {}
        if meta_path.is_file():
            metadata = json.loads(meta_path.read_text(encoding="utf-8", errors="ignore"))
        figures = len(list((out_dir / "figures").glob("*"))) if (out_dir / "figures").is_dir() else 0
        rows.append(
            {
                "relative_path": manifest["relative_path"],
                "sha256": manifest["sha256"],
                "out_dir": str(out_dir),
                "content_md": str(content_path),
                "title": metadata.get("title", ""),
                "abstract": metadata.get("abstract", ""),
                "figures": figures,
                "intro_chars": len(intro),
                "intro": intro,
            }
        )

    rows.sort(key=lambda row: row["relative_path"].lower())
    OUT_JSON.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["relative_path", "title", "intro_chars", "figures", "content_md"],
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(
                {
                    "relative_path": row["relative_path"],
                    "title": row["title"],
                    "intro_chars": row["intro_chars"],
                    "figures": row["figures"],
                    "content_md": row["content_md"],
                }
            )
    print(f"papers={len(rows)}")
    print(f"with_intro={sum(1 for row in rows if row['intro_chars'] > 0)}")
    print(f"json={OUT_JSON}")
    print(f"csv={OUT_CSV}")


if __name__ == "__main__":
    main()
