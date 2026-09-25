"""[M1 graph router — §11 grilling 定稿, 2026-07-03] Shortest-hop navigation over
the node-region-button graph, shared by in-traversal backtrack (M1) and, later,
collection navigation (M2). Platform-agnostic: all execution primitives are
INJECTED by the engine, so this module holds only the graph/plan logic.

§11 decisions implemented here:
  Q1  optimize = fewest hops (tie-break by measured edge success — TODO once stats
      are persisted; v1 uses first-found shortest).
  Q2  edge model = button->node. Shared regions expose button inventory on every
      containing node, but Phase 1 routes destinations only from verified direct
      edges on the current source. Cross-host destinations remain pending until
      the later action-sharing protocol verifies their scope.
  Q6  execute = already-at short-circuit -> BFS route -> per-hop (region-scoped
      name resolve + click) -> per-hop identify verify -> derail => replan
      (budget) -> no route/over budget => hard reset + route from root.

The engine always constructs this router. Shared coverage remains region-keyed;
explicit peer-navigation regions may borrow a unique target hint, but the first
real traversal is still identity-verified and then persisted source-locally.
"""
from __future__ import annotations

import json
import logging
import re
from collections import deque
from dataclasses import dataclass
from inspect import Parameter, signature
from typing import Any, Callable, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

_TOK = re.compile(r"[0-9a-z一-鿿]+")


def _norm(s: Optional[str]) -> str:
    return " ".join(_TOK.findall((s or "").lower()))


_PEER_NAVIGATION_ROLES = frozenset({
    "tab bar", "tabbar", "tabs", "bottom navigation", "bottom nav",
    "navigation bar", "nav bar", "navigation sidebar", "nav sidebar",
    "sidebar", "primary navigation",
})

# Back is a platform navigation affordance, not a visual element and not a
# Region member.  The sentinel only gives the verified graph edge a stable key;
# it must never enter element coverage or target grounding.
VIRTUAL_BACK_LABEL = "__NAVIGATE_BACK__"
VIRTUAL_ACTION_PREFIX = "__NATIVE_ACTION__"


def _virtual_back_step(source_id: str, effect_kind: str) -> Dict[str, Any]:
    """Describe one verified, regionless platform-navigation hop."""
    return {
        "name": VIRTUAL_BACK_LABEL,
        "region": "",
        "source_region_id": "",
        "effect_kind": effect_kind,
        "provenance": "natural_return",
        "virtual_action": True,
    }


