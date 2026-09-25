from __future__ import annotations

from pathlib import Path
import json
import re


INPUT = Path(r"C:\tmp\gui_agents_papers.yaml")
OUT = Path(r"C:\tmp\recent_gui_dataset_papers.json")


KEYWORDS = [
    "dataset",
    "benchmark",
    "data",
    "trajectory",
    "trajectories",
    "synthetic",
    "synthesis",
    "generation",
    "exploration",
    "evaluation",
    "corpus",
    "training",
]


def split_records(text: str) -> list[str]:
    starts = [m.start() for m in re.finditer(r"(?m)^- title:", text)]
    records = []
    for i, start in enumerate(starts):
        end = starts[i + 1] if i + 1 < len(starts) else len(text)
        records.append(text[start:end])
    return records


def get_scalar(record: str, field: str) -> str:
    match = re.search(rf"(?m)^  {field}: (.*)$", record)
    if not match:
        return ""
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        value = value[1:-1]
    return value


def get_title(record: str) -> str:
    match = re.search(r"(?m)^- title: (.*)$", record)
    if not match:
        return ""
    value = match.group(1).strip()
    if len(value) >= 2 and value[0] in "'\"" and value[-1] == value[0]:
        value = value[1:-1]
    return value


def get_list(record: str, field: str) -> list[str]:
    match = re.search(rf"(?ms)^  {field}:\n((?:  - .*\n)+)", record)
    if not match:
        return []
    values = []
    for line in match.group(1).splitlines():
        item = line.strip()
        if item.startswith("- "):
            values.append(item[2:].strip().strip("'\""))
    return values


def get_block(record: str, field: str) -> str:
    match = re.search(rf"(?ms)^  {field}: \|-\n(.*?)(?=\n  [a-zA-Z_]+:|\n- title:|\Z)", record)
    if not match:
        return get_scalar(record, field)
    lines = []
    for line in match.group(1).splitlines():
        lines.append(line[4:] if line.startswith("    ") else line.strip())
    return "\n".join(lines).strip()


def main() -> None:
    text = INPUT.read_text(encoding="utf-8", errors="ignore")
    papers = []
    for record in split_records(text):
        paper = {
            "title": get_title(record),
            "link": get_scalar(record, "link"),
            "date": get_scalar(record, "date"),
            "publisher": get_scalar(record, "publisher"),
            "envs": get_list(record, "envs"),
            "keywords": get_list(record, "keywords"),
            "tldr": get_block(record, "tldr"),
        }
        haystack = " ".join(
            [
                paper["title"],
                paper["publisher"],
                " ".join(paper["keywords"]),
                paper["tldr"],
            ]
        ).lower()
        if paper["date"] >= "2026-04-01" and any(k in haystack for k in KEYWORDS):
            papers.append(paper)

    OUT.write_text(json.dumps(papers, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"matched={len(papers)} out={OUT}")
    for paper in papers:
        print(f"{paper['date']} | {paper['publisher']} | {paper['title']}")


if __name__ == "__main__":
    main()
