"""独立的 capability 合成入口（D19 会话新增）。

从遍历产出的 node artifacts 合成每页的「应用功能」(page_capabilities.json)，
作为指令采集(capability → 指令 → 执行)的前置。纯离线，用 Qwen，不碰模拟器，
可与遍历并行。

用法:
  export DASHSCOPE_API_KEY=...   # 或 source server_env.sh
  python gui_rewalk/run_capability_synth.py \
      --graph_path result_android_d18_verify/gen_data/Qwen/graphs/0_graph.json \
      --node_dir   result_android_d18_verify/gen_data/Qwen/0/nodes
"""
import argparse
import logging
import os
import sys

sys.path.insert(0, ".")
sys.path.insert(0, "gui_rewalk")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(name)s %(levelname)s %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("capability_synth")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph_path", required=True)
    ap.add_argument("--node_dir", required=True)
    ap.add_argument("--model", default="Qwen")
    ap.add_argument("--model_version", default="qwen3.7-plus")
    ap.add_argument("--force", action="store_true",
                    help="强制重新合成；若已有遍历期 capability.discovery.v1，"
                         "保留其 verified 证据并另写 page_capabilities_enrichment.json")
    ap.add_argument("--limit", type=int, default=0,
                    help="只合成前 N 个视觉节点(0=全部),用于冒烟")
    args = ap.parse_args()

    from gui_rewalk.src.core.graph.state_graph import StateGraph
    from gui_rewalk.src.core.scenario.capability_synthesizer import (
        CapabilitySynthesizer)
    from gui_rewalk.env.gui_gen_agent import GUIGenAgent

    graph = StateGraph.load(args.graph_path)
    logger.info("Graph: %d nodes", graph.graph.number_of_nodes())

    # Qwen via DashScope compatible-mode. predict_mm provides
    # the (text, [image]) -> (resp, ...) surface CapabilitySynthesizer needs.
    agent = GUIGenAgent(
        model=args.model, model_version=args.model_version,
        max_tokens=8000, top_p=0.9, temperature=0.4,
        action_space="gen_data", observation_type="screenshot",
        enable_ocr=False, max_trajectory_length=0, max_retry=2,
        enable_thinking=False)

    synth = CapabilitySynthesizer(
        args.node_dir, agent=agent, app_id=graph.app_name)

    # The active graph contract accepts visual nodes only.
    node_ids = [n for n, d in graph.graph.nodes(data=True)
                if str(d.get("state_type", "visual")).startswith("visual")]
    if args.limit:
        node_ids = node_ids[:args.limit]
    logger.info("Synthesizing capabilities for %d visual nodes...", len(node_ids))

    caps = synth.synthesize_all(node_ids, force=args.force)
    logger.info("Done: %d nodes got page_capabilities.json", len(caps))
    # quick sanity: count total capabilities
    total = sum(len(getattr(pc, "capabilities", []) or []) for pc in caps.values())
    logger.info("Total capabilities synthesized: %d", total)
    return 0


if __name__ == "__main__":
    sys.exit(main())
