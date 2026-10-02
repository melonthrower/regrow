"""Generate a Region-guided task from a discovered application graph."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("ledger", help="Exploration ledger produced by traversal")
    parser.add_argument("--request", default="", help="Desired task or composition requirements")
    parser.add_argument("--output", required=True)
    return parser


def main(argv=None):
    from gui_rewalk.src.core.scenario.collection_graph import load_collection_graph
    from gui_rewalk.src.core.scenario.function_collection_research import (
        build_region_model_agent, design_region_instruction)
    args = build_parser().parse_args(argv)
    source = Path(args.ledger).expanduser().resolve()
    output = Path(args.output).expanduser().resolve()
    try:
        if source == output:
            raise ValueError("Task output must not overwrite the exploration ledger")
        if output.exists():
            raise ValueError('Task output already exists; choose a new output path')
        ledger, digest = load_collection_graph(source)
        agent = build_region_model_agent("openai_api", None, str(output.parent))
        task = design_region_instruction(ledger, agent, args.request)
        task["source_ledger"] = os.path.relpath(source, output.parent)
        task["source_ledger_digest"] = digest
        task["instruction_id"] = output.stem
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(task, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"Task generation failed: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
