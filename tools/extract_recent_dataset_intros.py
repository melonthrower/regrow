from __future__ import annotations

from pathlib import Path
import json
import re

from pypdf import PdfReader

ROOT = Path(r"C:\tmp\recent_gui_dataset_papers")
OUT = ROOT / "recent_dataset_intro_extractions.json"

NEXT_HEADINGS = [
    "related work", "related works", "background", "preliminaries", "method", "methods",
    "approach", "dataset", "datasets", "benchmark", "benchmarks", "experiments",
    "experiment", "evaluation", "task", "tasks", "framework", "system", "data collection",
    "problem formulation", "overview", "conclusion",
]

def read_pdf(path: Path) -> str:
    reader = PdfReader(str(path))
    pages = []
    for page in reader.pages[:10]:
        try:
            pages.append(page.extract_text() or "")
        except Exception:
            pass
    return "\n".join(pages)

def clean(text: str) -> str:
    text = text.replace("\x00", " ")
    text = re.sub(r"-\n(?=[a-z])", "", text)
    text = re.sub(r"(?m)^\s*\d+\s*$", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()

def extract_intro(text: str) -> str | None:
    text = clean(text)
    starts = []
    for pat in [
        r"(?im)^\s*(?:\d+\.?\s*)?introduction\s*$",
        r"(?im)^\s*i\.\s*introduction\s*$",
        r"(?im)^\s*1\s*\n\s*introduction\s*$",
    ]:
        starts.extend((m.start(), m.end()) for m in re.finditer(pat, text))
    if not starts:
        m = re.search(r"(?i)(?:^|\n)\s*(?:1\.?\s*)?introduction\s+([A-Z][^\n]{20,})", text)
        if m:
            starts.append((m.start(), m.start() + len("Introduction")))
    if not starts:
        return None
    start = min(starts, key=lambda x: x[0])[1]
    rest = text[start:]
    ends = []
    for heading in NEXT_HEADINGS:
        pat = rf"(?im)^\s*(?:\d+\.?|[IVX]+\.)?\s*{re.escape(heading)}\s*$"
        for m in re.finditer(pat, rest):
            if m.start() > 1000:
                ends.append(m.start())
    end = min(ends) if ends else min(len(rest), 10000)
    intro = rest[:end].strip()
    intro = re.sub(r"\s+", " ", intro)
    return intro

items = []
for pdf in sorted(ROOT.glob("*.pdf")):
    text = read_pdf(pdf)
    intro = extract_intro(text)
    items.append({"paper": pdf.stem, "pdf": str(pdf), "intro_chars": len(intro or ""), "intro": intro or ""})
OUT.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
print(f"wrote {OUT}")
for it in items:
    print(it["paper"], it["intro_chars"])
