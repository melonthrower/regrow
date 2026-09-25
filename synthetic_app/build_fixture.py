"""Build standalone fixture pages by embedding the machine-readable oracle."""

from __future__ import annotations

import json
from pathlib import Path

try:
    from .qwen_responses import write_responses
except ImportError:  # direct ``python synthetic_app/build_fixture.py`` execution
    from qwen_responses import write_responses


ROOT = Path(__file__).resolve().parent
PLACEHOLDER = "__REWALK_ORACLE_JSON__"


def _compact_oracle() -> str:
    payload = json.loads((ROOT / "oracle.json").read_text(encoding="utf-8"))
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":")).replace(
        "</", "<\\/"
    )


def _render(template_name: str, output_name: str, oracle_json: str) -> Path:
    template = (ROOT / template_name).read_text(encoding="utf-8")
    if template.count(PLACEHOLDER) != 1:
        raise RuntimeError(f"{template_name} must contain exactly one oracle placeholder")
    output = ROOT / output_name
    output.write_text(template.replace(PLACEHOLDER, oracle_json), encoding="utf-8")
    return output


def main() -> int:
    oracle_json = _compact_oracle()
    outputs = [
        _render("index.template.html", "index.html", oracle_json),
        _render("inspector.template.html", "inspector.html", oracle_json),
        write_responses(),
    ]
    for output in outputs:
        print(f"built {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
