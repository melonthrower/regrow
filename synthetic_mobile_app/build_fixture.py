"""Build Mingle standalone pages and copy the app page into Android assets."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .qwen_responses import write_responses
except ImportError:
    from qwen_responses import write_responses


ROOT = Path(__file__).resolve().parent
PLACEHOLDER = "__REWALK_ORACLE_JSON__"


def _compact_oracle() -> str:
    payload = json.loads((ROOT / "oracle.json").read_text(encoding="utf-8"))
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )


def _render(template: Path, output: Path, oracle_json: str) -> Path:
    source = template.read_text(encoding="utf-8")
    if source.count(PLACEHOLDER) != 1:
        raise RuntimeError(f"{template} must contain exactly one oracle placeholder")
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(source.replace(PLACEHOLDER, oracle_json), encoding="utf-8")
    return output


def main() -> int:
    oracle_json = _compact_oracle()
    standalone = _render(ROOT / "index.template.html", ROOT / "index.html", oracle_json)
    inspector = _render(
        ROOT / "inspector.template.html", ROOT / "inspector.html", oracle_json
    )
    asset = _render(
        ROOT / "index.template.html",
        ROOT / "app" / "src" / "main" / "assets" / "index.html",
        oracle_json,
    )
    outputs = [standalone, inspector, asset, write_responses()]
    for output in outputs:
        print(f"built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
