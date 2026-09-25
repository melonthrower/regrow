"""Screenshot-only capability rollout executor.

This module is deliberately an orchestration layer.  It owns neither page
identity nor GUI grounding: every live boundary is injected through one adapter
per application.  Application graphs remain independent, and cross-application
movement is represented as an explicit, one-step boundary event.

Adapter contract (all observations are opaque to this module)::

    capture() -> observation
    identify(observation) -> node_id | None
    ground(action_spec, observation) -> grounded_action | None
    execute(grounded_action) -> execution_result
    settle(execution_result=None) -> None
    activate() -> optional execution_result             # optional

The completion verifier approves ordinary capability references and the final
instruction.  A collection-only workflow Agent may reuse one explicit
predicted-effect-State confirmation for both gates; malformed output, unknown
visual state, failed grounding, and route derailment still fail closed.
"""

from __future__ import annotations

import inspect
import json
import math
import re
from dataclasses import dataclass, field, replace
from typing import Any, Callable, Dict, List, Mapping, Optional, Protocol, Sequence, Tuple

import networkx as nx

from .agent_trajectory_audit import audit_agent_trajectory


class LiveVisualAdapter(Protocol):
    """Live screenshot/action boundary for one application."""

    def capture(self) -> Any: ...

    def identify(self, observation: Any) -> Optional[str]: ...

    def ground(self, action_spec: Mapping[str, Any], observation: Any) -> Any: ...

    def execute(self, grounded_action: Any) -> Any: ...

    def settle(self, execution_result: Any = None) -> Any: ...


class CompletionVerifier(Protocol):
    """Semantic completion boundary; implementations may call a VLM."""

    def verify_ref(
        self,
        ref: Mapping[str, Any],
        before: Any,
        after: Any,
        context: Mapping[str, Any],
    ) -> Any: ...

    def verify_final(
        self,
        instruction: Mapping[str, Any],
        observation: Any,
        context: Mapping[str, Any],
    ) -> Any: ...


@dataclass(frozen=True)
class CapabilityExecutionRef:
    """Normalized capability-backed instruction reference."""

    ref_id: str
    app_id: str
    node_id: str
    target_node: str
    name: str = ""
    requires: Tuple[Any, ...] = ()
    depends_on: Tuple[str, ...] = ()
    params: Mapping[str, Any] = field(default_factory=dict)
    output_slot: str = ""
    desired_outcome: Any = None
    action_steps: int = 1
    raw: Mapping[str, Any] = field(default_factory=dict, compare=False)

    @classmethod
    def from_mapping(
        cls,
        raw: Mapping[str, Any],
        index: int,
        default_app_id: str = "",
    ) -> "CapabilityExecutionRef":
        app_id = str(raw.get("app_id") or raw.get("app") or default_app_id or "").strip()
        node_id = str(raw.get("node_id") or raw.get("entry_node") or "").strip()
        target_node = (
            str(raw.get("target_node") or "").strip()
            if "target_node" in raw else node_id)
        name = str(raw.get("name") or raw.get("capability") or "").strip()
        ref_id = str(
            raw.get("ref_id")
            or raw.get("capability_id")
            or raw.get("id")
            or name
            or f"ref_{index + 1}"
        ).strip()
        requires_raw = raw.get("requires") or []
        if isinstance(requires_raw, (str, Mapping)):
            requires_raw = [requires_raw]
        depends_raw = raw.get("depends_on") or []
        if isinstance(depends_raw, str):
            depends_raw = [depends_raw]
        params = raw.get("params") or {}
        if not isinstance(params, Mapping):
            params = {}
        output_slot = str(raw.get("output_slot") or "").strip()
        return cls(
            ref_id=ref_id,
            app_id=app_id,
            node_id=node_id,
            target_node=target_node,
            name=name,
            requires=tuple(requires_raw),
            depends_on=tuple(str(v).strip() for v in depends_raw if str(v).strip()),
            params=dict(params),
            output_slot=output_slot,
            desired_outcome=raw.get("desired_outcome"),
            action_steps=_action_steps(raw, default=1, allow_zero=True),
            raw=dict(raw),
        )

    def to_dict(self) -> Dict[str, Any]:
        value = dict(self.raw)
        value.update(
            {
                "ref_id": self.ref_id,
                "app_id": self.app_id,
                "node_id": self.node_id,
                "target_node": self.target_node,
                "name": self.name,
                "requires": list(self.requires),
                "depends_on": list(self.depends_on),
                "params": dict(self.params),
                "output_slot": self.output_slot,
                "action_steps": self.action_steps,
            }
        )
        if self.desired_outcome is not None:
            value["desired_outcome"] = self.desired_outcome
        return value


@dataclass(frozen=True)
class _RouteHop:
    source: str
    target: str
    edge_key: Any
    edge: Mapping[str, Any]
    action_steps: int


@dataclass
class _PreconditionDecision:
    satisfied: bool
    skip_capability: bool = False
    action_steps: int = 0
    evidence: Any = None
    bindings: Dict[str, Any] = field(default_factory=dict)
    action_events: List[Dict[str, Any]] = field(default_factory=list)
    reason: str = ""


class VLMCompletionVerifier:
    """Small fail-closed JSON wrapper around a screenshot-capable VLM agent.

    ``agent`` may expose ``predict_mm(prompt, images)`` or be a callable taking
    ``(prompt, images)``.  The model must return JSON with an explicit boolean
    ``complete`` (``success`` and ``completed`` are accepted aliases).
    """

    _JSON_OBJECT = re.compile(r"\{.*\}", re.S)

    def __init__(self, agent: Any):
        self.agent = agent

    def verify_ref(
        self,
        ref: Mapping[str, Any],
        before: Any,
        after: Any,
        context: Mapping[str, Any],
    ) -> Dict[str, Any]:
        desired_outcome = ref.get("desired_outcome")
        output_slot = str(ref.get("output_slot") or "").strip()
        outcome_contract = ""
        if output_slot:
            outcome_contract = (
                "Return JSON {\"complete\":true|false,\"reason\":\"...\","
                "\"query_result\":<the visible non-empty string, boolean, integer, "
                "or finite number>}. query_result is required when complete is true "
                "and must be read from the after screenshot.\n"
                f"Requested runtime output slot: {output_slot}\n"
            )
        elif desired_outcome is not None:
            outcome_contract = (
                "The requested result has an explicit direction. Return JSON "
                "{\"complete\":true|false,\"observed_outcome\":<the visible "
                "boolean/string/number>,\"changed\":true|false,"
                "\"reason\":\"...\"}. The observed_outcome must describe the "
                "after screenshot and must not be copied from the request.\n"
                f"Desired observable outcome: {json.dumps(desired_outcome, ensure_ascii=False)}\n"
            )
        else:
            outcome_contract = (
                "Return JSON {\"complete\":true|false,\"reason\":\"...\"}.\n"
            )
        prompt = (
            "Judge whether this GUI capability is visibly complete. "
            "Use only the screenshots and requested capability. "
            f"{outcome_contract}"
            f"Capability: {ref.get('name') or ref.get('ref_id')}\n"
            f"Parameters: {json.dumps(ref.get('params') or {}, ensure_ascii=False)}\n"
            f"Expected page: {ref.get('target_node') or ref.get('node_id')}\n"
            f"Visible success condition: {ref.get('success_predicate') or ''}\n"
            f"Expected effects: {json.dumps(ref.get('effects') or [], ensure_ascii=False)}"
        )
        return self._invoke(prompt, [before, after])

    def verify_final(
        self,
        instruction: Mapping[str, Any],
        observation: Any,
        context: Mapping[str, Any],
    ) -> Dict[str, Any]:
        prompt = (
            "Judge whether the whole GUI instruction is visibly complete. "
            "Return JSON {\"complete\":true|false,\"reason\":\"...\"}.\n"
            f"Instruction: {instruction.get('instruction') or instruction.get('text') or ''}\n"
            f"Completed capability refs: {context.get('completed_refs', [])}"
        )
        return self._invoke(prompt, [observation])

    def _invoke(self, prompt: str, images: Sequence[Any]) -> Dict[str, Any]:
        try:
            images = [_visual_payload(value) for value in images]
            if hasattr(self.agent, "predict_mm"):
                raw = self.agent.predict_mm(prompt, list(images))
            elif callable(self.agent):
                raw = self.agent(prompt, list(images))
            else:
                return {"complete": False, "reason": "verifier agent is not callable"}
            if isinstance(raw, tuple):
                raw = raw[0] if raw else ""
            if isinstance(raw, Mapping):
                return _normalize_verdict(raw)
            text = str(raw or "").strip()
            match = self._JSON_OBJECT.search(text)
            if match:
                text = match.group(0)
            parsed = json.loads(text)
            if not isinstance(parsed, Mapping):
                raise ValueError("completion output is not an object")
            verdict = _normalize_verdict(parsed)
            verdict["raw"] = raw
            return verdict
        except Exception as exc:  # VLM/transport/parse failures must never approve.
            return {"complete": False, "reason": f"verifier failure: {exc}"}


