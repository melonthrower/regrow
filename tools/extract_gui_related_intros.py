from pathlib import Path
import json
import re

from pypdf import PdfReader


ROOT = Path(r"C:\Users\Admin\Desktop\GUI agent\related works")
OUT = Path(r"C:\tmp\gui_related_intro_extractions.json")

SKIP_PARTS = {"AAAI_Press_LaTeX_Template", "acl_template", ".claude"}
SKIP_NAMES = {"gui_agents_readme.md"}
NEXT_SECTION_WORDS = [
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
    "system",
    "framework",
    "conclusion",
    "problem formulation",
    "data collection",
]


def read_text(path: Path) -> str:
    suffix = path.suffix.lower()
    try:
        if suffix in {".txt", ".md"}:
            return path.read_text(encoding="utf-8", errors="ignore")
        if suffix == ".pdf":
            reader = PdfReader(str(path))
            pages = []
            for page in reader.pages[:8]:
                try:
                    pages.append(page.extract_text() or "")
                except Exception:
                    pass
            return "\n".join(pages)
    except Exception:
        return ""
    return ""


def clean_text(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"(?m)^\s*\d+\s*$", " ", text)
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = re.sub(r"\n+", "\n", text)
    return text.strip()


def extract_intro(text: str) -> str | None:
    text = clean_text(text)
    heading_patterns = [
        r"(?im)^\s*(?:\d+\.?\s*)?introduction\s*$",
        r"(?im)^\s*i\.\s*introduction\s*$",
        r"(?im)^\s*1\s*\n\s*introduction\s*$",
    ]
    starts = []
    for pattern in heading_patterns:
        for match in re.finditer(pattern, text):
            if match.start() <= 200000:
                starts.append((match.start(), match.end()))

    if not starts:
        match = re.search(
            r"(?i)(?:^|\n)\s*(?:1\.?\s*)?introduction\s+([A-Z][^\n]{20,})",
            text,
        )
        if match:
            starts.append((match.start(), match.start() + len("Introduction")))

    if not starts:
        return None

    start = min(starts, key=lambda item: item[0])[1]
    rest = text[start:]
    next_offsets = []
    for word in NEXT_SECTION_WORDS:
        pattern = rf"(?im)^\s*(?:\d+\.?|[IVX]+\.)?\s*{re.escape(word)}\s*$"
        for match in re.finditer(pattern, rest):
            if match.start() > 800:
                next_offsets.append(match.start())

    end = min(next_offsets) if next_offsets else min(len(rest), 9000)
    intro = rest[:end].strip()
    intro = re.sub(r"\s+", " ", intro)
    return intro or None


def should_skip(path: Path) -> bool:
    if path.suffix.lower() not in {".pdf", ".txt", ".md"}:
        return True
    if path.name in SKIP_NAMES or path.name.startswith("."):
        return True
    if any(part in SKIP_PARTS for part in path.parts):
        return True
    low_name = path.name.lower()
    low_path = str(path).lower()
    if "translation_cache" in low_name or "template" in low_path:
        return True
    if low_name.startswith("related_work") or low_name.startswith("graph_traversal"):
        return True
    if "综述" in path.name or "汇总" in path.name or "排行榜" in path.name:
        return True
    return False


def dedup_key(item: dict) -> tuple[str, str]:
    stem = Path(item["file"]).stem.lower()
    name_key = re.sub(r"[^a-z0-9]+", "", stem)[:80]
    prefix = re.sub(r"\W+", "", item["intro"].lower())[:250]
    return name_key, prefix


def main() -> None:
    items = []
    for path in ROOT.rglob("*"):
        if not path.is_file() or should_skip(path):
            continue
        text = read_text(path)
        intro = extract_intro(text) if text else None
        if intro:
            items.append(
                {
                    "file": str(path.relative_to(ROOT)),
                    "chars": len(intro),
                    "intro": intro[:12000],
                }
            )

    seen = set()
    deduped = []
    for item in sorted(items, key=lambda value: value["file"].lower()):
        key = dedup_key(item)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(item)

    OUT.write_text(json.dumps(deduped, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"extracted={len(deduped)} raw_items={len(items)} out={OUT}")
    for item in deduped[:160]:
        print(f"{item['chars']:5d}  {item['file']}")


if __name__ == "__main__":
    main()
