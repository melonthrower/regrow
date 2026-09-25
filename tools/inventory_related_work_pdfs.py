from __future__ import annotations

from pathlib import Path
import csv
import hashlib
import json
import os
import re


REPO_ROOT = Path(__file__).resolve().parents[1]
GENERATED_DIR = REPO_ROOT / "research" / "paper" / "generated"
ROOT = Path(os.environ.get(
    "RELATED_WORKS_ROOT", REPO_ROOT / "research" / "paper" / "references"))
OUT_JSON = GENERATED_DIR / "related_work_pdf_inventory.json"
OUT_CSV = GENERATED_DIR / "related_work_pdf_inventory.csv"

SKIP_PARTS = {
    ".claude",
    "AAAI_Press_LaTeX_Template",
    "acl_template",
}


def norm_title_from_path(path: Path) -> str:
    stem = path.stem
    stem = re.sub(r"[_\-]+", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    stem = re.sub(r"^(arxiv\s*)?\d{4}\.\d{4,5}\s*", "", stem, flags=re.I)
    return stem


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def should_skip(path: Path) -> bool:
    if any(part in SKIP_PARTS for part in path.parts):
        return True
    # Some downloaded "PDFs" are actually HTML error pages.
    try:
        with path.open("rb") as handle:
            header = handle.read(5)
        if header != b"%PDF-":
            return True
    except OSError:
        return True
    return False


def main() -> None:
    GENERATED_DIR.mkdir(parents=True, exist_ok=True)
    rows = []
    for path in sorted(ROOT.rglob("*.pdf")):
        if should_skip(path):
            continue
        digest = sha256_file(path)
        rows.append(
            {
                "path": str(path),
                "relative_path": str(path.relative_to(ROOT)),
                "size": path.stat().st_size,
                "sha256": digest,
                "name_guess": norm_title_from_path(path),
            }
        )

    by_hash: dict[str, list[dict]] = {}
    for row in rows:
        by_hash.setdefault(row["sha256"], []).append(row)

    unique = []
    for digest, group in by_hash.items():
        group = sorted(group, key=lambda item: (len(item["relative_path"]), item["relative_path"]))
        canonical = dict(group[0])
        canonical["duplicate_count"] = len(group)
        canonical["duplicates"] = [item["relative_path"] for item in group[1:]]
        unique.append(canonical)

    unique.sort(key=lambda item: item["relative_path"].lower())
    payload = {"root": str(ROOT), "total_pdf_files": len(rows), "unique_pdf_files": len(unique), "items": unique}
    OUT_JSON.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    with OUT_CSV.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=["relative_path", "size", "sha256", "duplicate_count", "name_guess", "duplicates"],
        )
        writer.writeheader()
        for item in unique:
            writer.writerow(
                {
                    "relative_path": item["relative_path"],
                    "size": item["size"],
                    "sha256": item["sha256"],
                    "duplicate_count": item["duplicate_count"],
                    "name_guess": item["name_guess"],
                    "duplicates": " | ".join(item["duplicates"]),
                }
            )

    print(f"total_pdf_files={len(rows)}")
    print(f"unique_pdf_files={len(unique)}")
    print(f"json={OUT_JSON}")
    print(f"csv={OUT_CSV}")


if __name__ == "__main__":
    main()