class VLMCollectionWorkflowAgent:
    """Confirm one predicted landing from compact natural-language context."""

    def __init__(self, agent: Any, *, timeout: int = 120) -> None:
        self.agent = agent
        self.timeout = max(1, int(timeout))

    def confirm(
        self,
        *,
        screenshot: Any,
        expected_state: str,
        previous_action: str,
        remaining_route: str,
        recent_steps: Sequence[str],
        next_target: str = "",
        required_region: str = "",
    ) -> Dict[str, Any]:
        recent = "\n".join(
            f"- {step}" for step in list(recent_steps)[-3:]
        ) or "- 无"
        user_prompt = (
            f"框架预计当前位置：\n{expected_state}\n\n"
            f"上一步：\n{previous_action}\n\n"
            f"后续路线：\n{remaining_route}\n\n"
            f"下一步需要执行：\n"
            f"{('点击 ' + next_target) if next_target else '没有下一步'}\n\n"
            f"如果整个 Stage 对不上，只检查下一步需要的区块：\n"
            f"{required_region or '没有可单独复用的区块'}\n\n"
            f"最近操作：\n{recent}\n\n"
            "请看最新截图。时间、计数、普通数据和窗口尺寸变化可以忽略；"
            "主要 Page、主要功能区域、前景菜单或对话框、关键操作按钮冲突时，"
            "不能认为位置一致。"
        )
        system_prompt = (
            "你只确认上一步是否成功到达框架描述的位置。不要重新规划路线，"
            "不要创建新页面身份。只输出 JSON："
            '{"match_scope":"stage|region|none",'
            '"matches_expected":true|false,'
            '"previous_action":"success|no_effect|unexpected",'
            '"reason":"简短截图依据",'
            '"next_click":null或'
            '{"target":"下一步目标","bbox_1000":[x0,y0,x1,y1],'
            '"click_point_1000":[x,y]}}。'
            "只有截图中清楚看到下一步目标时才能给 next_click；坐标使用 0~1000。"
            "match_scope=region 只用于下一步所需区块本身处于当前活动表面且目标可操作；"
            "弹窗后方、变暗背景或仅文字相似的区块必须返回 none。"
        )
        if hasattr(self.agent, "predict_mm_with_policy"):
            raw = self.agent.predict_mm_with_policy(
                user_prompt,
                [screenshot],
                max_attempts=1,
                timeout_seconds=float(self.timeout),
                system_prompt=system_prompt,
            )
        else:
            raw = self.agent.predict_mm(user_prompt, [screenshot])
        if isinstance(raw, tuple):
            raw = raw[0] if raw else ""
        parsed = self.agent.parse_json(raw) if hasattr(
            self.agent, "parse_json") else None
        if not isinstance(parsed, Mapping):
            raise ValueError("workflow Agent did not return a JSON object")
        matches = parsed.get("matches_expected")
        scope = str(parsed.get("match_scope") or (
            "stage" if matches is True else "none"))
        previous = str(parsed.get("previous_action") or "")
        reason = str(parsed.get("reason") or "").strip()
        if scope not in {"stage", "region", "none"} \
                or not isinstance(matches, bool) \
                or matches != (scope == "stage") \
                or previous not in {"success", "no_effect", "unexpected"} \
                or not reason:
            raise ValueError("workflow Agent reply violates the minimal contract")
        if scope == "region" and (not required_region or not next_target):
            raise ValueError("workflow region match has no required next Region")
        next_click = parsed.get("next_click")
        if next_click is not None:
            if not isinstance(next_click, Mapping):
                raise ValueError("workflow next_click is not an object")
            target = str(next_click.get("target") or "").strip()
            bbox = next_click.get("bbox_1000")
            point = next_click.get("click_point_1000")
            if not target or not isinstance(bbox, list) or len(bbox) != 4 \
                    or not isinstance(point, list) or len(point) != 2:
                raise ValueError("workflow next_click is incomplete")
            try:
                bbox = [int(value) for value in bbox]
                point = [int(value) for value in point]
            except (TypeError, ValueError) as exc:
                raise ValueError("workflow next_click coordinates are invalid") from exc
            if not (0 <= bbox[0] < bbox[2] <= 1000
                    and 0 <= bbox[1] < bbox[3] <= 1000
                    and bbox[0] <= point[0] <= bbox[2]
                    and bbox[1] <= point[1] <= bbox[3]):
                raise ValueError("workflow next_click is outside its bbox")
            next_click = {
                "target": target,
                "bbox_1000": bbox,
                "click_point_1000": point,
            }
        return {
            "match_scope": scope,
            "matches_expected": matches,
            "previous_action": previous,
            "reason": reason,
            "next_click": next_click,
        }


def _visual_payload(value: Any) -> Any:
    """Convert an observation/screenshot byte string to a model image payload."""
    if isinstance(value, Mapping) and value.get("screenshot") is not None:
        value = value.get("screenshot")
    if isinstance(value, (bytes, bytearray)):
        try:
            import io
            import numpy as np
            from PIL import Image
            return np.array(Image.open(io.BytesIO(bytes(value))).convert("RGB"))
        except Exception:
            return value
    return value


