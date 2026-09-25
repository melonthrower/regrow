#!/usr/bin/env python3
"""Run the read-only GUI-ReWalk graph quality audit.

Rules-only evaluation is the default and does not import or initialise a VLM
client.  ``--use-vlm`` explicitly enables semantic node/edge review through the
existing :class:`GUIGenAgent`.  API credentials are read only from named
environment variables; this entry point contains no credential fallback.

Examples::

    python gui_rewalk/run_graph_quality.py result/app/graph.json
    python gui_rewalk/run_graph_quality.py result/app/graph.json \
        --json-out result/app/quality.json --fail-on error
    python gui_rewalk/run_graph_quality.py result/app/graph.json --use-vlm \
        --model Qwen --model-version qwen3.7-plus
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path
from typing import Any, Callable, Iterable, Mapping, MutableMapping, Optional


if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.graph.graph_quality_agent import GraphQualityAgent
from gui_rewalk.src.core.graph.graph_quality_annotations import export_annotated_evidence


QUALITY_MODEL_ENV = "GUIWALK_GRAPH_QUALITY_MODEL"
QUALITY_MODEL_VERSION_ENV = "GUIWALK_GRAPH_QUALITY_MODEL_VERSION"


def _default_report_path(graph_path: Path) -> Path:
    return graph_path.with_name(f"{graph_path.stem}.quality.json")


def _json_object(text: Any) -> Mapping[str, Any]:
    if isinstance(text, Mapping):
        return dict(text)
    raw = str(text or "")
    fenced = re.search(r"```(?:json)?\s*(\{.*\})\s*```", raw, re.DOTALL)
    candidate = fenced.group(1) if fenced else ""
    if not candidate:
        start, end = raw.find("{"), raw.rfind("}")
        candidate = raw[start : end + 1] if start >= 0 and end > start else ""
    if not candidate:
        raise ValueError("VLM returned no JSON object")
    value = json.loads(candidate)
    if not isinstance(value, Mapping):
        raise ValueError("VLM response JSON must be an object")
    return dict(value)


def _screenshot_paths(request: Mapping[str, Any]) -> list[Path]:
    """Extract unique readable screenshot paths from a structured judge request."""
    paths: list[Path] = []
    seen: set[str] = set()

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            candidate = value.get("resolved_path")
            if candidate and value.get("exists", True):
                path = Path(str(candidate)).expanduser()
                try:
                    resolved = path.resolve()
                except OSError:
                    resolved = path
                key = str(resolved).casefold()
                if key not in seen and resolved.is_file():
                    seen.add(key)
                    paths.append(resolved)
            for nested in value.values():
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)

    visit(request.get("evidence") or {})
    return paths


class GUIGenGraphQualityJudge:
    """Adapt ``GUIGenAgent.predict_mm`` to GraphQualityAgent's JSON contract."""

    def __init__(self, agent: Any) -> None:
        self.agent = agent
        self.calls = 0
        self.prompt_tokens = 0
        self.completion_tokens = 0
        self.transport_attempts = 0

    def __call__(self, request: Mapping[str, Any]) -> Mapping[str, Any]:
        from PIL import Image
        import numpy as np

        images = []
        for path in _screenshot_paths(request):
            with Image.open(path) as image:
                images.append(np.asarray(image.convert("RGB")))
        prompt = (
            "You are the semantic judge for a screenshot-only GUI graph audit. "
            "Use only the supplied screenshots and structured evidence. Return "
            "exactly one JSON object matching response_schema. Never claim "
            "coverage_status=unsupported without concrete visible evidence; use "
            "unknown when evidence is insufficient. Do not propose graph edits.\n\n"
            + json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        )
        result = self.agent.predict_mm(prompt, images)
        response: Any = result
        prompt_tokens = completion_tokens = attempts = None
        if isinstance(result, tuple):
            response = result[0] if result else ""
            prompt_tokens = result[1] if len(result) > 1 else None
            completion_tokens = result[2] if len(result) > 2 else None
            attempts = result[3] if len(result) > 3 else None
        self.calls += 1
        if isinstance(prompt_tokens, int):
            self.prompt_tokens += prompt_tokens
        if isinstance(completion_tokens, int):
            self.completion_tokens += completion_tokens
        if isinstance(attempts, int):
            self.transport_attempts += attempts

        parser = getattr(self.agent, "parse_json", None)
        parsed = parser(response) if callable(parser) else None
        return dict(parsed) if isinstance(parsed, Mapping) else _json_object(response)

    def usage(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
            "transport_attempts": self.transport_attempts,
        }


