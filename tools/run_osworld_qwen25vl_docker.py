#!/usr/bin/env python3
"""Run OSWorld tasks with Qwen2.5-VL on a Docker-backed desktop VM.

This wrapper avoids patching OSWorld's qwen25vl runner, whose current copy is
AWS-oriented even when `--provider_name docker` is accepted by argparse.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import logging
import os
import sys
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--osworld_dir", default="OSWorld")
    parser.add_argument("--provider_name", default="docker")
    parser.add_argument("--path_to_vm", default="/tmp/System.qcow2")
    parser.add_argument("--headless", action="store_true")
    parser.add_argument("--action_space", default="pyautogui")
    parser.add_argument("--observation_type", default="screenshot", choices=["screenshot"])
    parser.add_argument("--screen_width", type=int, default=1920)
    parser.add_argument("--screen_height", type=int, default=1080)
    parser.add_argument("--sleep_after_execution", type=float, default=3.0)
    parser.add_argument("--max_steps", type=int, default=8)
    parser.add_argument("--max_tokens", type=int, default=1500)
    parser.add_argument("--temperature", type=float, default=0.5)
    parser.add_argument("--top_p", type=float, default=0.9)
    parser.add_argument("--model", default="qwen2.5-vl-72b-instruct")
    parser.add_argument("--client_password", default="password")
    parser.add_argument("--test_config_base_dir", default="OSWorld/evaluation_examples")
    parser.add_argument("--test_all_meta_path", default="OSWorld/evaluation_examples/test_small.json")
    parser.add_argument("--domain", default="all")
    parser.add_argument("--limit", type=int, default=1)
    parser.add_argument("--result_dir", default="results_qwen25vl")
    parser.add_argument("--log_level", default="INFO")
    parser.add_argument("--add_thought_prefix", action="store_true")
    parser.add_argument("--dry_run", action="store_true")
    return parser.parse_args()


def setup_logging(level: str) -> logging.Logger:
    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s %(levelname)s %(name)s] %(message)s"))
    root.handlers[:] = [handler]
    return logging.getLogger("osworld.qwen25vl_docker")


def load_tasks(meta_path: Path, domain: str, limit: int) -> list[tuple[str, str]]:
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    if domain != "all":
        meta = {domain: meta[domain]}
    tasks: list[tuple[str, str]] = []
    for task_domain, example_ids in meta.items():
        for example_id in example_ids:
            tasks.append((task_domain, example_id))
            if limit > 0 and len(tasks) >= limit:
                return tasks
    return tasks


def main() -> int:
    args = parse_args()
    logger = setup_logging(args.log_level)

    osworld_dir = Path(args.osworld_dir).resolve()
    sys.path.insert(0, str(osworld_dir))

    import lib_run_single  # pylint: disable=import-error,import-outside-toplevel
    from desktop_env.desktop_env import DesktopEnv  # pylint: disable=import-error,import-outside-toplevel
    from mm_agents.qwen25vl_agent import Qwen25VLAgent  # pylint: disable=import-error,import-outside-toplevel

    class CompatQwen25VLAgent(Qwen25VLAgent):
        def reset(self, _logger=None, vm_ip=None):  # noqa: D401
            return super().reset(_logger)

    tasks = load_tasks(Path(args.test_all_meta_path), args.domain, args.limit)
    if not tasks:
        raise SystemExit(f"No tasks found in {args.test_all_meta_path}")

    if not os.environ.get("DASHSCOPE_API_KEY"):
        logger.warning("DASHSCOPE_API_KEY is not set; Qwen2.5-VL calls will fail unless the endpoint ignores auth.")
    os.environ.setdefault("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1")
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

    run_id = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    logger.info("OSWorld dir: %s", osworld_dir)
    logger.info("Model endpoint: %s", os.environ.get("DASHSCOPE_BASE_URL"))
    logger.info("Tasks: %s", tasks)
    if args.dry_run:
        logger.info("Dry run passed; DesktopEnv was not started.")
        return 0

    env = DesktopEnv(
        provider_name=args.provider_name,
        path_to_vm=args.path_to_vm,
        action_space=args.action_space,
        screen_size=(args.screen_width, args.screen_height),
        headless=args.headless,
        os_type="Ubuntu",
        require_a11y_tree=False,
        client_password=args.client_password,
    )
    scores: list[float] = []
    try:
        for task_domain, example_id in tasks:
            config_file = Path(args.test_config_base_dir) / "examples" / task_domain / f"{example_id}.json"
            example = json.loads(config_file.read_text(encoding="utf-8"))
            example_result_dir = (
                Path(args.result_dir)
                / args.action_space
                / args.observation_type
                / args.model
                / task_domain
                / example_id
            )
            example_result_dir.mkdir(parents=True, exist_ok=True)
            (example_result_dir / "runner_args.json").write_text(
                json.dumps({**vars(args), "run_id": run_id}, indent=2),
                encoding="utf-8",
            )
            agent = CompatQwen25VLAgent(
                model=args.model,
                max_tokens=args.max_tokens,
                top_p=args.top_p,
                temperature=args.temperature,
                action_space=args.action_space,
                observation_type=args.observation_type,
                add_thought_prefix=args.add_thought_prefix,
            )
            logger.info("Running %s/%s: %s", task_domain, example_id, example.get("instruction"))
            lib_run_single.run_single_example(
                agent,
                env,
                example,
                args.max_steps,
                example["instruction"],
                args,
                str(example_result_dir),
                scores,
            )
    finally:
        env.close()

    average = sum(scores) / len(scores) if scores else 0.0
    logger.info("Finished %d task(s), average score %.4f", len(scores), average)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
