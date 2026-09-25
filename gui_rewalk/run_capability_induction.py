"""Offline, evidence-only capability induction from a saved StateGraph."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.scenario.capability_induction import (
    compile_collection_bundle,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--graph_path", required=True, help="input graph.json")
    parser.add_argument("--output", required=True, help="capability graph JSON output")
    parser.add_argument(
        "--annotated_graph_output",
        help="required copy destination when autonomous inventory is projected",
    )
    parser.add_argument("--entries_path", help="autonomous_entries.json snapshot")
    parser.add_argument("--regions_path", help="autonomous_regions.json snapshot")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        compile_collection_bundle(
            args.graph_path,
            args.output,
            annotated_graph_path=args.annotated_graph_output or "",
            entries_path=args.entries_path or "",
            regions_path=args.regions_path or "",
        )
    except (OSError, ValueError) as exc:
        print(f"capability induction error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