def build_parser(environ: Optional[Mapping[str, str]] = None) -> argparse.ArgumentParser:
    env = environ if environ is not None else os.environ
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("graph", nargs="?", type=Path, help="visual traversal graph.json")
    parser.add_argument(
        "--graph-path",
        "--graph_path",
        "--graph",
        dest="graph_option",
        type=Path,
        default=None,
        help="named alternative to the positional graph path",
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=None,
        help="base directory for repository-relative screenshot paths (default: cwd)",
    )
    parser.add_argument(
        "--json-out",
        type=Path,
        default=None,
        help="report destination (default: <graph-stem>.quality.json beside graph)",
    )
    parser.add_argument(
        "--annotated-dir",
        type=Path,
        default=None,
        help=(
            "optional directory for one annotated PNG per ERROR/WARN plus "
            "manifest.json; source graph/screenshots remain read-only"
        ),
    )
    parser.add_argument(
        "--fail-on",
        choices=("none", "error", "warning"),
        default="none",
        help="non-zero exit threshold; invalid graph JSON always fails",
    )
    parser.add_argument("--use-vlm", action="store_true", help="enable semantic VLM review")
    parser.add_argument(
        "--min-vlm-confidence",
        type=float,
        default=0.70,
        help="minimum confidence for a VLM verdict to affect the report",
    )
    parser.add_argument("--model", default=env.get(QUALITY_MODEL_ENV))
    parser.add_argument(
        "--model-version",
        "--model_version",
        dest="model_version",
        default=env.get(QUALITY_MODEL_VERSION_ENV),
    )
    parser.add_argument(
        "--dashscope-api-key-env",
        default="DASHSCOPE_API_KEY",
        help="name of the environment variable containing the DashScope key",
    )
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--top-p", type=float, default=0.9)
    parser.add_argument("--temperature", type=float, default=0.2)
    parser.add_argument("--max-retry", type=int, default=2)
    return parser


def _temporary_agent_environment(
    args: argparse.Namespace,
    environ: Mapping[str, str],
) -> tuple[dict[str, Optional[str]], dict[str, str]]:
    """Return (old values, temporary values) required by GUIGenAgent.

    The existing transport reads fixed environment names.  The CLI accepts a
    caller-selected credential variable name, then exposes it only while the
    client is constructed.  Secret values are never copied into reports or
    command defaults.
    """
    key = environ.get(args.dashscope_api_key_env)
    if not key:
        raise ValueError(
            f"--use-vlm requires environment variable {args.dashscope_api_key_env}"
        )
    temporary = {"DASHSCOPE_API_KEY": key}
    old = {name: os.environ.get(name) for name in temporary}
    return old, temporary


