"""Capability-driven instruction generator (shortest chain).

Reads synthesized page_capabilities.json (D12) and composes user-facing
instructions directly, bypassing the older TaskComposer / ScenarioGenerator
pipelines. Key feature: runtime-slot parameters.

A capability's param can be:
  - compile-time known (enum with explicit `values`)  -> instruction fills a value
  - runtime-only (`source: discover_at_runtime`)       -> left as a <runtime>
    placeholder and recorded in `runtime_slots`, to be filled during live
    rollout when the real page/options are observed (PROJECT_GOAL section 3).

Design: see design/design_decisions.md D12 (and the capability synthesizer).
Output instructions carry capability refs plus visual element grounding for the
future screenshot-only collection engine.
"""

from __future__ import annotations

import glob
import json
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

logger = logging.getLogger("desktopenv.scenario.cap_instruction_gen")

RUNTIME_PLACEHOLDER = "<runtime>"
# Discovery is enough to propose and attempt a task; live results prove success.
TASK_ELIGIBLE_VERIFICATION_LEVELS = frozenset({
    "discovered", "executable", "effect_verified", "composable",
})


def _execution_recipe_from_mapping(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    recipe: Any = raw.get("execution_recipe")
    if recipe is None:
        recipe = raw.get("action_recipe")
    if recipe is None:
        recipe = raw.get("actions")
    if isinstance(recipe, dict):
        recipe = [recipe]
    if not isinstance(recipe, list):
        return []
    return [dict(step) for step in recipe if isinstance(step, dict)]


def _is_task_eligible_capability(raw: Mapping[str, Any]) -> bool:
    """Select known candidates without promoting their evidence status."""
    verification_level = str(
        raw.get("verification_level") or "").strip().casefold()
    if verification_level:
        return verification_level in TASK_ELIGIBLE_VERIFICATION_LEVELS
    lifecycle = str(raw.get("status") or "").strip().casefold()
    availability = str(
        raw.get("availability_status") or "").strip().casefold()
    if lifecycle in {"discovered", "executable", "verified"} or availability in {
            "discovered", "executable", "verified"}:
        return True
    return not lifecycle and not availability


@dataclass
class CapabilityRef:
    """A capability referenced by an instruction, with grounding."""
    node_id: str
    page_name: str
    name: str                       # capability name (verb phrase)
    param_type: str                 # continuous / boolean / enum / none
    slot: str = ""                  # parameter slot name (if parameterized)
    value: str = ""                 # filled value, or RUNTIME_PLACEHOLDER
    runtime: bool = False           # True if value must be discovered at runtime
    elements: List[str] = field(default_factory=list)
    element_map: Dict[str, List[str]] = field(default_factory=dict)
    # For a navigation capability (e.g. "进入设置分类页面" with value
    # "Sound & vibration") node_id is where the control LIVES (the parent/home
    # page) while target_node is the page you LAND on after the click. Graph nav
    # must aim at the landing page, not the control's page, or it concludes
    # "already at target" and never navigates. Defaults to node_id when the ref
    # is not a resolvable navigation (see _resolve_nav_target).
    target_node: str = ""
    app_id: str = ""
    capability_id: str = ""
    requires: List[Dict[str, Any]] = field(default_factory=list)
    effects: List[Dict[str, Any]] = field(default_factory=list)
    success_predicate: str = ""
    observables: List[Dict[str, Any]] = field(default_factory=list)
    setup_recipe: List[Dict[str, Any]] = field(default_factory=list)
    execution_recipe: List[Dict[str, Any]] = field(default_factory=list)
    recovery: List[Dict[str, Any]] = field(default_factory=list)
    cleanup: List[Dict[str, Any]] = field(default_factory=list)
    availability_status: str = "verified"
    risk_level: str = "normal"
    verification_level: str = ""
    action_steps: int = 1
    depends_on: List[str] = field(default_factory=list)
    params: Dict[str, Any] = field(default_factory=dict)
    desired_outcome: Any = None

    def to_dict(self) -> Dict[str, Any]:
        value = {
            "node_id": self.node_id,
            "page_name": self.page_name,
            "name": self.name,
            "param_type": self.param_type,
            "slot": self.slot,
            "value": self.value,
            "runtime": self.runtime,
            "elements": self.elements,
            "element_map": self.element_map,
            "target_node": self.target_node,
            "app_id": self.app_id,
            "capability_id": self.capability_id,
            "requires": self.requires,
            "effects": self.effects,
            "success_predicate": self.success_predicate,
            "observables": self.observables,
            "setup_recipe": self.setup_recipe,
            "execution_recipe": self.execution_recipe,
            "recovery": self.recovery,
            "cleanup": self.cleanup,
            "availability_status": self.availability_status,
            "risk_level": self.risk_level,
            "action_steps": self.action_steps,
            "depends_on": self.depends_on,
            "params": self.params,
        }
        if self.desired_outcome is not None:
            value["desired_outcome"] = self.desired_outcome
        if self.verification_level:
            value["verification_level"] = self.verification_level
        return value


@dataclass
class Instruction:
    """A generated user-facing instruction backed by capabilities."""
    instruction_id: str
    type: str                       # single / cross_page / conditional
    instruction: str                # natural-language, user voice
    capability_refs: List[CapabilityRef] = field(default_factory=list)
    runtime_slots: List[str] = field(default_factory=list)
    params: Dict[str, str] = field(default_factory=dict)
    apps_involved: List[str] = field(default_factory=list)
    fixed_order: bool = True

    def to_dict(self) -> Dict[str, Any]:
        return {
            "instruction_id": self.instruction_id,
            "type": self.type,
            "instruction": self.instruction,
            "capability_refs": [r.to_dict() for r in self.capability_refs],
            "runtime_slots": self.runtime_slots,
            "params": self.params,
            "apps_involved": self.apps_involved,
            "fixed_order": self.fixed_order,
        }


@dataclass
class _Cap:
    """Internal: a capability loaded from page_capabilities.json."""
    node_id: str
    page_name: str
    name: str
    param_type: str
    current: str
    values: List[str]
    source: str
    slot: str
    elements: List[str]
    element_map: Dict[str, List[str]]
    app_id: str = ""
    capability_id: str = ""
    requires: List[Dict[str, Any]] = field(default_factory=list)
    effects: List[Dict[str, Any]] = field(default_factory=list)
    success_predicate: str = ""
    observables: List[Dict[str, Any]] = field(default_factory=list)
    setup_recipe: List[Dict[str, Any]] = field(default_factory=list)
    execution_recipe: List[Dict[str, Any]] = field(default_factory=list)
    recovery: List[Dict[str, Any]] = field(default_factory=list)
    cleanup: List[Dict[str, Any]] = field(default_factory=list)
    availability_status: str = "verified"
    risk_level: str = "normal"
    verification_level: str = ""
    action_steps: int = 1

    @property
    def is_runtime(self) -> bool:
        """Whether this capability's parameter must be resolved at runtime."""
        if self.source == "discover_at_runtime":
            return True
        # enum/parameterized with no concrete values listed → runtime
        if self.param_type == "enum" and not self.values and not self.element_map:
            return True
        return False


_PROMPT = """你是 GUI 任务设计专家。下面是从一个应用状态图里提取的【功能清单】，
每条功能含：所属页面、功能名、参数类型，以及参数是"编译期已知"还是"运行时才能确定"。

请基于这些功能设计 {n} 条贴近真实用户口吻的指令，要求：
1. 指令像真人说话（"帮我…""我想…""能不能…"），不要罗列功能名。
2. 三种类型尽量都覆盖：
   - single：完成单个功能
   - cross_page：串 2-3 个不同页面的功能成一个合理目标
   - conditional：带"如果…就…否则…"，条件基于某功能当前状态
3. **每个子目标都要具体、可执行**：含明确的目标页面 + 具体操作 + 具体取值。
   禁止"打开X的详细设置界面""看看X"这类只到页面、没有操作和取值的含糊说法；
   每个用到的功能都必须在指令文本里有对应的一句可执行子目标，不能只在 refs 里挂名。
4. 参数处理（重要）：
   - 功能 runtime=no 且有可选值的：**直接填一个具体值**（如主题=Dark、缩放=200%）。
   - 只有真要到实机页面看到才知道的值才写 "{placeholder}" 并列进 runtime_slots
     （比如壁纸文件名、具体的输出设备型号、列表里的某一项）。能事前定的一律写死。
5. 每条指令标注用到的功能名（capability_refs，原样抄"页面::功能名"）。

只输出 JSON：
{{"instructions":[
  {{"type":"single|cross_page|conditional","instruction":"...",
    "capability_refs":["页面::功能名"],
    "params":{{"槽名":"值或{placeholder}"}},
    "runtime_slots":["需运行时确定的槽名"]}}
]}}

功能清单：
{inventory}
"""


_PROMPT_LONG = """你是 GUI 任务设计专家。下面是从一个应用状态图里提取的【功能清单】，
每条功能含：所属页面、功能名、参数类型，以及参数是"编译期已知"还是"运行时才能确定"。

请基于这些功能设计 {n} 条**中等复杂度**用户指令，要求：
1. 指令像真人说话（"帮我…""顺便…""然后…"），把相关设置整理成一个合理的生活场景目标。
2. **每条指令串联 3-4 个功能**（cross_page 为主），形成约 6-12 步的操作链。
   不要贪心地串太多功能——宁可短而连贯，也不要长而散乱。
3. **优先选同一设置区域、彼此相邻的功能**（如都在声音页、或声音→通知这种相近页面），
   减少在多个不相关页面间反复跳转（跨页跳转越多，agent 越容易迷路）。
4. **每个子目标都要具体、可执行、含明确的目标页面 + 具体操作 + 具体取值**——
   像"先切换到外观设置页面，把桌面背景换成日落田野的预设图片，再把系统主题改成深色模式"。
   - **禁止含糊动词**：不要写"打开X的详细设置界面/页面""看看X""配置一下X"这类只到页面、
     没有具体操作和取值的说法。要写成"进入 Network 页面，把 Network Proxy 模式切到 Manual"。
   - 每个用到的功能（capability_refs 里的每一项）都必须在指令文本里有一句对应的、
     可执行的子目标——**不能漏掉某个功能只在 refs 里挂名**（否则采集会少做一步）。
   - 子目标顺序 = capability_refs 顺序 = 真实操作顺序。
5. 参数处理：
   - 功能 runtime=no 且有可选值的：**直接填一个具体值**（如主题=Dark、缩放=200%、模式=Manual）。
   - 只有"真要到实机页面看到才知道"的值才写 "{placeholder}" 并列进 runtime_slots
     （例：壁纸文件列表里的某个文件名、输出设备的具体型号）。能事前定的一律写死，别滥用 placeholder。
6. 每条指令标注用到的功能名（capability_refs，原样抄"页面::功能名"，按操作顺序排列）。

只输出 JSON：
{{"instructions":[
  {{"type":"cross_page","instruction":"...",
    "capability_refs":["页面::功能名1","页面::功能名2","..."],
    "params":{{"槽名":"值或{placeholder}"}},
    "runtime_slots":["需运行时确定的槽名"]}}
]}}

功能清单：
{inventory}
"""


_DESIRED_OUTCOME_PROMPT = """

For every state-setting capability in capability_refs, explicitly state the
requested observable result without using a page variant. Add a JSON object
named "desired_outcomes" keyed by the exact capability_refs string. Use JSON
booleans for on/off outcomes and a concrete string/number for other settings.
Example: "desired_outcomes":{"Settings::Set notifications":false}.
Do not add desired_outcomes entries for pure navigation or open-page actions.
"""


class CapabilityInstructionGenerator:
    """Generate user-facing instructions directly from page capabilities."""

    def __init__(self, node_dir: str, agent: Any, graph: Any = None,
                 app_id: str = ""):
        self.node_dir = node_dir
        self.agent = agent
        self.app_id = str(
            app_id or getattr(graph, "app_name", "") or "")
        self._caps: List[_Cap] = []
        self._by_key: Dict[str, _Cap] = {}
        # graph-awareness (D13.1): filter capabilities unreachable from the root
        self.G = graph.graph if (graph is not None and hasattr(graph, "graph")) else graph
        self._reach: set = set()
        if self.G is not None:
            self._init_graph()

    def _init_graph(self) -> None:
        """Identify the real root and the set of nodes reachable from it.

        The root is the traversal home page (e.g. the Settings home), from
        which the rest of the app is reachable — NOT a leaf or a mid-tree hub.

        Earlier this used max out-degree, but that is wrong on apps where a
        mid-tree hub (e.g. the app-list page) links to more nodes than the
        home page: it picked a deep node and only 12/113 nodes were reachable,
        dropping 342/368 capabilities. We now pick the node whose reachable
        set is LARGEST — the true entry point by construction — preferring
        in-degree-0 nodes (genuine roots) as a cheap tie-break/shortlist.
        """
        import networkx as nx
        nodes = list(self.G.nodes())
        if not nodes:
            self._reach = set()
            return
        # Candidate shortlist: in-degree-0 nodes (real entry points). Fall back
        # to all nodes if the graph has none (fully cyclic).
        candidates = [n for n in nodes if self.G.in_degree(n) == 0] or nodes

        def _reach_of(n):
            return nx.descendants(self.G, n) | {n}

        best = max(candidates, key=lambda n: len(_reach_of(n)))
        best_reach = _reach_of(best)
        # Safety net: if some other node reaches strictly more (e.g. the only
        # in-degree-0 node is itself a stranded orphan), prefer that.
        global_best = max(nodes, key=lambda n: len(_reach_of(n)))
        if len(_reach_of(global_best)) > len(best_reach):
            best, best_reach = global_best, _reach_of(global_best)
        self._reach = best_reach
        logger.info("Graph root=%s, reachable=%d/%d",
                    str(best)[:8], len(self._reach), self.G.number_of_nodes())


    # ── loading ───────────────────────────────────────────────────────

    def load_capabilities(self) -> int:
        """Load every page_capabilities.json under node_dir."""
        self._caps = []
        skipped_ineligible = 0
        for p in sorted(glob.glob(os.path.join(self.node_dir, "*", "page_capabilities.json"))):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    d = json.load(f)
            except Exception:
                continue
            node_id = os.path.basename(os.path.dirname(p))
            page_app_id = str(d.get("app_id", "") or self.app_id)
            page_name = self._short_page_name(d.get("page_name", ""), node_id)
            for c in d.get("capabilities", []) or []:
                if not isinstance(c, Mapping) or not _is_task_eligible_capability(c):
                    skipped_ineligible += 1
                    continue
                name = str(c.get("name", "") or "").strip()
                if not name:
                    continue
                pm = c.get("param", {}) or {}
                execution_recipe = _execution_recipe_from_mapping(c)
                availability = str(c.get("availability_status") or c.get("status")
                                   or c.get("verification_level") or "verified")
                if availability in {"effect_verified", "composable"}:
                    availability = "verified"
                cap = _Cap(
                    node_id=node_id,
                    verification_level=str(
                        c.get("verification_level", "") or ""),
                    page_name=page_name,
                    name=name,
                    param_type=str(pm.get("type", "none") or "none").strip().lower(),
                    current=str(pm.get("current", "") or "").strip(),
                    values=[str(v).strip() for v in (pm.get("values") or []) if str(v).strip()],
                    source=str(pm.get("source", "") or "").strip(),
                    slot=str(pm.get("slot", "") or "").strip(),
                    elements=[str(e) for e in (c.get("elements") or [])],
                    element_map={str(k): [str(v) for v in (vs or [])]
                                 for k, vs in (pm.get("element_map") or c.get("element_map") or {}).items()},
                    app_id=str(c.get("app_id", "") or page_app_id),
                    capability_id=str(c.get("capability_id", "") or ""),
                    requires=[dict(v) for v in (c.get("requires") or [])
                              if isinstance(v, dict)],
                    effects=[dict(v) for v in (c.get("effects") or [])
                             if isinstance(v, dict)],
                    success_predicate=str(
                        c.get("success_predicate", "") or ""),
                    observables=[dict(v) for v in (c.get("observables") or [])
                                 if isinstance(v, dict)],
                    setup_recipe=[dict(v) for v in (c.get("setup_recipe") or [])
                                  if isinstance(v, dict)],
                    execution_recipe=execution_recipe,
                    recovery=[dict(v) for v in (c.get("recovery") or [])
                              if isinstance(v, dict)],
                    cleanup=[dict(v) for v in (c.get("cleanup") or [])
                             if isinstance(v, dict)],
                    availability_status=availability,
                    risk_level=str(c.get("risk_level", "normal") or "normal"),
                    action_steps=self._safe_action_steps(
                        c.get("action_steps", len(execution_recipe) or 1)),
                )
                self._caps.append(cap)
                if cap.app_id:
                    self._by_key[
                        f"{cap.app_id}::{cap.page_name}::{cap.name}"] = cap
                self._by_key[f"{cap.page_name}::{cap.name}"] = cap
                self._by_key[cap.name] = cap  # also key by bare name
        # graph-aware filter: drop caps on nodes unreachable from the root,
        # so generated instructions can't reference dead-end pages (D13.1).
        if self.G is not None and self._reach:
            before = len(self._caps)
            self._caps = [c for c in self._caps
                          if not c.node_id or c.node_id in self._reach]
            dropped = before - len(self._caps)
            if dropped:
                logger.info("Graph filter: dropped %d caps on unreachable nodes",
                            dropped)
            self._by_key = {}
            for c in self._caps:
                if c.app_id:
                    self._by_key[f"{c.app_id}::{c.page_name}::{c.name}"] = c
                self._by_key[f"{c.page_name}::{c.name}"] = c
                self._by_key[c.name] = c
        logger.info("Loaded %d capabilities from %s", len(self._caps), self.node_dir)
        if skipped_ineligible:
            logger.info(
                "Skipped %d capability record(s) without a recognized discovery "
                "status", skipped_ineligible)
        return len(self._caps)

    @staticmethod
    def _safe_action_steps(value: Any) -> int:
        try:
            return max(0, int(value))
        except (TypeError, ValueError):
            return 1

    @staticmethod
    def _short_page_name(raw: str, fallback: str) -> str:
        """Extract a short page label from a (possibly long) page_name/summary."""
        if not raw:
            return fallback[:8]
        # prefer a quoted section name, e.g. "...the 'Sound' settings..."
        m = re.search(r"'([^']{2,40})'", raw)
        if m:
            return m.group(1)
        first = raw.split(".")[0].split(",")[0].strip()
        return first[:40] if first else fallback[:8]

    # ── inventory text ────────────────────────────────────────────────

    def _inventory_text(self) -> str:
        lines: List[str] = []
        for c in self._caps:
            runtime = "yes" if c.is_runtime else "no"
            extra = ""
            if c.slot:
                opts = list(c.element_map.keys()) or c.values
                extra = f" 槽={c.slot} 可选={opts[:8]}" if opts else f" 槽={c.slot}"
            elif c.values:
                extra = f" 可选值={[v[:20] for v in c.values[:6]]}"
            elif c.current:
                extra = f" 当前={c.current}"
            if c.requires:
                extra += " 前置=" + json.dumps(
                    c.requires, ensure_ascii=False, separators=(",", ":"))
            extra += f" 页内最少动作={c.action_steps} 状态={c.availability_status}"
            lines.append(
                f"[{c.app_id}::{c.page_name}::{c.name}] 参数类型={c.param_type} "
                f"runtime={runtime}{extra}")
        return "\n".join(lines)

    # ── generation ────────────────────────────────────────────────────

    def generate(self, n: int = 6, long_chain: bool = False) -> List[Instruction]:
        """Generate n instructions from loaded capabilities.

        long_chain=True asks for complex multi-page chains (4-6 capabilities
        each, ~10+ steps) instead of the default mixed single/cross/conditional.
        """
        if not self._caps:
            self.load_capabilities()
        if not self._caps:
            logger.warning("No capabilities loaded; nothing to generate")
            return []

        template = _PROMPT_LONG if long_chain else _PROMPT
        prompt = template.format(
            n=n, placeholder=RUNTIME_PLACEHOLDER, inventory=self._inventory_text())
        prompt += _DESIRED_OUTCOME_PROMPT
        try:
            resp, *_ = self.agent.predict_mm(prompt, [])
        except Exception as e:
            logger.warning("Instruction generation LLM call failed: %s", e)
            return []

        raw = resp.strip()
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            raw = m.group(0)
        try:
            data = json.loads(raw)
        except Exception as e:
            logger.warning("Instruction JSON parse failed: %s", e)
            return []

        out: List[Instruction] = []
        for i, ins in enumerate(data.get("instructions", []), 1):
            instr_text = str(ins.get("instruction", "") or "").strip()
            if not instr_text:
                continue
            raw_refs = ins.get("capability_refs") or []
            if not isinstance(raw_refs, list) or not raw_refs:
                continue
            refs = self._resolve_refs(
                raw_refs,
                ins.get("params", {}) or {},
                ins.get("desired_outcomes", {}) or {},
            )
            if len(refs) != len(raw_refs):
                continue
            runtime_slots = [str(s) for s in (ins.get("runtime_slots") or [])]
            # auto-augment runtime_slots from resolved refs (don't rely on LLM only)
            for r in refs:
                if r.runtime and r.slot and r.slot not in runtime_slots:
                    runtime_slots.append(r.slot)
            out.append(Instruction(
                instruction_id=f"CAP{i:03d}",
                type=str(ins.get("type", "single") or "single").strip(),
                instruction=instr_text,
                capability_refs=refs,
                runtime_slots=runtime_slots,
                params={str(k): str(v) for k, v in (ins.get("params", {}) or {}).items()},
                apps_involved=list(dict.fromkeys(
                    r.app_id for r in refs if r.app_id)),
                fixed_order=True,
            ))
        logger.info("Generated %d instructions (%d with runtime slots)",
                    len(out), sum(1 for o in out if o.runtime_slots))
        return out

    @staticmethod
    def _norm_edge_label(s: str) -> str:
        """Strip the 'Click <role>: ' prefix from a graph edge label.

        Edge labels are stored as e.g. 'Click list-item: Sound & vibration';
        the navigation capability's element_map / param value is the bare name
        'Sound & vibration'. Normalize both to the bare lowercased name.
        """
        return re.sub(r"^click [a-z-]+:\s*", "", (s or "").strip().lower())

    def _resolve_nav_target(self, src_node: str, value: str) -> str:
        """Resolve a navigation capability's value to the page it lands on.

        For a category-navigation capability (e.g. value 'Sound & vibration'
        clicked on the Settings home), find the out-edge of *src_node* whose
        label names that value and return its target node — that's the real
        goal page. Returns '' if no graph, no value, or no matching edge (e.g.
        the category was never traversed → off-graph; caller keeps src_node and
        lets the VLM find it). Name-matched, not id-matched: element ids differ
        between capability synthesis and the graph edges, but labels are stable.
        """
        if self.G is None or not src_node or not value:
            return ""
        if value == RUNTIME_PLACEHOLDER or src_node not in self.G:
            return ""
        want = value.strip().lower()
        if not want:
            return ""
        # exact label match first, then bidirectional substring
        fuzzy = None
        for _, tgt, ed in self.G.out_edges(src_node, data=True):
            lbl = self._norm_edge_label(ed.get("element_label", ""))
            if not lbl:
                continue
            if lbl == want:
                return tgt
            if fuzzy is None and (want in lbl or lbl in want):
                fuzzy = tgt
        return fuzzy or ""

    def _resolve_refs(
        self,
        ref_names: List[str],
        params: Dict[str, Any],
        desired_outcomes: Optional[Mapping[str, Any]] = None,
    ) -> List[CapabilityRef]:
        """Map LLM-cited capability names back to loaded caps + grounding."""
        desired_outcomes = desired_outcomes or {}
        refs: List[CapabilityRef] = []
        for rn in ref_names:
            key = str(rn).strip()
            cap = self._by_key.get(key)
            if cap is None and "::" in key:
                cap = self._by_key.get(key.split("::", 1)[1])
            if cap is None:
                # fuzzy: match by bare name contained
                for k, c in self._by_key.items():
                    if key and (key in k or k in key):
                        cap = c
                        break
            if cap is None:
                continue
            # determine the value for this ref
            value = ""
            runtime = cap.is_runtime
            if cap.slot and cap.slot in params:
                value = str(params[cap.slot])
            if runtime:
                value = RUNTIME_PLACEHOLDER
            desired_outcome = None
            for desired_key in (key, cap.name, cap.capability_id):
                if desired_key and desired_key in desired_outcomes:
                    desired_outcome = desired_outcomes[desired_key]
                    break
            # Navigation resolution: if this capability's value names a page
            # reachable by one click from cap.node_id, the real goal is that
            # landing page — set target_node so graph nav aims there instead of
            # concluding "already at target" (the control's own page). Only
            # fires for compile-time values; runtime placeholders resolve live.
            target_node = self._resolve_nav_target(cap.node_id, value)
            refs.append(CapabilityRef(
                node_id=cap.node_id,
                page_name=cap.page_name,
                name=cap.name,
                param_type=cap.param_type,
                slot=cap.slot,
                value=value,
                runtime=runtime,
                elements=cap.elements,
                element_map=cap.element_map,
                target_node=target_node,
                app_id=cap.app_id or self.app_id,
                capability_id=cap.capability_id,
                requires=cap.requires,
                effects=cap.effects,
                success_predicate=cap.success_predicate,
                observables=cap.observables,
                setup_recipe=cap.setup_recipe,
                execution_recipe=cap.execution_recipe,
                recovery=cap.recovery,
                cleanup=cap.cleanup,
                availability_status=cap.availability_status,
                verification_level=cap.verification_level,
                risk_level=cap.risk_level,
                action_steps=cap.action_steps,
                params={str(k): v for k, v in params.items()},
                desired_outcome=desired_outcome,
            ))
        return refs

    # ── persistence ───────────────────────────────────────────────────

    def save(self, instructions: List[Instruction], path: str) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump([i.to_dict() for i in instructions], f,
                      ensure_ascii=False, indent=2)
        logger.info("Saved %d instructions to %s", len(instructions), path)
