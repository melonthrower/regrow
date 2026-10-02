"""Region-guided task generation and live screenshot collection."""
from __future__ import annotations

import json
from typing import Mapping

import networkx as nx

# The live Region consumer shares the existing model transport and episode writer.
_REGION_GOAL = {"type": "object", "properties": {
    "region_ref": {"type": "string"}, "goal": {"type": "string"}},
    "required": ["region_ref", "goal"], "additionalProperties": False}
REGION_INSTRUCTION_SCHEMA = {"type": "object", "properties": {
    "instruction": {"type": "string"},
    "condition": {"anyOf": [_REGION_GOAL, {"type": "null"}]},
    **{key: {"type": "array", "items": _REGION_GOAL}
       for key in ("before", "if_true", "if_false", "after")}},
    "required": ["instruction", "before", "condition", "if_true", "if_false", "after"],
    "additionalProperties": False}


def validate_region_instruction(task, ledger):
    if not isinstance(task, Mapping) or not str(task.get("instruction") or "").strip():
        raise ValueError("Region task needs an instruction")
    goals = []
    for key in ("before", "if_true", "if_false", "after"):
        if not isinstance(task.get(key), list):
            raise ValueError(f"Region task {key} must be a list")
        goals.extend(task[key])
    if task.get("condition") is not None:
        goals.append(task["condition"])
    elif task["if_true"] or task["if_false"]:
        raise ValueError("Branch goals require a condition")
    if not goals:
        raise ValueError("Region task has no goals")
    for goal in goals:
        if (not isinstance(goal, Mapping) or goal.get("region_ref") not in ledger.regions
                or not str(goal.get("goal") or "").strip()):
            raise ValueError("Every goal needs a known Region ref and a nonempty goal")
    return dict(task)


def design_region_instruction(ledger, agent, request=""):
    from .region_function_research import region_function_inventory
    inventory = region_function_inventory(ledger)
    if not inventory:
        raise ValueError("No discovered Region functions")
    task = agent._call(
        role="region_instruction", response_schema=REGION_INSTRUCTION_SCHEMA, screenshots=[],
        system_prompt=("根据已发现功能设计一个有共同目的的用户任务。无需历史成功或完整点击配方。"
                       "只使用目录中的功能、参数依据和Region引用，不把推测写成已验证。"
                       "before是条件前的目标，condition是执行时要看图判断的问题和所在Region；"
                       "if_true/if_false互斥，after是共同后续。普通任务condition=null且分支为空。"
                       "每个goal写该区块要实现的结果与必要对象/参数，不写历史坐标。"
                       "不枚举导航目标不等于禁止导航；不要添加请求中没有的起始页面或导航限制。"
                       "instruction用自然用户目标表达，必要导航和输入实现细节由实时执行处理。"
                       "如要求3至5个子操作，按逻辑目标组织，不枚举导航点击；不生成无授权的危险任务。"),
        user_prompt=json.dumps({"request": request, "regions": inventory}, ensure_ascii=False),
    )
    return validate_region_instruction(task, ledger)