def _build_vlm_judge(
    args: argparse.Namespace,
    *,
    environ: Mapping[str, str],
    agent_factory: Optional[Callable[..., Any]],
) -> GUIGenGraphQualityJudge:
    if not args.model or not args.model_version:
        raise ValueError(
            "--use-vlm requires --model and --model-version (or "
            f"{QUALITY_MODEL_ENV}/{QUALITY_MODEL_VERSION_ENV})"
        )
    if args.max_tokens <= 0 or args.max_retry <= 0:
        raise ValueError("--max-tokens and --max-retry must be positive")
    if not 0.0 <= args.temperature <= 2.0 or not 0.0 < args.top_p <= 1.0:
        raise ValueError("--temperature must be in [0,2] and --top-p in (0,1]")

    old_environment, temporary = _temporary_agent_environment(args, environ)
    os.environ.update(temporary)
    try:
        if agent_factory is None:
            # Delayed import guarantees rules-only mode never creates/imports a
            # network transport merely to inspect a graph.
            from gui_rewalk.env.gui_gen_agent import GUIGenAgent

            agent_factory = GUIGenAgent
        agent = agent_factory(
            model=args.model,
            model_version=args.model_version,
            max_tokens=args.max_tokens,
            top_p=args.top_p,
            temperature=args.temperature,
            action_space="gen_data",
            observation_type="screenshot",
            max_trajectory_length=0,
            max_retry=args.max_retry,
            enable_ocr=False,
            enable_thinking=False,
        )
    finally:
        for name, previous in old_environment.items():
            if previous is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = previous
    return GUIGenGraphQualityJudge(agent)


def main(
    argv: Optional[Iterable[str]] = None,
    *,
    agent_factory: Optional[Callable[..., Any]] = None,
    environ: Optional[MutableMapping[str, str]] = None,
) -> int:
    env = environ if environ is not None else os.environ
    parser = build_parser(env)
    args = parser.parse_args(list(argv) if argv is not None else None)
    if args.graph is not None and args.graph_option is not None:
        parser.error("pass the graph either positionally or via --graph-path, not both")
    selected_graph = args.graph_option or args.graph
    if selected_graph is None:
        parser.error("a graph path is required")
    graph_path = selected_graph.expanduser().resolve()
    report_path = (
        args.json_out.expanduser().resolve()
        if args.json_out is not None
        else _default_report_path(graph_path)
    )
    if graph_path == report_path:
        parser.error("--json-out must not overwrite the source graph")
    if not graph_path.is_file():
        parser.error(f"graph does not exist: {graph_path}")
    if not 0.0 <= args.min_vlm_confidence <= 1.0:
        parser.error("--min-vlm-confidence must be in [0,1]")

    judge: Optional[GUIGenGraphQualityJudge] = None
    if args.use_vlm:
        try:
            judge = _build_vlm_judge(
                args,
                environ=env,
                agent_factory=agent_factory,
            )
        except ValueError as exc:
            parser.error(str(exc))

    evaluator = GraphQualityAgent(
        vlm_judge=judge,
        min_vlm_confidence=args.min_vlm_confidence,
        workspace=args.workspace,
    )
    report = evaluator.evaluate(graph_path)
    report["evaluation"] = {
        "mode": "rules+vlm" if judge else "rules-only",
        "model": str(args.model or "") if judge else None,
        "model_version": str(args.model_version or "") if judge else None,
        "min_vlm_confidence": args.min_vlm_confidence,
    }
    if judge:
        report["vlm_usage"] = judge.usage()
    evaluator.write_report(report, report_path)

    annotation_manifest = None
    if args.annotated_dir is not None:
        try:
            annotation_manifest = export_annotated_evidence(
                graph_path,
                report,
                args.annotated_dir,
            )
        except (OSError, ValueError) as exc:
            parser.error(f"cannot export annotated evidence: {exc}")

    summary = report.get("summary") or {}
    print(
        f"[{report.get('status')}] score={report.get('score')} "
        f"confidence={report.get('confidence')} nodes={summary.get('nodes', 0)} "
        f"edges={summary.get('edges', 0)} errors={summary.get('errors', 0)} "
        f"warnings={summary.get('warnings', 0)}"
    )
    print(f"report={report_path}")
    if annotation_manifest is not None:
        print(
            f"annotations={annotation_manifest['output_directory']} "
            f"generated={annotation_manifest['generated_count']} "
            f"skipped={annotation_manifest['skipped_count']}"
        )

    invalid = any(item.get("code") == "invalid_graph_json" for item in report.get("findings") or [])
    if invalid:
        return 1
    if args.fail_on == "error" and report.get("status") == "error":
        return 1
    if args.fail_on == "warning" and report.get("status") != "pass":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
