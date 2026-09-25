"""Offline regression for the live monitor's process-end graph summary."""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from tools.live_status import RunSummary


def _graph(path, stop_reason="max_actions"):
    data = {
        "nodes": [
            {"id": "a", "page_name": "Network"},
            {"id": "b", "page_name": "Sound"},
            {"id": "c", "page_name": "Displays"},
        ],
        "edges": [{"source": "a", "target": "b"},
                  {"source": "b", "target": "c"}],
        "action_counter": 2,
        "stop_reason": stop_reason,
        "abnormal_buttons": [
            {"element_name": "Sound", "reason": "app_crash"}
        ] if stop_reason != "frontier_empty" else [],
    }
    with open(path, "w", encoding="utf-8") as stream:
        json.dump(data, stream)


def test_stopped_summary_reports_graph_and_problems():
    with tempfile.TemporaryDirectory() as tmp:
        graph = os.path.join(tmp, "graph.json")
        _graph(graph)
        summary = RunSummary(os.path.join(tmp, "live.log"), graph)
        lines = [
            "[进度] 节点 3(2待探) · 区块 5 · 导航按钮 7/10已探(70%)",
            "explorer: click 'Sound' (test)",
            "focus guard: off-app detected, relaunching 'setting' (attempt 1)",
            "focus guard: off-app detected, relaunching 'setting' (attempt 1)",
            "predict_mm: VLM call failed (attempt 1/3): timeout",
            "QUARANTINE navigation click 'Learn more': no_effect",
            "visual traversal done: 3 states, 2 actions (stop=max_actions)",
            "env closed (container/VM released)",
        ]
        for line in lines:
            summary.observe(line)
        text = summary.render()
        assert "遍历已停止：3 个节点，2 条实测边，2 个已提交动作" in text
        assert "导航覆盖 7/10 (70%)" in text
        assert "Sound×2" in text
        assert "VLM/grounding 失败或重试 1 次" in text
        assert "遍历尚未达到 frontier_empty" in text
        assert "异常按钮 1 个（Sound:app_crash）" in text


def test_frontier_empty_without_certificate_is_not_complete():
    with tempfile.TemporaryDirectory() as tmp:
        graph = os.path.join(tmp, "graph.json")
        _graph(graph, stop_reason="frontier_empty")
        summary = RunSummary(os.path.join(tmp, "live.log"), graph)
        summary.observe(
            "visual traversal done: 3 states, 2 actions (stop=frontier_empty)"
        )
        text = summary.render()
        assert summary._read_graph()["completion_status"] == "incomplete"
        assert "完整性认证未通过" in text
        assert "全部可探索候选已处理" in text


def test_certified_summary_is_clean():
    from tests.test_traversal_completion_certificate import _happy_graph

    with tempfile.TemporaryDirectory() as tmp:
        graph = os.path.join(tmp, "graph.json")
        with open(graph, "w", encoding="utf-8") as stream:
            json.dump(_happy_graph(), stream, ensure_ascii=False)
        summary = RunSummary(os.path.join(tmp, "live.log"), graph)
        summary.observe(
            "visual traversal done: 3 states, 3 actions (stop=frontier_empty)"
        )
        text = summary.render()
        assert summary._read_graph()["completion_status"] == "certified"
        assert "遍历已完成" in text
        assert "完整性认证未通过" not in text


if __name__ == "__main__":
    test_stopped_summary_reports_graph_and_problems()
    test_frontier_empty_without_certificate_is_not_complete()
    test_certified_summary_is_clean()
    print("ALL PASS")
