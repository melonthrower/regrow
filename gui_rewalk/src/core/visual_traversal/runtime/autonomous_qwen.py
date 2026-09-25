"""DashScope-compatible Qwen transport for autonomous exploration."""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional, Sequence

from .autonomous_agent import CodexAutonomousAgent
from .autonomous_prompt import (
    _model_retry_correction,
    _requires_entry_review,
    build_prompt,
    build_system_prompt,
)
from .autonomous_protocol import available_tool_catalog
from .autonomous_schema import (
    _require_model_reason,
    fixed_identity_from_context,
    identity_stage_from_context,
    response_schema_for_tools,
)
from .autonomous_turn import AutonomousTurn, parse_turn


class _QwenResponseContractError(ValueError):
    """A safe response-envelope error with debug-only raw evidence."""

    def __init__(
        self,
        message: str,
        *,
        raw_response: str,
        backend: Dict[str, Any],
    ) -> None:
        super().__init__(message)
        self.raw_response = raw_response
        self.backend = dict(backend)


class QwenAutonomousAgent(CodexAutonomousAgent):
    """Use the repository's DashScope-compatible Qwen screenshot transport."""

    def __init__(
        self,
        model: str,
        output_root: str,
        transport: Any,
        *,
        timeout: int = 120,
    ):
        super().__init__(model, output_root, timeout=timeout)
        self.transport = transport
        if hasattr(self.transport, "model_version"):
            self.transport.model_version = self.model
        if (getattr(self.transport, "model_client", None) is not None
                and not str(os.environ.get("DASHSCOPE_API_KEY") or "").strip()):
            raise RuntimeError("DASHSCOPE_API_KEY is not configured")

    @staticmethod
    def _schema_instruction(schema: Dict[str, Any]) -> str:
        def compact(value: Any) -> Any:
            if isinstance(value, dict):
                return {
                    key: compact(item)
                    for key, item in value.items()
                    if key not in {"description", "title", "$comment"}
                }
            if isinstance(value, list):
                return [compact(item) for item in value]
            return value

        return (
            "\n\n只输出一个 JSON 对象，不要 Markdown、代码围栏或额外说明。"
            "所有 required 字段都必须出现；无内容时使用 schema 允许的空字符串、空数组或 null。"
            "本轮 JSON Schema：\n"
            + json.dumps(
                compact(schema), ensure_ascii=False, separators=(",", ":"))
        )

    def _call_qwen(
        self,
        prompt: str,
        screenshots: Sequence[bytes],
        *,
        role: str,
        system_prompt: str = "",
    ) -> tuple[Dict[str, Any], str, Dict[str, Any]]:
        response, prompt_tokens, completion_tokens, attempts = (
            self.transport.predict_mm_with_policy(
                prompt,
                list(screenshots),
                max_attempts=1,
                timeout_seconds=float(self.timeout),
                system_prompt=system_prompt,
            )
        )
        raw = str(response or "")
        backend = {
            "backend": "qwen_api",
            "role": role,
            "requested_model": self.model,
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "transport_attempts": attempts,
        }
        prompt_details = getattr(
            self.transport, "last_prompt_tokens_details", {})
        if isinstance(prompt_details, dict) and prompt_details:
            backend["prompt_tokens_details"] = dict(prompt_details)
        try:
            payload = self.transport.parse_json(raw)
        except Exception as exc:
            raise _QwenResponseContractError(
                "response must contain one valid JSON object",
                raw_response=raw,
                backend=backend,
            ) from exc
        if not isinstance(payload, dict):
            raise _QwenResponseContractError(
                "response must be a JSON object",
                raw_response=raw,
                backend=backend,
            )
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
        role = f"autonomous_{tool_name}_specialist"
        role_system_prompt = (
            str(system_prompt or "")
            + self._schema_instruction(response_schema)
        )
        raw = ""
        backend: Dict[str, Any] = {
            "backend": "qwen_api", "role": role,
            "requested_model": self.model,
        }
        error = ""
        try:
            payload, raw, backend = self._call_qwen(
                prompt,
                screenshots,
                role=role,
                system_prompt=role_system_prompt,
            )
            if "reason" in (response_schema.get("required") or []):
                return _require_model_reason(payload, role=role)
            return payload
        except _QwenResponseContractError as exc:
            raw = exc.raw_response
            backend = exc.backend
            error = str(exc)[:500]
            raise
        except Exception as exc:
            error = str(exc)[:500]
            raise
        finally:
            self.backend_runs.append(dict(backend))
            self._record_debug({
                "role": role,
                "system_prompt": role_system_prompt,
                "prompt": prompt,
                "backend": backend,
                "raw_response": raw,
                "error": error,
            })

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
        self.last_error_kind = ""
        correction = ""
        requires_entry_review = _requires_entry_review(exploration_map)
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
        catalog = list(
            tool_catalog if tool_catalog is not None
            else available_tool_catalog(pending_identity=False)
        )
        identity_stage, selected_page_name, selected_page_identity = (
            identity_stage_from_context(exploration_map)
        )
        fixed_page_name, fixed_variant_name = fixed_identity_from_context(
            exploration_map)
        if pending_identity:
            fixed_page_name, fixed_variant_name = "", ""
        schema = response_schema_for_tools(
            catalog,
            has_previous=previous_screenshot is not None,
            requires_tool_review=bool(pending_identity),
            requires_entry_review=requires_entry_review,
            identity_stage=identity_stage,
            fixed_identity=bool(fixed_page_name and fixed_variant_name),
        )
        task = (
            (exploration_map or {}).get("task")
            or (exploration_map or {}).get("exploration_task")
            or {}
        )
        system_prompt = build_system_prompt(
            app_name=app_name,
            platform=platform,
            task_type=str(
                task.get("type") or task.get("task_type") or "survey_page"),
            phase=str(task.get("phase") or ""),
            has_pending_action=bool(
                (exploration_map or {}).get("pending_action")),
            pending_identity=bool(pending_identity),
            tool_catalog=catalog,
        ) + self._schema_instruction(schema)
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
                continuation=False,
                pending_identity=pending_identity,
                tool_catalog=catalog,
                include_tool_input_schemas=False,
                include_static_prefix=False,
                include_task_instructions=True,
                include_app_context=True,
                include_tool_catalog=False,
            )
            raw = ""
            backend: Dict[str, Any] = {
                "backend": "qwen_api",
                "role": "autonomous_explorer",
                "requested_model": self.model,
            }
            error = ""
            error_kind = ""
            try:
                payload, raw, backend = self._call_qwen(
                    prompt,
                    screenshots,
                    role="autonomous_explorer",
                    system_prompt=system_prompt,
                )
            except _QwenResponseContractError as exc:
                turn = None
                raw = exc.raw_response
                backend = exc.backend
                error = str(exc)[:500]
                error_kind = "contract"
            except Exception as exc:
                # Provider/transport detail is retained only in debug.  The
                # model-facing retry receives the generic safe correction.
                turn = None
                error = str(exc)[:500]
                error_kind = "backend"
            else:
                # parse_turn returns a safe contract error instead of raising;
                # keep it separate so field-level feedback reaches retry two.
                turn, parse_error = parse_turn(
                    payload,
                    has_previous=previous_screenshot is not None,
                    requires_tool_review=bool(pending_identity),
                    requires_entry_review=requires_entry_review,
                    available_tools=[str(item.get("name") or "")
                                     for item in catalog],
                    identity_stage=identity_stage,
                    selected_page_name=selected_page_name,
                    selected_page_identity=selected_page_identity,
                    fixed_page_name=fixed_page_name,
                    fixed_variant_name=fixed_variant_name,
                )
                if turn is None:
                    error = parse_error
                    error_kind = "contract"
            self._record_debug({
                "role": "autonomous_explorer",
                "attempt": attempt + 1,
                "system_prompt": system_prompt,
                "prompt": prompt,
                "raw_response": raw,
                "backend": backend,
                "error": error,
                "error_kind": error_kind,
            })
            self.backend_runs.append(dict(backend))
            if turn is not None:
                return turn
            correction = _model_retry_correction(
                error,
                contract_error=error_kind == "contract",
            )
        self.last_error = correction
        self.last_error_kind = error_kind
        return None
