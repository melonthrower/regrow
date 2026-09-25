"""Shared autonomous model adapter and stateless specialist calls."""

from __future__ import annotations

from copy import deepcopy
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from typing import Any, Dict, List, Optional, Sequence, Tuple

from PIL import Image, ImageDraw

from .autonomous_action_tools import (
    CLICK_REVIEW_PROMPT,
    CLICK_REVIEW_SCHEMA,
    INTERRUPTION_REVIEW_PROMPT,
    INTERRUPTION_REVIEW_SCHEMA,
)
from .autonomous_prompt import (
    _entry_review_feedback_text,
    _history_memory_text,
    _model_region_record,
    _model_retry_correction,
    _natural_rejection_text,
    _requires_entry_review,
    build_prompt,
)
from .autonomous_protocol import (
    ENTRY_PRESENCE_REVIEW_PROMPT,
    ENTRY_REVIEW_SPECIALIST_PROMPT,
    PAGE_ONLY_IDENTITY_RESPONSE_SCHEMA,
    PAGE_ONLY_IDENTITY_SPECIALIST_PROMPT,
    PAGE_IDENTITY_RESPONSE_SCHEMA,
    PAGE_IDENTITY_SPECIALIST_PROMPT,
    VARIANT_ONLY_IDENTITY_RESPONSE_SCHEMA,
    VARIANT_ONLY_IDENTITY_SPECIALIST_PROMPT,
    available_tool_catalog,
)
from .autonomous_region_tools import (
    CROSS_PAGE_REGION_REVIEW_PROMPT,
    CROSS_PAGE_REGION_REVIEW_SCHEMA,
    REGION_MAPPING_PROMPT,
    REGION_MAPPING_SCHEMA,
    REGION_REVIEW_PROMPT,
    REGION_REVIEW_SCHEMA,
)
from .autonomous_schema import (
    ENTRY_PRESENCE_REVIEW_RESPONSE_SCHEMA,
    ENTRY_REVIEW_RESPONSE_SCHEMA,
    RESPONSE_SCHEMA,
    _require_model_reason,
    fixed_identity_from_context,
    identity_stage_from_context,
    response_schema_for_tools,
)
from .autonomous_turn import AutonomousTurn, parse_turn


INTERRUPTION_ROUND_LIMIT = 3
REGION_REVIEW_ATTEMPT_LIMIT = 3
ENTRY_REVIEW_ATTEMPT_LIMIT = 3


def _region_bbox_overlay(
    screenshot: bytes,
    regions: Sequence[Any],
) -> Tuple[Optional[bytes], List[str]]:
    """Draw one deterministic R-label overlay for Region-bound review."""
    with Image.open(io.BytesIO(screenshot)) as source:
        overlay = source.convert("RGB")
    draw = ImageDraw.Draw(overlay)
    labels: List[str] = []
    palette = (
        (255, 0, 255),
        (0, 170, 255),
        (255, 128, 0),
        (0, 190, 90),
    )
    image_width, image_height = overlay.size
    line_width = max(2, round(min(image_width, image_height) / 250))
    for index, region in enumerate(regions, start=1):
        if not isinstance(region, dict):
            continue
        bbox = region.get("bbox_1000")
        if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
            continue
        try:
            x1, y1, x2, y2 = [float(value) for value in bbox]
        except (TypeError, ValueError):
            continue
        if not (0 <= x1 < x2 <= 1000 and 0 <= y1 < y2 <= 1000):
            continue
        pixels = (
            round(x1 * max(0, image_width - 1) / 1000.0),
            round(y1 * max(0, image_height - 1) / 1000.0),
            round(x2 * max(0, image_width - 1) / 1000.0),
            round(y2 * max(0, image_height - 1) / 1000.0),
        )
        color = palette[(index - 1) % len(palette)]
        draw.rectangle(pixels, outline=color, width=line_width)
        label = f"R{index}"
        label_left, label_top = pixels[0], pixels[1]
        draw.rectangle(
            (label_left, label_top, label_left + 28, label_top + 15),
            fill=color,
        )
        draw.text(
            (label_left + 3, label_top + 1), label, fill=(255, 255, 255))
        name = str(region.get("name") or "").strip() or "unnamed Region"
        labels.append(
            f"{label} marks Region '{name}' at bbox_1000 {list(bbox)}.")
    if not labels:
        return None, []
    stream = io.BytesIO()
    overlay.save(stream, format="PNG")
    return stream.getvalue(), labels


