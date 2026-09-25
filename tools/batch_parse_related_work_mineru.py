from __future__ import annotations

from pathlib import Path
import json
import re
import subprocess
import sys
import time


INVENTORY = Path(r"C:\tmp\related_work_pdf_inventory.json")
PARSE_SCRIPT = Path(r"C:\Users\Admin\Desktop\paper2Anything\paper2poster_dev\scripts\parse_pdf.py")
PYTHON = Path(r"C:\Users\Admin\miniconda3\envs\paper2anything\python.exe")
OUT_ROOT = Path(r"C:\tmp\related_work_mineru_parsed")
MANIFEST = OUT_ROOT / "manifest.jsonl"


def safe_name(relative_path: str, digest: str) -> str:
    stem = Path(relative_path).stem
    stem = re.sub(r"[^A-Za-z0-9._-]+", "_", stem).strip("._-")
    stem = stem[:90] or "paper"
    return f"{stem}_{digest[:10]}"


def load_done() -> set[str]:
    done = set()
    if not MANIFEST.is_file():
        return done
    for line in MANIFEST.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if row.get("status") == "success":
            done.add(row.get("sha256", ""))
    return done


def append_manifest(row: dict) -> None:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    with MANIFEST.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> None:
    max_count = int(sys.argv[1]) if len(sys.argv) > 1 else 9999
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    items = payload["items"]
    done = load_done()
    parsed_now = 0
    for index, item in enumerate(items, start=1):
        digest = item["sha256"]
        out_dir = OUT_ROOT / safe_name(item["relative_path"], digest)
        content = out_dir / "content.md"
        if digest in done or content.is_file():
            continue
        if parsed_now >= max_count:
            break

        print(f"\n[{index}/{len(items)}] {item['relative_path']}", flush=True)
        start = time.time()
        cmd = [
            str(PYTHON),
            str(PARSE_SCRIPT),
            item["path"],
            "--output-dir",
            str(out_dir),
            "--parser",
            "mineru",
        ]
        result = subprocess.run(cmd, text=True, encoding="utf-8", errors="replace", capture_output=True)
        elapsed = round(time.time() - start, 2)
        status = "success" if result.returncode == 0 and content.is_file() else "failed"
        append_manifest(
            {
                "status": status,
                "sha256": digest,
                "relative_path": item["relative_path"],
                "path": item["path"],
                "out_dir": str(out_dir),
                "elapsed_sec": elapsed,
                "returncode": result.returncode,
                "stdout_tail": result.stdout[-2000:],
                "stderr_tail": result.stderr[-2000:],
            }
        )
        print(f"  {status} in {elapsed}s -> {out_dir}", flush=True)
        if status != "success":
            print(result.stdout[-800:], flush=True)
            print(result.stderr[-800:], flush=True)
        parsed_now += 1

    print(f"parsed_now={parsed_now}")
    print(f"manifest={MANIFEST}")


if __name__ == "__main__":
    main()
