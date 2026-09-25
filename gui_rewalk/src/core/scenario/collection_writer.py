"""Collection Writer: persist live-rollout trajectories into a structured,
scalable dataset layout with graph-aware step annotations.

Design (agreed 2026-06-14):
- Layout: collections/<platform>/<date>/<app>/episodes/<instr_id>_<uid>/
- One screenshot per step (the "before"/decision frame), not before+after.
  step_i's after == step_{i+1}'s before, so storing decision frames + one
  final frame is lossless and halves image count.
- The visual graph is the source of truth for capabilities and element meaning.
  Trajectory steps reference visual ``arrived_node_id`` plus screenshot evidence.
- Each step gets graph-distance-based annotation:
    d_before = dist(prev_node -> target),  d_after = dist(curr_node -> target)
    delta<0 progress, delta>0 wrong_branch, revisit backtrack, inf recovery-needed.
  Page-local param actions (no new node) are judged by reverse_step_completed,
  not graph distance (the two are complementary; see PROJECT_GOAL §4).

See design/design_decisions.md D13.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import shutil
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

import networkx as nx

logger = logging.getLogger("desktopenv.scenario.collection_writer")

# step_type categories (PROJECT_GOAL §4)
PROGRESS = "progress"
EXPLORATION = "exploration"
WRONG_BRANCH = "wrong_branch"
BACKTRACK = "backtrack"
RECOVERY = "recovery"
EVIDENCE_CHECK = "evidence_check"
IMPOSSIBLE_STOP = "impossible_stop"
PAGE_LOCAL = "page_local"        # in-page param action, no node change
OFF_GRAPH = "off_graph"          # live page maps to no known graph node


@dataclass
class StepAnnotation:
    step_type: str
    had_effect: bool
    step_completed: bool
    changed_pixels: int = 0
    graph_distance_before: Optional[int] = None
    graph_distance_after: Optional[int] = None
    analysis: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "step_type": self.step_type,
            "had_effect": self.had_effect,
            "step_completed": self.step_completed,
            "changed_pixels": self.changed_pixels,
            "graph_distance_before": self.graph_distance_before,
            "graph_distance_after": self.graph_distance_after,
            "analysis": self.analysis,
        }


class _DistanceCache:
    """Directed shortest-path length on the state graph, memoized."""

    def __init__(self, graph: Any):
        self.G = graph.graph if hasattr(graph, "graph") else graph
        self._cache: Dict[tuple, Optional[int]] = {}

    def dist(self, src: str, dst: str) -> Optional[int]:
        if not src or not dst:
            return None
        if src == dst:
            return 0
        key = (src, dst)
        if key in self._cache:
            return self._cache[key]
        try:
            d = nx.shortest_path_length(self.G, src, dst)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            d = None  # unreachable in the directed graph
        self._cache[key] = d
        return d


def classify_step(
    prev_node: Optional[str],
    curr_node: Optional[str],
    target_node: Optional[str],
    visited_nodes: List[str],
    dist_cache: _DistanceCache,
    had_effect: bool,
    step_completed: bool,
    action: str = "",
) -> StepAnnotation:
    """Assign a step_type from graph distance + reverse-inference signals."""
    if action == "IMPOSSIBLE":
        return StepAnnotation(IMPOSSIBLE_STOP, had_effect, step_completed)

    # live page didn't map to any graph node
    if not curr_node:
        return StepAnnotation(OFF_GRAPH, had_effect, step_completed)

    d_before = dist_cache.dist(prev_node, target_node) if prev_node else None
    d_after = dist_cache.dist(curr_node, target_node)

    # no node change → page-local param action; judge by completion
    if prev_node and curr_node == prev_node:
        st = PAGE_LOCAL if had_effect else EXPLORATION
        return StepAnnotation(st, had_effect, step_completed,
                              graph_distance_before=d_before,
                              graph_distance_after=d_after)

    # revisiting an earlier node → backtrack
    if curr_node in visited_nodes[:-1]:
        return StepAnnotation(BACKTRACK, had_effect, step_completed,
                              graph_distance_before=d_before,
                              graph_distance_after=d_after)

    # distance-based progress / wrong-branch
    if d_before is not None and d_after is not None:
        if d_after < d_before:
            st = PROGRESS
        elif d_after > d_before:
            st = WRONG_BRANCH
        else:
            st = EXPLORATION
    elif d_after is None and d_before is not None:
        st = RECOVERY  # moved into an area with no path to target
    else:
        st = EXPLORATION
    return StepAnnotation(st, had_effect, step_completed,
                          graph_distance_before=d_before,
                          graph_distance_after=d_after)


class CollectionWriter:
    """Write executor results into the scalable collection layout.

    Layout::

        <root>/<platform>/<date>/<app>/
          manifest.json
          capabilities/<node_id>_page_capabilities.json
          instructions.json
          episodes/<instr_id>_<uid>/
            meta.json
            trajectory.json
            screenshots/step00.png ... stepNN.png  (decision frames + final)
    """

    def __init__(self, root: str, platform: str, date: str, app: str,
                 graph: Any = None, node_dir: str = ""):
        self.base = os.path.join(root, platform, date, app)
        self.app = app
        self.node_dir = node_dir
        self.dist_cache = _DistanceCache(graph) if graph is not None else None
        os.makedirs(os.path.join(self.base, "episodes"), exist_ok=True)
        os.makedirs(os.path.join(self.base, "capabilities"), exist_ok=True)
        self._manifest: List[Dict[str, Any]] = []

    # ── per-episode ───────────────────────────────────────────────────

    def _nearest_subgoal(self, node: str, subgoals: List[str],
                         visited: List[str]) -> str:
        """Pick the closest sub-goal not yet reached, by directed graph distance.

        For long cross-page chains the final ref is often unreachable from an
        intermediate page; targeting the nearest pending sub-goal gives
        meaningful per-segment progress/wrong_branch signals.
        """
        if not subgoals:
            return ""
        pending = [g for g in subgoals if g not in visited]
        if not pending:
            pending = [subgoals[-1]]  # all reached → keep final as target
        if not node or self.dist_cache is None:
            return pending[0]
        best, best_d = pending[0], None
        for g in pending:
            d = self.dist_cache.dist(node, g)
            if d is None:
                continue
            if best_d is None or d < best_d:
                best, best_d = g, d
        return best

    def write_episode(self, result: Dict[str, Any], uid: str,
                      target_node: str = "",
                      target_nodes: Optional[List[str]] = None,
                      instruction_meta: Optional[Dict[str, Any]] = None) -> str:
        instr_id = result.get("scenario_id", "EP")
        ep_name = f"{instr_id}_{uid}"
        ep_dir = os.path.join(self.base, "episodes", ep_name)
        ss_dir = os.path.join(ep_dir, "screenshots")
        os.makedirs(ss_dir, exist_ok=True)

        # sub-goal sequence for segmented distance (long cross-page chains).
        # Fall back to a single target if no sequence supplied.
        subgoals = [n for n in (target_nodes or []) if n]
        if not subgoals and target_node:
            subgoals = [target_node]

        traj = result.get("trajectory", [])
        visited: List[str] = []
        out_steps: List[Dict[str, Any]] = []
        prev_node: Optional[str] = None

        for i, t in enumerate(traj):
            curr_node = t.get("arrived_node_id") or t.get("node_id") or ""
            ctx_node = t.get("graph_context_node_id") or prev_node or ""
            if curr_node:
                visited.append(curr_node)

            # one decision frame per step (the "before")
            src_before = t.get("screen_before", "")
            frame_name = f"step{i:02d}.png"
            if src_before and os.path.exists(src_before):
                shutil.copy(src_before, os.path.join(ss_dir, frame_name))
            else:
                frame_name = ""

            # pick the nearest not-yet-reached sub-goal as this step's target
            step_target = self._nearest_subgoal(curr_node or ctx_node,
                                                subgoals, visited)

            # had_effect: trust pixel evidence over a possibly-missing or
            # over-optimistic VLM judgment. Default False when unknown, and
            # force False when the screen barely changed (<=200px == the
            # _has_visual_change "no effect" threshold). Non-visual actions
            # (WAIT/HOTKEY/STEP_DONE) carry no pixel diff, so only down-grade
            # when changed_pixels was actually measured.
            _changed_px = int(t.get("changed_pixels", 0) or 0)
            _has_pixel_diff = "changed_pixels" in t
            _had_effect = bool(t.get("reverse_had_effect", False))
            if _has_pixel_diff and _changed_px <= 200:
                _had_effect = False

            ann = classify_step(
                prev_node=ctx_node,
                curr_node=curr_node,
                target_node=step_target,
                visited_nodes=visited,
                dist_cache=self.dist_cache or _DistanceCache(nx.DiGraph()),
                had_effect=_had_effect,
                step_completed=bool(t.get("reverse_step_completed", False)),
                action=t.get("action", ""),
            )
            ann.changed_pixels = int(t.get("changed_pixels", 0) or 0)
            ann.analysis = t.get("reverse_analysis", "") or ""

            step_obj = {
                "step": i,
                "action": t.get("action", ""),
                "action_json": t.get("action_json", ""),
                "frame": frame_name,
                "instruction": t.get("scenario_instruction", "") or t.get("goal", ""),
                "thinking": t.get("thinking", "") or t.get("sub_instruction", ""),
                "grounding": {
                    "element_name": t.get("element_name", ""),
                    "element_role": t.get("element_role", ""),
                    "element_bbox": t.get("element_bbox", {}),
                    "element_center": t.get("element_center", {}),
                },
                "graph": {
                    "context_node_id": ctx_node,
                    "arrived_node_id": curr_node,
                    "edge_known": bool(curr_node),
                },
                "annotation": ann.to_dict(),
            }
            # observability + runtime backfill (pass through from executor)
            if t.get("vlm_action_raw") is not None:
                step_obj["vlm_action_raw"] = t.get("vlm_action_raw")
            if t.get("grounding_source"):
                step_obj["grounding_source"] = t.get("grounding_source")
            if t.get("grounding_failed"):
                step_obj["grounding_failed"] = True
            if t.get("resolved_value"):
                step_obj["resolved_value"] = t.get("resolved_value")
                step_obj["exploration_hint"] = t.get("exploration_hint", "")
            if t.get("resolved_runtime"):
                step_obj["resolved_runtime"] = t.get("resolved_runtime")

            out_steps.append(step_obj)
            if curr_node:
                prev_node = curr_node

        # final frame (last step's after)
        if traj:
            last_after = traj[-1].get("screen_after", "")
            if last_after and os.path.exists(last_after):
                shutil.copy(last_after, os.path.join(ss_dir, "final.png"))

        meta = {
            "instruction_id": instr_id,
            "instruction": result.get("instruction", ""),
            "task_structure": result.get("task_structure", ""),
            "app": self.app,
            "final_status": result.get("final_status", ""),
            "scenario_success": result.get("scenario_success", False),
            "target_node": target_node,
            "graph_path": result.get("nodes_visited", []),
            "covers_pages": result.get("covers_pages", []),
            "elapsed_seconds": result.get("elapsed_seconds", 0),
            "num_steps": len(out_steps),
        }
        if instruction_meta:
            meta.update({k: instruction_meta[k] for k in
                         ("capability_refs", "runtime_slots", "params")
                         if k in instruction_meta})
        # Runtime backfill (D27/C组): replace "<runtime>" placeholders in BOTH
        # params and the instruction text with the concrete values the VLM
        # discovered live (collected from step resolved_value, keyed by
        # exploration_hint == slot name). A saved trajectory must NOT retain
        # "<runtime>" anywhere.
        resolved = {}
        for s in out_steps:
            rv = s.get("resolved_value")
            slot = s.get("exploration_hint", "")
            if rv and slot:
                resolved[slot] = rv
            # terminal step may carry {slot: value} resolved on the final screen
            for k, v in (s.get("resolved_runtime") or {}).items():
                if k and v:
                    resolved[k] = v
        params = dict(meta.get("params", {}) or {})
        if resolved:
            meta["resolved_params"] = resolved
            for slot, val in resolved.items():
                if params.get(slot) in ("<runtime>", "", None):
                    params[slot] = val
            meta["params"] = params
        # Substitute into the instruction text. The instruction uses literal
        # "<runtime>" tokens (one per runtime slot); fill them in slot order,
        # then mop up any remainder with whatever concrete values we have.
        instr_text = meta.get("instruction", "") or ""
        if "<runtime>" in instr_text:
            for slot in (meta.get("runtime_slots") or []):
                if "<runtime>" not in instr_text:
                    break
                val = resolved.get(slot)
                if not val and params.get(slot) not in ("<runtime>", "", None):
                    val = params.get(slot)
                if val:
                    instr_text = instr_text.replace("<runtime>", str(val), 1)
            if "<runtime>" in instr_text and resolved:
                instr_text = instr_text.replace(
                    "<runtime>", str(next(iter(resolved.values()))))
            meta["instruction"] = instr_text
        # Guard: if a placeholder survived, the value was never resolved live —
        # flag it and don't let the episode masquerade as a clean success.
        leftover = ("<runtime>" in (meta.get("instruction", "") or "")
                    or any(v == "<runtime>"
                           for v in (meta.get("params", {}) or {}).values()))
        if leftover:
            # A genuinely-complete trajectory should never still carry "<runtime>"
            # (the value was never resolved live). Per project rule there is no
            # "incomplete" status, so flag it and treat it as not-a-clean-success
            # (impossible) for filtering — and warn loudly.
            logger.warning("Episode %s: unresolved <runtime> remains after "
                           "backfill — flagging runtime_unresolved", instr_id)
            meta["runtime_unresolved"] = True
            if meta.get("final_status") == "complete":
                meta["final_status"] = "impossible"

        with open(os.path.join(ep_dir, "meta.json"), "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
        with open(os.path.join(ep_dir, "trajectory.json"), "w", encoding="utf-8") as f:
            json.dump({"meta": meta, "steps": out_steps}, f,
                      ensure_ascii=False, indent=2)

        self._manifest.append({
            "episode": ep_name,
            "instruction_id": instr_id,
            "instruction": result.get("instruction", ""),
            "final_status": result.get("final_status", ""),
            "num_steps": len(out_steps),
            "step_types": [s["annotation"]["step_type"] for s in out_steps],
        })
        logger.info("Wrote episode %s (%d steps)", ep_name, len(out_steps))
        return ep_dir

    def write_visual_episode(
        self,
        result: Dict[str, Any],
        uid: str,
        *,
        instruction_meta: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Persist one M13 screenshot-only rollout without legacy annotations.

        ``VisualCollectionExecutor`` keeps observations in memory so the VLM can
        inspect them.  Those observations may contain PNG bytes, numpy arrays,
        or other runtime-only objects and therefore cannot be dumped directly.
        This writer extracts screenshot evidence first and then stores a compact,
        JSON-safe transaction record.  It deliberately does *not* invent the
        accessibility/reverse-inference fields used by :meth:`write_episode`.
        """
        instruction_id = str(
            result.get("instruction_id")
            or result.get("scenario_id")
            or "M13"
        )
        ep_name = "%s_%s" % (
            self._safe_component(instruction_id, "M13"),
            self._safe_component(uid, "run"),
        )
        ep_dir = os.path.join(self.base, "episodes", ep_name)
        ss_dir = os.path.join(ep_dir, "screenshots")
        os.makedirs(ss_dir, exist_ok=True)

        out_steps: List[Dict[str, Any]] = []
        trajectory = result.get("trajectory") or []
        if not isinstance(trajectory, list):
            raise ValueError("visual trajectory must be a list")

        for index, raw_step in enumerate(trajectory):
            if not isinstance(raw_step, dict):
                raise ValueError(f"visual trajectory step {index} must be an object")
            before_name = self._write_observation_frame(
                raw_step.get("observation_before"),
                ss_dir,
                f"step{index:03d}_before.png",
            )
            after_name = self._write_observation_frame(
                raw_step.get("observation_after"),
                ss_dir,
                f"step{index:03d}_after.png",
            )
            # A cross-app activation may only expose its post-switch frame.
            if not after_name and raw_step.get("observation") is not None:
                after_name = self._write_observation_frame(
                    raw_step.get("observation"),
                    ss_dir,
                    f"step{index:03d}_after.png",
                )

            step = {
                "step": int(raw_step.get("step", index) or 0),
                "kind": str(raw_step.get("kind") or "action"),
                "app_id": str(raw_step.get("app_id") or ""),
                "ref_id": str(raw_step.get("ref_id") or ""),
                "action_steps": self._safe_nonnegative_int(
                    raw_step.get("action_steps"), default=0),
                "committed": bool(raw_step.get("committed", False)),
                "frames": {"before": before_name, "after": after_name},
                "context_node_id": raw_step.get("context_node_id"),
                "arrived_node_id": raw_step.get("arrived_node_id"),
                "action_spec": self._json_safe(raw_step.get("action_spec") or {}),
                "grounding": self._json_safe(raw_step.get("grounding") or {}),
                "graph_provenance": self._json_safe(
                    raw_step.get("graph_provenance") or {}),
            }
            # Preconditions and semantic checks carry evidence rather than a
            # normal action_spec. Preserve only fields actually emitted.
            for key in (
                "requirement", "evidence", "verification", "reason", "action_intent",
                "from_app", "status", "effect", "expected_action_ids", "action",
            ):
                if key in raw_step:
                    step[key] = self._json_safe(raw_step.get(key))
            out_steps.append(step)

        ref_results = []
        for index, raw in enumerate(result.get("ref_results") or []):
            item = {key: self._json_safe(value) for key, value in raw.items() if key != "observation"}
            if raw.get("observation") is not None:
                item["frame"] = self._write_observation_frame(
                    raw["observation"], ss_dir, f"goal{index:03d}.png")
            ref_results.append(item)
        branch_decisions = []
        for index, decision in enumerate(result.get("branch_decisions") or []):
            frame = self._write_observation_frame(
                decision.get("observation"), ss_dir, f"condition{index:03d}.png")
            branch_decisions.append({key: self._json_safe(value) for key, value in decision.items()
                                     if key != "observation"})
            branch_decisions[-1]["frame"] = frame
        apps_involved = []
        source_meta = instruction_meta or {}
        for app_id in (
            source_meta.get("apps_involved")
            or [step.get("app_id") for step in out_steps]
        ):
            value = str(app_id or "")
            if value and value not in apps_involved:
                apps_involved.append(value)

        meta = {
            "schema_version": "m13.visual_collection.v1",
            "executor": result.get("executor", "VisualCollectionExecutor"),
            "model_calls": result.get("model_calls"),
            "final_frame": self._write_observation_frame(
                result.get("final_observation"), ss_dir, "final.png"),
            "instruction_id": instruction_id,
            "instruction": str(result.get("instruction") or ""),
            "app": self.app,
            "apps_involved": apps_involved,
            "final_status": str(result.get("final_status") or ""),
            "scenario_success": bool(
                result.get("scenario_success", result.get("success", False))),
            "total_action_steps": self._safe_nonnegative_int(
                result.get("total_action_steps"), default=0),
            "cleanup_action_steps": self._safe_nonnegative_int(
                result.get("cleanup_action_steps"), default=0),
            "total_episode_action_steps": self._safe_nonnegative_int(
                result.get(
                    "total_episode_action_steps",
                    result.get("total_action_steps")),
                default=0),
            "num_action_events": self._safe_nonnegative_int(
                result.get("num_action_events"), default=0),
            "app_switches": self._safe_nonnegative_int(
                result.get("app_switches"), default=0),
            "num_steps": len(out_steps),
            "completed_refs": self._json_safe(result.get("completed_refs") or []),
            "failed_refs": self._json_safe(result.get("failed_refs") or []),
            "final_verification": self._json_safe(
                result.get("final_verification") or {}),
            "agent_audit": self._json_safe(result.get("agent_audit") or {}),
            "errors": self._json_safe(result.get("errors") or []),
            "cleanup_report": self._json_safe(result.get("cleanup_report") or {}),
            "scenario_setup": self._json_safe(
                result.get("scenario_setup") or {}),
            "scenario_evaluation": self._json_safe(
                result.get("scenario_evaluation") or {}),
            "data_bindings": self._json_safe(
                result.get("data_bindings") or {}),
        }
        for key in ("type", "fixed_order", "runtime_slots", "params"):
            if key in source_meta:
                meta[key] = self._json_safe(source_meta.get(key))

        payload = {
            "meta": meta,
            "capability_refs": self._json_safe(
                result.get("capability_refs")
                or source_meta.get("capability_refs")
                or []),
            "ref_results": ref_results,
            "branch_taken": result.get("branch_taken"),
            "branch_decisions": branch_decisions,
            "region_task": self._json_safe({key: source_meta[key] for key in
                                           ("before", "condition", "if_true", "if_false", "after")
                                           if key in source_meta}),
            "graph_provenance": self._json_safe(
                result.get("graph_provenance") or []),
            "agent_audit": self._json_safe(result.get("agent_audit") or {}),
            "scenario_setup": meta["scenario_setup"],
            "scenario_evaluation": meta["scenario_evaluation"],
            "data_bindings": meta["data_bindings"],
            "steps": out_steps,
        }
        with open(os.path.join(ep_dir, "meta.json"), "w", encoding="utf-8") as stream:
            json.dump(meta, stream, ensure_ascii=False, indent=2)
        with open(
            os.path.join(ep_dir, "trajectory.json"), "w", encoding="utf-8"
        ) as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)

        self._manifest.append({
            "episode": ep_name,
            "instruction_id": instruction_id,
            "instruction": str(result.get("instruction") or ""),
            "final_status": str(result.get("final_status") or ""),
            "num_steps": len(out_steps),
            "total_action_steps": meta["total_action_steps"],
            "apps_involved": apps_involved,
            "step_types": [step["kind"] for step in out_steps],
            "schema_version": meta["schema_version"],
        })
        logger.info("Wrote M13 visual episode %s (%d steps)", ep_name, len(out_steps))
        return ep_dir

    @staticmethod
    def _safe_component(value: Any, fallback: str) -> str:
        clean = re.sub(r"[^0-9A-Za-z._-]+", "_", str(value or "")).strip("._")
        return (clean or fallback)[:120]

    @staticmethod
    def _safe_nonnegative_int(value: Any, *, default: int) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return max(0, int(default))

    @classmethod
    def _json_safe(cls, value: Any) -> Any:
        if value is None or isinstance(value, (str, int, bool)):
            return value
        if isinstance(value, float):
            return value if math.isfinite(value) else str(value)
        if isinstance(value, (bytes, bytearray, memoryview)):
            return {"binary_bytes": len(value)}
        if isinstance(value, Mapping):
            return {str(key): cls._json_safe(item) for key, item in value.items()}
        if isinstance(value, (list, tuple, set)):
            return [cls._json_safe(item) for item in value]
        # numpy scalar/array support without importing numpy at module import.
        if hasattr(value, "tolist"):
            try:
                converted = value.tolist()
                # Do not explode screenshot tensors into trajectory JSON.
                shape = getattr(value, "shape", None)
                if shape is not None and len(tuple(shape)) >= 2:
                    return {
                        "array_shape": [int(v) for v in tuple(shape)],
                        "array_dtype": str(getattr(value, "dtype", "")),
                    }
                return cls._json_safe(converted)
            except Exception:
                pass
        if hasattr(value, "to_dict") and callable(value.to_dict):
            try:
                return cls._json_safe(value.to_dict())
            except Exception:
                pass
        return str(value)

    @staticmethod
    def _observation_image(observation: Any) -> Any:
        if isinstance(observation, dict):
            for key in ("screenshot", "image", "screen"):
                if observation.get(key) is not None:
                    return observation.get(key)
            return None
        return observation

    @classmethod
    def _write_observation_frame(
        cls,
        observation: Any,
        directory: str,
        filename: str,
    ) -> str:
        image = cls._observation_image(observation)
        if image is None:
            return ""
        destination = os.path.join(directory, filename)
        try:
            if isinstance(image, str):
                if not os.path.isfile(image):
                    return ""
                from PIL import Image
                with Image.open(image) as source:
                    source.convert("RGB").save(destination, format="PNG")
            elif isinstance(image, (bytes, bytearray, memoryview)):
                import io
                from PIL import Image
                with Image.open(io.BytesIO(bytes(image))) as source:
                    source.convert("RGB").save(destination, format="PNG")
            elif hasattr(image, "save"):
                image.save(destination, format="PNG")
            else:
                from PIL import Image
                Image.fromarray(image).convert("RGB").save(destination, format="PNG")
        except Exception as exc:
            logger.warning("Could not persist visual frame %s: %s", filename, exc)
            return ""
        return filename

    # ── batch-level ───────────────────────────────────────────────────

    def snapshot_capabilities(self, node_ids: List[str]) -> int:
        """Copy each node's page_capabilities.json into the batch for provenance."""
        if not self.node_dir:
            return 0
        n = 0
        for nid in node_ids:
            src = os.path.join(self.node_dir, nid, "page_capabilities.json")
            if os.path.exists(src):
                shutil.copy(src, os.path.join(
                    self.base, "capabilities", f"{nid}_page_capabilities.json"))
                n += 1
        return n

    def write_instructions(self, instructions: List[Dict[str, Any]]) -> None:
        with open(os.path.join(self.base, "instructions.json"), "w",
                  encoding="utf-8") as f:
            json.dump(instructions, f, ensure_ascii=False, indent=2)

    def finalize(self) -> str:
        from collections import Counter
        manifest_path = os.path.join(self.base, "manifest.json")
        type_dist: Counter = Counter()
        for ep in self._manifest:
            type_dist.update(ep["step_types"])
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump({
                "app": self.app,
                "num_episodes": len(self._manifest),
                "step_type_distribution": dict(type_dist),
                "episodes": self._manifest,
            }, f, ensure_ascii=False, indent=2)
        logger.info("Finalized manifest: %d episodes", len(self._manifest))
        return manifest_path
