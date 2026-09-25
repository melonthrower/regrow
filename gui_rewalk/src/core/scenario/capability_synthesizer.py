"""Capability Synthesizer: synthesize human-oriented page capabilities from
graph node elements via a single VLM call.

Phase 2 Step 0 over pure-visual node artifacts.

Design: see design/design_decisions.md D12.
- Plan X: fully independent of traversal. Reads traversal artifacts
  (screenshot + elements), does NOT modify the BFS / exploration VLM call.
- Plan A: parameterized merging of structurally-identical repeated functions.
- Rich explain: page_breakdown prose + per-capability detailed explanation.

The synthesizer reuses visual grounding data from ``elements.json`` and asks the
VLM to organize it into named capabilities that map back to visual element ids.
"""

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np

logger = logging.getLogger("desktopenv.scenario.capability_synth")

CAPABILITY_FILE = "page_capabilities.json"
CAPABILITY_ENRICHMENT_FILE = "page_capabilities_enrichment.json"


def _nonnegative_int(value: Any, default: int = 1) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return max(0, int(default))


def _execution_recipe_from_raw(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Read the canonical recipe while accepting historical field names."""
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


@dataclass
class Capability:
    """A single human-oriented page capability mapped to grounding elements."""
    name: str
    param_type: str = "none"            # continuous / boolean / enum / none
    current: str = ""                   # boolean on/off, or enum current value
    values: List[str] = field(default_factory=list)     # enum visible options
    source: str = ""                    # "discover_at_runtime" if options need opening
    slot: str = ""                      # object slot name for parameterized merge
    elements: List[str] = field(default_factory=list)    # element_ids (non-param)
    element_map: Dict[str, List[str]] = field(default_factory=dict)  # {obj: [id]}
    explain: str = ""
    region: str = ""                    # [3-level] sub-region role this function lives
                                        # in: content / toolbar / tab_bar / form /
                                        # action_bar / dialog / other. Enables the
                                        # node->region->function grouping.
    app_id: str = ""
    capability_id: str = ""
    entry_surfaces: List[str] = field(default_factory=list)
    input_slots: List[Dict[str, Any]] = field(default_factory=list)
    requires: List[Dict[str, Any]] = field(default_factory=list)
    effects: List[Dict[str, Any]] = field(default_factory=list)
    success_predicate: str = ""
    observables: List[Dict[str, Any]] = field(default_factory=list)
    setup_recipe: List[Dict[str, Any]] = field(default_factory=list)
    execution_recipe: List[Dict[str, Any]] = field(default_factory=list)
    recovery: List[Dict[str, Any]] = field(default_factory=list)
    cleanup: List[Dict[str, Any]] = field(default_factory=list)
    # A screenshot can establish that a control is visible, not that its
    # business effect works.  Traversal promotes the online graph record only
    # after a real action + landing verification; offline synthesis therefore
    # defaults to discovered and may preserve an explicitly persisted verified
    # value when reading a newer artifact.
    availability_status: str = "discovered"
    risk_level: str = "normal"
    action_steps: int = 1

    def bind_context(self, app_id: str, node_id: str, page_name: str) -> None:
        """Fill stable graph provenance that a screenshot-only VLM cannot know."""
        self.app_id = self.app_id or str(app_id or "")
        if not self.entry_surfaces:
            self.entry_surfaces = [str(node_id)] if node_id else []
        if not self.capability_id:
            raw = "|".join((self.app_id, str(node_id), str(page_name),
                            self.region, self.name))
            self.capability_id = hashlib.sha256(
                raw.encode("utf-8")).hexdigest()[:16]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "region": self.region,
            "param": {
                "type": self.param_type,
                "current": self.current,
                "values": self.values,
                "source": self.source,
                "slot": self.slot,
            },
            "elements": self.elements,
            "element_map": self.element_map,
            "explain": self.explain,
            "app_id": self.app_id,
            "capability_id": self.capability_id,
            "entry_surfaces": self.entry_surfaces,
            "input_slots": self.input_slots,
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
        }

    @classmethod
    def from_raw(cls, raw: Dict[str, Any]) -> "Capability":
        p = raw.get("param", {}) or {}
        execution_recipe = _execution_recipe_from_raw(raw)
        return cls(
            name=str(raw.get("name", "")).strip(),
            param_type=str(p.get("type", "none") or "none").strip().lower(),
            current=str(p.get("current", "") or "").strip(),
            values=[str(v).strip() for v in (p.get("values") or []) if str(v).strip()],
            source=str(p.get("source", "") or "").strip(),
            slot=str(p.get("slot", "") or "").strip(),
            elements=[str(e).strip() for e in (raw.get("elements") or []) if str(e).strip()],
            element_map={
                str(k): [str(v) for v in (vs or [])]
                for k, vs in (p.get("element_map") or raw.get("element_map") or {}).items()
            },
            explain=str(raw.get("explain", "") or "").strip(),
            region=str(raw.get("region", "") or "").strip().lower(),
            app_id=str(raw.get("app_id", "") or ""),
            capability_id=str(raw.get("capability_id", "") or ""),
            entry_surfaces=[str(v) for v in (
                raw.get("entry_surfaces") or []) if str(v)],
            input_slots=[dict(v) for v in (raw.get("input_slots") or [])
                         if isinstance(v, dict)],
            requires=[dict(v) for v in (raw.get("requires") or [])
                      if isinstance(v, dict)],
            effects=[dict(v) for v in (raw.get("effects") or [])
                     if isinstance(v, dict)],
            success_predicate=str(raw.get("success_predicate", "") or ""),
            observables=[dict(v) for v in (raw.get("observables") or [])
                         if isinstance(v, dict)],
            setup_recipe=[dict(v) for v in (raw.get("setup_recipe") or [])
                          if isinstance(v, dict)],
            execution_recipe=execution_recipe,
            recovery=[dict(v) for v in (raw.get("recovery") or [])
                      if isinstance(v, dict)],
            cleanup=[dict(v) for v in (raw.get("cleanup") or [])
                     if isinstance(v, dict)],
            availability_status=str(
                raw.get("availability_status", "unknown") or "unknown"),
            risk_level=str(raw.get("risk_level", "normal") or "normal"),
            action_steps=_nonnegative_int(
                raw.get("action_steps", len(execution_recipe) or 1),
                len(execution_recipe) or 1,
            ),
        )


@dataclass
class PageCapabilities:
    node_id: str
    page_name: str
    page_breakdown: str
    capabilities: List[Capability] = field(default_factory=list)
    app_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        # [3-level] grouped view: node -> region -> functions. Derived from each
        # capability's `region` tag; falls back to a single "content" bucket when no
        # region tags are present (back-compat). The flat "capabilities" list is kept.
        regions: Dict[str, List[Dict[str, Any]]] = {}
        for c in self.capabilities:
            regions.setdefault(c.region or "content", []).append(c.to_dict())
        return {
            "node_id": self.node_id,
            "app_id": self.app_id,
            "page_name": self.page_name,
            "page_breakdown": self.page_breakdown,
            "capabilities": [c.to_dict() for c in self.capabilities],
            "regions": [{"region": r, "capabilities": caps} for r, caps in regions.items()],
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "PageCapabilities":
        page = cls(
            node_id=d.get("node_id", ""),
            app_id=str(d.get("app_id", "") or ""),
            page_name=d.get("page_name", ""),
            page_breakdown=d.get("page_breakdown", ""),
            capabilities=[Capability.from_raw(c) for c in d.get("capabilities", [])],
        )
        for capability in page.capabilities:
            capability.bind_context(page.app_id, page.node_id, page.page_name)
        return page


_PROMPT_TEMPLATE = """你是 GUI 功能分析专家。下面是一个应用页面的截图，以及视觉
grounder 在同一页面识别的元素清单。**以截图为主，元素清单用于语义和位置接地**。

请**以截图为主要依据**，模拟人类理解界面的方式，分三步分析：

【第一步：判断当前活跃表面】
看截图，判断当前真正活跃、可操作的是哪部分：
- 如果有弹层/下拉框/对话框打开，活跃表面就是那个弹层（背景被盖住的控件**不活跃**，忽略）。
- 否则活跃表面是当前主内容面板。

【第二步：区分"本页特有功能"和"通用边缘元素"】
在活跃表面里，区分两类元素：
- **通用边缘元素**（每个页面都有、不是本页特色）：左侧设置分类导航栏
  （Network/Bluetooth/Sound/Displays/Users 等一长串跳到别的页的项）、窗口标题栏
  （主菜单/汉堡菜单、搜索按钮、最小化/最大化/还原/关闭、应用标题）、纯页面切换标签。
  这些**一律不提取**。
- **本页特有功能**：只在这个页面出现、用来在本页实际操作设置的控件——开关、滑块、
  下拉选项、单选、输入框、本页的操作按钮、（若活跃表面是下拉框）下拉里的选项项 等。

【第三步：只从"本页特有功能"提取 capability】
- 如果整页几乎全是导航/边缘元素、只有极少数本页特有控件，那就**只提取那极少数**。
- 一个本页特有控件都没有也没关系，capabilities 就给空列表。

接地（element_id）：尽量为每个功能从"元素清单"里找到对应的真实 id 填进 elements。
**清单不一定有**——找不到就把 elements 留空、并在 explain 里描述它在截图中的视觉位置
（如"右侧内容区第3行的下拉框"），**不要为了凑 id 而编造清单里没有的 id**。

**屏幕下方元素（重要）**：元素清单里标了 `[屏幕下方-需滚动才可见]` 的元素，截图里看不到
（在当前视口下方，要滚动才显示），但它们**确实是本页的真实控件**。如果它们是本页特有的
内容功能（不是导航），**也要提取**，用清单里的 id 接地，并在 explain 注明"需向下滚动可见"。
不要因为截图里看不到就漏掉它们。

输出两部分：

【page_breakdown】：一段给人阅读的散文，只描述**本页特有功能**，逐条说明干什么、
当前状态、后果、使用场景。不要写导航栏/窗口控件。

【capabilities】：结构化功能列表，规则：
1. 命名用人类自然表达的简单操作（"调节系统整体音量""打开音量超限增益"），不要使用
   函数名、代码名或“点击第几个控件”这类机械描述。控件只是执行证据，不是功能名称。
2. 同模块内不同控件是不同功能（滑块=调值，开关=切状态，分开）。
3. **参数化归并**：多个功能**结构相同、只是作用对象不同**（"切换Files通知/切换Clocks通知/..."）
   必须合并成一个参数化功能：name用通用动词，param.type=enum，param.slot填对象语义名，
   param.values列对象名，param.element_map给{{对象名:[element_id...]}}。
   **语义不同的功能绝不能合并**。
4. 普通功能：boolean填current(on/off)；下拉/单选的实际选项填 enum，只有点开才知道时填
   source="discover_at_runtime"。数值滑条不要输出模糊 continuous 值，统一离散为 enum：
   slot="level"、values=["最小","一半","最大"]、source="fixed_semantic_anchors"。
   只有三个位置在当前画面上都能明确执行和验收时，才把该滑条列为可执行操作。
5. explain 要详细（当前状态、后果、场景）。
6. **region（区块归属，三层结构）**：给每个功能标它在活跃表面里所处的**子区块**——
   - 普通页：本页主内容面板里的功能填 `content`；页内工具栏/操作条填 `toolbar`。
   - 对话框/弹层：标签切换栏填 `tab_bar`，表单/主体填 `form`，底部确定取消等按钮条填
     `action_bar`，其它对话框控件填 `dialog`。
   - 拿不准就填 `content`。（导航侧栏/窗口控件本来就不提取，不用管。）
7. **可执行语义**：每个功能还要给出：
   - requires：截图能够证明的前置条件，kind 只能是 resource/state/authorization/login；
     不确定就给空列表，绝不能把“没看到”写成 unsupported。
   - effects：执行后可见状态会怎样变化。
   - success_predicate：只根据执行后截图，怎样判断这个功能已完成。
   - observables：完成后截图中可读取、可供后续功能使用的结果；没有就空列表。
   - availability_status：discovered/conditional/blocked/unknown 之一；仅凭本页截图看到控件只能填
     discovered，绝不能填 verified。verified 只能由遍历中的真实动作与落地验收写回能力图。
   - action_steps：从当前活跃表面执行该功能预计需要的最少 GUI 动作数，至少 1。
   - execution_recipe：按最少 GUI 步数给出可执行步骤。每步只允许动作类型、视觉语义 selector
     （element_label/type/region）和参数；参数槽用 `{{slot_name}}` 占位。禁止坐标、bbox、可访问性/DOM 选择器和脚本。
     动作限 CLICK/DOUBLE_CLICK/RIGHT_CLICK/LONG_PRESS/TYPE/PRESS/HOTKEY/BACK/SCROLL/DRAG/SET_SLIDER；
     数值滑条使用 SET_SLIDER + 当前滑条的语义 selector + parameters.level=`{{level}}`；
     DRAG 必须用 source_selector + target_selector 描述当前截图中可见的起点/终点，仍禁止坐标。
     例如：`{{"action_type":"CLICK","selector":{{"element_label":"Save","region":"action_bar"}}}}`、
     `{{"action_type":"TYPE","parameters":{{"text":"{{{{title}}}}"}}}}`。

只输出 JSON：
{{"active_surface":"一句话说明当前活跃表面是什么",
  "page_breakdown":"只讲本页特有功能的散文...",
  "capabilities":[
    {{"name":"...","region":"content/toolbar/tab_bar/form/action_bar/dialog","elements":["真实id或留空"],"param":{{"type":"...","current":"...","values":[...],"source":"...","slot":"...","element_map":{{}}}},"requires":[{{"kind":"resource/state/authorization/login","fact":"...","description":"..."}}],"effects":[{{"fact":"...","value":"..."}}],"success_predicate":"执行后截图中...","observables":[{{"name":"...","type":"text/number/state"}}],"availability_status":"discovered/conditional/blocked/unknown","action_steps":2,"execution_recipe":[{{"action_type":"CLICK","selector":{{"element_label":"...","region":"form"}}}},{{"action_type":"TYPE","parameters":{{"text":"{{{{slot_name}}}}"}}}}],"explain":"...（含视觉位置）"}}
  ]}}

参考元素清单（可能不全，以截图为准；id 用于接地，找不到可留空）：
{elem_table}
"""


class CapabilitySynthesizer:
    """Synthesize PageCapabilities for graph nodes from traversal artifacts.

    Independent of traversal (Plan X). Requires a VLM agent with
    ``predict_mm(text_prompt, [np.ndarray]) -> (response, ...)``.
    """

    def __init__(self, node_dir: str, agent: Any, app_id: str = ""):
        """Use ``screenshot.png`` plus visual ``elements.json`` per node."""
        self.node_dir = node_dir
        self.agent = agent
        self.app_id = str(app_id or "")

    # ── public API ────────────────────────────────────────────────────

    def synthesize_all(self, node_ids: List[str],
                       force: bool = False) -> Dict[str, PageCapabilities]:
        result: Dict[str, PageCapabilities] = {}
        for nid in node_ids:
            pc = self.synthesize_node(nid, force=force)
            if pc:
                result[nid] = pc
        logger.info("Synthesized capabilities for %d/%d nodes",
                    len(result), len(node_ids))
        return result

    def synthesize_node(self, node_id: str,
                        force: bool = False) -> Optional[PageCapabilities]:
        state_dir = os.path.join(self.node_dir, node_id)
        cache_path = os.path.join(state_dir, CAPABILITY_FILE)
        protected_online_cache = False

        # cache (same strategy as llm_unseen_candidates.json)
        if os.path.exists(cache_path):
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    protected_online_cache = (
                        str(loaded.get("schema_version") or "")
                        == "capability.discovery.v1")
                if not force:
                    return PageCapabilities.from_dict(loaded)
            except Exception:
                pass

        elem_table, valid_ids = self._build_element_table(node_id)
        if not elem_table:
            logger.warning("Node %s: no grounding elements, skip", node_id[:8])
            return None

        img = self._load_screenshot(node_id)
        if img is None:
            logger.warning("Node %s: no screenshot, skip", node_id[:8])
            return None

        prompt = _PROMPT_TEMPLATE.format(elem_table=elem_table)
        try:
            resp, *_ = self.agent.predict_mm(prompt, [img])
        except Exception as e:
            logger.warning("Node %s: VLM call failed: %s", node_id[:8], e)
            return None

        page_name = ""
        try:
            meta_path = os.path.join(state_dir, "state_meta.json")
            with open(meta_path, "r", encoding="utf-8") as stream:
                page_name = str(json.load(stream).get("page_name", "") or "")
        except Exception:
            pass

        pc = self._parse_response(resp, node_id, page_name, self.app_id)
        if pc is None:
            return None

        # ── 丢弃幻觉功能（active-surface 约束）────────────────────────────
        # VLM 可能无视元素清单、看截图把背景控件(被弹层盖住的)也提成功能，并
        # 编造清单外的 element_id。只保留 elements 全部落在 valid_ids 里的功能
        # （参数化功能则检查 element_map 的值）。这样"下拉框展开"节点只会保留
        # 它活跃表面对应的功能(选输入设备)，背景的调音量等被剔除——后者会在它们
        # 真正活跃的干净页节点上被正确提取。见 design_decisions D24。
        pc.capabilities = self._filter_hallucinated(
            pc.capabilities, valid_ids, node_id)
        if not pc.capabilities:
            logger.info("Node %s: all capabilities filtered as hallucinated",
                        node_id[:8])

        try:
            os.makedirs(state_dir, exist_ok=True)
            output_path = (
                os.path.join(state_dir, CAPABILITY_ENRICHMENT_FILE)
                if protected_online_cache else cache_path)
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(pc.to_dict(), f, ensure_ascii=False, indent=2)
            if protected_online_cache:
                logger.info(
                    "Node %s: kept online capability evidence canonical; wrote "
                    "offline enrichment to %s",
                    node_id[:8], CAPABILITY_ENRICHMENT_FILE)
        except Exception as e:
            logger.warning("Node %s: failed to write cache: %s", node_id[:8], e)
        return pc

    # ── internals ─────────────────────────────────────────────────────

    def _build_element_table(self, node_id: str):
        """Build a visual element table and its valid persisted ids."""
        lines: List[str] = []
        valid_ids: set = set()
        path = os.path.join(self.node_dir, node_id, "elements.json")
        try:
            with open(path, "r", encoding="utf-8") as stream:
                elements = json.load(stream)
        except Exception:
            return "", set()

        for element in elements:
            eid = str(element.get("id", ""))
            if eid:
                valid_ids.add(eid)
            name = element.get("name") or ""
            kind = element.get("el_type") or ""
            category = element.get("category") or ""
            region = element.get("region") or ""
            center = element.get("center") or []
            offscreen = (
                " [需滚动才可见]"
                if int(element.get("scroll_steps", 0) or 0) > 0
                else ""
            )
            lines.append(
                f"- id={eid} type={kind} category={category} region={region} "
                f"label={name!r} center={center}{offscreen}"
            )
        return "\n".join(lines), valid_ids

    @staticmethod
    def _filter_hallucinated(capabilities, valid_ids, node_id):
        """Clean grounding ids: strip ids not on the active surface (VLM-invented
        e.g. ``system_volume_slider``), but **keep** capabilities that have no
        real id — a capability may be extracted purely from the screenshot with
        its location described in ``explain``. So we do not drop it for lacking a
        real id; we only remove fabricated ids so nothing points at a non-existent
        element. See design_decisions D24.
        """
        if not valid_ids:
            return capabilities
        kept = []
        for c in capabilities:
            real_elems = [e for e in c.elements if e in valid_ids]
            real_map = {
                k: [v for v in vs if v in valid_ids]
                for k, vs in c.element_map.items()
            }
            real_map = {k: vs for k, vs in real_map.items() if vs}
            fabricated = [e for e in c.elements if e not in valid_ids]
            if fabricated:
                logger.info(
                    "Node %s: capability %r — stripped fabricated ids %s "
                    "(keeping it; grounding via screenshot)",
                    node_id[:8], c.name, fabricated)
            # keep only the real ids; capability survives even with none
            c.elements = real_elems
            if c.element_map:
                c.element_map = real_map
            kept.append(c)
        return kept

    def _load_screenshot(self, node_id: str) -> Optional[np.ndarray]:
        from PIL import Image
        ss = os.path.join(self.node_dir, node_id, "screenshot.png")
        if not os.path.exists(ss):
            return None
        try:
            return np.array(Image.open(ss).convert("RGB"))
        except Exception:
            return None

    @staticmethod
    def _parse_response(resp: str, node_id: str,
                        page_name: str,
                        app_id: str = "") -> Optional[PageCapabilities]:
        if not resp:
            return None
        raw = resp.strip()
        # strip markdown fences and isolate the JSON object
        m = re.search(r"\{.*\}", raw, re.S)
        if m:
            raw = m.group(0)
        try:
            d = json.loads(raw)
        except Exception as e:
            logger.warning("Node %s: capability JSON parse failed: %s",
                           node_id[:8], e)
            return None
        page = PageCapabilities(
            node_id=node_id,
            app_id=app_id,
            page_name=page_name,
            page_breakdown=str(d.get("page_breakdown", "") or ""),
            capabilities=[Capability.from_raw(c)
                          for c in d.get("capabilities", []) if c.get("name")],
        )
        for capability in page.capabilities:
            capability.bind_context(app_id, node_id, page_name)
        return page