class VisualCollectionExecutor:
    """Execute capability-backed instructions against independent app graphs.

    Planning minimizes reported GUI action count.  Navigation edge weight is
    ``action_steps`` (default 1); a cross-app switch costs one step; a capability
    action uses its own ``action_steps`` (default 1).  Explicit dependencies and
    fixed instruction order always constrain this optimization.
    """

    def __init__(
        self,
        app_graphs: Mapping[str, Any],
        app_adapters: Mapping[str, LiveVisualAdapter],
        completion_verifier: CompletionVerifier,
        *,
        precondition_resolver: Optional[Callable[..., Any]] = None,
        app_switcher: Optional[Callable[..., Any]] = None,
        max_replans: int = 3,
        max_route_correction_retries: int = 1,
        stop_on_failure: bool = True,
        cleanup_run_resources: bool = True,
        workflow_agent: Any = None,
    ) -> None:
        self.app_graphs = dict(app_graphs)
        self.app_adapters = dict(app_adapters)
        self.completion_verifier = completion_verifier
        self.precondition_resolver = precondition_resolver
        self.app_switcher = app_switcher
        self.max_replans = max(0, int(max_replans))
        self.max_route_correction_retries = max(
            0, int(max_route_correction_retries))
        self.stop_on_failure = bool(stop_on_failure)
        self.cleanup_run_resources = bool(cleanup_run_resources)
        self.workflow_agent = workflow_agent
        self._reset_run_state()

    def execute(
        self,
        instruction: Mapping[str, Any],
        *,
        initial_app_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Discard and recollect a trajectory after any corrected route edge."""
        discarded: List[Dict[str, Any]] = []
        for attempt in range(self.max_route_correction_retries + 1):
            result = self._execute_once(
                instruction, initial_app_id=initial_app_id)
            if not result.get("route_tainted"):
                result["route_collection_attempt"] = attempt + 1
                result["discarded_route_attempts"] = discarded
                return result
            discarded.append({
                "attempt": attempt + 1,
                "final_status": result.get("final_status"),
                "action_steps": result.get("total_action_steps", 0),
                "route_corrections": list(result.get("route_corrections") or []),
            })
        result["success"] = False
        result["scenario_success"] = False
        result["final_status"] = "route_correction_retry_exhausted"
        result["discarded"] = True
        result["trajectory"] = []
        result["graph_provenance"] = []
        result["num_action_events"] = 0
        result["discarded_route_attempts"] = discarded
        return result

    def _execute_once(
        self,
        instruction: Mapping[str, Any],
        *,
        initial_app_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Run one instruction and return an in-memory trajectory result."""
        self._reset_run_state()
        self._instruction = dict(instruction or {})
        raw_refs = self._instruction.get("capability_refs") or []
        if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, (str, bytes)):
            return self._finish("invalid_instruction", final_verification=None)

        default_app = str(self._instruction.get("app_id") or self._instruction.get("app") or "")
        refs = [
            CapabilityExecutionRef.from_mapping(raw, i, default_app)
            for i, raw in enumerate(raw_refs)
            if isinstance(raw, Mapping)
        ]
        validation_error = self._validate_refs(refs)
        if validation_error:
            self._errors.append(validation_error)
            return self._finish("invalid_instruction", final_verification=None)
        self._reserved_query_slots = {
            ref.output_slot for ref in refs if ref.output_slot
        }

        deps, runtime_requirements = self._dependency_model(refs, self._instruction)
        self._runtime_requirements = runtime_requirements
        by_id = {ref.ref_id: ref for ref in refs}
        pending = set(by_id)
        completed: set[str] = set()
        failed: set[str] = set()

        chosen_initial = initial_app_id or self._instruction.get("initial_app_id")
        if chosen_initial:
            ok, reason = self._ensure_app(str(chosen_initial), initial=True)
            if not ok:
                self._errors.append(reason)
                return self._finish("initial_app_failed", final_verification=None)

        while pending:
            ready = [
                by_id[rid]
                for rid in pending
                if deps[rid].issubset(completed)
                and not deps[rid].intersection(failed)
            ]
            if not ready:
                blocked = sorted(pending)
                self._errors.append(f"unresolved dependency cycle or failed dependency: {blocked}")
                for rid in blocked:
                    self._ref_results.append(
                        {"ref_id": rid, "status": "blocked_dependency", "committed": False}
                    )
                failed.update(blocked)
                self._failed_refs.extend(blocked)
                pending.clear()
                break

            ref = min(ready, key=self._candidate_sort_key)
            pending.remove(ref.ref_id)
            bound_ref, binding_reason = self._bind_runtime_ref(ref)
            if bound_ref is None:
                outcome = {
                    "ref_id": ref.ref_id,
                    "app_id": ref.app_id,
                    "node_id": ref.node_id,
                    "target_node": ref.target_node,
                    "committed": False,
                    "status": "runtime_binding_failed",
                    "reason": binding_reason,
                    "route_provenance": [],
                }
            else:
                outcome = self._execute_ref(bound_ref)
            self._ref_results.append(outcome)
            if outcome.get("committed"):
                completed.add(ref.ref_id)
                self._completed_refs.append(ref.ref_id)
            else:
                failed.add(ref.ref_id)
                self._failed_refs.append(ref.ref_id)
                if self.stop_on_failure:
                    for rid in sorted(pending):
                        self._ref_results.append(
                            {"ref_id": rid, "status": "not_attempted", "committed": False}
                        )
                    failed.update(pending)
                    self._failed_refs.extend(sorted(pending))
                    pending.clear()
                    break

        # Preserve execution order for later verifier/precondition context.
        self._completed_refs = list(dict.fromkeys(self._completed_refs))
        self._failed_refs = list(dict.fromkeys(self._failed_refs))
        final_obs = None
        if self._current_app and self._current_app in self.app_adapters:
            try:
                final_obs = self._capture(self._current_app)
                self._observations[self._current_app] = final_obs
                node = self._workflow_confirmed_nodes.get(self._current_app)
                if not node:
                    node = self._identify(self._current_app, final_obs)
                if node:
                    self._nodes[self._current_app] = node
            except Exception as exc:
                self._errors.append(f"final capture failed: {exc}")

        final_verdict = self._verify_final(final_obs)
        all_refs_committed = len(completed) == len(refs) and not failed
        success = all_refs_committed and bool(final_verdict.get("complete"))
        if success:
            status = "complete"
        elif failed:
            status = "capability_failed"
        else:
            status = "final_verification_failed"
        return self._finish(status, final_verification=final_verdict, success=success)

    def run(
        self,
        instruction: Mapping[str, Any],
        *,
        initial_app_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Compatibility spelling for callers that treat executors as runners."""
        return self.execute(instruction, initial_app_id=initial_app_id)

    # -- normalization / dependency model ---------------------------------

    def _validate_refs(self, refs: Sequence[CapabilityExecutionRef]) -> str:
        if not refs:
            return "instruction has no capability refs"
        ids = [ref.ref_id for ref in refs]
        if len(ids) != len(set(ids)):
            return "capability ref ids must be unique"
        producers: Dict[str, CapabilityExecutionRef] = {}
        for ref in refs:
            if not ref.app_id:
                return f"capability ref {ref.ref_id!r} has no app_id"
            if not ref.node_id:
                return f"capability ref {ref.ref_id!r} has no node_id"
            if ref.app_id not in self.app_graphs:
                return f"capability ref {ref.ref_id!r} names unknown graph {ref.app_id!r}"
            if ref.app_id not in self.app_adapters:
                return f"capability ref {ref.ref_id!r} names unknown adapter {ref.app_id!r}"
            if "output_slot" in ref.raw and not isinstance(
                    ref.raw.get("output_slot"), str):
                return f"capability ref {ref.ref_id!r} has non-string output_slot"
            if ref.output_slot:
                if not re.fullmatch(r"[a-z][a-z0-9_]*", ref.output_slot):
                    return f"capability ref {ref.ref_id!r} has invalid output_slot"
                if ref.output_slot in producers:
                    return f"runtime output_slot {ref.output_slot!r} has multiple producers"
                producers[ref.output_slot] = ref
            runtime_types = ref.raw.get("runtime_param_types")
            if runtime_types is not None and not isinstance(runtime_types, Mapping):
                return f"capability ref {ref.ref_id!r} has invalid runtime_param_types"
            if isinstance(runtime_types, Mapping):
                for name, expected in runtime_types.items():
                    if name not in ref.params or expected not in {
                            "string", "number", "boolean"}:
                        return f"capability ref {ref.ref_id!r} has invalid runtime parameter type"

        for ref in refs:
            for name, value in ref.params.items():
                if isinstance(value, Mapping) and "from_slot" in value:
                    if set(value) != {"from_slot"}:
                        return f"runtime parameter {name!r} has invalid token shape"
                    slot = value.get("from_slot")
                    if not isinstance(slot, str) or not slot.strip():
                        return f"runtime parameter {name!r} has empty from_slot"
                    producer = producers.get(slot)
                    if producer is None:
                        return f"runtime parameter {name!r} names unknown output_slot {slot!r}"
                    if producer.ref_id == ref.ref_id or producer.ref_id not in ref.depends_on:
                        return (
                            f"runtime parameter {name!r} must depend_on producer "
                            f"{producer.ref_id!r}"
                        )
        return ""

    def _bind_runtime_ref(
        self, ref: CapabilityExecutionRef,
    ) -> Tuple[Optional[CapabilityExecutionRef], str]:
        params: Dict[str, Any] = {}
        for name, value in ref.params.items():
            if isinstance(value, Mapping) and "from_slot" in value:
                slot = str(value.get("from_slot") or "").strip()
                if slot not in self._blackboard:
                    return None, f"runtime slot {slot!r} is missing"
                value = self._blackboard[slot]
                if not _is_runtime_scalar(value):
                    return None, f"runtime slot {slot!r} has invalid scalar value"
            params[str(name)] = value

        runtime_types = ref.raw.get("runtime_param_types") or {}
        if isinstance(runtime_types, Mapping):
            for name, expected in runtime_types.items():
                value = params.get(str(name))
                if not _matches_runtime_type(value, expected):
                    return None, (
                        f"runtime parameter {name!r} does not match {expected!r}"
                    )

        raw = dict(ref.raw)
        raw["params"] = dict(params)
        slot = raw.get("slot")
        if isinstance(slot, str) and slot in params:
            raw["value"] = params[slot]
            raw["runtime"] = False
        return replace(ref, params=params, raw=raw), ""

    def _bind_output_slot(
        self, ref: CapabilityExecutionRef, verdict: Mapping[str, Any],
    ) -> Dict[str, Any]:
        result = dict(verdict)
        if not ref.output_slot or not result.get("complete"):
            return result
        value = result.get("query_result")
        if not _is_runtime_scalar(value):
            result["complete"] = False
            result["reason"] = (
                f"runtime output_slot {ref.output_slot!r} requires a non-empty scalar query_result"
            )
            return result
        self._blackboard[ref.output_slot] = value
        return result

    def _dependency_model(
        self,
        refs: Sequence[CapabilityExecutionRef],
        instruction: Mapping[str, Any],
    ) -> Tuple[Dict[str, set[str]], Dict[str, List[Any]]]:
        known = {ref.ref_id for ref in refs}
        deps = {ref.ref_id: set(ref.depends_on).intersection(known) for ref in refs}
        runtime: Dict[str, List[Any]] = {ref.ref_id: [] for ref in refs}

        for ref in refs:
            for requirement in ref.requires:
                dependency = _requirement_dependency(requirement, known)
                if dependency:
                    deps[ref.ref_id].add(dependency)
                else:
                    runtime[ref.ref_id].append(requirement)

        order = instruction.get("dependency_order") or []
        if isinstance(order, str):
            order = [order]
        if instruction.get("fixed_order") or instruction.get("ordered") or instruction.get("preserve_order"):
            order = [ref.ref_id for ref in refs]
        if isinstance(order, Sequence):
            order_ids = [str(v) for v in order if str(v) in known]
            for before, after in zip(order_ids, order_ids[1:]):
                deps[after].add(before)

        explicit = instruction.get("dependencies") or []
        if isinstance(explicit, Mapping):
            explicit = [explicit]
        for relation in explicit if isinstance(explicit, Sequence) else []:
            if not isinstance(relation, Mapping):
                continue
            before = str(relation.get("before") or relation.get("requires") or "")
            after = str(relation.get("after") or relation.get("ref_id") or "")
            if before in known and after in known:
                deps[after].add(before)
        return deps, runtime

    # -- scheduling ---------------------------------------------------------

    def _candidate_sort_key(self, ref: CapabilityExecutionRef) -> Tuple[float, str]:
        switch_cost = 1 if self._current_app and self._current_app != ref.app_id else 0
        source = self._nodes.get(ref.app_id) or self._adapter_node_hint(ref.app_id)
        route_cost = min(
            (
                cost for cost in (
                    self._route_cost(ref.app_id, source, node_id)
                    for node_id in self._entry_nodes(ref)
                ) if cost is not None
            ),
            default=math.inf,
        )
        prerequisite_cost = _estimated_precondition_steps(ref, self._blackboard)
        return (
            switch_cost + route_cost + prerequisite_cost + ref.action_steps,
            ref.ref_id,
        )

    def _adapter_node_hint(self, app_id: str) -> Optional[str]:
        adapter = self.app_adapters[app_id]
        for attr in ("current_node", "current_node_id", "initial_node_id", "start_node"):
            value = getattr(adapter, attr, None)
            if callable(value):
                try:
                    value = value()
                except Exception:
                    value = None
            if value:
                return str(value)
        graph = self._graph(app_id)
        roots = [node for node in graph.nodes if graph.in_degree(node) == 0]
        if len(roots) == 1:
            return str(roots[0])
        return None

    def _entry_nodes(self, ref: CapabilityExecutionRef) -> List[str]:
        graph = self._graph(ref.app_id)
        nodes = [ref.node_id]
        surfaces = ref.raw.get("entry_surfaces") or []
        if isinstance(surfaces, Mapping):
            surfaces = [surfaces]
        if isinstance(surfaces, Sequence) and not isinstance(
                surfaces, (str, bytes)):
            for surface in surfaces:
                if not isinstance(surface, Mapping):
                    continue
                state_id = str(surface.get("state_id") or "").strip()
                if state_id:
                    nodes.append(state_id)
        valid = [
            node_id for node_id in dict.fromkeys(nodes)
            if node_id and node_id in graph
        ]
        return valid or [ref.node_id]

    def _nearest_entry_node(self, ref: CapabilityExecutionRef) -> str:
        source = self._nodes.get(ref.app_id) or self._adapter_node_hint(ref.app_id)
        ranked = []
        for index, node_id in enumerate(self._entry_nodes(ref)):
            cost = self._route_cost(ref.app_id, source, node_id)
            if cost is not None:
                ranked.append((cost, index, node_id))
        return min(ranked)[2] if ranked else ref.node_id

    def _state_description(self, app_id: str, state_id: str) -> str:
        graph = self._graph(app_id)
        node = graph.nodes[state_id] if state_id in graph else {}
        page = str(node.get("page_name") or state_id).strip()
        blocks = [
            block for block in (node.get("semantic_blocks") or [])
            if isinstance(block, Mapping)
        ]
        content = [
            block for block in blocks
            if "navigation" not in str(block.get("role") or "").casefold()
        ] or blocks
        descriptions = []
        for block in content[:2]:
            role = " ".join(str(
                block.get("role") or block.get("name") or "界面区域"
            ).split())
            names = [
                " ".join(str(value).split())
                for value in (block.get("element_names") or [])
                if str(value).strip()
            ][:4]
            if names:
                descriptions.append(f"{role} 有 {'、'.join(names)}")
        suffix = f"；{'；'.join(descriptions)}" if descriptions else ""
        return f"{state_id}，{page} 页面{suffix}"

    @staticmethod
    def _natural_action_label(value: Any) -> str:
        label = " ".join(str(value or "").split())
        return re.sub(r"^(?:click|tap)\s+", "", label, flags=re.I)

    @staticmethod
    def _workflow_target_key(value: Any) -> str:
        return re.sub(
            r"[^0-9a-z\u4e00-\u9fff]+", "",
            str(value or "").casefold())

    def _effect_state_id(self, ref: CapabilityExecutionRef) -> str:
        graph = self._graph(ref.app_id)
        found = []
        for effect in ref.raw.get("effects") or []:
            if not isinstance(effect, Mapping):
                continue
            for change in effect.get("changes") or []:
                if not isinstance(change, Mapping):
                    continue
                scope = change.get("scope") or {}
                state_id = str(
                    scope.get("state_id") if isinstance(scope, Mapping)
                    else ""
                ).strip()
                if state_id and state_id in graph:
                    found.append(state_id)
        unique = list(dict.fromkeys(found))
        return unique[0] if len(unique) == 1 else ""

    def _remaining_route_text(
        self,
        app_id: str,
        hops: Sequence[_RouteHop],
        final_step: Optional[Tuple[str, str]] = None,
    ) -> str:
        lines = []
        for hop in hops:
            label = self._natural_action_label(
                hop.edge.get("element_label")
                or hop.edge.get("semantic_description")
                or hop.edge.get("action"))
            lines.append(
                f"点击 {label}，预计到达 "
                f"{self._state_description(app_id, hop.target)}。")
        if final_step and final_step[1]:
            lines.append(
                f"点击 {self._natural_action_label(final_step[0])}，预计到达 "
                f"{self._state_description(app_id, final_step[1])}。")
        if not lines:
            return "没有后续动作。"
        return "\n".join(
            f"{index}. {line}" for index, line in enumerate(lines, 1))

    def _next_route_target(
        self,
        hops: Sequence[_RouteHop],
        final_step: Optional[Tuple[str, str]] = None,
    ) -> str:
        if hops:
            edge = hops[0].edge
            return self._natural_action_label(
                edge.get("element_label")
                or edge.get("semantic_description")
                or edge.get("action"))
        if final_step:
            return self._natural_action_label(final_step[0])
        return ""

    def _next_required_region(
        self, app_id: str, hops: Sequence[_RouteHop],
    ) -> str:
        if not hops:
            return ""
        hop = hops[0]
        region_ref = str(hop.edge.get("region") or "").strip()
        if not region_ref:
            return ""
        graph = self._graph(app_id)
        node = graph.nodes[hop.source] if hop.source in graph else {}
        matched = None
        for block in node.get("semantic_blocks") or []:
            if not isinstance(block, Mapping):
                continue
            if region_ref in {
                str(block.get("region_id") or ""),
                str(block.get("role") or ""),
            }:
                matched = block
                break
        if matched is None:
            return ""
        role = " ".join(str(
            matched.get("role") or region_ref).split())
        names = [
            " ".join(str(value).split())
            for value in (matched.get("element_names") or [])
            if str(value).strip()
        ][:6]
        controls = f"，包含 {'、'.join(names)}" if names else ""
        return f"{region_ref}，{role}{controls}"

    def _confirm_workflow_landing(
        self,
        *,
        app_id: str,
        source: str,
        target: str,
        action_label: str,
        observation: Any,
        remaining_route: str,
        next_target: str,
        required_region: str,
    ) -> Dict[str, Any]:
        if self.workflow_agent is None:
            return {}
        screenshot = observation.get("screenshot") if isinstance(
            observation, Mapping) else observation
        try:
            result = self.workflow_agent.confirm(
                screenshot=screenshot,
                expected_state=self._state_description(app_id, target),
                previous_action=(
                    f"从 {source} 点击 "
                    f"{self._natural_action_label(action_label)}，预计到达 {target}。"
                ),
                remaining_route=remaining_route,
                recent_steps=list(self._workflow_recent_steps[-3:]),
                next_target=next_target,
                required_region=required_region,
            )
        except Exception as exc:
            return {
                "matches_expected": False,
                "previous_action": "unexpected",
                "reason": f"workflow Agent unavailable: {exc}",
            }
        return dict(result) if isinstance(result, Mapping) else {}

    @staticmethod
    def _workflow_accepts(decision: Mapping[str, Any]) -> bool:
        return (
            str(decision.get("match_scope") or "stage") == "stage"
            and decision.get("matches_expected") is True
            and str(decision.get("previous_action") or "") == "success"
            and bool(str(decision.get("reason") or "").strip())
        )

    @staticmethod
    def _workflow_accepts_region(
        decision: Mapping[str, Any], *, required_region: str,
        next_target: str,
    ) -> bool:
        click = decision.get("next_click")
        return (
            bool(required_region)
            and bool(next_target)
            and str(decision.get("match_scope") or "") == "region"
            and decision.get("matches_expected") is False
            and str(decision.get("previous_action") or "") == "success"
            and bool(str(decision.get("reason") or "").strip())
            and isinstance(click, Mapping)
            and VisualCollectionExecutor._workflow_target_key(
                click.get("target"))
            == VisualCollectionExecutor._workflow_target_key(next_target)
        )

    # -- ref execution ------------------------------------------------------

    def _execute_ref(self, ref: CapabilityExecutionRef) -> Dict[str, Any]:
        self._workflow_final_verdict = {}
        result: Dict[str, Any] = {
            "ref_id": ref.ref_id,
            "app_id": ref.app_id,
            "node_id": ref.node_id,
            "target_node": ref.target_node,
            "committed": False,
            "status": "started",
            "route_provenance": [],
        }

        if _ref_crosses_login_boundary(ref):
            result.update(
                status="needs_user",
                reason="application login/sign-in requires user input",
            )
            return result

        ok, reason = self._ensure_app(ref.app_id)
        if not ok:
            result.update(status="app_switch_failed", reason=reason)
            self._errors.append(reason)
            return result

        entry_node = self._nearest_entry_node(ref)
        result["entry_node"] = entry_node
        effect_state = self._effect_state_id(ref)
        recipe = ref.raw.get("execution_recipe") or []
        recipe_step = recipe[0] if isinstance(recipe, list) and recipe \
            and isinstance(recipe[0], Mapping) else {}
        selector = recipe_step.get("selector") or {} \
            if isinstance(recipe_step, Mapping) else {}
        final_action_label = str(
            (selector.get("element_label") or "")
            if isinstance(selector, Mapping)
            else ""
        ) or str(ref.raw.get("action") or ref.name)
        final_step = (
            (final_action_label, effect_state) if effect_state else None)

        # Prefer checking gates on the capability entry surface.  If that
        # surface is currently unreachable (for example an alarm-populated list
        # while the list is empty), resolve the prerequisite from the current
        # surface first, then replan.  This handles both target-local Unlock
        # gates and resource-creation gates without hard-coding app semantics.
        route_ok, route_reason, provenance = self._route_to(
            ref.app_id, entry_node, final_step=final_step)
        result["route_provenance"] = provenance
        if not route_ok:
            if not self._runtime_requirements.get(ref.ref_id):
                result.update(status="route_failed", reason=route_reason)
                self._errors.append(route_reason)
                return result

        precondition = self._resolve_preconditions(ref)
        result["preconditions"] = precondition
        if not precondition["satisfied"]:
            result.update(status="skipped_precondition", reason=precondition.get("reason", ""))
            return result

        current_after_gate = self._nodes.get(ref.app_id)
        if not route_ok or current_after_gate != entry_node:
            retry_ok, retry_reason, retry_provenance = self._route_to(
                ref.app_id, entry_node, final_step=final_step)
            result["route_provenance"] = list(provenance) + list(retry_provenance)
            if not retry_ok:
                result.update(status="route_failed", reason=retry_reason)
                self._errors.append(retry_reason)
                return result

        before = self._capture(ref.app_id)
        before_node = self._workflow_confirmed_nodes.get(ref.app_id)
        if not before_node:
            before_node = self._identify(ref.app_id, before)
        if before_node != entry_node:
            result.update(
                status="entry_identity_failed",
                reason=f"expected entry {entry_node!r}, identified {before_node!r}",
            )
            return result

        if precondition.get("skip_capability") or ref.action_steps == 0:
            after = before
            landed = before_node
            verdict = self._bind_output_slot(
                ref, self._verify_ref(ref, before, after))
            result["verification"] = verdict
            if verdict.get("complete"):
                result.update(
                    status="completed_precondition_skip",
                    committed=True,
                    arrived_node=landed,
                )
            else:
                result.update(status="ref_verification_failed", reason=verdict.get("reason", ""))
            return result

        capability_ref = ref.to_dict()
        capability_ref["node_id"] = entry_node
        action_spec = {
            "kind": "capability",
            "app_id": ref.app_id,
            "ref_id": ref.ref_id,
            "name": ref.name,
            "params": dict(ref.params),
            "capability_ref": capability_ref,
        }
        provenance = {
            "kind": "capability",
            "graph_app_id": ref.app_id,
            "capability_ref_id": ref.ref_id,
            "entry_node": entry_node,
            "target_node": ref.target_node,
        }
        step = self._perform_action(
            ref.app_id,
            action_spec,
            action_steps=ref.action_steps,
            expected_source=entry_node,
            provenance=provenance,
            workflow_expected_landing=effect_state,
            workflow_action_label=final_action_label,
            workflow_remaining_route="没有后续动作。",
        )
        result["trajectory_step"] = step.get("step")
        if not step["executed"]:
            result.update(status=step["status"], reason=step.get("reason", ""))
            return result

        landed = step.get("arrived_node")
        if not landed:
            result.update(status="unknown_landing", reason="capability landing could not be identified")
            return result
        if ref.target_node and landed != ref.target_node:
            result.update(
                status="target_landing_failed",
                reason=f"expected {ref.target_node!r}, identified {landed!r}",
            )
            return result

        workflow_review = self._trajectory[step["step"]].get(
            "workflow_review") or {}
        if (not ref.output_slot
                and ref.desired_outcome is None
                and effect_state and landed == effect_state
                and self._workflow_accepts(workflow_review)):
            verdict = {
                "complete": True,
                "reason": str(workflow_review.get("reason") or ""),
                "workflow_confirmed_state": effect_state,
            }
            self._workflow_final_verdict = dict(verdict)
        else:
            verdict = self._verify_ref(ref, step["before"], step["after"])
        verdict = self._bind_output_slot(ref, verdict)
        result["verification"] = verdict
        trace_step = self._trajectory[step["step"]]
        trace_step["ref_id"] = ref.ref_id
        trace_step["verification"] = verdict
        if ref.desired_outcome is not None:
            effect = {
                "desired_outcome": ref.desired_outcome,
                "observed_outcome": verdict.get("observed_outcome"),
            }
            if isinstance(verdict.get("changed"), bool):
                effect["had_effect"] = verdict["changed"]
            trace_step["effect"] = effect
        if not verdict.get("complete"):
            trace_step["committed"] = False
            result.update(status="ref_verification_failed", reason=verdict.get("reason", ""))
            return result

        trace_step["committed"] = True
        result.update(status="complete", committed=True, arrived_node=landed)
        return result

    def _resolve_preconditions(self, ref: CapabilityExecutionRef) -> Dict[str, Any]:
        requirements = self._runtime_requirements.get(ref.ref_id, [])
        if not requirements:
            return {"satisfied": True, "skip_capability": False, "evidence": []}
        if self.precondition_resolver is None:
            return {
                "satisfied": False,
                "skip_capability": False,
                "reason": "runtime precondition resolver is not configured",
                "evidence": [],
            }

        evidence: List[Any] = []
        skip = False
        for requirement in requirements:
            context = self._runtime_context(ref)
            try:
                resolver = self.precondition_resolver
                if not callable(resolver) and callable(getattr(resolver, "resolve", None)):
                    # Direct compatibility with PrerequisiteRuntime, whose public
                    # resolve boundary consumes a sequence and returns a report.
                    raw = _call_compatible(resolver.resolve, [requirement])
                else:
                    raw = _call_compatible(resolver, requirement, ref.to_dict(), context)
            except Exception as exc:
                return {
                    "satisfied": False,
                    "skip_capability": False,
                    "reason": f"precondition resolver failed: {exc}",
                    "evidence": evidence,
                }
            decision = _normalize_precondition(raw)
            evidence.append(decision.evidence)
            if decision.action_steps or decision.action_events:
                self._total_action_steps += decision.action_steps
                if decision.action_events:
                    for raw_event in decision.action_events:
                        event = dict(raw_event)
                        event.update({
                            "step": len(self._trajectory),
                            "kind": "precondition",
                            "app_id": ref.app_id,
                            "ref_id": ref.ref_id,
                            "requirement": requirement,
                            "committed": bool(
                                event.get("committed", decision.satisfied)),
                            "evidence": event.get(
                                "evidence", decision.evidence),
                            "graph_provenance": {
                                "kind": "precondition",
                                "graph_app_id": ref.app_id,
                                "capability_ref_id": ref.ref_id,
                                "prerequisite_id": event.get(
                                    "prerequisite_id", ""),
                            },
                        })
                        self._trajectory.append(event)
                else:
                    # Backward-compatible aggregate for custom resolvers that
                    # report only a total. VisualPrerequisiteAgent emits one
                    # concrete event per grounded GUI primitive.
                    self._trajectory.append(
                        {
                            "step": len(self._trajectory),
                            "kind": "precondition",
                            "app_id": ref.app_id,
                            "ref_id": ref.ref_id,
                            "requirement": requirement,
                            "action_steps": decision.action_steps,
                            "committed": decision.satisfied,
                            "evidence": decision.evidence,
                            "graph_provenance": {
                                "kind": "precondition",
                                "graph_app_id": ref.app_id,
                                "capability_ref_id": ref.ref_id,
                            },
                        }
                    )
            reserved = sorted(
                set(decision.bindings).intersection(self._reserved_query_slots))
            if reserved:
                return {
                    "satisfied": False,
                    "skip_capability": False,
                    "reason": (
                        "precondition attempted reserved query slot "
                        f"{reserved[0]!r}"
                    ),
                    "evidence": evidence,
                }
            if decision.bindings:
                self._blackboard.update(decision.bindings)
            if not decision.satisfied:
                return {
                    "satisfied": False,
                    "skip_capability": False,
                    "reason": decision.reason or f"unsatisfied precondition: {requirement!r}",
                    "evidence": evidence,
                }
            skip = skip or decision.skip_capability

        # A resolver may have changed the live surface while satisfying a gate.
        observation = self._capture(ref.app_id)
        node = self._identify(ref.app_id, observation)
        self._observations[ref.app_id] = observation
        if node:
            self._nodes[ref.app_id] = node
        return {"satisfied": True, "skip_capability": skip, "evidence": evidence}

    # -- app boundary -------------------------------------------------------

    def _ensure_app(self, app_id: str, initial: bool = False) -> Tuple[bool, str]:
        if app_id not in self.app_adapters:
            return False, f"no adapter for app {app_id!r}"
        if self._current_app == app_id and app_id in self._observations:
            return True, ""

        adapter = self.app_adapters[app_id]
        from_app = self._current_app
        is_switch = from_app is not None and from_app != app_id
        try:
            activation_result = None
            if is_switch and self.app_switcher is not None:
                activation_result = _call_compatible(
                    self.app_switcher, from_app, app_id, adapter
                )
            else:
                activate = getattr(adapter, "activate", None)
                if callable(activate):
                    activation_result = _call_compatible(activate)
                else:
                    switch_to = getattr(adapter, "switch_to", None)
                    if callable(switch_to):
                        activation_result = _call_compatible(switch_to, app_id)
            settle = getattr(adapter, "settle", None)
            if callable(settle) and activation_result is not None:
                _call_compatible(settle, activation_result)
            observation = self._capture(app_id)
            node = self._identify(app_id, observation)
        except Exception as exc:
            return False, f"failed to activate {app_id!r}: {exc}"

        self._current_app = app_id
        self._observations[app_id] = observation
        if node:
            self._nodes[app_id] = node
            if self.workflow_agent is not None:
                self._workflow_confirmed_nodes[app_id] = node
        if is_switch:
            self._app_switches += 1
            self._total_action_steps += 1
            self._trajectory.append(
                {
                    "step": len(self._trajectory),
                    "kind": "app_switch",
                    "from_app": from_app,
                    "app_id": app_id,
                    "action_steps": 1,
                    "arrived_node_id": node,
                    "observation_after": observation,
                    "committed": bool(node),
                    "graph_provenance": {
                        "kind": "cross_app_boundary",
                        "source_app_id": from_app,
                        "target_app_id": app_id,
                        "graphs_merged": False,
                    },
                }
            )
        if node is None:
            return False, f"activated {app_id!r}, but page identity is unknown"
        return True, ""

    # -- graph planning / route execution ----------------------------------

    def _graph(self, app_id: str) -> nx.Graph:
        graph = self.app_graphs[app_id]
        route_view = getattr(graph, "routing_graph", None)
        if route_view is not None:
            return route_view() if callable(route_view) else route_view
        return graph.graph if hasattr(graph, "graph") and not isinstance(graph, nx.Graph) else graph

    def _route_cost(self, app_id: str, source: Optional[str], target: str) -> Optional[int]:
        if not source or not target:
            return None
        if source == target:
            return 0
        graph = self._graph(app_id)
        try:
            return int(nx.shortest_path_length(graph, source, target, weight=_edge_weight))
        except (nx.NetworkXNoPath, nx.NodeNotFound, TypeError, ValueError):
            return None

    def _plan_route(self, app_id: str, source: str, target: str) -> Optional[List[_RouteHop]]:
        if source == target:
            return []
        graph = self._graph(app_id)
        try:
            nodes = nx.shortest_path(graph, source, target, weight=_edge_weight)
        except (nx.NetworkXNoPath, nx.NodeNotFound, TypeError, ValueError):
            return None
        hops: List[_RouteHop] = []
        for src, dst in zip(nodes, nodes[1:]):
            key, edge = _select_edge(graph, src, dst)
            hops.append(
                _RouteHop(
                    source=str(src),
                    target=str(dst),
                    edge_key=key,
                    edge=dict(edge),
                    action_steps=_action_steps(edge, default=1),
                )
            )
        return hops

    def _route_to(
        self,
        app_id: str,
        target: str,
        *,
        final_step: Optional[Tuple[str, str]] = None,
    ) -> Tuple[bool, str, List[Dict[str, Any]]]:
        provenance: List[Dict[str, Any]] = []
        deviations = 0
        while True:
            observation = self._capture(app_id)
            current = self._workflow_confirmed_nodes.get(app_id)
            if not current:
                current = self._identify(app_id, observation)
            self._observations[app_id] = observation
            if not current:
                return False, f"cannot identify current page in app {app_id!r}", provenance
            self._nodes[app_id] = current
            if current == target:
                return True, "", provenance
            route = self._plan_route(app_id, current, target)
            if route is None:
                return False, f"no verified graph path {current!r} -> {target!r} in {app_id!r}", provenance

            replanning = False
            for hop_index, hop in enumerate(route):
                action_spec = {
                    "kind": "graph_edge",
                    "app_id": app_id,
                    "source_node": hop.source,
                    "target_node": hop.target,
                    "edge_key": hop.edge_key,
                    "edge": dict(hop.edge),
                }
                edge_provenance = {
                    "kind": "graph_edge",
                    "graph_app_id": app_id,
                    "source_node": hop.source,
                    "target_node": hop.target,
                    "edge_key": hop.edge_key,
                    "edge": dict(hop.edge),
                }
                step = self._perform_action(
                    app_id,
                    action_spec,
                    action_steps=hop.action_steps,
                    expected_source=hop.source,
                    provenance=edge_provenance,
                    workflow_expected_landing=hop.target,
                    workflow_action_label=(
                        hop.edge.get("element_label")
                        or hop.edge.get("semantic_description")
                        or hop.edge.get("action")),
                    workflow_remaining_route=self._remaining_route_text(
                        app_id, route[hop_index + 1:], final_step),
                    workflow_next_target=self._next_route_target(
                        route[hop_index + 1:], final_step),
                    workflow_required_region=self._next_required_region(
                        app_id, route[hop_index + 1:]),
                )
                record = {
                    "source": hop.source,
                    "planned_target": hop.target,
                    "arrived_node": step.get("arrived_node"),
                    "action_steps": hop.action_steps if step.get("executed") else 0,
                    "committed": False,
                    "trajectory_step": step.get("step"),
                    "edge": dict(hop.edge),
                    "region_only": bool(step.get("region_only")),
                }
                provenance.append(record)
                if not step["executed"]:
                    if step.get("status") == "source_derailed" and step.get("arrived_node"):
                        deviations += 1
                        if deviations > self.max_replans:
                            return False, "route replan budget exhausted before action", provenance
                        self._nodes[app_id] = str(step["arrived_node"])
                        replanning = True
                        break
                    return False, step.get("reason") or step["status"], provenance
                if step.get("region_only"):
                    if hop_index + 1 >= len(route):
                        return False, (
                            "region-only landing did not reenter a known State"
                        ), provenance
                    self._trajectory[step["step"]]["committed"] = True
                    record["committed"] = True
                    continue
                landed = step.get("arrived_node")
                if landed == hop.target:
                    self._trajectory[step["step"]]["committed"] = True
                    record["committed"] = True
                    continue
                deviations += 1
                if not landed:
                    return False, "route landing identity is unknown", provenance
                self._route_tainted = True
                correction = self._record_route_correction(
                    app_id, hop, str(landed),
                    str(step.get("source_arrival_context") or ""))
                self._route_corrections.append(correction)
                if deviations > self.max_replans:
                    return False, f"route replan budget exhausted at {landed!r}", provenance
                self._nodes[app_id] = landed
                replanning = True
                break
            if not replanning:
                return True, "", provenance

    # -- live single-action transaction ------------------------------------

    def _perform_action(
        self,
        app_id: str,
        action_spec: Mapping[str, Any],
        *,
        action_steps: int,
        expected_source: Optional[str],
        provenance: Mapping[str, Any],
        workflow_expected_landing: str = "",
        workflow_action_label: Any = "",
        workflow_remaining_route: str = "没有后续动作。",
        workflow_next_target: str = "",
        workflow_required_region: str = "",
    ) -> Dict[str, Any]:
        adapter = self.app_adapters[app_id]
        source_region_only = False
        try:
            before = self._capture(app_id)
            source = self._workflow_confirmed_nodes.get(app_id)
            region_context = self._workflow_region_only.get(app_id) or {}
            if (not source
                    and region_context.get("planned_state") == expected_source
                    and app_id in self._workflow_next_clicks):
                source = expected_source
                source_region_only = True
            if not source:
                source = self._identify(app_id, before)
        except Exception as exc:
            return {"executed": False, "status": "capture_failed", "reason": str(exc)}
        if not source:
            return {
                "executed": False,
                "status": "source_identity_failed",
                "reason": "source page identity is unknown",
            }
        if expected_source and source != expected_source:
            return {
                "executed": False,
                "status": "source_derailed",
                "reason": f"expected source {expected_source!r}, identified {source!r}",
                "arrived_node": source,
            }

        source_arrival_context = self._arrival_sources.get(app_id, "")
        try:
            grounded = None
            prepared_click = self._workflow_next_clicks.pop(app_id, None)
            workflow_ground = getattr(adapter, "ground_workflow_click", None)
            planned_target = self._natural_action_label(workflow_action_label)
            capability = action_spec.get("capability_ref") or {}
            workflow_safe = action_spec.get("kind") == "graph_edge" or (
                action_spec.get("kind") == "capability"
                and isinstance(capability, Mapping)
                and str(capability.get("verification_level") or "") in {
                    "effect_verified", "composable"}
                and str(capability.get("risk_level") or "normal")
                in {"normal", "safe"}
            )
            if (workflow_safe and isinstance(prepared_click, Mapping)
                    and callable(workflow_ground)
                    and self._workflow_target_key(
                        prepared_click.get("target")) == self._workflow_target_key(
                        planned_target)):
                grounded = _call_compatible(
                    workflow_ground, planned_target,
                    {"next_click": dict(prepared_click)}, before)
            if grounded is None:
                grounded = _call_compatible(adapter.ground, action_spec, before)
        except Exception as exc:
            return {"executed": False, "status": "grounding_failed", "reason": str(exc)}
        if grounded is None:
            return {
                "executed": False,
                "status": "grounding_failed",
                "reason": "adapter returned no grounded action",
            }

        execution_result = None
        execution_completed = False
        try:
            execution_result = _call_compatible(adapter.execute, grounded)
            execution_completed = True
            settle = getattr(adapter, "settle", None)
            if callable(settle):
                _call_compatible(settle, execution_result)
            after = self._capture(app_id)
            workflow_decision = self._confirm_workflow_landing(
                app_id=app_id,
                source=str(source or ""),
                target=workflow_expected_landing,
                action_label=workflow_action_label,
                observation=after,
                remaining_route=workflow_remaining_route,
                next_target=workflow_next_target,
                required_region=workflow_required_region,
            ) if workflow_expected_landing else {}
            if workflow_expected_landing and self._workflow_accepts(
                    workflow_decision):
                arrived = workflow_expected_landing
                self._workflow_confirmed_nodes[app_id] = arrived
                self._workflow_region_only.pop(app_id, None)
                next_click = workflow_decision.get("next_click")
                if (workflow_next_target and isinstance(next_click, Mapping)
                        and self._workflow_target_key(
                            next_click.get("target")) == self._workflow_target_key(
                            workflow_next_target)):
                    self._workflow_next_clicks[app_id] = dict(next_click)
                region_only_match = False
            elif (workflow_expected_landing
                  and not self._workflow_region_only.get(app_id)
                  and self._workflow_accepts_region(
                      workflow_decision,
                      required_region=workflow_required_region,
                      next_target=workflow_next_target)):
                arrived = None
                region_only_match = True
                self._workflow_confirmed_nodes.pop(app_id, None)
                self._workflow_region_only[app_id] = {
                    "planned_state": workflow_expected_landing,
                    "region": workflow_required_region,
                }
                self._workflow_next_clicks[app_id] = dict(
                    workflow_decision["next_click"])
            else:
                region_only_match = False
                self._workflow_confirmed_nodes.pop(app_id, None)
                self._workflow_next_clicks.pop(app_id, None)
                self._workflow_region_only.pop(app_id, None)
                arrived = self._identify(app_id, after)
                if arrived and self.workflow_agent is not None:
                    self._workflow_confirmed_nodes[app_id] = arrived
        except Exception as exc:
            executed_count = 0
            if isinstance(grounded, Mapping):
                raw_count = grounded.get("_executed_gui_actions")
                if raw_count is None and execution_completed:
                    raw_count = grounded.get("gui_action_count", action_steps)
                try:
                    executed_count = max(0, int(raw_count or 0))
                except (TypeError, ValueError):
                    executed_count = 0
            if executed_count:
                after = getattr(adapter, "_last_obs", None)
                if not isinstance(after, Mapping) and isinstance(execution_result, Mapping):
                    after = execution_result
                arrived = None
                if after is not None:
                    try:
                        arrived = self._identify(app_id, after)
                    except Exception:
                        arrived = None
                self._total_action_steps += executed_count
                step_index = len(self._trajectory)
                self._trajectory.append({
                    "step": step_index,
                    "kind": action_spec.get("kind", "action"),
                    "app_id": app_id,
                    "action_steps": executed_count,
                    "action_spec": dict(action_spec),
                    "grounding": grounded,
                    "observation_before": before,
                    "observation_after": after,
                    "context_node_id": source,
                    "arrived_node_id": arrived,
                    "committed": False,
                    "status": "execution_failed",
                    "error": str(exc),
                    "graph_provenance": dict(provenance),
                })
                if arrived:
                    self._nodes[app_id] = arrived
                if after is not None:
                    self._observations[app_id] = after
                return {
                    "executed": False,
                    "status": "execution_failed",
                    "reason": str(exc),
                    "step": step_index,
                    "before": before,
                    "after": after,
                    "arrived_node": arrived,
                }
            return {"executed": False, "status": "execution_failed", "reason": str(exc)}

        if isinstance(grounded, Mapping) \
                and grounded.get("_executed_gui_actions") is not None:
            try:
                action_steps = int(grounded.get("_executed_gui_actions"))
            except (TypeError, ValueError):
                pass
        elif isinstance(grounded, Mapping) and grounded.get("gui_action_count") is not None:
            try:
                action_steps = int(grounded.get("gui_action_count"))
            except (TypeError, ValueError):
                pass
        action_steps = max(0, int(action_steps))
        self._total_action_steps += action_steps
        self._observations[app_id] = after
        if region_only_match:
            self._workflow_recent_steps.append(
                f"从 {source} 点击 "
                f"{self._natural_action_label(workflow_action_label)}，"
                f"完整 Stage 未确认，只确认下一步所需区块。")
        elif arrived:
            self._nodes[app_id] = arrived
            if arrived != source:
                self._arrival_sources[app_id] = source
            self._workflow_recent_steps.append(
                f"从 {source} 点击 "
                f"{self._natural_action_label(workflow_action_label)}，"
                f"已到达 {arrived}。")
        step_index = len(self._trajectory)
        self._trajectory.append(
            {
                "step": step_index,
                "kind": action_spec.get("kind", "action"),
                "app_id": app_id,
                "action_steps": action_steps,
                "action_spec": dict(action_spec),
                "grounding": grounded,
                "observation_before": before,
                "observation_after": after,
                "context_node_id": None if source_region_only else source,
                "arrived_node_id": arrived,
                "committed": False,
                "graph_provenance": dict(provenance),
                "source_arrival_context": source_arrival_context,
                "workflow_review": workflow_decision,
                "workflow_region_only": region_only_match,
            }
        )
        return {
            "executed": True,
            "status": "executed",
            "step": step_index,
            "before": before,
            "after": after,
            "source_node": source,
            "arrived_node": arrived,
            "region_only": region_only_match,
            "source_arrival_context": source_arrival_context,
        }

    def _record_route_correction(
        self, app_id: str, hop: _RouteHop, actual_target: str,
        route_context: str,
    ) -> Dict[str, Any]:
        """Keep map evidence while the containing collection is discarded."""
        correction = {
            "app_id": app_id,
            "source": hop.source,
            "predicted_target": hop.target,
            "actual_target": actual_target,
            "route_context": route_context,
            "edge_key": hop.edge_key,
            "persisted": False,
        }
        owner = self.app_graphs.get(app_id)
        graph = owner if isinstance(owner, nx.Graph) else getattr(owner, "graph", owner)
        if graph is None or hop.source not in graph or actual_target not in graph:
            return correction
        attrs = dict(hop.edge)
        attrs.update({
            "routing_verified": True,
            "landing_verified": True,
            "transition_kind": "collection_route_corrected",
            "route_contexts": ([route_context] if route_context else []),
            "predicted_target": hop.target,
            "prediction_match": False,
        })
        if hasattr(owner, "record_action_event") and hasattr(owner, "add_transition"):
            action = attrs.get("action") or {
                "action_type": "CLICK",
                "selector": {"element_label": attrs.get("element_label", "")},
            }
            event_index = owner.record_action_event(
                source=hop.source, target=actual_target, action=action,
                element_id=str(attrs.get("element_id") or ""),
                element_label=str(attrs.get("element_label") or ""),
                semantic_description=str(attrs.get("semantic_description") or ""),
                region=str(attrs.get("region") or ""),
                outcome="transitioned_consistent",
                detail="collection corrected predicted route landing",
                landing_verified=True, committed=False,
                evidence={
                    "route_context": route_context,
                    "predicted_target": hop.target,
                    "actual_target": actual_target,
                    "prediction_match": False,
                },
            )
            owner.add_transition(
                hop.source, actual_target, action,
                element_id=str(attrs.get("element_id") or ""),
                element_label=str(attrs.get("element_label") or ""),
                semantic_description=str(attrs.get("semantic_description") or ""),
                region=str(attrs.get("region") or ""),
                effect_verdict="transitioned_consistent",
                effect_note="collection corrected predicted route landing",
                landing_verified=True, event_index=event_index,
                transition_kind="collection_route_corrected",
            )
        else:
            graph.add_edge(hop.source, actual_target, **attrs)
        correction["persisted"] = True
        return correction

    # -- verifier -----------------------------------------------------------

    def _verify_ref(
        self,
        ref: CapabilityExecutionRef,
        before: Any,
        after: Any,
    ) -> Dict[str, Any]:
        verifier = self.completion_verifier
        context = self._runtime_context(ref)
        try:
            method = getattr(verifier, "verify_ref", None) or getattr(
                verifier, "verify_capability", None
            )
            if method is None:
                return {"complete": False, "reason": "ref verifier method is missing"}
            raw = _call_compatible(method, ref.to_dict(), before, after, context)
            verdict = _normalize_verdict(raw)
            return _enforce_desired_outcome(ref.desired_outcome, verdict)
        except Exception as exc:
            return {"complete": False, "reason": f"ref verifier failed: {exc}"}

    def _verify_final(self, observation: Any) -> Dict[str, Any]:
        if self._workflow_final_verdict and not self._failed_refs:
            return dict(self._workflow_final_verdict)
        verifier = self.completion_verifier
        context = self._runtime_context(None)
        context["completed_refs"] = list(self._completed_refs)
        context["failed_refs"] = list(self._failed_refs)
        try:
            method = getattr(verifier, "verify_final", None) or getattr(
                verifier, "verify_instruction", None
            )
            if method is None:
                return {"complete": False, "reason": "final verifier method is missing"}
            raw = _call_compatible(method, dict(self._instruction), observation, context)
            return _normalize_verdict(raw)
        except Exception as exc:
            return {"complete": False, "reason": f"final verifier failed: {exc}"}

    # -- low-level / result -------------------------------------------------

    def _capture(self, app_id: str) -> Any:
        return _call_compatible(self.app_adapters[app_id].capture)

    def _identify(self, app_id: str, observation: Any) -> Optional[str]:
        value = _call_compatible(self.app_adapters[app_id].identify, observation)
        return str(value) if value is not None and str(value) else None

    def _runtime_context(
        self, ref: Optional[CapabilityExecutionRef]
    ) -> Dict[str, Any]:
        return {
            "instruction": dict(self._instruction),
            "ref": ref.to_dict() if ref else None,
            "current_app_id": self._current_app,
            "current_node_id": self._nodes.get(self._current_app or ""),
            "app_nodes": dict(self._nodes),
            "completed_refs": list(self._completed_refs),
            "failed_refs": list(self._failed_refs),
            "blackboard": self._blackboard,
            "adapter": self.app_adapters.get(ref.app_id) if ref else None,
            "graph": self.app_graphs.get(ref.app_id) if ref else None,
            "trajectory": self._trajectory,
        }

    def _reset_run_state(self) -> None:
        self._instruction: Dict[str, Any] = {}
        self._runtime_requirements: Dict[str, List[Any]] = {}
        self._reserved_query_slots: set[str] = set()
        self._current_app: Optional[str] = None
        self._observations: Dict[str, Any] = {}
        self._nodes: Dict[str, str] = {}
        self._trajectory: List[Dict[str, Any]] = []
        self._ref_results: List[Dict[str, Any]] = []
        self._completed_refs: List[str] = []
        self._failed_refs: List[str] = []
        self._blackboard: Dict[str, Any] = {}
        self._errors: List[str] = []
        self._total_action_steps = 0
        self._app_switches = 0
        self._cleanup_action_steps = 0
        self._arrival_sources: Dict[str, str] = {}
        self._route_tainted = False
        self._route_corrections: List[Dict[str, Any]] = []
        self._workflow_confirmed_nodes: Dict[str, str] = {}
        self._workflow_recent_steps: List[str] = []
        self._workflow_next_clicks: Dict[str, Dict[str, Any]] = {}
        self._workflow_region_only: Dict[str, Dict[str, str]] = {}
        self._workflow_final_verdict: Dict[str, Any] = {}
        self._cleanup_result: Dict[str, Any] = {
            "status": "not_required", "gui_action_count": 0, "results": []
        }
        self._precondition_cleanup_done = False

    def _cleanup_precondition_resources(self) -> Dict[str, Any]:
        if self._precondition_cleanup_done:
            return dict(self._cleanup_result)
        self._precondition_cleanup_done = True
        resolver = self.precondition_resolver
        cleanup = getattr(resolver, "cleanup", None)
        if not self.cleanup_run_resources or not callable(cleanup):
            return dict(self._cleanup_result)

        before_events = list(getattr(resolver, "action_events", ()) or ())
        try:
            raw = _call_compatible(cleanup)
            if isinstance(raw, Mapping):
                report = dict(raw)
            elif callable(getattr(raw, "to_dict", None)):
                report = dict(raw.to_dict())
            else:
                report = {
                    "status": "failed",
                    "gui_action_count": 0,
                    "error": "cleanup resolver returned no structured report",
                }
        except Exception as exc:
            report = {
                "status": "failed",
                "gui_action_count": 0,
                "error": f"precondition cleanup failed: {exc}",
            }

        try:
            count = max(0, int(report.get("gui_action_count", 0) or 0))
        except (TypeError, ValueError):
            count = 0
        self._cleanup_action_steps = count
        after_events = list(getattr(resolver, "action_events", ()) or ())
        new_events = after_events[len(before_events):]
        for raw_event in new_events:
            if not isinstance(raw_event, Mapping):
                continue
            event = dict(raw_event)
            event.update({
                "step": len(self._trajectory),
                "kind": "precondition_cleanup",
                "committed": bool(event.get("committed", False)),
                "graph_provenance": {
                    "kind": "precondition_cleanup",
                    "graphs_merged": False,
                },
            })
            self._trajectory.append(event)
        self._cleanup_result = report
        return dict(report)

    def _finish(
        self,
        status: str,
        *,
        final_verification: Optional[Mapping[str, Any]],
        success: bool = False,
    ) -> Dict[str, Any]:
        cleanup = self._cleanup_precondition_resources()
        cleanup_status = str(cleanup.get("status") or "").lower()
        cleanup_ok = cleanup_status in {
            "", "not_required", "already_clean", "complete", "completed"
        }
        if not cleanup_ok:
            self._errors.append(
                str(cleanup.get("error") or "run-owned prerequisite cleanup failed"))
            success = False
            if status == "complete":
                status = "complete_cleanup_failed"
        provenance = [step.get("graph_provenance", {}) for step in self._trajectory]
        auditable_steps = [
            step for step in self._trajectory
            if str(step.get("kind") or "") == "capability"
            or "effect" in step
            or "expected_action_ids" in step
            or "action" in step
        ]
        agent_audit = audit_agent_trajectory(auditable_steps)
        if agent_audit.get("agent_failure"):
            success = False
            if status == "complete":
                status = "agent_audit_failed"
            self._errors.append("agent trajectory audit detected execution failure")
        return {
            "instruction_id": self._instruction.get("instruction_id", ""),
            "instruction": self._instruction.get("instruction") or self._instruction.get("text") or "",
            "success": bool(success),
            "scenario_success": bool(success),
            "final_status": status,
            "capability_refs": list(self._instruction.get("capability_refs") or []),
            "ref_results": list(self._ref_results),
            "completed_refs": sorted(self._completed_refs),
            "failed_refs": sorted(self._failed_refs),
            "trajectory": list(self._trajectory),
            "graph_provenance": provenance,
            "app_nodes": dict(self._nodes),
            "app_switches": self._app_switches,
            "total_action_steps": self._total_action_steps,
            "cleanup_action_steps": self._cleanup_action_steps,
            "cleanup": cleanup,
            "num_action_events": sum(
                max(0, int(step.get("action_steps", 0) or 0))
                for step in self._trajectory
            ),
            "blackboard": dict(self._blackboard),
            "final_verification": dict(final_verification or {}),
            "agent_audit": agent_audit,
            "errors": list(self._errors),
            "route_tainted": bool(self._route_tainted),
            "route_corrections": list(self._route_corrections),
        }


def _call_compatible(function: Callable[..., Any], *args: Any) -> Any:
    """Call an injected boundary with the longest signature-compatible prefix."""
    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(*args)
    for count in range(len(args), -1, -1):
        candidate = args[:count]
        try:
            signature.bind(*candidate)
        except TypeError:
            continue
        return function(*candidate)
    return function(*args)


def _action_steps(
    value: Mapping[str, Any],
    *,
    default: int = 1,
    allow_zero: bool = False,
) -> int:
    raw: Any = value.get("action_steps", default)
    action = value.get("action")
    if "action_steps" not in value and isinstance(action, Mapping):
        raw = action.get("action_steps", default)
    try:
        steps = int(raw)
    except (TypeError, ValueError):
        steps = default
    return max(0 if allow_zero else 1, steps)


def _is_multiedge_data(data: Mapping[str, Any]) -> bool:
    return bool(data) and "action_steps" not in data and all(
        isinstance(v, Mapping) for v in data.values()
    )


def _edge_weight(_source: Any, _target: Any, data: Mapping[str, Any]) -> int:
    if _is_multiedge_data(data):
        return min(_action_steps(attrs, default=1) for attrs in data.values())
    return _action_steps(data, default=1)


def _select_edge(graph: nx.Graph, source: Any, target: Any) -> Tuple[Any, Mapping[str, Any]]:
    data = graph.get_edge_data(source, target) or {}
    if graph.is_multigraph():
        key, attrs = min(
            data.items(), key=lambda item: (_action_steps(item[1], default=1), str(item[0]))
        )
        return key, attrs
    return None, data


def _requirement_dependency(requirement: Any, known: set[str]) -> Optional[str]:
    if isinstance(requirement, str):
        return requirement if requirement in known else None
    if not isinstance(requirement, Mapping):
        return None
    for key in ("ref_id", "capability_ref", "capability_id", "depends_on"):
        value = requirement.get(key)
        if isinstance(value, str) and value in known:
            return value
    return None


_LOGIN_BOUNDARY_TERMS = (
    "sign in", "log in", "login", "enter password", "submit credentials",
    "登录", "登入", "账号登录",
)


def _contains_login_semantics(value: Any) -> bool:
    if isinstance(value, Mapping):
        return any(_contains_login_semantics(item) for item in value.values())
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return any(_contains_login_semantics(item) for item in value)
    if isinstance(value, str):
        text = value.casefold()
        return any(term in text for term in _LOGIN_BOUNDARY_TERMS)
    return False


def _ref_crosses_login_boundary(ref: CapabilityExecutionRef) -> bool:
    for requirement in ref.requires:
        if isinstance(requirement, Mapping) \
                and str(requirement.get("kind") or "").casefold() == "login":
            return True
    if _contains_login_semantics(ref.name):
        return True
    recipe = ref.raw.get("execution_recipe") or ref.raw.get("action_recipe")
    return _contains_login_semantics(recipe)


def _estimated_action_list_steps(actions: Any) -> int:
    if not isinstance(actions, Sequence) or isinstance(actions, (str, bytes)):
        actions = [actions] if actions else []
    total = 0
    for action in actions:
        if isinstance(action, Mapping):
            raw = action.get(
                "gui_action_cost", action.get("action_steps", 1))
            try:
                total += max(0, int(raw))
            except (TypeError, ValueError):
                total += 1
        elif action:
            total += 1
    return total


def _estimated_recipe_steps(raw: Any) -> int:
    """Estimate the minimum declared setup cost without executing a check."""

    if not raw:
        return 0
    if isinstance(raw, Mapping):
        nested = raw.get("recipes")
        if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
            costs = [_estimated_recipe_steps(item) for item in nested]
            return min(costs) if costs else 0
        estimated = raw.get("estimated_gui_actions")
        if estimated is not None:
            try:
                return max(0, int(estimated))
            except (TypeError, ValueError):
                pass
        actions = raw.get("actions") or raw.get("steps") or raw.get("setup_steps")
        if actions is not None:
            return _estimated_action_list_steps(actions)
        return _estimated_action_list_steps([raw])
    if isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
        values = list(raw)
        recipes = [
            item for item in values
            if isinstance(item, Mapping)
            and any(key in item for key in (
                "recipe_id", "actions", "steps", "estimated_gui_actions"))
        ]
        if recipes and len(recipes) == len(values):
            costs = [_estimated_recipe_steps(item) for item in recipes]
            return min(costs) if costs else 0
        return _estimated_action_list_steps(values)
    return 1


def _estimated_precondition_steps(
    ref: CapabilityExecutionRef, blackboard: Mapping[str, Any]
) -> int:
    total = 0
    used_capability_recipe = False
    capability_recipe = ref.raw.get("setup_recipe") or ref.raw.get("setup_recipes")
    for requirement in ref.requires:
        if isinstance(requirement, Mapping):
            fact = str(requirement.get("fact") or "")
            slot = str(requirement.get("resource_slot") or requirement.get("slot") or "")
            expected = requirement.get("expected", requirement.get("value", True))
            if (slot and slot in blackboard) \
                    or (fact and fact in blackboard and blackboard.get(fact) == expected):
                continue
            recipe = requirement.get("setup_recipe") or requirement.get("setup_recipes")
            if recipe:
                total += _estimated_recipe_steps(recipe)
            elif capability_recipe and not used_capability_recipe:
                total += _estimated_recipe_steps(capability_recipe)
                used_capability_recipe = True
    return total


def _normalize_precondition(raw: Any) -> _PreconditionDecision:
    if isinstance(raw, bool):
        return _PreconditionDecision(satisfied=raw)
    if not isinstance(raw, Mapping) and callable(getattr(raw, "to_dict", None)):
        raw = raw.to_dict()
    if not isinstance(raw, Mapping):
        return _PreconditionDecision(
            satisfied=False, reason="precondition callback returned no explicit decision"
        )
    satisfied_raw = raw.get("satisfied")
    if not isinstance(satisfied_raw, bool) and isinstance(raw.get("ready"), bool):
        satisfied_raw = raw.get("ready")
    if not isinstance(satisfied_raw, bool) and raw.get("status"):
        satisfied_raw = str(raw.get("status")) in {
            "ready",
            "satisfied",
            "setup_completed",
        }
    if not isinstance(satisfied_raw, bool):
        return _PreconditionDecision(
            satisfied=False, reason="precondition callback omitted boolean satisfied"
        )
    bindings: Dict[str, Any] = {}
    for key in (
        "bindings",
        "outputs",
        "world_facts",
        "produced_facts",
        "resource_bindings",
    ):
        value = raw.get(key) or {}
        if isinstance(value, Mapping):
            bindings.update(value)
    action_count = raw.get("action_steps", raw.get("gui_action_count", 0))
    try:
        action_count = max(0, int(action_count))
    except (TypeError, ValueError):
        action_count = 0
    raw_events = raw.get("action_events") or []
    action_events = [
        dict(item) for item in raw_events
        if isinstance(item, Mapping)
    ] if isinstance(raw_events, Sequence) \
        and not isinstance(raw_events, (str, bytes)) else []
    return _PreconditionDecision(
        satisfied=satisfied_raw,
        skip_capability=bool(raw.get("skip_capability") or raw.get("already_complete")),
        action_steps=action_count,
        evidence=raw.get("evidence") or raw.get("results"),
        bindings=bindings,
        action_events=action_events,
        reason=str(raw.get("reason") or raw.get("error") or raw.get("status") or ""),
    )


def _normalize_verdict(raw: Any) -> Dict[str, Any]:
    if isinstance(raw, bool):
        return {"complete": raw, "reason": ""}
    if not isinstance(raw, Mapping):
        return {"complete": False, "reason": "verifier returned no explicit decision"}
    value: Any = None
    for key in ("complete", "completed", "success"):
        if key in raw:
            value = raw[key]
            break
    if not isinstance(value, bool):
        return {
            "complete": False,
            "reason": str(raw.get("reason") or "verifier omitted boolean complete"),
            "raw": dict(raw),
        }
    verdict = dict(raw)
    verdict["complete"] = value
    verdict.setdefault("reason", "")
    return verdict


def _is_runtime_scalar(value: Any) -> bool:
    if isinstance(value, str):
        return bool(value.strip())
    if isinstance(value, bool) or isinstance(value, int):
        return True
    return isinstance(value, float) and math.isfinite(value)


def _matches_runtime_type(value: Any, expected: Any) -> bool:
    if expected == "string":
        return isinstance(value, str)
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "number":
        return (isinstance(value, (int, float)) and not isinstance(value, bool)
                and (not isinstance(value, float) or math.isfinite(value)))
    return False


def _normalized_outcome(value: Any) -> Any:
    if isinstance(value, str):
        text = " ".join(value.strip().casefold().split())
        if text in {"true", "on", "enabled", "checked", "yes", "open"}:
            return True
        if text in {"false", "off", "disabled", "unchecked", "no", "closed"}:
            return False
        return text
    return value


def _enforce_desired_outcome(
    desired_outcome: Any,
    verdict: Mapping[str, Any],
) -> Dict[str, Any]:
    """Fail closed when a directional result is absent or visibly inverted."""
    result = dict(verdict)
    if desired_outcome is None:
        return result
    observed_present = "observed_outcome" in result
    if not observed_present:
        for alias in ("actual_outcome", "outcome"):
            if alias in result:
                result["observed_outcome"] = result[alias]
                observed_present = True
                break
    result["desired_outcome"] = desired_outcome
    if not observed_present:
        result["complete"] = False
        result["outcome_match"] = False
        result["reason"] = (
            "directional capability verification omitted observed_outcome"
        )
        return result
    matched = _normalized_outcome(result["observed_outcome"]) == \
        _normalized_outcome(desired_outcome)
    result["outcome_match"] = matched
    if not matched:
        result["complete"] = False
        result["reason"] = (
            f"desired outcome {desired_outcome!r}, observed "
            f"{result['observed_outcome']!r}"
        )
    return result


__all__ = [
    "CapabilityExecutionRef",
    "CompletionVerifier",
    "LiveVisualAdapter",
    "VLMCompletionVerifier",
    "VisualCollectionExecutor",
]