class CodexAutonomousAgent:
    """Call one Codex multimodal model for observation and action together."""

    def __init__(self, model: str, output_root: str, *, timeout: int = 300):
        self.model = str(model or "").strip()
        self.output_root = os.path.abspath(output_root)
        self.timeout = int(timeout)
        self.debug_path = os.path.join(
            self.output_root, "_autonomous_debug.jsonl")
        self.temp_root = os.path.join(self.output_root, "_autonomous_tmp")
        self.backend_runs: List[Dict[str, Any]] = []
        self.thread_id = ""
        self.last_error = ""
        self._response_schema = deepcopy(RESPONSE_SCHEMA)

    @staticmethod
    def _command() -> List[str]:
        executable = shutil.which("codex")
        if not executable:
            raise RuntimeError("codex CLI was not found")
        if os.name == "nt" and executable.lower().endswith((".cmd", ".ps1")):
            node = shutil.which("node")
            script = Path(executable).parent / "node_modules" / \
                "@openai" / "codex" / "bin" / "codex.js"
            if not node or not script.is_file():
                raise RuntimeError("codex CLI Node.js entry point was not found")
            return [node, str(script)]
        return [executable]

    def _record_debug(self, payload: Dict[str, Any]) -> None:
        os.makedirs(self.output_root, exist_ok=True)
        with open(self.debug_path, "a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def _invoke(
        self,
        prompt: str,
        screenshots: Sequence[bytes],
    ) -> tuple[Any, str, Dict[str, Any]]:
        if not self.model:
            raise RuntimeError("autonomous model is empty")
        os.makedirs(self.temp_root, exist_ok=True)
        with tempfile.TemporaryDirectory(
                prefix="codex_autonomous_", dir=self.temp_root) as temporary:
            image_paths = []
            for index, screenshot in enumerate(screenshots, 1):
                path = os.path.join(temporary, f"image_{index}.png")
                with open(path, "wb") as stream:
                    stream.write(screenshot)
                image_paths.append(path)
            schema_path = os.path.join(temporary, "response.schema.json")
            output_path = os.path.join(temporary, "response.json")
            with open(schema_path, "w", encoding="utf-8") as stream:
                json.dump(self._response_schema, stream, ensure_ascii=False)
            if self.thread_id:
                command = self._command() + [
                    "exec", "resume", "--all", "-m", self.model,
                    "--skip-git-repo-check", "--json",
                    "--output-schema", schema_path,
                ]
                for image_path in image_paths:
                    command.extend(["-i", image_path])
                command.extend([
                    "-o", output_path, self.thread_id, prompt,
                ])
            else:
                command = self._command() + [
                    "exec", "-m", self.model,
                    "--sandbox", "read-only",
                    "--skip-git-repo-check", "--json",
                    "--output-schema", schema_path,
                    "-i", *image_paths,
                    "-o", output_path,
                    prompt,
                ]
            completed = subprocess.run(
                command,
                cwd=temporary,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
                check=False,
            )
            thread_id = self.thread_id
            for line in str(completed.stdout or "").splitlines():
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event.get("type") == "thread.started":
                    thread_id = str(event.get("thread_id") or "")
                    break
            backend = {
                "backend": "codex_cli",
                "requested_model": self.model,
                "thread_id": thread_id,
                "resumed": bool(self.thread_id),
                "returncode": completed.returncode,
            }
            if completed.returncode != 0:
                detail = str(completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(
                    f"codex CLI exited {completed.returncode}: {detail[:500]}")
            try:
                raw = Path(output_path).read_text(encoding="utf-8")
                payload = json.loads(raw)
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"codex CLI did not write valid final JSON: {exc}") from exc
            if thread_id:
                self.thread_id = thread_id
        return payload, raw, backend

    def invoke_specialist(
        self,
        *,
        tool_name: str,
        prompt: str,
        screenshots: Sequence[bytes],
        response_schema: Dict[str, Any],
        system_prompt: str = "",
    ) -> Dict[str, Any]:
        """Run one stateless specialist call without altering the main thread."""
        if not self.model:
            raise RuntimeError("autonomous model is empty")
        os.makedirs(self.temp_root, exist_ok=True)
        with tempfile.TemporaryDirectory(
                prefix=f"codex_{tool_name}_", dir=self.temp_root) as temporary:
            image_paths: List[str] = []
            for index, screenshot in enumerate(screenshots, 1):
                path = os.path.join(temporary, f"image_{index}.png")
                with open(path, "wb") as stream:
                    stream.write(screenshot)
                image_paths.append(path)
            schema_path = os.path.join(temporary, "response.schema.json")
            output_path = os.path.join(temporary, "response.json")
            with open(schema_path, "w", encoding="utf-8") as stream:
                json.dump(response_schema, stream, ensure_ascii=False)
            command = self._command() + [
                "exec", "-m", self.model,
                "--sandbox", "read-only",
                "--skip-git-repo-check", "--json",
                "--output-schema", schema_path,
            ]
            for image_path in image_paths:
                command.extend(["-i", image_path])
            request_prompt = (
                str(system_prompt or "")
                + ("\n\n" if system_prompt else "")
                + prompt
            )
            command.extend(["-o", output_path, "-"])
            completed = subprocess.run(
                command,
                cwd=temporary,
                input=request_prompt,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout,
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
            backend = {
                "backend": "codex_cli",
                "role": f"autonomous_{tool_name}_specialist",
                "requested_model": self.model,
                "thread_id": thread_id,
                "resumed": False,
                "returncode": completed.returncode,
            }
            self.backend_runs.append(dict(backend))
            if completed.returncode != 0:
                detail = str(completed.stderr or completed.stdout or "").strip()
                raise RuntimeError(
                    f"codex CLI exited {completed.returncode}: {detail[:500]}")
            try:
                raw = Path(output_path).read_text(encoding="utf-8")
                payload = json.loads(raw)
            except (OSError, json.JSONDecodeError) as exc:
                raise RuntimeError(
                    f"codex CLI did not write valid final JSON: {exc}") from exc
            self._record_debug({
                "role": f"autonomous_{tool_name}_specialist",
                "system_prompt": system_prompt,
                "prompt": prompt,
                "backend": backend,
                "raw_response": raw,
                "error": "",
            })
            return _require_model_reason(
                payload, role=f"autonomous_{tool_name}_specialist")

    def resolve_page_identity(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Adapt the Page Identity request to a stateless model call."""
        identity_stage = str(
            request.get("identity_stage") or "combined"
        ).strip().casefold()
        if identity_stage not in {"page", "variant"}:
            identity_stage = "combined"
        current = request.get("current_screenshot")
        if not isinstance(current, (bytes, bytearray)) or not current:
            raise RuntimeError("page_identity current screenshot is unavailable")
        screenshots: List[bytes] = [bytes(current)]
        image_labels = ["图1：当前最新完整截图"]
        source = request.get("source_screenshot")
        if isinstance(source, (bytes, bytearray)) and source:
            screenshots.append(bytes(source))
            image_labels.append("图2：最近真实 GUI 动作的 source/before 完整截图")
        candidates: List[Dict[str, Any]] = []
        for candidate in request.get("registered_pages") or []:
            if not isinstance(candidate, dict):
                continue
            summary = {
                key: value for key, value in candidate.items()
                if key not in {"variants", "representative_screenshot"}
            }
            representative = candidate.get("representative_screenshot")
            if (
                identity_stage == "page"
                and isinstance(representative, (bytes, bytearray))
                and representative
            ):
                screenshots.append(bytes(representative))
                image_labels.append(
                    f"图{len(screenshots)}：候选 Page “"
                    f"{summary.get('page_name', '')}”的代表截图")
                summary["image_number"] = len(screenshots)
            variant_summaries = []
            for variant in (
                candidate.get("variants") or []
                if identity_stage != "page" else []
            ):
                if not isinstance(variant, dict):
                    continue
                variant_image = variant.get("representative_screenshot")
                variant_summary = {
                    key: value for key, value in variant.items()
                    if key != "representative_screenshot"
                }
                if (
                    isinstance(variant_image, (bytes, bytearray))
                    and variant_image
                ):
                    screenshots.append(bytes(variant_image))
                    image_labels.append(
                        f"图{len(screenshots)}：候选 Page “"
                        f"{summary.get('page_name', '')}”的 Variant “"
                        f"{variant_summary.get('variant_name', '')}”代表截图")
                    variant_summary["image_number"] = len(screenshots)
                variant_summaries.append(variant_summary)
            if variant_summaries:
                summary["variants"] = variant_summaries
            candidates.append(summary)
        if identity_stage == "variant":
            question = {
                "selected_page": dict(request.get("selected_page") or {}),
                "variant_candidates": (
                    list(candidates[0].get("variants") or [])
                    if candidates else []
                ),
                "reason": request.get("reason") or "",
            }
        else:
            question = {
                "suspected_pages": request.get("suspected_pages") or [],
                "proposed_new_name": request.get("proposed_new_name") or "",
                "reason": request.get("reason") or "",
                "registered_page_count": int(
                    request.get("registered_page_count") or 0),
                "registered_candidates": candidates,
            }
        arrival = request.get("arrival_context")
        if isinstance(arrival, dict) and arrival:
            arrival_lines: List[str] = []
            source_page = str(arrival.get("source_page") or "").strip()
            via_control = str(arrival.get("via_control") or "").strip()
            via_action = str(arrival.get("via_action") or "").strip()
            if source_page:
                arrival_lines.append(f"此前位于页面 {source_page}。")
            if via_control:
                action_text = {
                    "CLICK": "点击",
                    "DOUBLE_TAP": "双击",
                    "LONG_PRESS": "长按",
                    "SCROLL": "滚动",
                }.get(via_action.upper(), "操作")
                arrival_lines.append(
                    f"最近通过{action_text}可见控件“{via_control}”到达当前画面。")
            for edge in arrival.get("source_neighbors") or []:
                if not isinstance(edge, dict):
                    continue
                source = str(edge.get("from") or "").strip()
                via = str(edge.get("via") or "").strip()
                target = str(edge.get("to") or "").strip()
                if source and target:
                    middle = f"通过“{via}”" if via else ""
                    arrival_lines.append(
                        f"现有地图记录：从 {source} {middle}可到达 {target}。")
            recent_action = arrival.get("recent_action")
            if isinstance(recent_action, dict) and recent_action:
                arrival_lines.append(
                    "最近一次 GUI 动作：" + _history_memory_text([recent_action]))
            if arrival_lines:
                question["arrival_context"] = "\n".join(arrival_lines)
        previous_feedback = _natural_rejection_text(
            request.get("previous_tool_feedback"))
        if previous_feedback:
            question["previous_feedback"] = (
                "上一轮页面判断没有被主 Agent 采用，具体原因和修正建议是："
                + previous_feedback
            )
        specialist_prompt = {
            "page": PAGE_ONLY_IDENTITY_SPECIALIST_PROMPT,
            "variant": VARIANT_ONLY_IDENTITY_SPECIALIST_PROMPT,
        }.get(identity_stage, PAGE_IDENTITY_SPECIALIST_PROMPT)
        response_schema = {
            "page": PAGE_ONLY_IDENTITY_RESPONSE_SCHEMA,
            "variant": VARIANT_ONLY_IDENTITY_RESPONSE_SCHEMA,
        }.get(identity_stage, PAGE_IDENTITY_RESPONSE_SCHEMA)
        prompt = (
            "图片顺序：\n"
            + json.dumps(image_labels, ensure_ascii=False)
            + "\n\n本次身份问题：\n"
            + json.dumps(question, ensure_ascii=False)
        )
        return self.invoke_specialist(
            tool_name="page_identity",
            prompt=prompt,
            screenshots=screenshots,
            response_schema=response_schema,
            system_prompt=specialist_prompt,
        )

    def review_click(self, request: Dict[str, Any]) -> Dict[str, Any]:
        """Independently veto a chosen point-targeted action without moving it."""
        current = request.get("current_screenshot")
        point = request.get("point_1000")
        if not isinstance(current, (bytes, bytearray)) or not current:
            raise RuntimeError("click reviewer screenshot is unavailable")
        if not isinstance(point, list) or len(point) != 2:
            raise RuntimeError("click reviewer point_1000 is invalid")
        operation = str(request.get("operation") or "").strip().casefold()
        if operation not in {
                "click", "input_text", "double_tap", "long_press"}:
            raise RuntimeError(
                "click reviewer requires the exact pointer operation")
        image = Image.open(io.BytesIO(current)).convert("RGB")
        width, height = image.size
        x = round(float(point[0]) * max(0, width - 1) / 1000.0)
        y = round(float(point[1]) * max(0, height - 1) / 1000.0)
        half = max(64, round(min(width, height) * 0.12))
        crop_size = half * 2
        left = max(0, x - half)
        top = max(0, y - half)
        right = min(width, x + half)
        bottom = min(height, y + half)
        zoom = Image.new("RGB", (crop_size, crop_size), (32, 32, 32))
        zoom.paste(
            image.crop((left, top, right, bottom)),
            (half - (x - left), half - (y - top)),
        )
        zoom = zoom.resize(
            (crop_size * 2, crop_size * 2), Image.Resampling.LANCZOS)
        center = crop_size
        radius = 18
        length = 8
        marker = ImageDraw.Draw(zoom)
        color = (255, 0, 255)
        width_px = 3
        for sx, sy in ((-1, -1), (1, -1), (-1, 1), (1, 1)):
            corner_x = center + sx * radius
            corner_y = center + sy * radius
            marker.line(
                (corner_x, corner_y,
                 corner_x - sx * length, corner_y),
                fill=color, width=width_px,
            )
            marker.line(
                (corner_x, corner_y,
                 corner_x, corner_y - sy * length),
                fill=color, width=width_px,
            )
        stream = io.BytesIO()
        zoom.save(stream, format="PNG")
        prompt = (
            "本次审核：\n"
            + json.dumps({
                "review_mode": "proposed_action",
                "target": request.get("target") or "",
                "purpose": request.get("purpose") or "",
                "current_task": request.get("current_task") or {},
                "agent_reason": request.get("agent_reason") or "",
                "requested_entry": request.get("requested_entry") or {},
                "operation": operation,
                **({
                    "requested_text": str(
                        request.get("requested_text") or ""),
                } if operation == "input_text" else {}),
                "image_order": [
                    "图1：最新完整截图，用于判断实际控件的直接视觉归属",
                    "图2：同帧局部放大图；四个洋红角标包围的精确中心像素是唯一拟点击点，中心未被标记覆盖",
                ],
            }, ensure_ascii=False)
        )
        return self.invoke_specialist(
            tool_name="click_reviewer",
            prompt=prompt,
            screenshots=[bytes(current), stream.getvalue()],
            response_schema=CLICK_REVIEW_SCHEMA,
            system_prompt=CLICK_REVIEW_PROMPT,
        )

    def review_interruption(
        self, request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Choose one bounded recovery strategy for a visible interruption."""
        current = request.get("current_screenshot")
        if not isinstance(current, (bytes, bytearray)) or not current:
            raise RuntimeError("interruption reviewer screenshot is unavailable")
        task = request.get("current_task")
        task_text = "当前没有框架派发的具体探索任务。"
        if isinstance(task, dict) and task:
            task_type = {
                "survey_page": "调查当前页面的 Region 与主要功能入口",
                "explore_entry": "探索一个已经登记的功能入口",
            }.get(
                str(task.get("task_type") or "").strip(),
                "继续当前应用探索",
            )
            task_parts = [task_type]
            page_name = str(task.get("page_name") or "").strip()
            region_name = str(task.get("region_name") or "").strip()
            target = str(task.get("target") or "").strip()
            if page_name:
                task_parts.append(f"所在页面是“{page_name}”")
            if region_name:
                task_parts.append(f"当前 Region 是“{region_name}”")
            if target:
                task_parts.append(f"目标是“{target}”")
            task_text = "；".join(task_parts) + "。"
        observation = request.get("main_agent_observation")
        observation_text = "主 Agent 没有提供额外观察。"
        if isinstance(observation, dict):
            surface = str(observation.get("suspected_surface") or "").strip()
            obstruction = str(
                observation.get("obstruction_reason") or "").strip()
            observation_parts = []
            if surface:
                observation_parts.append(f"它看到的疑似临时表面是“{surface}”")
            if obstruction:
                observation_parts.append(f"认为受到影响的原因是：{obstruction}")
            if observation_parts:
                observation_text = "；".join(observation_parts) + "。"
        round_number = max(1, int(request.get("handling_round") or 1))
        round_limit = max(
            round_number,
            int(request.get("handling_round_limit") or INTERRUPTION_ROUND_LIMIT),
        )
        prompt = (
            "本次干扰判断：\n"
            + json.dumps({
                "review_mode": "temporary_interruption",
                "platform": request.get("platform") or "",
                "current_page": request.get("current_page") or "",
                "current_assignment": task_text,
                "main_agent_observation": observation_text,
                "review_conversation": (
                    f"这是当前任务处理可见干扰的第 {round_number} 次判断，"
                    f"最多允许 {round_limit} 次。"
                ),
                "image_order": ["图1：当前最新完整截图"],
            }, ensure_ascii=False)
        )
        return self.invoke_specialist(
            tool_name="interruption_handler",
            prompt=prompt,
            screenshots=[bytes(current)],
            response_schema=INTERRUPTION_REVIEW_SCHEMA,
            system_prompt=INTERRUPTION_REVIEW_PROMPT,
        )

    def review_region_proposal(
        self, request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Review one new Region partition before it changes the ledger."""
        current = request.get("current_screenshot")
        if not isinstance(current, (bytes, bytearray)) or not current:
            raise RuntimeError("region reviewer screenshot is unavailable")

        def region_view(item: Any) -> Dict[str, str]:
            if not isinstance(item, dict):
                return {}
            return {
                key: str(item.get(key) or "").strip()
                for key in ("name", "summary")
                if str(item.get(key) or "").strip()
            }

        proposal = {
            "page_name": request.get("page_name") or "",
            "main_agent_reason": request.get("main_agent_reason") or "",
            "existing_regions": [
                region_view(item)
                for item in request.get("existing_regions") or []
            ],
            "image_order": [(
                "图1：本次区域讨论首次提案的固定完整证据截图"
                if request.get("fixed_evidence") is True else
                "图1：当前最新完整截图"
            )],
        }
        screenshots = [bytes(current)]
        attempt = max(1, int(request.get("review_attempt") or 1))
        limit = max(
            attempt,
            int(request.get("review_attempt_limit")
                or REGION_REVIEW_ATTEMPT_LIMIT),
        )
        previous_review = request.get("previous_review")
        if isinstance(previous_review, dict) and previous_review:
            conversation = [
                f"这是同一讨论中的第 {attempt} 次复核，最多 {limit} 次。",
            ]
            previous_regions = [
                str(item.get("name") or "").strip()
                for item in previous_review.get("regions") or []
                if isinstance(item, dict)
                and str(item.get("name") or "").strip()
            ]
            if previous_regions:
                conversation.append(
                    "上一轮返回的当前区域：" + "；".join(previous_regions))
            previous_revisions = []
            for item in previous_review.get("revisions") or []:
                if not isinstance(item, dict):
                    continue
                old_name = str(item.get("old_region") or "").strip()
                decision = str(item.get("decision") or "").strip()
                target = str(item.get("merged_into") or "").strip()
                if old_name and decision:
                    previous_revisions.append(
                        f"{old_name}→{target if decision == 'merge' else decision}"
                    )
            if previous_revisions:
                conversation.append(
                    "上一轮逐项归属：" + "；".join(previous_revisions))
            old_reason = str(previous_review.get("reason") or "").strip()
            if old_reason:
                conversation.append("上一轮 Reviewer 的完整理由：" + old_reason)
            conversation.append(
                "主 Agent 已用本轮完整区域提案和理由作出回应；请依据固定证据"
                "截图重新返回完整 regions 和 revisions，不要只重复上一轮结论。")
            proposal["review_conversation"] = "\n".join(conversation)
        elif attempt > 1:
            proposal["review_conversation"] = (
                f"这是第 {attempt} 次复核，最多 {limit} 次。请依据固定证据截图重新"
                "返回完整 regions、每个已有区域恰好一次的 revisions 和整体理由。"
            )
        prompt = (
            "本次 Region 复核输入：\n"
            + json.dumps(proposal, ensure_ascii=False)
        )
        return self.invoke_specialist(
            tool_name="region_reviewer",
            prompt=prompt,
            screenshots=screenshots,
            response_schema=REGION_REVIEW_SCHEMA,
            system_prompt=REGION_REVIEW_PROMPT,
        )

    def review_cross_page_regions(
        self, request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Review accepted Regions against prior Page representatives."""
        current = request.get("current_screenshot")
        candidates = request.get("candidate_screenshots") or []
        if not isinstance(current, (bytes, bytearray)) or not current:
            raise RuntimeError("cross-page Region screenshot is unavailable")
        if not all(isinstance(item, (bytes, bytearray)) and item
                   for item in candidates):
            raise RuntimeError("cross-page candidate screenshot is unavailable")
        prompt = (
            "本次跨页面 Region 身份复核输入：\n"
            + json.dumps({
                "occurrences": request.get("occurrences") or [],
                "image_order": request.get("image_order") or [],
            }, ensure_ascii=False)
        )
        return self.invoke_specialist(
            tool_name="region_reviewer",
            prompt=prompt,
            screenshots=[bytes(current), *[bytes(item) for item in candidates]],
            response_schema=CROSS_PAGE_REGION_REVIEW_SCHEMA,
            system_prompt=CROSS_PAGE_REGION_REVIEW_PROMPT,
        )

    def map_region_partitions(
        self, request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Map two already reviewed Region catalogs in one stateless call."""
        before_screenshot = request.get("before_screenshot")
        after_screenshot = request.get("after_screenshot")
        if not isinstance(before_screenshot, bytes) or not before_screenshot:
            raise RuntimeError("Region mapping before screenshot is unavailable")
        if not isinstance(after_screenshot, bytes) or not after_screenshot:
            raise RuntimeError("Region mapping after screenshot is unavailable")

        before_catalog = [
            {
                "id": f"A{index}",
                "name": str(item.get("name") or ""),
                "summary": str(item.get("summary") or ""),
            }
            for index, item in enumerate(request.get("before_regions") or [], 1)
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        after_catalog = [
            {
                "id": f"B{index}",
                "name": str(item.get("name") or ""),
                "summary": str(item.get("summary") or ""),
            }
            for index, item in enumerate(request.get("after_regions") or [], 1)
            if isinstance(item, dict) and str(item.get("name") or "").strip()
        ]
        prompt = (
            "图片顺序：图1为动作前完整截图，图2为动作后完整截图。\n\n"
            "实际执行的动作：\n"
            + json.dumps(request.get("action") or {}, ensure_ascii=False)
            + "\n\n动作前页面与区域目录：\n"
            + json.dumps({
                "page": request.get("before_page") or "",
                "regions": before_catalog,
            }, ensure_ascii=False)
            + "\n\n动作后页面与区域目录：\n"
            + json.dumps({
                "page": request.get("after_page") or "",
                "regions": after_catalog,
            }, ensure_ascii=False)
        )
        result = self.invoke_specialist(
            tool_name="region_mapping",
            prompt=prompt,
            screenshots=[before_screenshot, after_screenshot],
            response_schema=REGION_MAPPING_SCHEMA,
            system_prompt=REGION_MAPPING_PROMPT,
        )
        before_ids = {item["id"] for item in before_catalog}
        after_ids = {item["id"] for item in after_catalog}
        used_before: set[str] = set()
        used_after: set[str] = set()
        matches: List[Dict[str, Any]] = []
        for item in result.get("matches") or []:
            if not isinstance(item, dict):
                raise RuntimeError("Region mapping match must be an object")
            before = [str(value) for value in item.get("before") or []]
            after = [str(value) for value in item.get("after") or []]
            reason = str(item.get("reason") or "").strip()
            if (
                not before or not after or not reason
                or len(before) != len(set(before))
                or len(after) != len(set(after))
                or not set(before) <= before_ids
                or not set(after) <= after_ids
                or used_before.intersection(before)
                or used_after.intersection(after)
            ):
                raise RuntimeError("Region mapping contains an invalid match")
            used_before.update(before)
            used_after.update(after)
            matches.append({"before": before, "after": after, "reason": reason})
        new = [str(value) for value in result.get("new") or []]
        uncertain = [
            {
                "after": str(item.get("after") or ""),
                "reason": str(item.get("reason") or "").strip(),
            }
            for item in result.get("uncertain") or []
            if isinstance(item, dict)
        ]
        new_set = set(new)
        uncertain_ids = {item["after"] for item in uncertain}
        if (
            len(new) != len(new_set)
            or len(uncertain) != len(uncertain_ids)
            or any(not item["reason"] for item in uncertain)
            or new_set.intersection(uncertain_ids)
            or used_after.intersection(new_set | uncertain_ids)
            or used_after | new_set | uncertain_ids != after_ids
        ):
            raise RuntimeError(
                "Every after Region must appear exactly once in the mapping")
        return {"matches": matches, "new": new, "uncertain": uncertain}

    def review_entry_candidates(
        self, request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Independently filter and complete one page's proposed entries."""
        current = request.get("current_screenshot")
        if not isinstance(current, (bytes, bytearray)) or not current:
            raise RuntimeError("entry reviewer screenshot is unavailable")
        proposal = {
            "page_name": request.get("page_name") or "",
            "main_agent_reason": request.get("main_agent_reason") or "",
            "regions": [
                _model_region_record(item)
                for item in request.get("regions") or []
            ],
            "candidates": request.get("candidates") or [],
            "shared_region_entries": (
                request.get("shared_region_entries") or []
            ),
            "entry_dispute": request.get("entry_dispute") or {},
            "known_entries": request.get("known_entries") or [],
            "coverage_audit_regions": (
                request.get("coverage_audit_regions") or []
            ),
            "image_order": ["图1：产生本次入口候选的固定完整证据截图"],
        }
        if request.get("entry_resolutions"):
            proposal["entry_resolutions"] = request["entry_resolutions"]
        screenshots = [bytes(current)]
        overlay_image, overlay_labels = _region_bbox_overlay(
            bytes(current), proposal["regions"])
        if overlay_image is not None:
            screenshots.append(overlay_image)
            proposal["image_order"].append(
                "Image 2: the same screenshot with only the audited Region "
                "bbox borders and R labels drawn; these marks are not UI content."
            )
            proposal["bbox_overlay_legend"] = overlay_labels
        attempt = max(1, int(request.get("review_attempt") or 1))
        limit = max(
            attempt,
            int(request.get("review_attempt_limit")
                or ENTRY_REVIEW_ATTEMPT_LIMIT),
        )
        previous_review = request.get("previous_review")
        if isinstance(previous_review, dict) and previous_review:
            previous_main_reason = str(
                previous_review.get("main_agent_reason") or "未保留"
            ).strip()
            proposal["review_conversation"] = "\n".join([
                f"这是同一份 GUI 证据下的第 {attempt} 次复核，最多 {limit} 次。",
                f"上一轮主 Agent 的说明：{previous_main_reason}",
                _entry_review_feedback_text(previous_review),
                "主 Agent 已根据上述意见提交了本轮候选和说明。请重新依据完整截图判断；"
                "结构化选择必须与本轮自然语言理由表达同一个结论。",
            ])
        elif attempt > 1:
            proposal["review_conversation"] = (
                f"这是第 {attempt} 次复核，最多 {limit} 次。请重新依据完整截图判断，"
                "并确保结构化选择与自然语言理由一致。"
            )
        previous_feedback = _natural_rejection_text(
            request.get("previous_rejection"))
        if previous_feedback:
            proposal["previous_response_feedback"] = (
                "上一份 Reviewer 回复没有被框架采用，原因如下："
                + previous_feedback
                + " 请按这段说明修正回复格式和候选引用。"
            )
        prompt = (
            "本次入口提案：\n"
            + json.dumps(proposal, ensure_ascii=False)
        )
        return self.invoke_specialist(
            tool_name="entry_reviewer",
            prompt=prompt,
            screenshots=screenshots,
            response_schema=ENTRY_REVIEW_RESPONSE_SCHEMA,
            system_prompt=ENTRY_REVIEW_SPECIALIST_PROMPT,
        )

    def review_entry_presence(
        self, request: Dict[str, Any],
    ) -> Dict[str, Any]:
        """Compare one Entry's accepted discovery frame with the current frame."""
        discovery = request.get("discovery_screenshot")
        current = request.get("current_screenshot")
        if not isinstance(discovery, (bytes, bytearray)) or not discovery:
            raise RuntimeError("entry discovery screenshot is unavailable")
        if not isinstance(current, (bytes, bytearray)) or not current:
            raise RuntimeError("current entry screenshot is unavailable")
        proposal = {
            "entry": request.get("entry") or {},
            "owner_region": request.get("owner_region") or {},
            "main_agent_observation": (
                request.get("main_agent_observation") or ""
            ),
            "image_order": [
                "图1：该入口首次通过复核时的完整截图",
                "图2：同一来源状态下本次定位失败的当前完整截图",
            ],
        }
        return self.invoke_specialist(
            tool_name="entry_presence_reviewer",
            prompt="入口存在性复核：\n" + json.dumps(
                proposal, ensure_ascii=False),
            screenshots=[bytes(discovery), bytes(current)],
            response_schema=ENTRY_PRESENCE_REVIEW_RESPONSE_SCHEMA,
            system_prompt=ENTRY_PRESENCE_REVIEW_PROMPT,
        )

    def decide(
        self,
        current_screenshot: bytes,
        history: Sequence[Dict[str, Any]],
        *,
        app_name: str,
        platform: str,
        actions_used: int = 0,
        max_actions: int = 0,
        previous_screenshot: Optional[bytes] = None,
        exploration_map: Optional[Dict[str, Any]] = None,
        tool_images: Sequence[bytes] = (),
        tool_image_labels: Sequence[str] = (),
        pending_identity: Optional[Dict[str, Any]] = None,
        tool_catalog: Optional[Sequence[Dict[str, Any]]] = None,
    ) -> Optional[AutonomousTurn]:
        self.last_error = ""
        correction = ""
        requires_entry_review = _requires_entry_review(exploration_map)
        identity_stage, selected_page_name, selected_page_identity = (
            identity_stage_from_context(exploration_map)
        )
        fixed_page_name, fixed_variant_name = fixed_identity_from_context(
            exploration_map)
        if pending_identity:
            fixed_page_name, fixed_variant_name = "", ""
        screenshots = (
            [previous_screenshot, current_screenshot]
            if previous_screenshot else [current_screenshot]
        )
        image_labels = (
            ["上一动作前完整截图", "当前最新完整截图"]
            if previous_screenshot else ["当前最新完整截图"]
        )
        screenshots.extend(tool_images)
        image_labels.extend(tool_image_labels)
        for attempt in range(2):
            prompt = build_prompt(
                history,
                app_name=app_name,
                platform=platform,
                actions_used=actions_used,
                max_actions=max_actions,
                correction=correction,
                exploration_map=exploration_map,
                image_labels=image_labels,
                continuation=bool(self.thread_id),
                pending_identity=pending_identity,
                tool_catalog=tool_catalog,
            )
            raw = ""
            backend: Dict[str, Any] = {
                "backend": "codex_cli", "requested_model": self.model,
            }
            try:
                self._response_schema = response_schema_for_tools(
                    list(tool_catalog) if tool_catalog is not None
                    else available_tool_catalog(pending_identity=False),
                    has_previous=previous_screenshot is not None,
                    requires_tool_review=bool(pending_identity),
                    requires_entry_review=requires_entry_review,
                    identity_stage=identity_stage,
                    fixed_identity=bool(
                        fixed_page_name and fixed_variant_name),
                )
                payload, raw, backend = self._invoke(prompt, screenshots)
                turn, error = parse_turn(
                    payload,
                    has_previous=previous_screenshot is not None,
                    requires_tool_review=bool(pending_identity),
                    requires_entry_review=requires_entry_review,
                    available_tools=[
                        str(item.get("name") or "")
                        for item in (tool_catalog or [])
                    ],
                    identity_stage=identity_stage,
                    selected_page_name=selected_page_name,
                    selected_page_identity=selected_page_identity,
                    fixed_page_name=fixed_page_name,
                    fixed_variant_name=fixed_variant_name,
                )
            except Exception as exc:
                turn, error = None, str(exc)[:500]
            record = {
                "role": "autonomous_explorer",
                "attempt": attempt + 1,
                "prompt": prompt,
                "raw_response": raw,
                "backend": backend,
                "error": error,
            }
            self._record_debug(record)
            self.backend_runs.append(dict(backend))
            if turn is not None:
                return turn
            correction = _model_retry_correction(error)
        self.last_error = correction
        return None