class RegionGuidedCollector:
    """Let the Agent execute goals on fresh screens; the graph supplies guidance."""

    def __init__(self, ledger, agent, env, scope, *, platform="desktop", max_turns=40, visual_guard=None):
        self.ledger, self.agent, self.env, self.scope = ledger, agent, env, scope
        self.platform, self.max_turns = platform, max_turns
        self.visual_guard = visual_guard

    def _guidance(self, visible, target):
        from .collection_graph import collection_relations
        if target in visible:
            return []
        relations = collection_relations(self.ledger)
        graph = nx.DiGraph()
        for edge in relations:
            for revealed in edge["revealed_region_refs"]:
                graph.add_edge(edge["source_region_ref"], revealed)
        paths = []
        for region in visible:
            try:
                paths.append(nx.shortest_path(graph, region, target))
            except (nx.NodeNotFound, nx.NetworkXNoPath):
                pass
        if not paths:
            return [edge for edge in relations if target in edge["revealed_region_refs"]]
        path = min(paths, key=len)
        return [edge for source, dest in zip(path, path[1:]) for edge in relations
                if edge["source_region_ref"] == source and dest in edge["revealed_region_refs"]]

    def execute(self, instruction, initial_observation=None):
        from copy import deepcopy
        from ..explore.actions import action_dict, execute_action, validate_for_platform
        from ..explore.contracts import _parse_action
        from ..explore.prompts import RESPONSE_SCHEMA
        task = validate_region_instruction(instruction, self.ledger)
        schema = {"type": "object", "properties": {
            "app_scope": {"type": "string", "enum": ["target_app", "external_app", "uncertain"]},
            "visible_region_refs": {"type": "array", "items": {"type": "string"}},
            "region_visible": {"type": "boolean"}, "complete": {"type": "boolean"},
            "condition_value": {"anyOf": [{"type": "boolean"}, {"type": "null"}]},
            "previous_action_outcome": {"type": "string", "enum": ["none", "success", "no_effect", "uncertain"]},
            "reason": {"type": "string"}, "action": RESPONSE_SCHEMA["properties"]["action"]},
            "required": ["app_scope", "visible_region_refs", "region_visible", "complete",
                         "condition_value", "previous_action_outcome", "reason", "action"],
            "additionalProperties": False}
        if self.visual_guard is not None:
            schema["properties"].update({
                "visual_target_ref": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "action_intent": {"type": "string"},
                "previous_action_observation": {"type": "string"},
                "previous_action_matches_intent": {"anyOf": [{"type": "boolean"}, {"type": "null"}]}})
            schema["required"].extend(["visual_target_ref", "action_intent",
                                       "previous_action_observation", "previous_action_matches_intent"])
        grounding_feedback = None
        pending_schema = deepcopy(schema)
        pending_schema["properties"]["previous_action_outcome"]["enum"] = ["success", "no_effect", "uncertain"]
        schema["properties"]["previous_action_outcome"]["enum"] = ["none"]
        queue = [("goal", goal) for goal in task["before"]]
        if task["condition"] is not None:
            queue.append(("condition", task["condition"]))
        else:
            queue.extend(("goal", goal) for goal in task["after"])
        observation = initial_observation or self.env._get_obs()
        trajectory, completed, decisions, goal_frames = [], [], [], []
        visible, branch, errors, success = [], None, [], False
        calls = 0
        try:
            for _ in range(self.max_turns):
                if not queue:
                    break
                if self.scope.check() != "target":
                    errors.append("target app foreground unavailable")
                    break
                kind, goal = queue[0]
                frame = observation["screenshot"]
                context = {"instruction": task["instruction"], "current_goal": goal,
                           "condition_check": kind == "condition", "branch_taken": branch,
                           "completed_goals": [{"region_ref": x["region_ref"], "goal": x["goal"]}
                                               for x in completed],
                           "regions": [{"region_ref": r.region_id, "name": r.name}
                                       for r in self.ledger.regions.values()],
                           "region_memory": self.ledger.regions[goal["region_ref"]].memory,
                           "historical_guidance": self._guidance(visible, goal["region_ref"]),
                           "recent_actions": [{"action": x["action_spec"], "verification": x.get("verification")}
                                              for x in trajectory[-3:]]}
                if self.visual_guard is not None:
                    context["known_visual_controls"] = self.visual_guard.catalog()
                    context["grounding_feedback"] = grounding_feedback
                    context["previous_action_intent"] = trajectory[-1].get("action_intent") if trajectory else None
                images = [frame]
                pending_receipt = bool(trajectory and trajectory[-1].get("verification") is None)
                if pending_receipt:
                    images.insert(0, trajectory[-1]["observation_before"]["screenshot"])
                decision = self.agent._call(
                    role="region_collection", response_schema=pending_schema if pending_receipt else schema, screenshots=images,
                    system_prompt=("根据最新截图执行当前目标。图只提供功能区块与带上下文的历史路线；"
                                   "路径不是必执行脚本。目标区块已可操作时自行完成对象、参数和按钮操作，"
                                   "未知中间页面不阻止继续，不创建或猜测图State。历史返回落点不可跨上下文套用。"
                                   "有两张图时第一张是上一步before，最后一张为当前图；报告上一步真实结果。"
                                   "导航和恢复也是真实GUI动作，有上一步时不得填none；只有没有待回填动作时才填none。"
                                   "外部事件不当成动作效果。condition_check时只在看清条件后填true/false，"
                                   "不确定填null并继续观察，不通过切换被检查控件来判断条件。"
                                   "本轮只执行current_goal，instruction仅说明整体目的，不能自行提前或重复执行其他阶段。"
                                   "completed_goals是已确认完成的阶段目标，应保持其结果，不能因最近动作没有它们就重做或撤销。"
                                   "若current_goal是定位、展开或观察准备，达到其要求的可见状态即可complete；"
                                   "若是业务目标，须实现所写结果。当前目标完成立即complete=true、action=null，将控制交回框架。"
                                   "完成后来源区块可消失或变为结果区块，按真实结果确认complete，不为保持旧区块可见而回退。"
                                   "click、input_text、long_press、scroll都必须给当前图0至1000的point_1000；输入框已聚焦也不能省略输入点位或填null。只有back、wait无需点位。采集中的新控件owner_ref可为空。"
                                   "不能用未显示的功能、输入凭据或执行超出用户目标的危险动作。"
                                   "完成目标或条件时action=null；否则至多一个动作。"
                                   + ("已知目标visual_target_ref复制known_visual_controls中的ref，未登记目标填null；"
                                      "不能把目标换成坐标附近的其他控件来通过核对。已知目标action.target复制该ref的name，不填ref或内部ID；未知目标写实际控件和必要对象。"
                                      "action_intent写这一个动作期待的直接可见效果；无动作填空。"
                                      "grounding_feedback拒绝的提议未执行，不是上一动作，不要报告它的结果；"
                                      "根据最新截图重新定位，不盲重发。反馈box为像素，动作仍用0..1000。"
                                      "previous_action_observation只写实际观察，previous_action_matches_intent说明是否实现上一步意图。"
                                      "success仅指预期直接效果已发生；误碰别的开关不是success或no_effect，应填uncertain并描述副作用。"
                                      "无待结算动作时observation为空、matches_intent=null。"
                                      if self.visual_guard is not None else "")),
                    user_prompt=json.dumps(context, ensure_ascii=False))
                calls += 1
                if pending_receipt:
                    outcome = decision.get("previous_action_outcome", "uncertain")
                    trajectory[-1]["verification"] = {"outcome": outcome, "reason": decision.get("reason", "")}
                    if self.visual_guard is not None:
                        receipt = trajectory[-1]["verification"]
                        receipt.update(reported_outcome=outcome,
                                       observation=decision.get("previous_action_observation", ""),
                                       matches_intent=decision.get("previous_action_matches_intent"))
                        if outcome == "success" and (receipt["matches_intent"] is not True or not receipt["observation"].strip()):
                            receipt["outcome"] = "uncertain"
                    trajectory[-1]["committed"] = trajectory[-1]["verification"]["outcome"] == "success"
                    if outcome not in {"success", "no_effect", "uncertain"}:
                        errors.append("Missing explicit previous GUI action outcome")
                        break
                if decision.get("app_scope") != "target_app":
                    errors.append("Agent cannot confirm target app surface")
                    break
                visible = [ref for ref in decision.get("visible_region_refs", []) if ref in self.ledger.regions]
                value = decision.get("condition_value")
                if kind == "condition" and type(value) is bool and decision.get("region_visible"):
                    branch = value
                    goal_frames.append(frame)
                    decisions.append({"condition": goal, "value": value, "reason": decision.get("reason", ""),
                                      "observation": observation})
                    queue.pop(0)
                    queue[:0] = [("goal", x) for x in task["if_true" if value else "if_false"] + task["after"]]
                    continue
                if kind == "goal" and decision.get("complete") is True:
                    completed.append({**goal, "complete": True, "reason": decision.get("reason", ""),
                                      "observation": observation})
                    if trajectory and trajectory[-1].get("committed"):
                        before_confirmation = trajectory[-1]["observation_before"].get("screenshot")
                        if before_confirmation and before_confirmation not in goal_frames:
                            goal_frames.append(before_confirmation)
                    goal_frames.append(frame)
                    queue.pop(0)
                    continue
                action = _parse_action(decision.get("action"))
                if action is None:
                    observation = self.env._get_obs()
                    continue
                issue = validate_for_platform(action, platform=self.platform)
                if issue:
                    raise ValueError(issue)
                grounding = None
                if self.visual_guard is not None:
                    grounding = self.visual_guard.check(action, decision, frame, self.agent)
                    if not grounding["allowed"]:
                        grounding_feedback = grounding
                        observation = self.env._get_obs()
                        continue
                    grounding_feedback = None
                before = observation
                primitives = []
                trajectory.append({"kind": "region_goal", "app_id": self.scope.app_name,
                                   "ref_id": goal["region_ref"], "action_steps": 1, "committed": False,
                                   "observation_before": before, "observation_after": None,
                                   "grounding": {"primitive_actions": primitives, "visual_check": grounding},
                                   "action_intent": decision.get("action_intent"),
                                   "context_node_id": None, "arrived_node_id": None,
                                   "action_spec": action_dict(action), "verification": None,
                                   "graph_provenance": {"target_region_ref": goal["region_ref"],
                                                        "goal": goal["goal"], "branch_taken": branch}})
                observation = execute_action(self.env, action, screenshot=frame, platform=self.platform,
                                             executed_actions=primitives)
                trajectory[-1]["observation_after"] = observation
                if observation.get("action_error"):
                    errors.append(str(observation["action_error"]))
                    break
            verification = {}
            if not queue and not errors:
                verification = self.agent._call(
                    role="region_collection_final", screenshots=goal_frames + [observation["screenshot"]],
                    response_schema={"type": "object", "properties": {
                        "complete": {"type": "boolean"}, "reason": {"type": "string"}},
                        "required": ["complete", "reason"], "additionalProperties": False},
                    system_prompt="检查所选分支和共同目标是否有实际截图证据。图按条件和目标完成顺序排列，含最近成功动作的提交前帧和完成帧，最后一图是最新画面。提交前参数需结合动作后结果判断，历史完成不保证仍成立，核对后续是否撤销了目标；预期不是事实。",
                    user_prompt=json.dumps({"instruction": task["instruction"], "branch_taken": branch, "condition": task["condition"],
                                            "observed_goals": [{key: value for key, value in item.items() if key != "observation"}
                                                               for item in completed]}, ensure_ascii=False))
                calls += 1
                success = verification.get("complete") is True
        except Exception as exc:
            errors.append(str(exc))
            verification = {}
        for step in trajectory:
            step["action_steps"] = len(step["grounding"]["primitive_actions"])
        return {"executor": "RegionGuidedCollector",
                "instruction_id": task.get("instruction_id", "REGION"), "instruction": task["instruction"],
                "success": success, "final_status": "complete" if success else "partial",
                "grounding_checks": self.visual_guard.checks if self.visual_guard is not None else [],
                "trajectory": trajectory, "ref_results": completed, "branch_taken": branch,
                "branch_decisions": decisions, "final_verification": verification,
                "final_observation": observation,
                "total_action_steps": sum(x["action_steps"] for x in trajectory), "model_calls": calls + (self.visual_guard.model_calls if self.visual_guard is not None else 0), "errors": errors}


def build_region_model_agent(backend, model, output_root):
    from ..explore.agent import CodexExplorerAgent, OpenAIAPIExplorerAgent, QwenExplorerAgent
    if backend == "openai_api":
        from ..explore.api_config import load_explore_api_config, local_explore_api_config_path
        cfg = load_explore_api_config(local_explore_api_config_path())
        return OpenAIAPIExplorerAgent(base_url=cfg.base_url, api_key=cfg.api_key,
                                      model=model or cfg.model, reasoning_effort=cfg.reasoning_effort,
                                      timeout=cfg.timeout_seconds, output_root=output_root)
    if backend == "codex_cli":
        return CodexExplorerAgent(model=model or "gpt-5.6-luna", output_root=output_root)
    from gui_rewalk.env.gui_gen_agent import GUIGenAgent
    chosen = model or "qwen3.7-plus"
    return QwenExplorerAgent(transport=GUIGenAgent(model="Qwen", model_version=chosen),
                             model=chosen, output_root=output_root)


__all__ = ["RegionGuidedCollector", "design_region_instruction", "validate_region_instruction",
           "build_region_model_agent"]
