"""Model-led choices over framework-observed traversal work."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict

from .common import _img_arr, _parse_json
from ..action_space import is_android, normalize_native_action
from ..prompts.exploration import (
    build_element_exploration_prompt,
    build_explorer_prompt,
    build_route_choice_prompt,
)

logger = logging.getLogger(__name__)


class ExplorerAgent:
    """Propose the next target while the framework validates and executes it."""

    def __init__(self, agent, ledger=None, coverage_reviewer=None, *,
                 codex_model: str = "", codex_temp_root: str = ""):
        self.agent = agent
        self.ledger = ledger
        self.codex_model = str(codex_model or "").strip()
        self.codex_temp_root = str(codex_temp_root or "").strip() or None
        self.last_reason = ""
        self.last_raw_responses = []
        self.last_prompts = []
        self.last_backend_runs = []

    @staticmethod
    def _codex_command():
        executable = shutil.which("codex")
        if not executable:
            raise RuntimeError("codex CLI was not found")
        if os.name == "nt" and executable.lower().endswith(
                (".cmd", ".ps1")):
            node = shutil.which("node")
            script = Path(executable).parent / "node_modules" / \
                "@openai" / "codex" / "bin" / "codex.js"
            if not node or not script.is_file():
                raise RuntimeError("codex CLI Node.js entry point was not found")
            return [node, str(script)]
        return [executable]

    def _predict_codex(self, role: str, prompt: str,
                       screenshot_bytes: bytes):
        if role == "element_explorer":
            schema = {
                "type": "object",
                "properties": {
                    "current_page": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": [
                                "known", "new", "uncertain"]},
                            "page_ref": {"anyOf": [
                                {"type": "string"}, {"type": "null"}]},
                            "proposed_name": {"type": "string"},
                            "reason": {"type": "string"},
                        },
                        "required": [
                            "kind", "page_ref", "proposed_name", "reason"],
                        "additionalProperties": False,
                    },
                    "discovered_controls": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "target": {"type": "string"},
                                "area": {"type": "string"},
                                "relation": {"type": "string", "enum": [
                                    "return", "close", "navigation",
                                    "function", "other"]},
                                "reason": {"type": "string"},
                            },
                            "required": [
                                "target", "area", "relation", "reason"],
                            "additionalProperties": False,
                        },
                    },
                    "loop_assessment": {
                        "type": "object",
                        "properties": {
                            "status": {"type": "string", "enum": [
                                "not_looping", "suspected", "confirmed"]},
                            "reason": {"type": "string"},
                        },
                        "required": ["status", "reason"],
                        "additionalProperties": False,
                    },
                    "action": {
                        "type": "object",
                        "properties": {
                            "type": {"type": "string", "enum": [
                                "CLICK", "SCROLL", "BACK", "WAIT",
                                "FINISH", "DEFER", "CALL_TOOL"]},
                            "target": {"type": "string"},
                            "point_1000": {"anyOf": [
                                {"type": "array", "items": {
                                    "type": "number"}, "minItems": 2,
                                 "maxItems": 2},
                                {"type": "null"}]},
                            "direction": {"anyOf": [
                                {"type": "string", "enum": [
                                    "up", "down", "left", "right"]},
                                {"type": "null"}]},
                            "safety": {"type": "string", "enum": [
                                "safe", "unsafe", "uncertain"]},
                            "action_role": {"type": "string", "enum": [
                                "goal", "route", "recovery", "other"]},
                            "reason": {"type": "string"},
                            "expected_result": {"type": "string"},
                            "tool_name": {"type": "string"},
                            "arguments": {"type": "object"},
                        },
                        "required": [
                            "type", "target", "point_1000", "direction",
                            "safety", "action_role", "reason",
                            "expected_result"],
                        "additionalProperties": False,
                    },
                },
                "required": [
                    "current_page", "discovered_controls", "action"],
                "additionalProperties": False,
            }
        else:
            result_key = (
                "selected_page_id" if role == "explorer_route"
                else "selected_entry_id"
            )
            schema = {
                "type": "object",
                "properties": {
                    result_key: {
                        "anyOf": [{"type": "string"}, {"type": "null"}],
                    },
                    "reason": {"type": "string"},
                },
                "required": [result_key, "reason"],
                "additionalProperties": False,
            }
        if self.codex_temp_root:
            os.makedirs(self.codex_temp_root, exist_ok=True)
        with tempfile.TemporaryDirectory(
                prefix="codex_explorer_", dir=self.codex_temp_root) as tmp:
            screenshot_path = os.path.join(tmp, "screen.png")
            schema_path = os.path.join(tmp, "response.schema.json")
            output_path = os.path.join(tmp, "response.json")
            with open(screenshot_path, "wb") as stream:
                stream.write(screenshot_bytes)
            with open(schema_path, "w", encoding="utf-8") as stream:
                json.dump(schema, stream, ensure_ascii=False)
            command = self._codex_command() + [
                "exec", "-m", self.codex_model,
                "--sandbox", "read-only",
                "--skip-git-repo-check", "--json",
                "--output-schema", schema_path,
                "-i", screenshot_path,
                "-o", output_path,
                prompt,
            ]
            completed = subprocess.run(
                command, cwd=tmp, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=300,
                check=False,
            )
            thread_id = ""
            for line in str(completed.stdout or "").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "thread.started":
                    thread_id = str(event.get("thread_id") or "")
                    break
            self.last_backend_runs.append({
                "backend": "codex_cli",
                "model": self.codex_model,
                "thread_id": thread_id,
                "returncode": completed.returncode,
            })
            if completed.returncode != 0:
                detail = str(completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(
                    f"codex CLI exited {completed.returncode}: {detail[:300]}")
            try:
                response = Path(output_path).read_text(encoding="utf-8")
            except OSError as exc:
                raise RuntimeError(
                    f"codex CLI did not write a final response: {exc}") from exc
        self.last_raw_responses.append(response)
        return _parse_json(response)

    def _predict(self, role: str, prompt: str, screenshot_bytes: bytes, *,
                 use_response_cache: bool):
        self.last_prompts.append(prompt)
        if self.codex_model:
            return self._predict_codex(role, prompt, screenshot_bytes)
        from ..visual_cache import predict_mm_role
        response, *_ = predict_mm_role(
            self.agent,
            role,
            prompt,
            [_img_arr(screenshot_bytes)],
            self.ledger,
            max_attempts=1,
            use_response_cache=use_response_cache,
        )
        self.last_raw_responses.append(str(response or ""))
        return _parse_json(response)

    def choose(self, screenshot_bytes: bytes, context: Dict[str, Any], *,
               platform: str) -> Dict[str, Any]:
        self.last_reason = ""
        self.last_raw_responses = []
        self.last_prompts = []
        self.last_backend_runs = []
        records = [
            dict(item) for item in context.get("function_entries") or []
            if isinstance(item, dict)
            and str(item.get("target") or "")
        ]
        entries = [
            item for item in records if str(item.get("entry_id") or "")
        ]
        if ((self.agent is None and not self.codex_model)
                or not screenshot_bytes or not entries):
            self.last_reason = "explorer unavailable"
            return {}
        allowed = {str(item["entry_id"]) for item in entries}
        feedback = ""
        for attempt in range(2):
            prompt_context = dict(context)
            prompt_context["function_entries"] = records
            prompt_context["framework_feedback"] = feedback
            try:
                parsed = self._predict(
                    "explorer",
                    build_explorer_prompt(prompt_context, platform=platform),
                    screenshot_bytes,
                    use_response_cache=(attempt == 0),
                )
            except Exception as exc:
                logger.warning("explorer decision failed: %s", exc)
                self.last_reason = f"explorer failed: {exc}"[:200]
                return {}
            if not isinstance(parsed, dict):
                feedback = "回复不是合法 JSON 对象。请严格按给定格式重新判断。"
                continue
            if "selected_entry_id" not in parsed:
                feedback = "回复缺少 selected_entry_id。请重新选择或明确返回 null。"
                continue
            reason = str(parsed.get("reason") or "").strip()
            if not reason:
                feedback = "回复缺少 reason。请说明选择依据或当前无法执行的可见原因。"
                continue
            raw_selected = parsed.get("selected_entry_id")
            selected = str(raw_selected or "").strip()
            if raw_selected is None or not selected:
                if attempt == 0:
                    feedback = (
                        "当前仍有待探索入口。请根据最新截图再次检查；如果它们确实都不属于当前前景界面、"
                        "被遮挡或无法可靠执行，可以继续返回 null，并具体说明截图证据。"
                    )
                    continue
                self.last_reason = (
                    f"Explorer model declined current entries: {reason}"
                )[:200]
                return {
                    "selected_entry_id": None,
                    "next_action": None,
                    "reason": reason,
                }
            if selected not in allowed:
                feedback = (
                    f"selected_entry_id={selected!r} 不在本次候选中。"
                    f"只能选择 {sorted(allowed)} 或返回 null。"
                )
                continue
            action_name = "click" if is_android(platform) else "CLICK"
            action, action_error = normalize_native_action(
                {"action_type": action_name}, platform=platform)
            if action_error or action is None:
                self.last_reason = str(
                    action_error or "invalid click action")
                return {}
            return {
                "selected_entry_id": selected,
                "next_action": {
                    "action": action,
                    "choice_id": selected,
                    "reason": reason,
                },
                "reason": reason,
            }
        self.last_reason = feedback or "explorer returned an invalid decision"
        return {}

    def choose_route(self, screenshot_bytes: bytes, context: Dict[str, Any]):
        """Choose one prompt-local known page for the Router to revisit."""
        self.last_reason = ""
        self.last_raw_responses = []
        self.last_prompts = []
        self.last_backend_runs = []
        pages = [
            dict(item) for item in context.get("candidate_pages") or []
            if isinstance(item, dict) and str(item.get("page_id") or "")
        ]
        if ((self.agent is None and not self.codex_model)
                or not screenshot_bytes or not pages):
            self.last_reason = "route choice unavailable"
            return {}
        allowed = {str(item["page_id"]) for item in pages}
        feedback = ""
        for attempt in range(2):
            prompt_context = dict(context)
            prompt_context["candidate_pages"] = pages
            prompt_context["framework_feedback"] = feedback
            try:
                parsed = self._predict(
                    "explorer_route",
                    build_route_choice_prompt(prompt_context),
                    screenshot_bytes,
                    use_response_cache=(attempt == 0),
                )
            except Exception as exc:
                logger.warning("explorer route choice failed: %s", exc)
                self.last_reason = f"route choice failed: {exc}"[:200]
                return {}
            if not isinstance(parsed, dict):
                feedback = "回复不是合法 JSON 对象。请严格按给定格式重新判断。"
                continue
            if "selected_page_id" not in parsed:
                feedback = "回复缺少 selected_page_id。请重新选择或明确返回 null。"
                continue
            reason = str(parsed.get("reason") or "").strip()
            if not reason:
                feedback = "回复缺少 reason。请说明选择依据。"
                continue
            raw_selected = parsed.get("selected_page_id")
            selected = str(raw_selected or "").strip()
            if raw_selected is None or not selected:
                if attempt == 0:
                    feedback = (
                        "这些已知界面仍有待探索内容。请再次选择下一处；如果仍不应前往，"
                        "请具体说明为什么所有候选都不适合。"
                    )
                    continue
                self.last_reason = (
                    f"Explorer model declined route candidates: {reason}"
                )[:200]
                return {"selected_page_id": None, "reason": reason}
            if selected not in allowed:
                feedback = (
                    f"selected_page_id={selected!r} 不在本次候选中。"
                    f"只能选择 {sorted(allowed)} 或返回 null。"
                )
                continue
            return {"selected_page_id": selected, "reason": reason}
        self.last_reason = feedback or "explorer returned an invalid route choice"
        return {}

    def explore_target(
        self, screenshot_bytes: bytes, context: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Choose one direct safe action for a framework-selected target."""
        self.last_reason = ""
        self.last_raw_responses = []
        self.last_prompts = []
        self.last_backend_runs = []
        goal = dict(context.get("goal") or {})
        if ((self.agent is None and not self.codex_model)
                or not screenshot_bytes
                or not str(goal.get("target") or "").strip()):
            self.last_reason = "element explorer unavailable"
            return {}
        page_graph = dict(context.get("page_graph") or {})
        allowed_pages = {
            str(value) for value in page_graph.get("page_refs") or []
            if str(value)
        }
        feedback = ""
        for attempt in range(2):
            prompt_context = dict(context)
            prompt_context["goal"] = goal
            prompt_context["framework_feedback"] = feedback
            try:
                parsed = self._predict(
                    "element_explorer",
                    build_element_exploration_prompt(prompt_context),
                    screenshot_bytes,
                    use_response_cache=(attempt == 0),
                )
            except Exception as exc:
                logger.warning("element exploration decision failed: %s", exc)
                self.last_reason = f"element explorer failed: {exc}"[:200]
                return {}
            if not isinstance(parsed, dict):
                feedback = "回复不是合法 JSON 对象。请严格按给定格式重新判断。"
                continue
            current_page = parsed.get("current_page")
            discovered = parsed.get("discovered_controls")
            loop_assessment = parsed.get("loop_assessment")
            action = parsed.get("action")
            if not isinstance(current_page, dict) or not isinstance(
                    discovered, list) or not isinstance(action, dict):
                feedback = (
                    "current_page、discovered_controls 和 action 的类型不正确。"
                )
                continue
            page_kind = str(current_page.get("kind") or "").strip().casefold()
            page_ref_value = current_page.get("page_ref")
            page_ref = str(page_ref_value or "").strip()
            if page_kind not in {"known", "new", "uncertain"}:
                feedback = "current_page.kind 必须是 known、new 或 uncertain。"
                continue
            if page_kind == "known" and page_ref not in allowed_pages:
                feedback = (
                    f"current_page.page_ref={page_ref!r} 不在页面图中。"
                    f"只能选择 {sorted(allowed_pages)}。"
                )
                continue
            if page_kind != "known" and page_ref_value is not None:
                feedback = "new 或 uncertain 时 current_page.page_ref 必须是 null。"
                continue
            action_type = str(action.get("type") or "").strip().upper()
            target = str(action.get("target") or "").strip()
            direction_value = action.get("direction")
            direction = str(direction_value or "").strip().casefold()
            safety = str(action.get("safety") or "").strip().casefold()
            action_role = str(
                action.get("action_role") or "").strip().casefold()
            reason = str(action.get("reason") or "").strip()
            expected = str(action.get("expected_result") or "").strip()
            tool_name = str(action.get("tool_name") or "").strip().casefold()
            tool_arguments = action.get("arguments")
            point_value = action.get("point_1000")
            if loop_assessment is None:
                loop_assessment = {
                    "status": "not_looping", "reason": "not reported"}
            if not isinstance(loop_assessment, dict):
                feedback = "loop_assessment 必须是 JSON 对象。"
                continue
            loop_status = str(
                loop_assessment.get("status") or "").strip().casefold()
            if loop_status not in {"not_looping", "suspected", "confirmed"}:
                feedback = "loop_assessment.status 不合法。"
                continue
            point = None
            if point_value is not None:
                if (not isinstance(point_value, list) or len(point_value) != 2):
                    feedback = "point_1000 必须是 [x,y] 或 null。"
                    continue
                try:
                    point = [float(point_value[0]), float(point_value[1])]
                except (TypeError, ValueError):
                    feedback = "point_1000 中的坐标必须是数字。"
                    continue
                if not all(0.0 <= value <= 1000.0 for value in point):
                    feedback = "point_1000 坐标必须位于 0..1000。"
                    continue
            if action_type not in {
                    "CLICK", "SCROLL", "BACK", "WAIT", "FINISH", "DEFER",
                    "CALL_TOOL"}:
                feedback = "action.type 不在允许集合中。"
                continue
            if loop_status == "confirmed" and action_type not in {
                    "DEFER", "FINISH"}:
                feedback = "确认死循环后必须 DEFER，或在目标已完成时 FINISH。"
                continue
            if safety not in {"safe", "unsafe", "uncertain"}:
                feedback = "action.safety 必须是 safe、unsafe 或 uncertain。"
                continue
            if action_role not in {"goal", "route", "recovery", "other"}:
                feedback = "action.action_role 不合法。"
                continue
            if not reason or not expected:
                feedback = "action.reason 和 expected_result 不能为空。"
                continue
            if action_type == "CALL_TOOL":
                allowed_tools = {
                    str(item.get("name") or "").strip().casefold()
                    for item in context.get("tool_catalog") or []
                    if isinstance(item, dict)
                }
                if tool_name not in allowed_tools:
                    feedback = (
                        f"tool_name={tool_name!r} 不在可用工具中："
                        f"{sorted(allowed_tools)}。"
                    )
                    continue
                if not isinstance(tool_arguments, dict):
                    feedback = "CALL_TOOL 的 arguments 必须是 JSON 对象。"
                    continue
                if point is not None or direction_value is not None:
                    feedback = "CALL_TOOL 的 point_1000 和 direction 必须是 null。"
                    continue
            elif action_type == "CLICK" and (not target or point is None):
                feedback = "CLICK 必须提供 target 和 point_1000。"
                continue
            if action_type not in {"CLICK", "SCROLL"} \
                    and point is not None:
                feedback = "非 CLICK/SCROLL 的 point_1000 必须是 null。"
                continue
            if action_type == "SCROLL" and direction not in {
                    "up", "down", "left", "right"}:
                feedback = "SCROLL 必须提供合法 direction。"
                continue
            if action_type != "SCROLL" and direction_value is not None:
                feedback = "非 SCROLL 动作的 direction 必须是 null。"
                continue
            normalized_discovered = []
            for item in discovered[:20]:
                if not isinstance(item, dict):
                    continue
                relation = str(item.get("relation") or "").strip().casefold()
                item_target = str(item.get("target") or "").strip()
                if not item_target or relation not in {
                        "return", "close", "navigation", "function", "other"}:
                    continue
                normalized_discovered.append({
                    "target": item_target[:160],
                    "area": str(item.get("area") or "").strip()[:160],
                    "relation": relation,
                    "reason": str(item.get("reason") or "").strip()[:300],
                })
            self.last_reason = reason[:200]
            return {
                "decision": (
                    "defer" if action_type == "DEFER"
                    else "finish" if action_type == "FINISH"
                    else "tool" if action_type == "CALL_TOOL"
                    else "act"
                ),
                "current_page": {
                    "kind": page_kind,
                    "page_ref": page_ref if page_kind == "known" else None,
                    "proposed_name": str(
                        current_page.get("proposed_name") or "").strip()[:160],
                    "reason": str(
                        current_page.get("reason") or "").strip()[:500],
                },
                "discovered_controls": normalized_discovered,
                "loop_assessment": {
                    "status": loop_status,
                    "reason": str(
                        loop_assessment.get("reason") or "").strip()[:500],
                },
                "next_action": {
                    "type": action_type,
                    "target": target[:160],
                    "point_1000": point,
                    "direction": direction if action_type == "SCROLL" else None,
                    "safety": safety,
                    "action_role": action_role,
                    "reason": reason[:500],
                    "expected_result": expected[:500],
                    "tool_name": tool_name,
                    "arguments": dict(tool_arguments or {}),
                },
                "reason": reason[:500],
            }
        self.last_reason = feedback or "invalid element exploration decision"
        return {}


__all__ = ["ExplorerAgent"]