def _native_action_label(action: Dict[str, Any]) -> str:
    """Stable internal route key for a non-visual native platform action."""
    action_type = str((action or {}).get("action_type") or "UNKNOWN")
    payload = {
        key: value for key, value in (action or {}).items()
        if key not in {"x", "y"}
    }
    return (f"{VIRTUAL_ACTION_PREFIX}:{action_type}:"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def _route_action_key(label: str, action: Optional[Dict[str, Any]] = None) -> str:
    """Keep distinct native actions on the same stable visual target."""
    action = action if isinstance(action, dict) else {}
    payload = {
        "action_type": str(action.get("action_type") or "CLICK").upper(),
    }
    for key in ("parameters", "key", "keys", "text", "button", "direction"):
        if key in action:
            payload[key] = action[key]
    return (f"{_norm(label)}\x1f"
            f"{json.dumps(payload, ensure_ascii=False, sort_keys=True)}")


def is_peer_navigation_role(role: Optional[str]) -> bool:
    """Whether a shared region represents peer page selection.

    Overflow/top-app-bar actions are deliberately excluded: their destinations
    are host-relative overlays and must remain pending until clicked locally.
    """
    normalized = " ".join(
        str(role or "").replace("_", " ").replace("-", " ").casefold().split()
    )
    return normalized in _PEER_NAVIGATION_ROLES


def _routing_verified(edge: Dict[str, Any]) -> bool:
    """Whether an observed transition is allowed in the replay route view.

    Schema-v3 edges carry an explicit flag.  Historical graphs predate that
    field, so only their positive landing/effect evidence is accepted; an
    absent/uncertain verdict is never silently upgraded.
    """
    if "routing_verified" in edge:
        return edge.get("routing_verified") is True
    if edge.get("landing_verified") is True:
        return True
    return str(edge.get("effect_verdict") or "").strip().lower() in {
        "success", "verified", "transitioned_consistent"
    }


def _replay_selector_value(edge: Dict[str, Any], key: str) -> str:
    action = edge.get("action") if isinstance(edge.get("action"), dict) else {}
    selector = (action.get("selector")
                if isinstance(action.get("selector"), dict) else {})
    return str(selector.get(key) or edge.get(key) or "")


def _is_router_replayable(edge: Dict[str, Any]) -> bool:
    """VisualRouter can replay one atomic native action."""
    if str(edge.get("transition_kind") or "").strip().casefold() \
            == "prerequisite_setup":
        return False
    try:
        if int(edge.get("action_steps", 1) or 1) != 1:
            return False
    except (TypeError, ValueError):
        return False
    sequence = edge.get("action_sequence") or []
    if isinstance(sequence, list) and len(sequence) > 1:
        return False
    action = edge.get("action") if isinstance(edge.get("action"), dict) else {}
    action_type = str(
        action.get("action_type") or action.get("type") or ""
    ).strip().upper()
    native_types = {
        # OSWorld computer_13.
        "MOVE_TO", "CLICK", "MOUSE_DOWN", "MOUSE_UP", "RIGHT_CLICK",
        "DOUBLE_CLICK", "DRAG_TO", "SCROLL", "TYPING", "PRESS",
        "KEY_DOWN", "KEY_UP", "HOTKEY", "WAIT",
        # AndroidWorld JSONAction.
        "DOUBLE_TAP", "INPUT_TEXT", "KEYBOARD_ENTER", "LONG_PRESS",
        "NAVIGATE_BACK", "NAVIGATE_HOME", "OPEN_APP", "SWIPE",
        # Historical common adapter aliases.
        "BACK", "HOME", "TYPE", "DRAG",
    }
    # Empty means a verified legacy semantic-click topology edge.
    return not action_type or action_type in native_types


def _edge_source_region_id(graph, source: str, edge: Dict[str, Any]) -> str:
    """Resolve a graph-local source region id without polluting portable actions.

    New node artifacts already persist ``region_id`` on elements.  Prefer an
    explicit edge sidecar when present, otherwise bind the edge's element id/name
    back to the source node.  Ambiguous name-only matches fail closed.
    """
    explicit = str(edge.get("source_region_id") or "").strip()
    if explicit:
        return explicit
    if source not in graph:
        return ""
    node = graph.nodes[source]
    elements = node.get("elements", []) if isinstance(node, dict) else []
    raw_id = edge.get("element_id")
    wanted_id = ("" if raw_id is None else str(raw_id)).strip()
    wanted_name = _norm(_replay_selector_value(edge, "element_label"))
    wanted_role = _norm(_replay_selector_value(edge, "region"))
    exact = []
    named = []
    for element in elements or []:
        get = element.get if isinstance(element, dict) else \
            lambda key, default=None: getattr(element, key, default)
        rid = str(get("region_id", "") or "").strip()
        if not rid:
            continue
        element_id = get("id", None)
        ids = {
            "" if element_id is None else str(element_id),
            str(get("uid", "") or ""),
        }
        if wanted_id and wanted_id in ids:
            exact.append(rid)
            continue
        if wanted_name and _norm(str(get("name", "") or "")) == wanted_name:
            role = _norm(str(get("region", "") or ""))
            if not wanted_role or not role or role == wanted_role:
                named.append(rid)
    candidates = set(exact or named)
    return next(iter(candidates)) if len(candidates) == 1 else ""


@dataclass(frozen=True)
class RouterClickResult:
    """One Router click result.

    Neither ``not_attempted`` nor dispatch-uncertain ``dispatch_unknown`` permits
    compensating Back. Only ``action_dispatched`` has a reliable post-call result.
    """

    status: str
    observation: Any = None
    reason: str = ""

    @classmethod
    def not_attempted(cls, observation: Any, reason: str) -> "RouterClickResult":
        return cls("not_attempted", observation, reason)

    @classmethod
    def action_dispatched(cls, observation: Any,
                          reason: str = "") -> "RouterClickResult":
        return cls("action_dispatched", observation, reason)

    @classmethod
    def dispatch_unknown(cls, observation: Any,
                         reason: str) -> "RouterClickResult":
        return cls("dispatch_unknown", observation, reason)


@dataclass(frozen=True)
class RouteResult:
    """Verified route outcome with enough evidence for safe scheduling."""

    status: str
    observation: Any
    landed_id: Optional[str] = None
    failure_kind: str = ""
    failed_edge: Optional[Dict[str, Any]] = None
    action_dispatched: bool = False
    attempts_used: int = 0

    @property
    def arrived(self) -> bool:
        return self.status == "arrived"

    def __iter__(self):
        """Keep legacy two-value unpacking while callers adopt the contract."""
        yield self.arrived
        yield self.observation

    def __eq__(self, other):
        if isinstance(other, tuple) and len(other) == 2:
            return (self.arrived, self.observation) == other
        if not isinstance(other, RouteResult):
            return NotImplemented
        return (
            self.status, self.observation, self.landed_id,
            self.failure_kind, self.failed_edge, self.action_dispatched,
            self.attempts_used,
        ) == (
            other.status, other.observation, other.landed_id,
            other.failure_kind, other.failed_edge, other.action_dispatched,
            other.attempts_used,
        )


class VisualRouter:
    """Fewest-hop router over the node-region-button graph (§11 Q1/Q2/Q6).

    Injected primitives (engine-provided, platform-agnostic):
      identify_fn(obs, source_id=None, step=None) -> state_id | None
      register_landing_fn(obs, source_id, step) -> state_id | None
      click_button_fn(source_id, name, region_id, region_role, obs)
          -> RouterClickResult
      back_fn(obs, source_id=None) -> obs | None      # regionless platform Back
      hard_reset_root_fn() -> (root_id|None, obs)    # last resort, land at app root
    """

    def __init__(self, graph, region_registry, state_data,
                 identify_fn: Callable, click_button_fn: Callable,
                 execute_action_fn: Optional[Callable] = None,
                 back_fn: Optional[Callable] = None,
                 hard_reset_root_fn: Optional[Callable] = None,
                 verified_transition_fn: Optional[Callable] = None,
                 replan_budget: int = 3,
                 quarantined_edges: Optional[set] = None,
                 register_landing_fn: Optional[Callable] = None,
                 attempt_outcome_fn: Optional[Callable] = None):
        self.graph = graph                     # StateGraph (has .graph = networkx DiGraph)
        self.regions = region_registry         # RegionRegistry (._regions: id->Region)
        self.state_data = state_data           # state_id -> {"elements","path",...}
        self._identify = identify_fn
        self._legacy_identify_callback = self._uses_legacy_context_signature(
            identify_fn)
        self._identify_accepts_step = self._accepts_step_context(identify_fn)
        self._click_button = click_button_fn
        self._legacy_click_callback = self._uses_legacy_click_signature(
            click_button_fn)
        self._execute_action = execute_action_fn
        self._back = back_fn
        self._legacy_back_callback = (
            back_fn is not None and self._uses_legacy_context_signature(back_fn))
        self._hard_reset_root = hard_reset_root_fn
        self._record_verified_transition = verified_transition_fn
        self._record_attempt_outcome = attempt_outcome_fn
        self._register_landing = register_landing_fn
        self._replan_budget = max(0, int(replan_budget))
        self._live_entry_sources: Dict[str, str] = {}
        # [2026-07-07 用户 问题1] 串页自纠隔离的 (from,to) 转移集(engine 传引用, 会随
        # 震荡增长)。plan_route 规划时绕开这些反复串页的边。
        self._quarantined = quarantined_edges if quarantined_edges is not None else set()

    @staticmethod
    def _uses_legacy_click_signature(callback: Callable) -> bool:
        """Recognize the old three-argument callback without masking TypeErrors."""
        try:
            params = list(signature(callback).parameters.values())
        except (TypeError, ValueError):
            return False
        if any(param.kind == Parameter.VAR_POSITIONAL for param in params):
            return False
        positional = [param for param in params if param.kind in {
            Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}]
        return len(positional) <= 3

    @staticmethod
    def _uses_legacy_context_signature(callback: Callable) -> bool:
        """Recognize callbacks that accept only the observation argument."""
        try:
            params = list(signature(callback).parameters.values())
        except (TypeError, ValueError):
            return False
        if any(param.kind == Parameter.VAR_POSITIONAL for param in params):
            return False
        positional = [param for param in params if param.kind in {
            Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}]
        return len(positional) <= 1

    @staticmethod
    def _accepts_step_context(callback: Callable) -> bool:
        """Whether identity accepts the optional executed Router step."""
        try:
            params = list(signature(callback).parameters.values())
        except (TypeError, ValueError):
            return False
        if any(param.kind == Parameter.VAR_POSITIONAL for param in params):
            return False
        positional = [param for param in params if param.kind in {
            Parameter.POSITIONAL_ONLY, Parameter.POSITIONAL_OR_KEYWORD}]
        return len(positional) >= 3

    def _invoke_identify(self, obs: Any, source_id: str = "",
                         step: Optional[Dict[str, Any]] = None):
        """Identify from source-local context without exposing the final target."""
        if self._legacy_identify_callback:
            return self._identify(obs)
        if self._identify_accepts_step:
            return self._identify(obs, source_id or None, step)
        return self._identify(obs, source_id or None)

    def _resolve_landing(self, obs: Any, source_id: str,
                         step: Dict[str, Any]) -> Optional[str]:
        """Identify a fresh landing, registering it when it is genuinely new."""
        landed = self._invoke_identify(obs, source_id, step)
        if landed is not None or self._register_landing is None:
            return landed
        try:
            landed = self._register_landing(obs, source_id, dict(step))
        except Exception as exc:
            logger.warning(
                "router: unknown landing registration failed from %s: %s",
                source_id, exc)
            return None
        if landed is not None:
            logger.info(
                "router: identity candidates missed the live landing; "
                "registered actual state %s from %s", landed, source_id)
        return landed

    def _invoke_back(self, obs: Any, source_id: str = ""):
        if self._back is None:
            return None
        if self._legacy_back_callback:
            return self._back(obs)
        return self._back(obs, source_id or None)

    def _invoke_click(self, step: Dict[str, Any], obs: Any) -> RouterClickResult:
        if self._legacy_click_callback:
            value = self._click_button(step["name"], step["region"], obs)
        else:
            value = self._click_button(
                step["source_id"], step["name"], step.get("source_region_id", ""),
                step["region"], obs)
        if isinstance(value, RouterClickResult):
            return value
        if value is None:
            return RouterClickResult.not_attempted(obs, "legacy_callback_none")
        return RouterClickResult.action_dispatched(value, "legacy_callback_observation")

    def _invoke_action(self, step: Dict[str, Any], obs: Any) -> RouterClickResult:
        if self._execute_action is None:
            return RouterClickResult.not_attempted(obs, "native_action_unavailable")
        value = self._execute_action(step, obs)
        if isinstance(value, RouterClickResult):
            return value
        if value is None:
            return RouterClickResult.not_attempted(obs, "native_action_none")
        return RouterClickResult.action_dispatched(value, "native_action_observation")

    @staticmethod
    def _element_value(element: Any, key: str, default: Any = "") -> Any:
        if isinstance(element, dict):
            return element.get(key, default)
        return getattr(element, key, default)

    def _selected_peer_target(self, region_id: str, label: str) -> Optional[str]:
        """Use a selected tab/sidebar occurrence as a unique target hint."""
        wanted = _norm(label)
        candidates = set()
        for state_id, data in self.state_data.items():
            for element in (data or {}).get("elements", []) or []:
                if str(self._element_value(element, "region_id") or "") != region_id:
                    continue
                if _norm(str(self._element_value(element, "name") or "")) != wanted:
                    continue
                if self._element_value(element, "selected", False) is True:
                    candidates.add(str(state_id))
        return next(iter(candidates)) if len(candidates) == 1 else None

    def _verified_shared_target(self, graph, region_id: str,
                                label: str) -> Optional[str]:
        """Find one unambiguous target observed for a shared control elsewhere.

        This remains a prediction for the current host until a live click and
        independent landing identity confirm it in that context.
        """
        wanted = _norm(label)
        candidates = set()
        region = getattr(self.regions, "_regions", {}).get(region_id)
        for source in getattr(region, "seen_on", ()):
            if source not in graph:
                continue
            for _u, target, edge in graph.out_edges(source, data=True):
                if not _routing_verified(edge) or not _is_router_replayable(edge):
                    continue
                if self._is_terminal_action(str(source), edge):
                    continue
                if str(edge.get("effect_kind") or "").casefold() in {
                        "return", "return_via_control",
                        "return_native_action", "dismiss_overlay"}:
                    continue
                if _norm(_replay_selector_value(edge, "element_label")) != wanted:
                    continue
                if _edge_source_region_id(graph, source, edge) != region_id:
                    continue
                if self._source_element_is_stateful(
                        str(source), edge, region_id=region_id, label=label):
                    # A toggle/input mutation is a bounded exploration
                    # transaction with a mandatory restore. Replaying it as a
                    # route hop can strand routing on its temporary variant.
                    continue
                candidates.add(str(target))
        return next(iter(candidates)) if len(candidates) == 1 else None

    def _source_element_is_stateful(
            self, source: str, edge: Dict[str, Any], *,
            region_id: str = "", label: str = "") -> bool:
        source_element_id = str(edge.get("element_id") or "")
        wanted = _norm(label or _replay_selector_value(
            edge, "element_label"))
        wanted_region = str(
            region_id or _edge_source_region_id(
                getattr(self.graph, "graph", None), source, edge) or "")
        for element in (
                self.state_data.get(str(source), {}) or {}).get(
                    "elements", []) or []:
            element_id = str(self._element_value(element, "id", "") or "")
            element_name = _norm(str(
                self._element_value(element, "name", "") or ""))
            element_region = str(
                self._element_value(element, "region_id", "") or "")
            id_matches = bool(source_element_id) and element_id == source_element_id
            semantic_matches = (
                element_name == wanted
                and (not wanted_region or element_region == wanted_region))
            if id_matches or semantic_matches:
                return bool(self._element_value(element, "stateful", False))
        return False

    def _is_terminal_action(
            self, source_id: str, edge: Dict[str, Any]) -> bool:
        """Whether durable terminal evidence forbids replaying this action."""
        records = getattr(self.graph, "abnormal_buttons", ()) or ()
        edge_id = str(edge.get("element_id") or "").strip()
        edge_name = _norm(_replay_selector_value(edge, "element_label"))
        edge_region = str(
            edge.get("source_region_id")
            or _edge_source_region_id(
                getattr(self.graph, "graph", None),
                source_id, edge)
            or ""
        ).strip()
        for record in records:
            if str(record.get("state_id") or "") != str(source_id):
                continue
            record_id = str(record.get("element_id") or "").strip()
            if edge_id and record_id and edge_id == record_id:
                return True
            if (_norm(str(record.get("element_name") or "")) == edge_name
                    and (not edge_region
                         or not str(record.get("region_id") or "").strip()
                         or str(record.get("region_id") or "").strip()
                         == edge_region)):
                return True
        return False

    def has_direct_edge(self, source_id: str, label: str,
                        region_id: str = "", action_type: str = "") -> bool:
        """Whether this source owns the requested verified control action."""
        wanted = _norm(label)
        for edge in self.node_out_edges(source_id).values():
            if edge.get("provenance") != "direct_verified":
                continue
            if _norm(str(edge.get("label") or "")) != wanted:
                continue
            if region_id and str(edge.get("source_region_id") or "") != str(region_id):
                continue
            observed_type = str((edge.get("action") or {}).get(
                "action_type") or "CLICK").upper()
            if action_type and observed_type != str(action_type).upper():
                continue
            return True
        return False

    # ── Q2 edge model ──────────────────────────────────────────────────────
    def note_arrival(
            self, target_id: Optional[str], source_id: Optional[str],
            step: Optional[Dict[str, Any]] = None) -> None:
        """Remember the live stack parent, preserving it across a return."""
        if not target_id:
            return
        target = str(target_id)
        source = str(source_id or "")
        step = step if isinstance(step, dict) else {}
        action = step.get("action") \
            if isinstance(step.get("action"), dict) else {}
        action_type = str(action.get("action_type") or "").strip().upper()
        effect_kind = str(step.get("effect_kind") or "").casefold()
        is_return = (
            action_type in {"BACK", "NAVIGATE_BACK"}
            or effect_kind in {
                "return", "return_via_control",
                "return_native_action", "dismiss_overlay"}
            or (
                bool(source)
                and self._live_entry_sources.get(source) == target
            )
        )
        if is_return:
            self._live_entry_sources.pop(source, None)
            parent = self._live_entry_sources.get(target, "")
        else:
            self._live_entry_sources[target] = source
            parent = source
        self._live_arrival = (target, parent)

    def _arrival_source(self, node_id: str) -> str:
        live = getattr(self, "_live_arrival", None)
        return live[1] if live and live[0] == str(node_id) else ""

    def _is_live_stack_ancestor(
            self, context_id: str, destination_id: str) -> bool:
        """Whether one destination is on the current live navigation stack."""
        destination = str(destination_id or "")
        current = str(context_id or "")
        seen = set()
        while current and current not in seen:
            if current == destination:
                return True
            seen.add(current)
            current = str(self._live_entry_sources.get(current) or "")
        return False

    def _is_contextual_return_candidate(
            self, node_id: str, candidate: Dict[str, Any]) -> bool:
        """Whether a direct action should return to the live entry source."""
        action = candidate.get("action") \
            if isinstance(candidate.get("action"), dict) else {}
        action_type = str(action.get("action_type") or "").strip().upper()
        effect_kind = str(candidate.get("effect_kind") or "").casefold()
        if (action_type in {"BACK", "NAVIGATE_BACK"}
                or effect_kind in {
                    "return", "return_via_control",
                    "return_native_action", "dismiss_overlay"}
                or str(candidate.get("label") or "") == VIRTUAL_BACK_LABEL):
            return True
        destination = str(candidate.get("dst") or "")
        for edge in getattr(self.graph, "action_edges", ()) or ():
            if (str(edge.get("source") or "") != str(node_id)
                    or str(edge.get("target") or "") != destination
                    or not _routing_verified(edge)
                    or not _is_router_replayable(edge)):
                continue
            if str(edge.get("effect_kind") or "").casefold() in {
                    "return", "return_via_control",
                    "return_native_action", "dismiss_overlay"}:
                return True
        wanted_id = str(candidate.get("element_id") or "")
        wanted_name = _norm(str(candidate.get("label") or ""))
        for element in (self.state_data.get(str(node_id)) or {}).get(
                "elements", []):
            get = element.get if isinstance(element, dict) else (
                lambda key, default=None: getattr(element, key, default))
            element_id = str(get("id", "") or "")
            element_name = _norm(str(get("name", "") or ""))
            if ((wanted_id and element_id == wanted_id)
                    or (wanted_name and element_name == wanted_name)):
                if bool(get("back", False)):
                    return True
        return False

    def node_out_edges(self, node_id: str,
                       arrival_source_id: Optional[str] = None
                       ) -> Dict[str, Dict[str, Any]]:
        """[§11 Q2 — three-part graph: page → region → button → page]
        A page's out-edges = for every REGION the page contains (region.seen_on ∋
        page, ①), every BUTTON that region contains (region.names, ② — INCLUDING
        ones not yet clicked). A shared occurrence exposes that inventory with
        dst=None and pending provenance; it does not inherit another source's
        destination. Direct verified edges observed from THIS page override it."""
        # StateGraph's compact topology can reference several semantic
        # ActionEdges for the same source/target pair.  Its display attributes
        # are therefore not a replay contract: the most recently observed,
        # unverified action may coexist with an older verified one.  Route from
        # the derived view, which selects a verified ActionEdge representative.
        g = getattr(self.graph, "routing_graph", None)
        if callable(g):
            g = g()
        if g is None:
            # Tiny/legacy graph adapters do not expose a derived route view;
            # retain the explicit per-edge verification filter below.
            g = getattr(self.graph, "graph", None)
        if g is None:
            return {}
        # Shared occurrences expose inventory. Only explicit peer navigation may
        # borrow a unique target hint; host-relative menus stay pending.
        edges: Dict[str, Dict[str, Any]] = {}
        # ①② page → its regions (seen_on) → their buttons (names, incl. unclicked)
        for region_id, r in getattr(self.regions, "_regions", {}).items():
            if node_id not in getattr(r, "seen_on", ()):
                continue
            buttons = getattr(r, "action_names", None)
            if buttons is None:
                buttons = getattr(r, "names", ())
            for btn in buttons:
                shared_action = {"action_type": "CLICK"}
                k = _norm(btn)
                if not k or k in edges:
                    continue
                edges[k] = {
                    "label": btn, "region": r.role,
                    "source_id": node_id, "source_region_id": region_id,
                    "provenance": "shared_pending", "dst": None,
                    "action": shared_action,
                }
                peer = is_peer_navigation_role(getattr(r, "role", ""))
                inferred = self._verified_shared_target(g, region_id, btn)
                if peer:
                    inferred = inferred or self._selected_peer_target(region_id, btn)
                if inferred is not None and inferred != node_id:
                    edges[k].update({
                        "dst": inferred,
                        "provenance": ("peer_inferred" if peer
                                       else "shared_predicted"),
                        "effect_kind": ("peer_navigation" if peer
                                        else "shared_action"),
                        "probe_required": True,
                    })
        # Direct observations from this State override shared predictions.  One
        # selector can have several targets when Back depends on entry history.
        direct_by_key: Dict[str, List[Dict[str, Any]]] = {}
        corrections_by_key: Dict[str, List[Dict[str, str]]] = {}
        owner = getattr(self, "graph", None)
        topology = getattr(owner, "graph", None)
        raw_action_edges = getattr(owner, "action_edges", None)
        if isinstance(raw_action_edges, list):
            direct_records = [
                (str(d.get("target") or ""), d)
                for d in raw_action_edges
                if str(d.get("source") or "") == str(node_id)
                and str(d.get("target") or "")
            ]
        elif node_id in g:
            direct_records = [(str(v), d) for _u, v, d in g.out_edges(
                node_id, data=True)]
        else:
            direct_records = []
        for v, d in direct_records:
            if not _routing_verified(d):
                continue
            if not _is_router_replayable(d):
                continue
            if self._is_terminal_action(str(node_id), d):
                continue
            if self._source_element_is_stateful(str(node_id), d):
                continue
            effect_kind = str(d.get("effect_kind") or "forward")
            action = d.get("action") if isinstance(d.get("action"), dict) else {}
            action_type = str(action.get("action_type") or "").strip().upper()
            visual_label = _replay_selector_value(d, "element_label")
            if visual_label:
                replay_label = visual_label
                replay_region = _replay_selector_value(d, "region")
            elif action_type in {"BACK", "NAVIGATE_BACK"}:
                replay_label = VIRTUAL_BACK_LABEL
                replay_region = ""
            else:
                replay_label = _native_action_label(action)
                replay_region = ""
            k = _route_action_key(replay_label, action)
            if k:
                contextual_correction = self._is_contextual_return_candidate(
                    str(node_id), {
                        "dst": v,
                        "label": replay_label,
                        "element_id": str(d.get("element_id") or ""),
                        "effect_kind": effect_kind,
                        "action": action,
                    })
                attempts = [
                    attempt for attempt in d.get("attempts") or []
                    if attempt.get("committed") is True
                    and attempt.get("landing_verified") is True
                ]
                route_contexts = sorted({
                    str((attempt.get("evidence") or {}).get(
                        "route_context") or "")
                    for attempt in attempts
                    if str((attempt.get("evidence") or {}).get(
                        "route_context") or "")
                }) or list(d.get("route_contexts") or [])
                if not contextual_correction:
                    route_contexts = []
                for attempt in attempts:
                    evidence = attempt.get("evidence") or {}
                    predicted = str(evidence.get("predicted_target") or "")
                    if (evidence.get("prediction_match") is False
                            and predicted and predicted != str(v)):
                        corrections_by_key.setdefault(k, []).append({
                            "predicted_target": predicted,
                            "route_context": (
                                str(evidence.get("route_context") or "")
                                if contextual_correction else ""),
                        })
                candidate = {
                    "label": replay_label, "region": replay_region, "dst": v,
                    "source_id": node_id,
                    "element_id": str(d.get("element_id") or ""),
                    "source_region_id": _edge_source_region_id(
                        topology or g, node_id, d),
                    "provenance": "direct_verified",
                    "effect_kind": effect_kind,
                    "route_contexts": route_contexts,
                    "action": dict(action) or {"action_type": "CLICK"},
                }
                if (effect_kind.casefold() in {"", "forward"}
                        and self._is_contextual_return_candidate(
                            str(node_id), candidate)):
                    candidate["effect_kind"] = "return_via_control"
                direct_by_key.setdefault(k, []).append(candidate)
        context = str(arrival_source_id or "")
        for key, candidates in direct_by_key.items():
            superseded = {
                correction["predicted_target"]
                for correction in corrections_by_key.get(key, [])
                if (not correction["route_context"]
                    or correction["route_context"] == context)
            }
            corrected_candidates = [
                candidate for candidate in candidates
                if str(candidate.get("dst") or "") not in superseded
            ]
            if corrected_candidates:
                candidates = corrected_candidates
            selected: Optional[Dict[str, Any]] = None
            if context:
                exact = [candidate for candidate in candidates
                         if context in candidate.get("route_contexts", [])]
                exact_targets = {str(candidate["dst"]) for candidate in exact}
                if len(exact_targets) == 1:
                    selected = exact[0]
                else:
                    global_candidates = [candidate for candidate in candidates
                                         if not candidate.get("route_contexts")]
                    contextual_returns = [
                        candidate for candidate in candidates
                        if self._is_contextual_return_candidate(
                            str(node_id), candidate)
                    ]
                    stack_returns = [
                        candidate for candidate in candidates
                        if self._is_live_stack_ancestor(
                            context, str(candidate.get("dst") or ""))
                    ]
                    stack_targets = {
                        str(candidate["dst"]) for candidate in stack_returns}
                    if len(stack_targets) == 1:
                        selected = stack_returns[0]
                    elif (context != str(node_id)
                            and (context in g or context in self.state_data)
                            and contextual_returns):
                        selected = dict(contextual_returns[0])
                        selected.update({
                            "dst": context,
                            "provenance": "context_predicted",
                            "probe_required": True,
                        })
                    else:
                        global_targets = {str(candidate["dst"])
                                          for candidate in global_candidates}
                        if len(global_targets) == 1:
                            selected = global_candidates[0]
                        else:
                            all_targets = {str(candidate["dst"])
                                           for candidate in candidates}
                            if len(all_targets) == 1:
                                selected = dict(candidates[0])
                                selected.update({
                                    "provenance": "context_predicted",
                                    "probe_required": True,
                                })
            else:
                targets = {str(candidate["dst"]) for candidate in candidates}
                if len(targets) == 1:
                    selected = candidates[0]
            if selected is not None:
                selected = dict(selected)
                selected["route_context"] = context
                action_type = str((selected.get("action") or {}).get(
                    "action_type") or "").strip().upper()
                if (context and context != str(node_id)
                        and self._is_live_stack_ancestor(
                            context, str(selected.get("dst") or ""))
                        and action_type == "CLICK"
                        and str(selected.get(
                            "effect_kind") or "forward").casefold()
                        in {"", "forward"}):
                    # The same visible control can have different destinations
                    # under different live entry contexts.  A verified click
                    # back to this occurrence's entry source is a contextual
                    # return even when an older inventory omitted ``back=true``.
                    selected["effect_kind"] = "return_via_control"
                base = _norm(str(selected.get("label") or ""))
                existing = edges.get(base)
                if (existing is None
                        or existing.get("provenance") == "shared_pending"
                        or _route_action_key(
                            str(existing.get("label") or ""),
                            existing.get("action")) == key):
                    edges[base] = selected
                else:
                    edges[key] = selected
        return edges

    def expected_destinations(self, source_id: str,
                              clicked_label: str) -> List[str]:
        """Return the deterministic, verified one-hop arrival candidate set.

        The clicked label's known destination is strongest evidence and is
        therefore first.  The source follows because a click can legitimately
        leave the page unchanged.  Remaining verified/replayable destinations
        are sorted by normalized selector and state id.  ``node_out_edges`` is
        the canonical replay view, so unverified, ambiguous, and recipe-only
        edges never enter this read-only candidate query.
        """
        edges = self.node_out_edges(source_id)
        wanted = _norm(clicked_label)
        ordered: List[str] = []

        direct = [edge for key, edge in edges.items()
                  if _norm(str(edge.get("label") or key)) == wanted
                  and edge.get("dst") is not None]
        ordered.extend(str(edge["dst"]) for edge in direct)
        ordered.append(str(source_id))

        siblings = sorted(
            ((key, str(edge["dst"])) for key, edge in edges.items()
             if edge.get("dst") is not None
             and _norm(str(edge.get("label") or key)) != wanted),
            key=lambda item: (item[0], item[1]),
        )
        ordered.extend(dst for _key, dst in siblings)
        owner = getattr(self, "graph", None)
        graph = getattr(owner, "routing_graph", None)
        graph = graph() if callable(graph) else graph
        if graph is None:
            graph = getattr(owner, "graph", None)
        if graph is not None and source_id in graph:
            ordered.extend(sorted(str(node) for node in graph.predecessors(source_id)))
        return list(dict.fromkeys(ordered))

    # ── Q1 plan ────────────────────────────────────────────────────────────
    def _plan_route_to_any(
            self, current: str, targets: List[str],
            arrival_source_id: Optional[str] = None,
    ) -> Optional[Tuple[str, List[Dict[str, Any]]]]:
        """Run one equal-hop BFS and return the nearest requested target.

        Target order breaks ties at the same hop depth. This preserves the
        scheduler's graph-order tie break while avoiding one full BFS per
        frontier State.
        """
        target_order = {
            str(target): index for index, target in enumerate(targets)
            if str(target) != str(current)
        }
        if not target_order:
            return None
        start_context = str(arrival_source_id or self._arrival_source(current))
        q: deque = deque([(current, start_context, [])])
        seen = {(current, start_context)}
        found: Dict[str, List[Dict[str, Any]]] = {}
        found_hops: Optional[int] = None
        while q:
            node, context, path = q.popleft()
            if found_hops is not None and len(path) >= found_hops:
                break
            for _k, e in self.node_out_edges(node, context).items():
                dst = e["dst"]
                if dst is None:            # registered but unexplored → not routable
                    continue
                if (node, dst) in self._quarantined:   # 反复串页的边 → 绕开
                    continue
                step = {
                    "source_id": node,
                    "source_region_id": e.get("source_region_id", ""),
                    "name": e["label"], "region": e["region"], "dst": dst,
                    "provenance": e.get("provenance", "direct_verified"),
                }
                if e.get("element_id") not in {None, ""}:
                    step["element_id"] = str(e.get("element_id"))
                if isinstance(e.get("action"), dict) and e.get("action"):
                    step["action"] = dict(e["action"])
                if e.get("probe_required"):
                    step["probe_required"] = True
                if context:
                    step["route_context"] = context
                effect_kind = str(e.get("effect_kind") or "forward")
                if effect_kind != "forward":
                    step["effect_kind"] = effect_kind
                next_path = path + [step]
                destination = str(dst)
                if destination in target_order:
                    found_hops = len(next_path)
                    found.setdefault(destination, next_path)
                    continue
                next_context = str(node)
                next_key = (destination, next_context)
                if next_key not in seen:
                    seen.add(next_key)
                    q.append((destination, next_context, next_path))
        if not found:
            return None
        target = min(found, key=target_order.__getitem__)
        return target, found[target]

    def nearest_reachable_target(
            self, current: str, targets: List[str],
            arrival_source_id: Optional[str] = None,
    ) -> Optional[str]:
        """Return the graph-nearest target from one shared BFS."""
        if str(current) in {str(target) for target in targets}:
            return str(current)
        planned = self._plan_route_to_any(
            current, targets, arrival_source_id)
        return planned[0] if planned is not None else None

    def plan_route(self, current: str, target: str,
                   arrival_source_id: Optional[str] = None
                   ) -> Optional[List[Dict[str, Any]]]:
        """Use equal-hop planning for verified edges and predicted shared edges.

        Shared/pending and registered-but-unexplored buttons (dst=None) are
        skipped. Steps retain source, region, and provenance for the semantic
        execution primitive. None means no known path; [] means already there.
        """
        if current == target:
            return []
        planned = self._plan_route_to_any(
            current, [str(target)], arrival_source_id)
        return planned[1] if planned is not None else None

    # ── Q6 execute ─────────────────────────────────────────────────────────
    def route_to(self, current_obs: Any, current_id: str,
                 target_id: str,
                 arrival_source_id: Optional[str] = None) -> RouteResult:
        """Navigate to a target and return verified, diagnostic evidence."""
        obs = current_obs
        if current_id == target_id:
            return RouteResult("arrived", obs, current_id)
        cur = current_id
        cur_context = str(arrival_source_id or self._arrival_source(cur))
        last_failure = "no_verified_path"
        action_dispatched = False
        attempts_used = 0
        for attempt in range(self._replan_budget + 1):
            attempts_used = attempt + 1
            route = self.plan_route(cur, target_id, cur_context)
            if route is None:
                if self._back is not None:
                    back_source = cur
                    value = self._invoke_back(obs, back_source)
                    if value is not None:
                        obs = value
                        action_dispatched = True
                    back_step = _virtual_back_step(
                        back_source, self._back_effect_kind(back_source))
                    back_cur = self._resolve_landing(
                        obs, back_source, back_step)
                    if back_cur and back_cur != back_source:
                        self._persist_verified_hop(
                            back_source, back_cur, back_step)
                        self.note_arrival(back_cur, back_source, back_step)
                    if back_cur == target_id:
                        return RouteResult(
                            "arrived", obs, target_id,
                            action_dispatched=action_dispatched,
                            attempts_used=attempts_used)
                    if back_cur and back_cur != cur:
                        cur = back_cur
                        cur_context = self._arrival_source(back_cur)
                        continue
                last_failure = "no_verified_path"
                break
            if not route:
                return RouteResult(
                    "arrived", obs, cur,
                    action_dispatched=action_dispatched,
                    attempts_used=attempts_used)
            ok, obs, new_cur, click_status = self._run_route(route, obs)
            action_dispatched = action_dispatched or click_status in {
                "action_dispatched", "dispatch_unknown", "no_effect",
                "identity_unknown", "off_app_recovered"}
            if ok:
                return RouteResult(
                    "arrived", obs, new_cur,
                    action_dispatched=action_dispatched,
                    attempts_used=attempts_used)
            if click_status == "dispatch_unknown":
                last_failure = "dispatch_unknown"
            elif click_status == "not_attempted":
                last_failure = "not_attempted"
            elif click_status == "no_effect":
                last_failure = "no_effect"
            elif click_status == "off_app_recovered":
                last_failure = "off_app_recovered"
            elif new_cur is None:
                last_failure = "identity_unknown"
            else:
                last_failure = "identity_mismatch"
            if new_cur is not None and new_cur != cur:
                cur_context = self._arrival_source(new_cur)
                cur = new_cur
                continue
            if click_status in {
                    "not_attempted", "dispatch_unknown", "no_effect",
                    "identity_unknown", "off_app_recovered"}:
                break
            if self._back is not None:
                back_source = cur
                value = self._invoke_back(obs, back_source)
                if value is not None:
                    obs = value
                    action_dispatched = True
                back_step = _virtual_back_step(
                    back_source, self._back_effect_kind(back_source))
                back_cur = self._resolve_landing(obs, back_source, back_step)
                if back_cur and back_cur != back_source:
                    self._persist_verified_hop(
                        back_source, back_cur, back_step)
                    self.note_arrival(back_cur, back_source, back_step)
                if back_cur == target_id:
                    return RouteResult(
                        "arrived", obs, target_id,
                        action_dispatched=action_dispatched,
                        attempts_used=attempts_used)
                if back_cur and back_cur != cur:
                    cur = back_cur
                    cur_context = self._arrival_source(back_cur)
                    continue
            break
        if self._hard_reset_root is None:
            status = "dispatch_unknown" if last_failure == "dispatch_unknown" \
                else ("blocked" if last_failure == "no_verified_path" else "retryable")
            return RouteResult(
                status, obs, cur, last_failure,
                action_dispatched=action_dispatched,
                attempts_used=attempts_used)
        root_id, obs = self._hard_reset_root()
        if root_id is None:
            return RouteResult(
                "retryable", obs, None, "reset_identity_unknown",
                action_dispatched=action_dispatched,
                attempts_used=attempts_used)
        self._live_entry_sources.clear()
        self._live_arrival = (str(root_id), "")
        if root_id == target_id:
            return RouteResult(
                "arrived", obs, target_id,
                action_dispatched=True, attempts_used=attempts_used)
        route = self.plan_route(
            root_id, target_id, self._arrival_source(root_id))
        if not route:
            return RouteResult(
                "blocked", obs, root_id, "no_verified_path",
                action_dispatched=True, attempts_used=attempts_used)
        ok, obs, landed, click_status = self._run_route(route, obs)
        if ok:
            return RouteResult(
                "arrived", obs, landed,
                action_dispatched=True, attempts_used=attempts_used)
        return RouteResult(
            "dispatch_unknown" if click_status == "dispatch_unknown"
            else "retryable",
            obs, landed,
            ("identity_unknown" if landed is None else click_status),
            # The hard reset itself was dispatched even when the following
            # selector was not. Preserve that fact so callers may continue from
            # the verified reset landing.
            action_dispatched=True,
            attempts_used=attempts_used)

    def verify_return_path(self, target_obs: Any, source_id: str,
                           target_id: str,
                           return_step: Optional[Dict[str, Any]] = None,
                           ) -> RouteResult:
        """Execute one selected reverse action, verify it, then restore."""
        if return_step is not None:
            return_step = dict(return_step)
            return_step.setdefault("route_context", str(source_id))
            return_step.setdefault("probe_required", True)
            ok, return_obs, landed, click_status = self._run_route(
                [return_step], target_obs)
            if (not ok and click_status == "action_dispatched"
                    and landed is not None and landed != target_id):
                # A confirmed return action defines its edge by the live landing,
                # not by the page that happened to open the target.  _run_route
                # has already persisted the corrected target->landed hop. Restore
                # the probed target from that real page and keep traversing.
                logger.info(
                    "return probe: expected %s but landed on %s; accepting "
                    "the verified live destination", source_id, landed)
                ok = True
            if not ok:
                safe_landed = (
                    target_id
                    if click_status == "not_attempted" and landed is None
                    else landed)
                failure_kind = {
                    "not_attempted": "return_control_not_attempted",
                    "no_effect": "return_no_effect",
                    "identity_unknown": "return_identity_unknown",
                    "off_app_recovered": "return_off_app",
                    "dispatch_unknown": "return_dispatch_unknown",
                }.get(click_status, "return_control_failed")
                return RouteResult(
                    "dispatch_unknown" if click_status == "dispatch_unknown"
                    else "retryable",
                    return_obs, safe_landed,
                    failure_kind,
                    dict(return_step),
                    click_status != "not_attempted",
                    1)
            return_attempts = 1
        else:
            if self._back is None:
                return RouteResult(
                    "blocked", target_obs, target_id, "back_unavailable")
            back_value = self._invoke_back(target_obs, target_id)
            if back_value is None:
                return RouteResult(
                    "retryable", target_obs, target_id, "back_not_dispatched")
            return_obs = back_value
            return_attempts = 1
            back_step = _virtual_back_step(
                target_id, self._back_effect_kind(target_id))
            back_step.update({"source_id": target_id, "dst": source_id})
            landed = self._resolve_landing(return_obs, target_id, back_step)
            landing_status = self._classify_dispatched_landing(
                back_step, landed)
            if landing_status == "identity_unknown":
                return RouteResult(
                    "retryable", return_obs, None, "return_identity_unknown",
                    action_dispatched=True, attempts_used=1)
            if landing_status == "no_effect":
                return RouteResult(
                    "retryable", return_obs, landed,
                    "return_no_effect",
                    action_dispatched=True, attempts_used=1)
            if landing_status == "prediction_corrected":
                logger.info(
                    "return probe: expected %s but Back landed on %s; "
                    "accepting the verified live destination",
                    source_id, landed)
        restore_source = landed or source_id
        restored = self.route_to(return_obs, restore_source, target_id)
        if not restored.arrived:
            return RouteResult(
                restored.status, restored.observation, restored.landed_id,
                "target_restore_failed", restored.failed_edge,
                True, restored.attempts_used + return_attempts)
        return RouteResult(
            "arrived", restored.observation, target_id,
            action_dispatched=True,
            attempts_used=restored.attempts_used + return_attempts)

    def _is_overlay_host_return(self, source_id: str,
                                landed_id: Optional[str]) -> bool:
        """Whether ``landed_id`` is the bare host Page of an overlay source."""
        if not landed_id or landed_id == source_id:
            return False
        source = self.state_data.get(str(source_id)) or {}
        landed = self.state_data.get(str(landed_id)) or {}
        surface_kind = " ".join(str(
            source.get("surface_kind") or "").replace("_", " ")
            .replace("-", " ").casefold().split())
        if surface_kind not in {
                "dialog", "popup", "popup menu", "menu", "overlay",
                "drawer", "bottom sheet"}:
            return False
        source_page = str(source.get("page_id") or "")
        landed_page = str(landed.get("page_id") or "")
        return bool(source_page and source_page == landed_page)

    def _route_to_legacy(self, current_obs: Any, current_id: str,
                         target_id: str) -> Tuple[bool, Any]:
        """Navigate to ``target_id`` from ``current_id``. Returns (arrived, obs)."""
        obs = current_obs
        if current_id == target_id:
            return True, obs
        cur = current_id
        for attempt in range(self._replan_budget + 1):
            route = self.plan_route(cur, target_id)
            if route is None:
                # [2026-07-07 用户] No FORWARD path (backtracking to an ANCESTOR — the
                # graph has only forward edges, so plan_route can't route UP). The
                # reliable way up is the grounder-flagged back control (‹/Back), NOT
                # hard-reset (GNOME Settings reopens to the LAST page, not root). Click
                # back, verify by ACTUAL region-set identity, replan from where we
                # really landed. This is the fix for "no path + back key not in graph".
                if self._back is not None:
                    back_source = cur
                    obs = self._invoke_back(obs, back_source) or obs
                    back_cur = self._invoke_identify(obs, back_source)
                    if back_cur and back_cur != back_source:
                        self._persist_verified_hop(
                            back_source, back_cur,
                            _virtual_back_step(
                                back_source,
                                self._back_effect_kind(back_source)))
                    if back_cur == target_id:
                        logger.info("router: back-ascent reached target %s", target_id)
                        return True, obs
                    if back_cur and back_cur != cur:
                        logger.info("router: back-ascent %s -> %s — replan", cur, back_cur)
                        cur = back_cur
                        continue
                logger.info("router: no path %s -> %s and back didn't help (attempt %d)",
                            cur, target_id, attempt)
                break
            if not route:
                return True, obs           # plan_route [] = cur already IS target
            logger.info("router: plan %s -> %s = %d hop(s) [路径: %s]",
                        cur, target_id, len(route),
                        " → ".join(str(s.get("name", "?")) for s in route))
            ok, obs, new_cur, click_status = self._run_route(route, obs)
            if ok:
                return True, obs           # every hop VERIFIED by region-set identity
            logger.info("router: derail: new_cur=%s cur=%s", new_cur, cur)
            # Derail or lost. Made real progress to a KNOWN different node -> replan
            # there. Otherwise (no progress, or identity UNKNOWN=None) -> BACK hop
            # (dismiss a dialog / ascend one level), verify by ACTUAL identity, replan.
            if new_cur is not None and new_cur != cur:
                cur = new_cur
                continue
            if click_status in {"not_attempted", "dispatch_unknown"}:
                logger.info(
                    "router: click status %s at %s; compensating Back is forbidden",
                    click_status, cur)
                break
            if self._back is not None:
                back_source = cur
                obs = self._invoke_back(obs, back_source) or obs
                back_cur = self._invoke_identify(obs, back_source)
                if back_cur and back_cur != back_source:
                    self._persist_verified_hop(
                        back_source, back_cur,
                        _virtual_back_step(
                            back_source,
                            self._back_effect_kind(back_source)))
                if back_cur == target_id:
                    return True, obs
                if back_cur and back_cur != cur:
                    cur = back_cur
                    continue
            logger.info("router: no progress + back didn't help at %s — abort to %s",
                        cur, target_id)
            break
        # Last resort: hard reset to root + route from there. _hard_reset_root returns
        # the ACTUAL identified landing (it may reopen to the last page, not root), so
        # only claim success when the landing TRULY equals the target — no optimism.
        if self._hard_reset_root is None:
            return False, obs
        root_id, obs = self._hard_reset_root()
        if root_id is None:
            return False, obs
        if root_id == target_id:
            return True, obs
        route = self.plan_route(root_id, target_id)
        if not route:
            return False, obs
        ok, obs, _cur, _status = self._run_route(route, obs)
        return ok, obs

    def _back_effect_kind(self, source_id: str) -> str:
        data = self.state_data.get(source_id) or {}
        kinds = {
            str(self._element_value(element, "surface_kind") or "").strip().casefold()
            for element in (data.get("elements") or [])
        }
        return "dismiss_overlay" if kinds & {
            "dialog", "popup", "popup_menu", "menu", "overlay", "drawer",
            "bottom_sheet"} \
            else "return"

    def _persist_verified_hop(self, source_id: str, target_id: str,
                              step: Dict[str, Any]) -> None:
        if self._record_verified_transition is None:
            return
        try:
            self._record_verified_transition(source_id, target_id, dict(step))
        except Exception as exc:
            logger.warning("router: failed to persist verified hop %s -> %s: %s",
                           source_id, target_id, exc)

    def _persist_attempt_outcome(
            self, step: Dict[str, Any], target_id: Optional[str],
            outcome: str) -> None:
        if self._record_attempt_outcome is None:
            return
        try:
            self._record_attempt_outcome(dict(step), target_id, outcome)
        except Exception as exc:
            logger.warning(
                "router: failed to persist attempt outcome %s: %s",
                outcome, exc)

    def _classify_dispatched_landing(
            self, step: Dict[str, Any], landed: Optional[str], *,
            persist_match: bool = True) -> str:
        """Separate an execution failure from a wrong destination prediction."""
        source_id = str(step.get("source_id") or "")
        expected_id = str(step.get("dst") or "")
        actual_id = str(landed or "")
        if not actual_id:
            return "identity_unknown"
        if actual_id == source_id and expected_id != source_id:
            return "no_effect"
        verified_step = dict(step)
        verified_step.update({
            "predicted_target": expected_id,
            "prediction_match": actual_id == expected_id,
        })
        if actual_id != expected_id:
            verified_step.update({
                "dst": actual_id,
                "provenance": "live_corrected",
            })
            self._persist_verified_hop(source_id, actual_id, verified_step)
            return "prediction_corrected"
        if persist_match:
            self._persist_verified_hop(source_id, actual_id, verified_step)
        return "prediction_match"

    def _run_route(self, route: List[Dict[str, Any]], obs: Any
                   ) -> Tuple[bool, Any, Optional[str], str]:
        """Execute a planned route hop-by-hop, verifying arrival each hop. Returns
        (ok, obs, current_id_after) — on a derail, ok=False and current_id_after is
        where we ACTUALLY landed so the caller can replan from there."""
        if not route:                       # defensive: empty route = nothing to do
            return True, obs, None, "not_attempted"
        # A planned route always starts from a verified source node. If the
        # first live target cannot be executed, no action changed the screen;
        # preserve that known actual landing instead of degrading it to None.
        cur = str(route[0].get("source_id") or "") or None
        for step in route:
            action_type = str((step.get("action") or {}).get(
                "action_type") or "").strip().upper()
            if (isinstance(step.get("action"), dict) and step.get("action")
                    and self._execute_action is not None):
                result = self._invoke_action(step, obs)
            elif (action_type in {"BACK", "NAVIGATE_BACK"}
                  or str(step.get("effect_kind") or "").casefold() in {
                    "return", "dismiss_overlay"}):
                if self._back is None:
                    return False, obs, cur, "not_attempted"
                value = self._invoke_back(obs, str(step.get("source_id") or ""))
                result = RouterClickResult.action_dispatched(
                    value if value is not None else obs, "return_primitive")
            else:
                result = self._invoke_click(step, obs)
            if result.status == "not_attempted":
                logger.info("router: hop click '%s' not attempted (%s)",
                            step["name"], result.reason)
                return False, result.observation or obs, cur, result.status
            if result.status == "dispatch_unknown":
                logger.info("router: hop click '%s' dispatch unknown (%s)",
                            step["name"], result.reason)
                return False, result.observation or obs, cur, result.status
            if result.status == "off_app_recovered":
                obs = result.observation if result.observation is not None else obs
                landed = self._resolve_landing(
                    obs, str(step.get("source_id") or ""), step)
                if (landed is not None
                        and landed != str(step.get("source_id") or "")):
                    self.note_arrival(
                        landed, str(step.get("source_id") or ""), step)
                logger.info(
                    "router: hop click '%s' left the target app and was "
                    "recovered by Back; rejecting it as an internal transition",
                    step["name"])
                return False, obs, landed, result.status
            if result.status != "action_dispatched":
                logger.info("router: hop click '%s' returned invalid status %s",
                            step["name"], result.status)
                return False, result.observation or obs, cur, "not_attempted"
            obs = result.observation if result.observation is not None else obs
            landed = self._resolve_landing(
                obs, str(step.get("source_id") or ""), step)
            if (landed is not None
                    and landed != str(step.get("source_id") or "")):
                self.note_arrival(
                    landed, str(step.get("source_id") or ""), step)
            landing_status = self._classify_dispatched_landing(
                step, landed, persist_match=False)
            if (landing_status == "prediction_match"
                    and step.get("provenance") == "direct_verified"
                    and not step.get("probe_required")):
                self._persist_attempt_outcome(
                    step, landed, "transitioned_consistent")
            if landing_status != "prediction_match":
                if landing_status in {"no_effect", "identity_unknown"}:
                    self._persist_attempt_outcome(
                        step, landed, landing_status)
                if landing_status == "no_effect":
                    source_id = str(step.get("source_id") or "")
                    target_id = str(step.get("dst") or "")
                    if source_id and target_id:
                        self._quarantined.add((source_id, target_id))
                        logger.warning(
                            "router: quarantined no-effect edge %s -> %s "
                            "for this run",
                            source_id, target_id)
                logger.info(
                    "router: hop '%s' expected %s got %s (%s) — replan",
                    step["name"], step["dst"], landed, landing_status)
                post_status = (
                    "action_dispatched"
                    if landing_status == "prediction_corrected"
                    else landing_status)
                return False, obs, landed, post_status
            if landed != step["dst"]:
                # [2026-07-07 用户: 去掉乐观拐杖] NO optimism — report the ACTUAL
                # region-set identity (None = "don't know where I am"), NEVER assume
                # the planned dst. The old `landed or step["dst"]` fallback (a pHash-
                # era crutch for identify() returning None on sparse pages) made the
                # router claim it arrived when it had strayed — the stranded-click
                # desync. Region-set identity is reliable now, so require real proof.
                logger.info("router: hop '%s' expected %s got %s — replan",
                            step["name"], step["dst"], landed)
                if landed is not None:
                    actual_step = dict(step)
                    actual_step.update({
                        "dst": landed,
                        "predicted_target": step.get("dst"),
                        "prediction_match": False,
                        "provenance": "live_corrected",
                    })
                    self._persist_verified_hop(
                        str(step.get("source_id") or ""), landed, actual_step)
                return False, obs, landed, result.status
            cur = landed
            if (step.get("provenance") != "direct_verified"
                    or step.get("probe_required")):
                verified_step = dict(step)
                verified_step.update({
                    "predicted_target": step.get("dst"),
                    "prediction_match": True,
                })
                self._persist_verified_hop(
                    step["source_id"], landed, verified_step)
        return True, obs, cur, "action_dispatched"  # all hops VERIFIED -> cur == dst
