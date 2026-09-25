from __future__ import annotations

from pathlib import Path
import json
import re


ROOT = Path(r"C:\tmp\recent_gui_dataset_papers\mineru_parsed")
OUT = Path(r"C:\tmp\recent_gui_dataset_papers\mineru_recent_dataset_intro_extractions.json")

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
    patterns = [
        r"(?im)^#{1,3}\s*(?:\d+\.?\s*)?introduction\s*$",
        r"(?im)^\s*(?:\d+\.?\s*)?introduction\s*$",
        r"(?im)^\s*i\.\s*introduction\s*$",
    ]
    for pattern in patterns:
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
        pattern = rf"(?im)^#{{1,3}}\s*(?:\d+\.?|[IVX]+\.)?\s*{escaped}\s*$|^\s*(?:\d+\.?|[IVX]+\.)\s*{escaped}\s*$"
        for match in re.finditer(pattern, rest):
            if match.start() > 900:
                ends.append(match.start())
    end = min(ends) if ends else min(len(rest), 12000)
    intro = rest[:end].strip()
    intro = re.sub(r"[ \t]+", " ", intro)
    intro = re.sub(r"\n{2,}", "\n\n", intro)
    return intro


def main() -> None:
    items = []
    for content in sorted(ROOT.glob("*/content.md")):
        intro = extract_intro(content.read_text(encoding="utf-8", errors="ignore"))
        meta_path = content.parent / "metadata.json"
        metadata = {}
        if meta_path.is_file():
            metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        fig_count = len(list((content.parent / "figures").glob("*"))) if (content.parent / "figures").is_dir() else 0
        items.append(
            {
                "paper": content.parent.name,
                "content_md": str(content),
                "title": metadata.get("title", ""),
                "abstract": metadata.get("abstract", ""),
                "figures": fig_count,
                "intro_chars": len(intro or ""),
                "intro": intro or "",
            }
        )
    OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    for item in items:
        print(f"{item['paper']}: intro={item['intro_chars']} chars, figures={item['figures']}")


if __name__ == "__main__":
    main()
