"""Visual BFS traversal engine — the a11y-free main loop.

Mirrors the high-level shape of the existing a11y traversal but every decision
is made from screenshots:

  register state (pHash+SSIM) -> perceive & name elements (YOLO+VLM) ->
  enqueue clickable elements (dedup by visual uid) -> click pixel center ->
  observe -> register new/loop state + add edge -> when current state is
  exhausted, dequeue next state with unvisited elements and backtrack to it.

Reuses ``StateGraph`` (add_state/add_transition/save) with ``state_type=
"visual"``. Writes StateGraph-compatible artifacts via ``ArtifactWriter``.
"""

from __future__ import annotations

import copy
import logging
import re
import tempfile
import os
from collections import deque
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..app_lifecycle import (
    DesktopWindowOwner,
    _get_app_window_bbox,
)
from .navigation.frontier import (
    FrontierContext,
    unvisited_candidates as frontier_unvisited_candidates,
)
from .visual_perception import (
    VisualElement,
    VisualPerception,
)
from .stateful import (
    is_active_restore_candidate,
    normalize_state_key,
    resume_stateful_probe_state,
)
from .visual_state import VisualStateRegistry
from .state.resolver import IdentityResolver, identify_existing_frame
# (VisualBacktracker removed 2026-07-05 — the graph router is the sole backtrack
#  mechanism; route_to self-handles no-path via hard-reset-to-root.)
from .artifacts import ArtifactWriter
from . import live_targeting as _live
# [REGION-SCROLL CHANGE 8] region-dedup (node→region→button). Only used when the
# region_dedup flag is on; import is harmless otherwise. revert: remove this import.
from .grounding.region import (
    RegionRegistry,
    assign_elements_to_regions,
    element_is_action,
    element_member_token,
)
from .grounding.scroll import (
    VIEW_STABLE_DISTANCE,
    ScrollContext,
    ScrollRuntime,
)
from .grounding.region.scroll import RegionScrollContext, RegionScrollRuntime
from .grounding.locate import LocateContext, LocateRuntime
from .grounding.stitch import (
    STITCH_TILE_OVERLAP_PX, STITCH_VLM_MAX_H, StitchContext, StitchRuntime,
)
from .runtime.contracts import PerceptionUnavailable
from .runtime.runner import run_traversal
from .runtime.scheduling import available_unvisited_candidates
from .runtime.recovery import (
    adopt_relaunch_landing,
    dismiss_interruptions,
    ensure_on_app,
)
from .state.registration import register_observation, retry_semantic_scroll_audit
from .visual_resume import (
    VisualResumeRebuilder,
    abnormal_button_key as resume_abnormal_button_key,
    assert_runtime_state_consistent,
    sync_live_to_graph as resume_sync_live_to_graph,
)

logger = logging.getLogger(__name__)


DEFAULT_PAUSE = 2.0
GRAPH_SAVE_INTERVAL = 10


def _element_id_text(value) -> str:
    """Stringify an element id without treating numeric zero as missing."""
    return "" if value is None else str(value)


# Scroll/stitch constants are canonical in ``grounding``.
SETTLE_MAX_POLLS = 4
SETTLE_PAUSE = 0.6

# ── [SCROLL-MAP CHANGE 18] map-based desktop goto (flag-guarded, default OFF) ──
# design/modules/scroll_scheme.md: the region is scrolled ONCE into a pixel-exact
# tall MAP; later gotos MEASURE the live viewport's offset inside the map instead
# of counting wheel steps (fling/animation displacement is not reproducible).
# Validated standalone: _scratch/_scrollmap_probe.py run8 = 5/5 landings,
# _scrollmap_sound_demo.py ALL PASS (incl. stale-map auto-rebuild).
# revert: set env GUIWALK_SCROLL_MAP=0 (default) — every _map_* path is dormant.
# Safe reversible function-set toggles enter the existing bounded state probe by
# default.  Set GUIWALK_STATEFUL_DISCOVER_ONLY=1 as an emergency fallback to
# record every such toggle without clicking it; the candidate-loop guard below
# keeps that rollback path isolated from the normal risk-gated transaction.
STATEFUL_DISCOVER_ONLY = os.environ.get("GUIWALK_STATEFUL_DISCOVER_ONLY", "0") != "0"
# Names that carry no discriminating function — perception emits these for
# blank/icon/number boxes. They poison the cross-page name-dedup (root cause #3:
# clicking one 'icon'/'' anywhere would prune every same-named row everywhere) and
# never represent a real navigation target, so they are dropped from the global
# function-dedup and never count as a navigation candidate. All lower-cased.
_GENERIC_NAMES = frozenset({
    "", "icon", "image", "button", "text", "label", "grid", "menu", "more",
    "无名", "图标", "按钮", "未知", "unknown", "n/a", "...", "…",
})

# Genuinely cross-page shared CHROME controls — the same Back/Home/Close/Up
# navigation arrow that legitimately repeats on every page. ONLY these are deduped
# GLOBALLY by name; ordinary list rows are deduped per-(state_id, name) so a
# 'Settings'/'Search'/duplicate row on page A never prunes the same-named row on
# page B (root cause #3). All lower-cased; substring match.
_CHROME_NAMES = (
    "back", "返回", "上一步", "navigate up", "go back", "close", "关闭", "dismiss",
    "home", "主页", "首页", "up", "返回上级", "返回上一页",
)






# [REGION-SCROLL CHANGE 6 helpers] name normalisation for OCR name-verify.
_NAME_TOK = re.compile(r"[0-9a-z一-鿿]+")


def _norm_name(s: str) -> str:
    """Lowercase, keep alnum + CJK tokens, collapse whitespace."""
    return " ".join(_NAME_TOK.findall((s or "").lower()))


def _name_match(target: str, got: str) -> bool:
    """True if OCR/live text ``got`` plausibly IS the ``target`` label.
    Substring hit, or >=60% of the target's tokens present in ``got``."""
    if not target or not got:
        return False
    if target in got:
        return True
    tt = set(_NAME_TOK.findall(target))
    gg = set(_NAME_TOK.findall(got))
    return bool(tt) and (len(tt & gg) / len(tt)) >= 0.6


# [REGION-SCROLL CHANGE 8] modal-aware region segmentation prompt (validated in
# _scratch/_modal_regseg_probe.py). Used only when region_dedup is on.
# [G2 fix 2026-07-03] The modal-aware rewrite dropped the §7 prompt's two load-
# bearing constraints — (a) "app window ONLY, exclude the desktop / system tray /
# left Dock launcher" and (b) a concrete role glossary — and regressed hard on a
# FULL-SCREEN shot: the content region swallowed the Ubuntu Dock icons (VLC/Sheets
# polluted the content signature -> false "shared" skip) and the whole nav sidebar
# collapsed into a single toolbar item. The §7 wording, re-verified live on the
# EXACT failing frame, segments it perfectly (nav_sidebar tight around all 22 rows,
# content starts at the sidebar edge, Dock excluded). Restore those constraints;
# keep the modal branch. revert: git-diff this block back to the terser version.
# [2026-07-07 用户: 身份质检根因] 纯 window-chrome 区块(标题栏/菜单栏/状态栏)每页都一样,
# 对【区分页面】零贡献,却因 VLM seg 不稳定而时有时无地被切出来 -> 混进区块集身份 -> 同一页
# rset 抖动 -> 过度分裂(实证: 蓝牙同图 pHash=0 却因 titlebar 时切时不切建了两个节点)。身份
# 只取【有语义、能区分页面】的区块; chrome 排除。revert: 清空这个集合。
_IDENTITY_CHROME_ROLES = frozenset({"titlebar", "menubar", "statusbar"})



def _region_member_tokens(elements) -> List[str]:
    return [token for token in (element_member_token(e) for e in elements)
            if token]


def _region_action_names(elements) -> List[str]:
    return [e.name for e in elements if element_is_action(e)]


class VisualTraversalEngine:
    def __init__(
        self,
        env,
        agent,
        perception: VisualPerception,
        app_name: str,
        output_root: str,
        max_states: int = 50,
        max_actions: int = 200,
        relaunch_fn: Optional[Callable[[], Dict[str, Any]]] = None,
        focus_guard_enabled: bool = True,
        scroll_aggregate: bool = True,
        settle: bool = True,
        stitch_node_image: bool = False,
        region_dedup: bool = False,
        preserve_initial_surface: bool = False,
        verify_navigation_effect: bool = True,
        verify_return_paths: bool = True,
        explorer_codex_model: str = "",
        desktop_window_owner: Optional[DesktopWindowOwner] = None,
    ):
        from gui_rewalk.src.core.graph.state_graph import StateGraph

        self.env = env
        self.agent = agent
        self.perception = perception
        self.app_name = app_name
        self.desktop_window_owner = desktop_window_owner
        self.max_states = max_states
        self.max_actions = max_actions
        # Scroll-aggregate reveals below-the-fold elements. Touch (Android) uses a
        # SWIPE; desktop uses MOVE-cursor-to-content + wheel SCROLL (the desktop
        # wheel scrolls whatever sits under the cursor, so the cursor must be parked
        # over the scrollable content first — see _scroll_aggregate). The re-perceive
        # + viewport-unchanged patience loop is platform-agnostic, so enabling it on
        # desktop only requires swapping the scroll action + restore. Full-page
        # STITCH stays touch-only (its small-swipe overlap capture is Android-tuned).
        try:
            is_touch = str(getattr(env, "vm_platform", "")).lower() == "android"
        except Exception:
            is_touch = False
        self._is_touch = is_touch
        self._scroll_aggregate_enabled = scroll_aggregate
        # [REGION-SCROLL CHANGE 8] region-dedup: when ON (desktop), node registration
        # segments regions (VLM), registers each in a shared RegionRegistry, scrolls
        # only NEW scrollable regions to full, and SKIPS re-scroll/re-explore of a
        # region already seen on another node. Default OFF = existing behaviour.
        self._region_dedup = bool(region_dedup)
        # An attached/live run may intentionally start on a functional dialog.
        # In that mode the current surface is the traversal root, so startup
        # popup cleanup must not dismiss it before registration.  Keep the
        # historical cleanup behaviour as the default for cold app launches.
        self._preserve_initial_surface = bool(preserve_initial_surface)
        self._verify_navigation_effect = bool(verify_navigation_effect)
        self._proactive_return_verification = bool(verify_return_paths)
        self.region_registry = RegionRegistry()
        self._settle_enabled = settle
        # STITCH_NODE_IMAGE (flag, default OFF = exactly today's per-viewport
        # behaviour). When ON, _scroll_aggregate captures its scroll frames with
        # SMALLER swipes, the engine stitches them into one tall full-page composite
        # (visual_stitch), perceives that composite ONCE for naming (instead of N
        # per-viewport naming calls), uses it as the node's canonical screenshot,
        # and maps each composite-detected element back to its (scroll_step,
        # in-viewport y) so it can still be scrolled-into-view + clicked. Identity is
        # UNCHANGED (element-set / chrome-band — never the composite pixels), so the
        # fling-varying frame-set can't re-introduce scroll-splits. Only meaningful
        # on a touch surface where scroll-aggregate runs.
        self._stitch_node_image = bool(stitch_node_image) and self._scroll_aggregate_enabled
        # Filled by _scroll_aggregate on the most recent call when stitching is ON:
        # the ordered scroll frames (PNG bytes) and per-frame element-anchored
        # content offsets (frame i-1 -> i shift in px, or None). Read by _register
        # immediately after the aggregate call, then cleared.
        self._last_scroll_frames: List[bytes] = []
        self._last_scroll_offsets: List[Optional[float]] = []

        self.graph = StateGraph(app_name)
        # [2026-07-08 用户] 落盘前把 live 元素状态回填进节点(见 _sync_live_to_graph)。
        self.graph._live_sync = self._sync_live_to_graph
        self.registry = VisualStateRegistry(namespace=app_name)
        self.writer = ArtifactWriter(output_root)
        self.graph_save_path = os.path.join(output_root, "graph.json")

        # Shared per-run cache + role ledger.  The ledger is observational and
        # persists logical calls, transport attempts, latency/tokens and cache
        # hits to ``vlm_calls.json`` for cost/quality A/B runs.
        from .visual_cache import VLMCallLedger, VLMRoleCache
        self.vlm_ledger = VLMCallLedger(
            os.path.join(output_root, "vlm_calls.json"),
            response_cache_dir=getattr(
                agent, "vlm_response_cache_dir", None),
        )
        self.vlm_cache = VLMRoleCache(ledger=self.vlm_ledger)

        # In-traversal VLM agent roles (a11y-free): semantic page identity and
        # cross-page explored-function memory. Frontier scheduling itself is
        # deterministic and category-driven; it does not call a chooser VLM.
        from .agents import (
            BlockIdentityJudge, PageIdentityJudge, ExplorerAgent,
            ExplorationMemory, AppFocusGuard, ObserverAgent,
            InterruptionDismisser, AnnotationReviewer, ReviewDebugSink,
            classify_edge_consistency, classify_scroll_waste,
            StatefulRiskGuard)
        self._classify_edge_consistency = classify_edge_consistency
        self._classify_scroll_waste = classify_scroll_waste
        self.stateful_risk_guard = StatefulRiskGuard(
            agent, ledger=self.vlm_ledger)
        self.page_judge = PageIdentityJudge(
            agent, cache=self.vlm_cache, ledger=self.vlm_ledger)
        self.block_identity_judge = BlockIdentityJudge(
            agent, ledger=self.vlm_ledger)
        self.observer = ObserverAgent(agent, ledger=self.vlm_ledger)
        self.explorer = ExplorerAgent(
            agent, ledger=self.vlm_ledger,
            coverage_reviewer=self.observer.compare_coverage,
            codex_model=explorer_codex_model,
            codex_temp_root=os.path.join(output_root, "_explorer_tmp"))
        self.mem = ExplorationMemory()
        # Resume rehydration is built entirely on fresh temporary objects.  The
        # factories clone the live registry configuration so a later resume does
        # not silently reset tuned identity/region thresholds to class defaults.
        self._resume_rebuilder = VisualResumeRebuilder(
            registry_factory=lambda: VisualStateRegistry(
                phash_threshold=self.registry.phash_threshold,
                ssim_threshold=self.registry.ssim_threshold,
                namespace=self.registry.namespace,
            ),
            region_registry_factory=lambda: RegionRegistry(
                overlap_threshold=self.region_registry.overlap_threshold,
                min_names=self.region_registry.min_names,
            ),
            memory_factory=ExplorationMemory,
            element_type=VisualElement,
            identity_chrome_roles=_IDENTITY_CHROME_ROLES,
            normalize_name=_norm_name,
            is_chrome_name=self._is_chrome_name,
        )
        # Exception-handling agent (two-layer, 用户 2026-07-05): grounding flags
        # is_interruption on a frame (boot wizard / cookie / update / permission /
        # ad popup); this VLM agent then picks the control that closes it so we
        # register the REAL page, not the popup (task #42). No hard-coded close-word
        # list — the VLM decides, so non-standard keys / multi-step / decline cases
        # all work.
        self.interruption = InterruptionDismisser(
            agent, ledger=self.vlm_ledger)
        self._dismiss_enabled = True
        # [2026-07-06] Annotation QA: after a node is grounded, a reviewer VLM checks
        # the boxes like a human (wrong / missing / duplicate). Log-only wiring for
        # now (safe, fails open) — surfaces grounding quality per node; the dedup /
        # re-ground / stop-scroll consumption is a follow-up.
        self.reviewer = AnnotationReviewer(agent, ledger=self.vlm_ledger)
        # [2026-07-06] DEBUG-agent mode: with env GUIWALK_REVIEW_DEBUG=1, persist
        # every node's reviewer verdict + engine mis-click/retarget events to
        # <output_root>/_review_debug.jsonl (structured, UTF-8) so a run's grounding
        # quality + fly-clicks are inspectable without grepping the log. No-op when
        # the env is unset (production default).
        _dbg_path = (
            os.path.join(output_root, "_review_debug.jsonl")
            if (os.environ.get("GUIWALK_REVIEW_DEBUG")
                or str(explorer_codex_model or "").strip())
            else None
        )
        self.review_debug = ReviewDebugSink(_dbg_path)
        # [spec B] (src, button-name) -> first dst, for non-deterministic edge detect
        self._edge_dsts: Dict[Any, Any] = {}
        if self.review_debug.enabled:
            logger.info("review DEBUG sink ON -> %s", _dbg_path)
        # Let perception reuse the same pHash cache for its naming call so a
        # re-perceived identical frame (route/reconcile re-observe) isn't re-named.
        try:
            self.perception.cache = self.vlm_cache
            self.perception.vlm_ledger = self.vlm_ledger
        except Exception:
            pass
        # [2026-07-07 用户 删除] 感知 state-reuse(pHash 抄近路)已删:它在 grounding
        # 之前用 pHash 判身份、绕过 region-set,GNOME Settings 框架相似的子页被误判成
        # 已见帧 → 复用旧元素 → content 区块永不更新 → 全部假合并进 Network(暗坑)。
        # 每帧都真感知,region-set 身份才能生效。
        # App-focus uses only Android task/activity or desktop window-owner
        # metadata. Screenshot/VLM ownership guessing is intentionally absent.
        self.relaunch_fn = relaunch_fn
        self.focus_guard = (
            AppFocusGuard(
                env, app_name, is_touch=self._is_touch,
                desktop_window_owner=desktop_window_owner)
            if focus_guard_enabled else None)
        self._relaunch_attempts = 0

        # [2026-07-05 用户决定] The legacy VisualBacktracker (blind BACK / raw path
        # replay / hard reset) was REMOVED — the graph router below is the SOLE
        # backtrack mechanism. Its route_to() self-handles the no-path case by
        # hard-resetting to root and re-routing, so no separate backtracker is
        # needed; the old blind BACK is exactly what thrashed into the sibling-page
        # retry storms (settings run 2026-07-05).

        # state_id -> {"elements": [VisualElement], "path": [action dicts]}
        self._state_data: Dict[str, Dict[str, Any]] = {}
        self._bfs_queue: deque[str] = deque()
        self._visited_uids: set[str] = set()
        # Failed live-target / semantic-effect attempts are retried once.  The
        # second failure retires only this node-local candidate (without marking
        # the shared region ledger), preventing an infinite retry while allowing
        # the same shared button to be resolved from another stable page.
        self._click_failures: Dict[Tuple[str, str], int] = {}
        # An unresolved read-only transition judgment must not cause the source
        # control to be clicked again immediately. Keep it pending but out of
        # this run's frontier; the observed landing remains available for work.
        self._observer_unresolved_controls: set[Tuple[str, str]] = set()
        self._targeting_corrections: Dict[Tuple[str, str], str] = {}
        # Terminal button failures. Shared desktop regions use region_id+name;
        # pages without a stable region fall back to state_id+uid/name.
        self._abnormal_buttons: set[tuple[str, str, str]] = set()
        self._last_off_app_kind = ""
        self._last_off_app_reason = ""
        self._last_off_app_recovered_by_back = False
        # The latest real Region set supports arrival reconciliation; quarantined
        # edges remain excluded from Router planning.
        self._last_arrival_rset: set = set()
        self._quarantined_edges: set = set()
        # [homogeneous-group cross-frame dedup] (state_id, group) pairs whose ONE
        # representative was already explored. Survives re-detection, so a
        # same-kind list (app-notification items backups/files/…, alarms, songs)
        # is NOT re-entered from its first item every time we return to the page.
        # The per-frame seen_groups collapse only dedups within one detection;
        # this makes "explore one representative" persist across frames — the fix
        # for the backups dialog spin (stale uid/name that live-dedup misses).
        self._explored_groups: set[tuple[str, str]] = set()
        # Functional-state controls are explored one axis at a time.  While a
        # reversible mutation is active, shared navigation and independent state
        # axes are held back until the newly exposed local functions are drained,
        # then the inverse control is executed and verified.  This avoids the 2^N
        # product of unrelated switches and prevents a run from casually leaving
        # the sandbox in a mutated state.
        self._active_state_mutation: Optional[Dict[str, Any]] = None
        self._stateful_inflight: Optional[Dict[str, Any]] = None
        self._stateful_probe_count = 0
        self._stateful_probe_sources: set[tuple[str, str, str]] = set()
        # Zero means no separate stateful cap: the global action budget and the
        # mandatory one-axis-at-a-time restore transaction already bound work.
        # A finite opt-in cap is fail-closed at traversal end; it may never make
        # the frontier look complete while safe controls remain unexecuted.
        self._stateful_probe_limit = max(
            0, int(os.environ.get("GUIWALK_MAX_STATEFUL_PROBES", "0")))
        self._stateful_per_node_limit = max(
            0, int(os.environ.get("GUIWALK_MAX_STATEFUL_PROBES_PER_NODE", "0")))
        self._stateful_budget_blocked = False
        self._action_count = 0
        self._map_guided_inherited = None
        self._map_guided_bypass_once = False
        # [M1 graph router, §11] ALWAYS ON (2026-07-05 用户决定: sole backtrack
        # mechanism; the GUIWALK_GRAPH_ROUTER flag + its off-path were removed). A
        # frontier backtrack routes by GRAPH PATH (region-inherited edges, Q2) —
        # sidebar edges are inherited by every page, so returning to any node is a
        # shortest hop sequence, not a sibling-page-confusing blind BACK. route_to
        # self-handles no-path by hard-resetting to root + re-routing. Router holds
        # only graph/plan logic; the execution primitives are engine-provided.
        from .navigation.router import VisualRouter
        self.router = VisualRouter(
            graph=self.graph, region_registry=self.region_registry,
            state_data=self._state_data,
            identify_fn=self._router_identify,
            click_button_fn=self._router_click_button,
            execute_action_fn=self._router_execute_action,
            back_fn=self._router_back,
            hard_reset_root_fn=self._router_hard_reset_root,
            verified_transition_fn=self._record_router_verified_transition,
            attempt_outcome_fn=self._record_router_attempt_outcome,
            register_landing_fn=self._router_register_actual_landing,
            quarantined_edges=self._quarantined_edges)   # [问题1] 绕开串页隔离边
        self.identity_resolver = IdentityResolver(
            registry=self.registry,
            state_data=self._state_data,
            judge=self.page_judge,
            descriptor_fn=self._node_descriptor,
            local_candidates_fn=lambda source_id, clicked_label: (
                self.router.expected_destinations(
                    source_id, clicked_label)
            ),
        )
        logger.info("[M1] graph router ACTIVE (sole backtrack mechanism)")
        # Diagnostic total only. Route retirement is bounded per historical
        # target; failures from unrelated targets must not terminate the run.
        self._backtrack_fail_count = 0
        # Route failures are transient run evidence, not permanent graph truth.
        # A target is cooled down until new graph progress appears; unresolved
        # cooled work produces routing_incomplete rather than frontier_empty.
        self._route_blocked_targets: set[str] = set()
        self._route_failures: Dict[Tuple[str, str], Dict[str, Any]] = {}
        self._route_target_failure_counts: Dict[str, int] = {}
        # Invalid Explorer output is local to one State/Region. Keep it out of
        # the active frontier until other work has run, without claiming any
        # controls covered or absent.
        self._explorer_deferred_regions: set[Tuple[str, str]] = set()
        self._explorer_region_failure_counts: Dict[Tuple[str, str], int] = {}
        self._element_exploration_task: Optional[Dict[str, Any]] = None
        self._return_probe_status: Dict[Tuple[str, str], Dict[str, Any]] = {}
        # Thrash guard. Backtrack work (BACK presses, pm-clear relaunches, replay)
        # does NOT increment _action_count, so a run that SUCCEEDS at each
        # backtrack but never registers a new node (re-exploring the same handful
        # of pages, each move a slow hard-reset) is invisible to the max_actions
        # budget and can spin for HOURS (observed: settings breadth-first did 1546
        # hard-resets / 7 nodes / ~7h before the wall clock). Count consecutive
        # frontier MOVES (dequeue+backtrack) that produce no new node; once the
        # graph stops growing for this many moves the frontier is unproductive
        # here — end cleanly with whatever was collected.
        self._moves_without_new = 0
        self._last_node_count = 0

    # Consecutive backtrack-moves with ZERO new nodes before we declare the
    # frontier unproductive and stop (each move can be a slow relaunch, so this
    # bounds a thrash to minutes, not hours).
    MAX_MOVES_WITHOUT_NEW = 25

    # ── helpers ──────────────────────────────────────────────────────────
    def _screenshot_to_tmp(self, shot: bytes) -> str:
        tmp = tempfile.NamedTemporaryFile(suffix=".png", delete=False)
        tmp.write(shot)
        tmp.close()
        return tmp.name

    @staticmethod
    def _screen_wh(obs: Dict[str, Any]) -> Tuple[int, int]:
        """(w, h) of the current screenshot — the pixel space the element boxes
        and centers live in. Read from the screenshot itself so it matches the
        coordinates exactly (avoids any logical-vs-physical resolution mismatch).
        Falls back to a phone-portrait default if the obs has no usable shot."""
        import io as _io
        from PIL import Image
        shot = obs.get("screenshot") if isinstance(obs, dict) else None
        if shot:
            try:
                return Image.open(_io.BytesIO(shot)).size  # (w, h)
            except Exception:
                pass
        return (1080, 2400)

    @staticmethod
    def _frame_phash(shot: bytes):
        """pHash of a frame for cheap same-view comparison (settle / scroll)."""
        import io as _io
        import imagehash
        from PIL import Image
        return imagehash.phash(Image.open(_io.BytesIO(shot)).convert("RGB"))

    def _frame_state_id(self, obs: Optional[Dict[str, Any]],
                        elements: Optional[List["VisualElement"]] = None
                        ) -> Optional[str]:
        return identify_existing_frame(self, obs, elements)

    @staticmethod
    def _renumber_unique(elements: List[VisualElement]) -> None:
        """Give every element a unique contiguous ``id`` for THIS node, in place.

        Perception numbers each frame 0..N on its own; the scroll-aggregate then
        concatenates the top frame with each re-perceived scrolled frame, so the
        merged set carries DUPLICATE ids (the same 0..N run repeated per frame).
        A node must own a single id space — otherwise an id->element map collides
        and the wrong element is clicked. We assign ids in reading order
        (top→bottom, left→right) so the numbering is stable across re-visits and
        matches the order the frontier scheduler and SoM image present elements in.
        Each element's name / clickable flag / center are untouched and travel
        with their record, so re-id only fixes the KEY, never the binding."""
        order = sorted(range(len(elements)),
                       key=lambda i: (elements[i].center[1], elements[i].center[0]))
        for new_id, i in enumerate(order):
            elements[i].id = new_id

    def _settle(self, obs: Dict[str, Any]) -> Dict[str, Any]:
        """Poll until two consecutive frames are pHash-stable before we treat
        ``obs`` as canonical. Removes transient keyboard/transition frames so the
        registered node screenshot (and its pHash state-id) is a settled view at
        a uniform resolution — the blurry/mid-animation 'All apps' & 'Search'
        nodes the reviewer flagged. Best-effort: returns the latest obs on any
        error or if it never fully settles within ``SETTLE_MAX_POLLS``."""
        import time as _time
        shot = obs.get("screenshot")
        if not shot:
            return obs
        try:
            prev = self._frame_phash(shot)
        except Exception:
            return obs
        for _ in range(SETTLE_MAX_POLLS):
            _time.sleep(SETTLE_PAUSE)
            try:
                nxt = self.env._get_obs()
            except Exception:
                return obs
            nshot = nxt.get("screenshot")
            if not nshot:
                return obs
            try:
                cur = self._frame_phash(nshot)
            except Exception:
                return nxt
            obs = nxt
            if (cur - prev) <= VIEW_STABLE_DISTANCE:
                return nxt  # two consecutive stable frames -> settled
            prev = cur
        return obs

    def _dismiss_interruptions(self, obs: Dict[str, Any],
                               force_first: bool = False,
                               page_identity_flagged: bool = False
                               ) -> Dict[str, Any]:
        return dismiss_interruptions(
            self, obs, pause=DEFAULT_PAUSE, force_first=force_first,
            page_identity_flagged=page_identity_flagged)

    def _record_scroll_evidence(self, **payload: Any) -> None:
        recorder = getattr(getattr(self, "graph", None),
                           "record_scroll_scope", None)
        if recorder is None:
            return
        try:
            recorder(**payload)
        except Exception as exc:
            logger.debug("scroll evidence record failed: %s", exc)

    def _begin_node_local_accumulation(self) -> None:
        self._scroll_node_local_functions: List[Dict[str, Any]] = []
        VisualTraversalEngine._accumulate_node_local_functions(self)

    def _accumulate_node_local_functions(self) -> None:
        """Union non-frontier function records from every grounded viewport."""
        records = getattr(self, "_scroll_node_local_functions", None)
        if records is None:
            records = self._scroll_node_local_functions = []
        for record in list(getattr(
                getattr(self, "perception", None),
                "last_node_local_functions", []) or []):
            if isinstance(record, dict) and record not in records:
                records.append(copy.deepcopy(record))

    def _collected_node_local_functions(
        self, initial: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        records = [copy.deepcopy(item) for item in (initial or [])]
        for record in getattr(self, "_scroll_node_local_functions", []) or []:
            if isinstance(record, dict) and record not in records:
                records.append(copy.deepcopy(record))
        return records

    def _new_scroll_runtime(self) -> ScrollRuntime:
        return ScrollRuntime(ScrollContext(
            env=self.env, perception=self.perception,
            focus_guard=getattr(self, "focus_guard", None),
            page_judge=getattr(self, "page_judge", None),
            block_identity_judge=getattr(
                self, "block_identity_judge", None),
            region_registry=getattr(self, "region_registry", None),
            writer=getattr(self, "writer", None),
            state_data=getattr(self, "_state_data", {}),
            pending_transition=getattr(self, "_pending_transition", None),
            is_touch=getattr(self, "_is_touch", True),
            stitch_node_image=getattr(self, "_stitch_node_image", False),
            last_scroll_frames=list(getattr(self, "_last_scroll_frames", [])),
            last_scroll_offsets=list(getattr(self, "_last_scroll_offsets", [])),
            semantic_scroll_seed_region_crops=dict(getattr(
                self, "_semantic_scroll_seed_region_crops", {}) or {}),
            semantic_scroll_seed_region_bboxes=dict(getattr(
                self, "_semantic_scroll_seed_region_bboxes", {}) or {}),
            semantic_scroll_force_top=bool(getattr(
                self, "_semantic_scroll_force_top", False)),
            frame_phash=self._frame_phash, screen_wh=self._screen_wh,
            record_scroll_evidence=self._record_scroll_evidence,
            map_to_top=self._map_to_top,
            begin_node_local_accumulation=self._begin_node_local_accumulation,
            accumulate_node_local_functions=self._accumulate_node_local_functions,
            collected_node_local_functions=self._collected_node_local_functions))

    def _sync_scroll_runtime(self, runtime: ScrollRuntime) -> None:
        self._last_scroll_frames = runtime._last_scroll_frames
        self._last_scroll_offsets = runtime._last_scroll_offsets

    def _is_short_non_scrollable_overlay(self, obs, elements):
        return self._new_scroll_runtime()._is_short_non_scrollable_overlay(obs, elements)

    def _scroll_aggregate(self, obs, first_elements, state_id=""):
        runtime = self._new_scroll_runtime()
        try:
            return runtime._scroll_aggregate(obs, first_elements, state_id)
        finally:
            self._sync_scroll_runtime(runtime)

    def _desktop_regional_scroll(self, obs, first_elements, state_id=""):
        runtime = self._new_scroll_runtime()
        try:
            return runtime._desktop_regional_scroll(obs, first_elements, state_id)
        finally:
            self._sync_scroll_runtime(runtime)

    def _detect_boxes_only(self, shot):
        return self._new_scroll_runtime()._detect_boxes_only(shot)

    @staticmethod
    def _element_anchored_offset(prev_shot, prev_elems, cur_shot, cur_elems):
        return ScrollRuntime._element_anchored_offset(prev_shot, prev_elems, cur_shot, cur_elems)

    def _scroll_back_to_top(self, top_view, down_steps):
        return self._new_scroll_runtime()._scroll_back_to_top(top_view, down_steps)

    # [REGION-SCROLL CHANGE 2b — entire method is additive; revert: delete it]

    # [REGION-SCROLL CHANGE 8 — additive; used only when region_dedup is ON]
    @staticmethod
    def _set_runtime_attr(owner, name, value):
        setattr(owner, name, value)

    def _new_region_scroll_runtime(self, *, segment_override=None):
        return RegionScrollRuntime(RegionScrollContext(
            perception=getattr(self, "perception", None),
            env=getattr(self, "env", None),
            region_registry=getattr(self, "region_registry", None),
            review_debug=getattr(self, "review_debug", None),
            vlm_ledger=getattr(self, "vlm_ledger", None),
            region_composites=getattr(self, "_region_composites", {}),
            segment_regions_override=segment_override,
            desktop_regional_scroll=self._desktop_regional_scroll,
            classify_scroll_waste=getattr(
                self, "_classify_scroll_waste", lambda *_a, **_k: None),
            record_scroll_evidence=self._record_scroll_evidence,
            begin_node_local_accumulation=self._begin_node_local_accumulation,
            accumulate_node_local_functions=self._accumulate_node_local_functions,
            cache_key_get=lambda: getattr(self, "_seg_cache_key", None),
            cache_key_set=lambda value: self._set_runtime_attr(self, "_seg_cache_key", value),
            cache_value_get=lambda: getattr(self, "_seg_cache_val", None),
            cache_value_set=lambda value: self._set_runtime_attr(self, "_seg_cache_val", value)))

    def _segment_regions(self, shot, elements=None):
        # The model-backed legacy Region partitioner was retired. Formal
        # Region-lazy traversal uses Page map + Region locator instead.
        return []

    @staticmethod
    def _region_element_signature(elements):
        return RegionScrollRuntime._region_element_signature(elements)

    def _segment_regions_cached(self, shot, elements=None, *, force_refresh=False):
        return self._new_region_scroll_runtime(
            segment_override=self._segment_regions
        )._segment_regions_cached(
            shot, elements, force_refresh=force_refresh)

    def _stabilize_region_observations(self, regions, elements):
        return self._new_region_scroll_runtime()._stabilize_region_observations(
            regions, elements)

    def _regional_scroll_dedup(self, obs, first_elements, state_id):
        return self._new_region_scroll_runtime(segment_override=self._segment_regions)._regional_scroll_dedup(obs, first_elements, state_id)






    def _new_stitch_runtime(self) -> StitchRuntime:
        return StitchRuntime(StitchContext(
            perception=self.perception, is_touch=getattr(self, "_is_touch", True),
            screen_wh=self._screen_wh,
            frames=list(getattr(self, "_last_scroll_frames", [])),
            offsets=list(getattr(self, "_last_scroll_offsets", [])),
            vlm_max_height=int(getattr(self, "STITCH_VLM_MAX_H", STITCH_VLM_MAX_H)),
            tile_overlap_px=int(getattr(self, "STITCH_TILE_OVERLAP_PX", STITCH_TILE_OVERLAP_PX))))

    def _sync_stitch_runtime(self, runtime: StitchRuntime) -> None:
        self._last_scroll_frames = runtime._last_scroll_frames
        self._last_scroll_offsets = runtime._last_scroll_offsets

    def _build_stitched_node(self, top_shot):
        runtime = self._new_stitch_runtime()
        try:
            return runtime._build_stitched_node(top_shot)
        finally:
            self._sync_stitch_runtime(runtime)

    def _map_composite_elements_back(self, elements, res, frames, comp_h):
        return self._new_stitch_runtime()._map_composite_elements_back(elements, res, frames, comp_h)

    def _composite_chunk_bounds(self, res, comp_h, cap):
        return self._new_stitch_runtime()._composite_chunk_bounds(res, comp_h, cap)

    @staticmethod
    def _is_stitched_system_ui_element(res, elem):
        return StitchRuntime._is_stitched_system_ui_element(res, elem)

    def _perceive_tiled(self, res, composite_png, cap):
        return self._new_stitch_runtime()._perceive_tiled(res, composite_png, cap)


    # ── tall-composite tiling (VLM downscale-recall fix) ─────────────────────







    # Map/OCR localization is implemented in grounding.locate. These wrappers
    # preserve the engine API and synchronize the small mutable runtime contract.

    def _new_locate_runtime(self) -> LocateRuntime:
        return LocateRuntime(LocateContext(
            env=self.env,
            perception=self.perception,
            region_maps=getattr(self, "_region_maps", {}),
            map_seg_cache=getattr(self, "_map_seg_cache", {}),
            map_anims_off=getattr(self, "_map_anims_off", False),
            last_live_rebind_observation=getattr(
                self, "_last_live_rebind_observation", None),
            segment_regions=self._segment_regions,
            screen_wh=self._screen_wh,
            ensure_on_app=self._ensure_on_app,
            best_live_rebind_match=self._best_live_rebind_match,
            is_explicit_noninteractive=self._is_explicit_noninteractive,
        ))

    def _sync_locate_runtime(self, runtime: LocateRuntime) -> None:
        self._region_maps = runtime._region_maps
        self._map_seg_cache = runtime._map_seg_cache
        self._map_anims_off = runtime._map_anims_off
        self._last_live_rebind_observation = (
            runtime._last_live_rebind_observation
        )

    def _call_locate_runtime(self, method, *args, **kwargs):
        runtime = self._new_locate_runtime()
        try:
            return getattr(runtime, method)(*args, **kwargs)
        finally:
            self._sync_locate_runtime(runtime)

    def _map_frame(self):
        return self._call_locate_runtime("_map_frame")

    def _map_segments_cached(self, obs, win_key):
        return self._call_locate_runtime("_map_segments_cached", obs, win_key)

    def _map_region_candidates(self, elem, obs, node_elements=None):
        return self._call_locate_runtime(
            "_map_region_candidates", elem, obs, node_elements)

    def _map_park(self, rect):
        return self._call_locate_runtime("_map_park", rect)

    def _map_wheel(self, park_xy, direction, amount):
        return self._call_locate_runtime(
            "_map_wheel", park_xy, direction, amount)

    def _map_settle_crop(
        self, rect, timeout=2.5, interval=0.18, outage_grace=12.0
    ):
        return self._call_locate_runtime(
            "_map_settle_crop", rect, timeout, interval, outage_grace)

    def _map_disable_animations(self):
        return self._call_locate_runtime("_map_disable_animations")

    def _map_to_top(self, rect, park_xy=None):
        return self._call_locate_runtime("_map_to_top", rect, park_xy)

    def _map_build(self, rect, park_xy=None):
        return self._call_locate_runtime("_map_build", rect, park_xy)

    def _map_name_index(self, map_img):
        return self._call_locate_runtime("_map_name_index", map_img)

    def _map_resolve_name(self, index, name):
        return self._call_locate_runtime("_map_resolve_name", index, name)

    def _map_localize(self, live_crop, map_img):
        return self._call_locate_runtime("_map_localize", live_crop, map_img)

    def _map_goto(self, elem, obs, node_elements=None):
        return self._call_locate_runtime(
            "_map_goto", elem, obs, node_elements)

    def _map_goto_once(self, elem, obs, node_elements=None):
        return self._call_locate_runtime(
            "_map_goto_once", elem, obs, node_elements)

    def _ocr_text_at(self, shot_bytes, center, tmpl_shape):
        return self._call_locate_runtime(
            "_ocr_text_at", shot_bytes, center, tmpl_shape)

    def _vlm_locate_by_name(self, shot_bytes, target, stored=None):
        return self._call_locate_runtime(
            "_vlm_locate_by_name", shot_bytes, target, stored)

    def _ocr_live_center_by_name(
        self, shot_bytes: bytes, elem: VisualElement, live_bbox_xywh=None
    ) -> Optional[List[int]]:
        return self._call_locate_runtime(
            "_ocr_live_center_by_name", shot_bytes, elem, live_bbox_xywh)


    @staticmethod
    def _bbox_iou_xywh(left: Any, right: Any) -> float:
        return _live.bbox_iou_xywh(left, right)




    @staticmethod
    def _bbox_area_xywh(bbox: Any) -> float:
        return _live.bbox_area_xywh(bbox)

    @classmethod
    def _topup_match_score(
        cls,
        stored: VisualElement,
        fresh: VisualElement,
    ) -> Optional[Tuple[Any, ...]]:
        """Score two revisit observations only when they denote one control.

        Appearance UIDs are useful but not globally unique: repeated list rows
        often share the same icon crop.  A UID therefore needs physical overlap
        (or very small center drift).  A structured ``state_key`` is stronger and
        deliberately merges a coarse whole-row switch alias with the compact
        switch widget discovered on a later pass.
        """
        stored_key = " ".join(
            str(getattr(stored, "state_key", "") or "").casefold().split())
        fresh_key = " ".join(
            str(getattr(fresh, "state_key", "") or "").casefold().split())
        iou = cls._bbox_iou_xywh(
            getattr(stored, "bbox_xywh", []),
            getattr(fresh, "bbox_xywh", []),
        )
        try:
            distance = (
                (float(stored.center[0]) - float(fresh.center[0])) ** 2
                + (float(stored.center[1]) - float(fresh.center[1])) ** 2
            ) ** 0.5
        except Exception:
            distance = float("inf")
        stored_uid = str(getattr(stored, "uid", "") or "")
        fresh_uid = str(getattr(fresh, "uid", "") or "")
        uid_match = bool(stored_uid and stored_uid == fresh_uid)
        name_match = bool(
            _norm_name(getattr(stored, "name", ""))
            and _norm_name(getattr(stored, "name", ""))
            == _norm_name(getattr(fresh, "name", "")))

        if stored_key and stored_key == fresh_key:
            return (4, iou, uid_match, name_match, -distance)
        if uid_match and (iou >= 0.25 or distance <= 24.0):
            return (3, iou, name_match, -distance)

        stored_semantic = (
            _norm_name(getattr(stored, "name", "")),
            str(getattr(stored, "group", "") or ""),
            str(getattr(stored, "state_value", "") or ""),
            str(getattr(stored, "region", "") or ""),
        )
        fresh_semantic = (
            _norm_name(getattr(fresh, "name", "")),
            str(getattr(fresh, "group", "") or ""),
            str(getattr(fresh, "state_value", "") or ""),
            str(getattr(fresh, "region", "") or ""),
        )
        if (stored_semantic[0] and stored_semantic == fresh_semantic
                and (iou >= 0.20 or distance <= 24.0)):
            return (2, iou, -distance)
        if name_match and iou >= 0.65:
            return (1, iou, -distance)
        return None

    @classmethod
    def _merge_topup_observation(
        cls,
        stored: VisualElement,
        fresh: VisualElement,
    ) -> bool:
        """Merge a fresh physical observation without erasing audit history.

        Returns ``True`` only when the fresh frame explicitly downgrades a stale
        interactive candidate to display/noninteractive.  IDs, stable UIDs,
        visited state and terminal outcomes remain attached to the original
        ledger entry; live geometry and more precise stateful-widget semantics
        may be refreshed.
        """
        was_noninteractive = cls._is_explicit_noninteractive(stored)
        fresh_noninteractive = cls._is_explicit_noninteractive(fresh)
        visited = bool(getattr(stored, "visited", False))
        abnormal_reason = str(getattr(stored, "abnormal_reason", "") or "")
        abnormal_detail = str(getattr(stored, "abnormal_detail", "") or "")

        state_key_match = bool(
            str(getattr(stored, "state_key", "") or "").strip()
            and " ".join(
                str(getattr(stored, "state_key", "") or "")
                .casefold().split())
            == " ".join(
                str(getattr(fresh, "state_key", "") or "")
                .casefold().split())
        )
        widget_types = {
            "switch", "toggle", "checkbox", "radio", "radio button",
        }
        stored_type = " ".join(
            str(getattr(stored, "el_type", "") or "").casefold().split())
        fresh_type = " ".join(
            str(getattr(fresh, "el_type", "") or "").casefold().split())
        prefer_fresh_geometry = not state_key_match or (
            (fresh_type in widget_types and stored_type not in widget_types)
            or (
                fresh_type in widget_types
                and stored_type in widget_types
                and cls._bbox_area_xywh(fresh.bbox_xywh)
                < cls._bbox_area_xywh(stored.bbox_xywh)
            )
        )
        if prefer_fresh_geometry:
            stored.bbox_xywh = list(fresh.bbox_xywh)
            stored.center = [int(fresh.center[0]), int(fresh.center[1])]
            stored.scroll_steps = int(getattr(fresh, "scroll_steps", 0) or 0)
            template = getattr(fresh, "_template", None)
            if template is not None:
                stored._template = template
        # Region/context visual memory is runtime evidence.  Preserve it across
        # an identity merge even when the stored semantic ledger entry wins.
        for attr in (
                "region_bbox", "_region_template", "_region_map",
                "_context_template", "_context_center_offset"):
            value = getattr(fresh, attr, None)
            if value is not None:
                setattr(stored, attr, value)

        if (not getattr(stored, "name", "")
                or VisualTraversalEngine._is_generic_name(stored.name)):
            stored.name = fresh.name or stored.name
        stored.el_type = fresh.el_type or stored.el_type
        stored.score = max(float(getattr(stored, "score", 0.0) or 0.0),
                           float(getattr(fresh, "score", 0.0) or 0.0))
        stored.source = fresh.source or stored.source
        stored.enabled = fresh.enabled
        stored.requires_permission = bool(fresh.requires_permission)
        stored.blocked_reason = fresh.blocked_reason or ""
        stored.back = bool(fresh.back)
        stored.selected = bool(fresh.selected)
        stored.group = fresh.group or stored.group
        stored.purpose = fresh.purpose or stored.purpose
        stored.expected_immediate_effect = (
            fresh.expected_immediate_effect
            or stored.expected_immediate_effect
        )
        stored.visible_state = fresh.visible_state or ""
        stored.semantic_evidence = fresh.semantic_evidence or ""
        stored.execution_safety = (
            fresh.execution_safety or stored.execution_safety
        )
        if fresh.changes_available_controls is not None:
            stored.changes_available_controls = (
                fresh.changes_available_controls
            )
        stored.region = fresh.region or stored.region
        stored.region_id = fresh.region_id or stored.region_id
        if getattr(fresh, "identity_anchor", None) is not None:
            stored.identity_anchor = fresh.identity_anchor
        if getattr(fresh, "surface_kind", ""):
            stored.surface_kind = fresh.surface_kind
        if getattr(fresh, "surface_bbox_xywh", None):
            stored.surface_bbox_xywh = list(fresh.surface_bbox_xywh)
        if getattr(fresh, "surface_scrollable", None) is not None:
            stored.surface_scrollable = fresh.surface_scrollable

        if fresh_noninteractive:
            stored.interactive = False
            stored.category = "display"
            stored.stateful = False
            stored.state_key = ""
            stored.state_value = ""
            stored.effect_scope = ""
            stored.reversible = None
            stored.risk = ""
        elif not was_noninteractive:
            stored.interactive = fresh.interactive
            stored.category = fresh.category or stored.category
            stored.stateful = bool(fresh.stateful)
            stored.state_key = fresh.state_key or stored.state_key
            stored.state_value = fresh.state_value or stored.state_value
            stored.effect_scope = fresh.effect_scope or stored.effect_scope
            stored.reversible = fresh.reversible
            stored.risk = fresh.risk or stored.risk

        # Scheduling/audit evidence belongs to the persisted entry, not to a
        # newly perceived duplicate.
        stored.visited = visited or fresh_noninteractive
        stored.abnormal_reason = abnormal_reason
        stored.abnormal_detail = abnormal_detail
        return fresh_noninteractive and not was_noninteractive

    @staticmethod
    def _is_explicit_noninteractive(element: VisualElement) -> bool:
        return _live.is_explicit_noninteractive(element)

    def _best_live_rebind_match(
        self,
        stored: VisualElement,
        live: List[VisualElement],
        shot: bytes,
    ) -> Optional[VisualElement]:
        """Find the strongest current-frame counterpart without guessing a click."""
        return _live.best_live_rebind_match(
            stored,
            live,
            shot,
            normalize_name=_norm_name,
            name_matches=_name_match,
        )


    def _live_center_for(
        self, elem: VisualElement, obs: Optional[Dict[str, Any]],
        correction_hint: str = "",
    ) -> Optional[List[int]]:
        """Return the reviewed Qwen-grounded center on the current frame.

        Historical geometry, OCR, templates and scroll maps may bring a target
        into view, but never authorize the final click.  The chosen element is
        rebound from one current-frame grounding batch and reviewed against that
        batch's SoM image.  If QA explicitly rejects the chosen box, one forced
        re-ground is allowed; a second rejection fails closed.
        """
        self._last_live_rebind_observation = None
        targeting = _live.LiveTargeting(
            env=getattr(self, "env", None),
            perception=getattr(self, "perception", None),
            reviewer=getattr(self, "reviewer", None),
            normalize_name=_norm_name,
            name_matches=_name_match,
            semantic_attempt_sink=getattr(
                getattr(self, "writer", None),
                "save_target_grounding_attempt", None),
        )
        center = targeting.live_center_for(
            elem, obs, correction_hint=correction_hint)
        self._last_live_rebind_observation = targeting.last_observation
        return center

    def _retire_live_noninteractive_reclassification(
        self,
        state_id: str,
        elem: VisualElement,
    ) -> bool:
        observation = getattr(self, "_last_live_rebind_observation", None)
        if not isinstance(observation, dict) \
                or observation.get("status") != "noninteractive":
            return False
        fresh = observation.get("fresh")
        if not isinstance(fresh, VisualElement) \
                or not self._is_explicit_noninteractive(fresh):
            return False

        def _same(candidate: VisualElement) -> bool:
            if candidate is elem:
                return True
            left_uid = str(getattr(candidate, "uid", "") or "")
            right_uid = str(getattr(elem, "uid", "") or "")
            if left_uid and right_uid:
                return left_uid == right_uid
            return (
                str(getattr(candidate, "id", "")) == str(getattr(elem, "id", ""))
                and _norm_name(candidate.name) == _norm_name(elem.name)
            )

        for candidate in (
                self._state_data.get(state_id, {}).get("elements", []) or []):
            if not _same(candidate):
                continue
            candidate.interactive = False
            candidate.category = "display"
            candidate.el_type = fresh.el_type or candidate.el_type
            candidate.enabled = fresh.enabled
            candidate.requires_permission = fresh.requires_permission
            candidate.blocked_reason = fresh.blocked_reason
            candidate.stateful = False
            candidate.visited = True
            candidate.exploration_status = "terminal"
            candidate.abnormal_reason = ""
            candidate.abnormal_detail = ""
        elem.interactive = False
        elem.category = "display"
        elem.visited = True
        elem.exploration_status = "terminal"
        self._click_failures.pop((state_id, elem.uid or elem.name), None)

        graph_reclassify = getattr(
            getattr(self, "graph", None),
            "reclassify_element_noninteractive",
            None,
        )
        if callable(graph_reclassify):
            graph_reclassify(
                state_id,
                element_id=str(elem.id),
                element_uid=str(elem.uid or ""),
                element_label=str(elem.name or ""),
            )
            try:
                node = self.graph.graph.nodes[state_id]
                data = self._state_data.get(state_id) or {}
                data["visible_capabilities"] = list(
                    node.get("visible_capabilities") or [])
            except Exception:
                pass

        data = self._state_data.get(state_id) or {}
        writer = getattr(self, "writer", None)
        if writer is not None and hasattr(writer, "update_node_observation"):
            try:
                node = self.graph.graph.nodes[state_id]
                writer.update_node_observation(
                    state_id,
                    elements=[candidate.to_dict() for candidate in (
                        data.get("elements") or [])],
                    page_name=str(data.get("page_name") or ""),
                    page_id=str(data.get("page_id") or ""),
                    variant_id=str(data.get("variant_id") or state_id),
                    page_identity_version=str(
                        node.get("page_identity_version") or ""),
                    variant_signature=node.get("variant_signature"),
                    observed_facts=dict(data.get("observed_facts") or {}),
                    visible_capabilities=list(
                        data.get("visible_capabilities") or []),
                )
                self._persist_online_capabilities(state_id)
            except Exception as exc:
                logger.warning(
                    "noninteractive reclassification sidecar update failed: %s",
                    exc)
        self.review_debug.record_event(
            "live_rebind_noninteractive",
            node=state_id,
            elem=elem.name,
            method=str(observation.get("method") or "live_perception"),
            fresh_name=fresh.name,
            fresh_type=fresh.el_type,
            step=int(getattr(self, "_action_count", 0)),
        )
        self._last_live_rebind_observation = None
        logger.info(
            "retired stale candidate '%s' after current-frame display/noninteractive "
            "reclassification (no click attempted)", elem.name)
        return True

    @staticmethod
    def _stateful_target_value(elem: VisualElement) -> str:
        return {"off": "on", "on": "off"}.get(
            (getattr(elem, "state_value", "") or "").strip().lower(),
            "unknown",
        )

    @staticmethod
    def _verified_state_value_changed(before: str, after: str) -> bool:
        """True only when both structured values prove a real mutation.

        A different registered page or an effect-verifier guess is not enough:
        mis-grounded toggles can navigate to an adjacent Settings row while the
        controlled value remains unchanged/unknown.  Treating that as an open
        mutation strands the whole traversal in restore mode.
        """
        known = {"off", "on"}
        before = str(before or "").strip().lower()
        after = str(after or "").strip().lower()
        return before in known and after in known and before != after

    @classmethod
    def _stateful_edge_label(
        cls, elem: VisualElement, target_value: str = "",
    ) -> str:
        key = (getattr(elem, "state_key", "") or getattr(elem, "name", "")
               or "state").strip().replace("_", " ")
        target = str(target_value or "").strip().lower()
        if target not in {"off", "on"}:
            target = cls._stateful_target_value(elem)
        return f"Set {key} {target}" if target != "unknown" else f"Toggle {key}"

    def _state_value_on_state(self, state_id: str, state_key: str) -> str:
        wanted = normalize_state_key(state_key)
        for candidate in (self._state_data.get(state_id, {}).get("elements", []) or []):
            if normalize_state_key(
                    getattr(candidate, "state_key", "")) == wanted:
                return (getattr(candidate, "state_value", "") or "unknown").strip().lower()
        return "unknown"

    @staticmethod
    def _normal_state_facts(value: Any) -> Dict[str, str]:
        if not isinstance(value, dict):
            return {}
        return {
            " ".join(str(key or "").replace("_", " ").casefold().split()):
            " ".join(str(item or "").casefold().split())
            for key, item in value.items()
            if str(key or "").strip()
        }

    def _stateful_landing_equivalent(
        self,
        source_state: str,
        target_state: str,
        *,
        state_key: str,
        before_value: str,
        after_value: str,
    ) -> bool:
        """Prove that a newly registered stateful landing is source-equivalent.

        Equal toggle values alone are insufficient: a stale click can navigate to
        a sibling Settings page while leaving the global value unchanged.  We also
        require the same semantic page, identical structured state facts, and the
        same selected mode set.  Missing evidence fails closed.
        """
        source_state = str(source_state or "")
        target_state = str(target_state or "")
        known = {"off", "on"}
        before = str(before_value or "").strip().casefold()
        after = str(after_value or "").strip().casefold()
        if not source_state or not target_state \
                or before not in known or after not in known or before != after:
            return False
        if source_state == target_state:
            return True

        def _data(state_id: str) -> Dict[str, Any]:
            data = dict(self._state_data.get(state_id) or {})
            topology = getattr(getattr(self, "graph", None), "graph", None)
            try:
                if topology is not None and state_id in topology:
                    data.update(dict(topology.nodes[state_id]))
            except Exception:
                pass
            return data

        source = _data(source_state)
        target = _data(target_state)
        source_page = str(source.get("page_id") or "")
        target_page = str(target.get("page_id") or "")
        if not source_page or source_page != target_page:
            return False
        source_facts = source.get("observed_facts") or {}
        target_facts = target.get("observed_facts") or {}
        source_states = self._normal_state_facts(
            source_facts.get("states") if isinstance(source_facts, dict) else {})
        target_states = self._normal_state_facts(
            target_facts.get("states") if isinstance(target_facts, dict) else {})
        if not source_states or source_states != target_states:
            return False
        wanted = " ".join(
            str(state_key or "").replace("_", " ").casefold().split())
        if not wanted or source_states.get(wanted) != before:
            return False

        def _selected(facts: Any) -> set[str]:
            if not isinstance(facts, dict):
                return set()
            values = facts.get("selected") or facts.get("selected_modes") or []
            return {
                " ".join(str(value or "").casefold().split())
                for value in values if str(value or "").strip()
            }

        source_selected = _selected(source_facts)
        target_selected = _selected(target_facts)
        return bool(source_selected) and source_selected == target_selected

    def _discard_uncommitted_equivalent_state(
        self,
        provisional_state: str,
        canonical_state: str,
        *,
        reason: str,
    ) -> bool:
        """Atomically retire a proven-equivalent, never-committed execution node."""
        provisional_state = str(provisional_state or "")
        canonical_state = str(canonical_state or "")
        graph_remove = getattr(
            getattr(self, "graph", None), "remove_uncommitted_state", None)
        registry_remove = getattr(
            getattr(self, "registry", None), "unregister_state", None)
        if (not provisional_state or provisional_state == canonical_state
                or not callable(graph_remove) or not callable(registry_remove)):
            return False
        if not graph_remove(provisional_state, alias_to=canonical_state):
            return False

        try:
            registry_remove(provisional_state)
        except Exception:
            logger.exception(
                "graph removed provisional state %s but registry cleanup failed",
                provisional_state)
        region_remove = getattr(
            getattr(self, "region_registry", None), "unregister_state", None)
        if callable(region_remove):
            region_remove(provisional_state)
        index_remove = getattr(
            getattr(self, "writer", None), "discard_node_index", None)
        if callable(index_remove):
            index_remove(provisional_state)
        self._state_data.pop(provisional_state, None)
        self._bfs_queue = deque(
            state_id for state_id in self._bfs_queue
            if str(state_id) != provisional_state)
        self._click_failures = {
            key: count for key, count in self._click_failures.items()
            if str(key[0]) != provisional_state
        }
        self._targeting_corrections = {
            key: hint for key, hint in getattr(
                self, "_targeting_corrections", {}).items()
            if str(key[0]) != provisional_state
        }
        self._quarantined_edges = {
            edge for edge in self._quarantined_edges
            if provisional_state not in edge
        }
        if hasattr(self, "_edge_dsts"):
            self._edge_dsts = {
                key: value for key, value in self._edge_dsts.items()
                if str(value) != provisional_state
            }
        try:
            self._last_node_count = self.graph.graph.number_of_nodes()
        except Exception:
            pass
        self.review_debug.record_event(
            "discard_equivalent_provisional_state",
            provisional=provisional_state,
            canonical=canonical_state,
            reason=str(reason or "structured equivalence"),
            step=self._action_count,
        )
        logger.info(
            "discarded uncommitted equivalent state %s -> %s (%s)",
            provisional_state, canonical_state, reason)
        return True

    def _stateful_scope_candidates(
        self, state_id: str, candidates: List[VisualElement]
    ) -> List[VisualElement]:
        """Bound one reversible function-set axis and reserve its inverse action."""
        active = getattr(self, "_active_state_mutation", None)
        action_count = int(getattr(self, "_action_count", 0) or 0)
        max_actions = int(getattr(self, "max_actions", 200) or 200)

        if active:
            host_states = {
                str(active.get("source_state") or ""),
                str(active.get("mutated_state") or ""),
            }
            current_is_mutated = (
                str(state_id) == str(active.get("mutated_state") or ""))
            key = normalize_state_key(active.get("state_key"))
            baseline = {
                str(item) for item in (active.get("baseline_candidates") or [])
                if str(item)
            }
            inverse: List[VisualElement] = []
            local: List[VisualElement] = []
            restore_candidate_key = str(
                active.get("restore_candidate_key") or "")
            transient_inverse = active.get("inverse_element")
            if (current_is_mutated
                    and transient_inverse is not None
                    and self._is_active_restore_candidate(
                        active, transient_inverse)):
                inverse.append(transient_inverse)
            elif current_is_mutated and restore_candidate_key:
                for candidate in (
                        self._state_data.get(state_id, {}).get(
                            "elements", []) or []):
                    if self._is_active_restore_candidate(active, candidate):
                        inverse.append(candidate)
                        break
            for candidate in candidates:
                if self._is_active_restore_candidate(active, candidate):
                    if candidate not in inverse:
                        inverse.append(candidate)
                    continue
                if candidate.is_safe_stateful_surface():
                    if (not restore_candidate_key
                            and normalize_state_key(candidate.state_key) == key):
                        if candidate not in inverse:
                            inverse.append(candidate)
                    # No independent state axis while another one is active.
                    continue
                if (current_is_mutated
                        and active.get("explore_local_functions", True)
                        and self._stateful_candidate_key(candidate)
                        not in baseline):
                    local.append(candidate)

            # A corrected/re-registered Variant may be the only live route back
            # to this transaction.  It may host the exact inverse, but it must
            # never borrow the stored element object or expose unrelated local
            # work from a different State.
            if str(state_id) not in host_states:
                if inverse:
                    for candidate in inverse:
                        candidate.priority = -2
                    return inverse
                return []

            # The last budgeted GUI action is reserved for restoration.  Routing
            # back to the mutated state uses graph replay but not exploration
            # action budget, so returning [] on a child lets the frontier do that.
            reserve_restore = max_actions > 0 and action_count >= max_actions - 1
            if local and not reserve_restore:
                return sorted(local, key=lambda e: getattr(e, "priority", 1))
            if inverse:
                for candidate in inverse:
                    candidate.priority = -2
                return inverse
            return []

        safe = [candidate for candidate in candidates
                if candidate.is_safe_stateful_surface()]
        if not safe:
            return candidates

        remaining = max_actions - action_count
        per_node = sum(1 for source, _key, _value in
                       getattr(self, "_stateful_probe_sources", set())
                       if source == state_id)
        can_probe = (
            (int(getattr(self, "_stateful_probe_limit", 0)) <= 0
             or int(getattr(self, "_stateful_probe_count", 0))
             < int(getattr(self, "_stateful_probe_limit", 0)))
            and (int(getattr(self, "_stateful_per_node_limit", 0)) <= 0
                 or per_node
                 < int(getattr(self, "_stateful_per_node_limit", 0)))
            and remaining >= 2
        )
        if not can_probe:
            self._stateful_budget_blocked = True
            return [candidate for candidate in candidates
                    if not candidate.is_safe_stateful_surface()]

        # Function-set gates outrank leaving the page: expose the gated functions,
        # explore them, restore, then continue ordinary navigation.
        safe.sort(key=lambda e: (getattr(e, "priority", -1), e.state_key, e.name))
        return safe[:1]

    @staticmethod
    def _stateful_candidate_key(elem: VisualElement) -> str:
        """Stable semantic key used to detect functions exposed by a mutation."""
        return "|".join((
            _norm_name(str(getattr(elem, "name", "") or "")),
            str(getattr(elem, "region", "") or "").strip().lower(),
            str(getattr(elem, "el_type", "") or "").strip().lower(),
            str(getattr(elem, "group", "") or "").strip().lower(),
        ))

    def _is_active_restore_candidate(
        self, active: Dict[str, Any], elem: VisualElement,
    ) -> bool:
        return is_active_restore_candidate(
            active, elem, candidate_key=self._stateful_candidate_key)

    def _commit_explored(self, state_id: str, elem: VisualElement,
                         is_seed: bool) -> None:
        """Record one verified attempt without completing the whole button."""
        elem.visited = str(getattr(
            elem, "exploration_status", "") or "") in {
                "complete", "covered", "semantic_only", "terminal"}
        key = (state_id, elem.uid or elem.name)
        self._click_failures.pop(key, None)
        getattr(self, "_observer_unresolved_controls", set()).discard(key)
        getattr(self, "_targeting_corrections", {}).pop(key, None)

    def _targeting_correction_for(
        self, state_id: str, elem: VisualElement,
    ) -> str:
        return str(getattr(self, "_targeting_corrections", {}).get(
            (state_id, elem.uid or elem.name), "") or "")

    def _record_click_failure(self, state_id: str, elem: VisualElement,
                              reason: str) -> int:
        """Allow three total attempts, then persist a terminal local outcome.

        ``visited`` is only a scheduling bit.  A repeatedly rejected control needs a
        durable abnormal outcome so frontier exhaustion cannot masquerade as
        verified coverage.
        """
        key = (state_id, elem.uid or elem.name)
        count = self._click_failures.get(key, 0) + 1
        self._click_failures[key] = count
        failure_history = getattr(self, "_click_failure_history", None)
        if failure_history is None:
            failure_history = {}
            self._click_failure_history = failure_history
        reason_counts = failure_history.setdefault(key, {})
        reason_counts[reason] = int(reason_counts.get(reason, 0)) + 1
        corrections = getattr(self, "_targeting_corrections", None)
        if corrections is None:
            corrections = {}
            self._targeting_corrections = corrections
        observation = getattr(self, "_last_live_rebind_observation", None)
        diagnostic = (
            observation.get("diagnostic")
            if isinstance(observation, dict) else None
        )
        if (count < 3 and reason in {
                "visible_target_not_confirmed",
                "scroll_map_target_not_confirmed"}):
            grounding_correction = _live.grounding_correction_hint(diagnostic)
            if grounding_correction:
                corrections[key] = grounding_correction
        elif reason == "no_effect" and count == 1:
            point = (
                diagnostic.get("click_point_1000")
                if isinstance(diagnostic, dict) else None
            )
            if isinstance(point, (list, tuple)) and len(point) == 2:
                corrections[key] = (
                    f"The previous click at normalized point "
                    f"[{int(point[0])},{int(point[1])}] was executed and "
                    "produced no visible or structured effect. Do not repeat "
                    "that point. Select a visibly different, directly "
                    "operable part of the same target where a click would "
                    "trigger the requested function. If no such point can be "
                    "confirmed, return found=false."
                )
        self.review_debug.record_event(
            "click_rejected", node=state_id, elem=elem.name,
            reason=reason, attempt=count)
        if count >= 3:
            corrections.pop(key, None)
            if reason in {
                    "below_fold_target_not_confirmed",
                    "visible_target_not_confirmed",
                    "scroll_map_target_not_confirmed"}:
                terminal_reason = "target_rebind_failed"
            elif reason == "env_step_failed":
                terminal_reason = "action_execution_failed"
            elif reason in {
                    "element_task_deferred",
                    "element_task_budget_exhausted",
                    "element_task_no_available_action"}:
                terminal_reason = "element_task_unresolved"
            elif elem.is_safe_stateful_surface():
                terminal_reason = (
                    "stateful_no_effect" if reason == "no_effect"
                    else "stateful_verification_failed"
                )
            else:
                terminal_reason = (
                    reason if reason in {
                        "no_effect", "transitioned_inconsistent", "uncertain"
                    } else "action_verification_failed"
                )
            self._record_abnormal_button(
                state_id,
                elem,
                terminal_reason,
                (f"three attempts were rejected ({reason}); the control is "
                 "retired locally without claiming shared coverage"),
                evidence={
                    "kind": "bounded_local_failure",
                    "attempts_used": count,
                    "failure_kind": reason,
                },
            )
            logger.error("click target '%s' rejected three times (%s) — retiring on "
                         "node %s without shared-ledger coverage",
                         elem.name, reason, state_id[:8])
        else:
            logger.warning(
                "click target '%s' rejected (%s) — attempt %d/3",
                elem.name, reason, count)
        return count

    @staticmethod
    def _abnormal_button_key(state_id: str, elem: VisualElement):
        return resume_abnormal_button_key(
            state_id,
            getattr(elem, "name", "") or "",
            getattr(elem, "uid", "") or "",
            getattr(elem, "region_id", "") or "",
            _norm_name,
        )

    def _is_abnormal_button(self, state_id: str, elem: VisualElement) -> bool:
        return self._abnormal_button_key(state_id, elem) in getattr(
            self, "_abnormal_buttons", set())

    @staticmethod
    def _terminal_off_app_outcome(kind: str) -> Optional[str]:
        """Map focus-guard outcomes that permanently retire one candidate.

        A verified external-app launch is a real terminal result of the click,
        just not a successful target-app transition.  Retiring it once prevents
        relaunch/click loops while keeping it out of the target application's
        semantic edges and successful coverage ledgers.
        """
        if kind in {"target_missing", "crash_dialog"}:
            return "app_crash"
        if kind == "screenshot_unavailable":
            return "unobservable_surface"
        if kind in {"external_app", "different_app"}:
            return "external_app"
        return None

    def _record_abnormal_button(
        self,
        state_id: str,
        elem: VisualElement,
        reason: str,
        detail: str,
        action: Optional[Dict[str, Any]] = None,
        evidence: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Retire and persist a terminal button without claiming coverage/edge."""
        reason = str(reason or "unknown")
        detail = str(detail or "")[:240]
        elem.visited = True
        elem.exploration_status = "terminal"
        elem.abnormal_reason = reason
        elem.abnormal_detail = detail
        key = self._abnormal_button_key(state_id, elem)
        if not hasattr(self, "_abnormal_buttons"):
            self._abnormal_buttons = set()
        self._abnormal_buttons.add(key)
        graph = getattr(self, "graph", None)
        if graph is not None and hasattr(graph, "record_abnormal_button"):
            graph.record_abnormal_button(
                state_id=state_id,
                element_id=str(getattr(elem, "id", "")),
                element_uid=str(getattr(elem, "uid", "") or ""),
                element_name=str(getattr(elem, "name", "") or ""),
                region=str(getattr(elem, "region", "") or ""),
                region_id=str(getattr(elem, "region_id", "") or ""),
                reason=reason,
                detail=detail,
                action=action,
                evidence=evidence,
            )
        logger.error(
            "TERMINAL BUTTON '%s': reason=%s state=%s region_id=%s detail=%s "
            "— skipping this button and continuing",
            elem.name, reason, state_id[:8],
            getattr(elem, "region_id", "") or "(node-local)", detail)
        self.review_debug.record_event(
            "abnormal_button", node=state_id, elem=elem.name,
            reason=reason, detail=detail,
            region_id=getattr(elem, "region_id", "") or "")

    # Max consecutive relaunches before we give up guarding (avoid an infinite
    # relaunch loop if the app simply won't stay up).
    MAX_RELAUNCH_ATTEMPTS = 3

    def _router_diagnostic(self, event: str, **fields: Any) -> None:
        logger.info("router semantic primitive: %s %s", event, fields)
        sink = getattr(self, "review_debug", None)
        if sink is not None:
            try:
                sink.record_event(event, **fields)
            except Exception:
                pass

    def _router_identify(self, obs, source_id=None, step=None):
        """Use the same identity service as ordinary landing registration."""
        try:
            shot = obs.get("screenshot") if isinstance(obs, dict) else None
            if (shot and bool(getattr(
                    self.perception, "use_semantic_inventory", False))):
                step = dict(step or {})
                source_reference = step.get("_source_reference_screenshot")
                intended_target = str(
                    step.get("intended_target") or step.get("dst") or "")
                if (
                    str(step.get("provenance") or "") == "reverse_probe"
                    and intended_target
                    and isinstance(source_reference, bytes)
                    and source_reference
                ):
                    compare_page = getattr(
                        getattr(self, "page_judge", None),
                        "compare_page", None)
                    if callable(compare_page):
                        same_source = compare_page(source_reference, shot)
                        self._router_diagnostic(
                            "reverse_probe_source_frame_identity",
                            source_id=source_id,
                            intended_target=intended_target,
                            same_page=same_source,
                        )
                        if same_source is True:
                            return intended_target
                resolver = getattr(self, "identity_resolver", None)
                if resolver is None:
                    resolver = IdentityResolver(
                        registry=self.registry,
                        state_data=getattr(self, "_state_data", {}),
                        judge=getattr(self, "page_judge", None),
                        descriptor_fn=self._node_descriptor,
                        local_candidates_fn=lambda source, label: (
                            self.router.expected_destinations(source, label)
                            if getattr(self, "router", None) else []),
                    )
                    self.identity_resolver = resolver
                step_action = dict(step.get("action") or {})
                step_parameters = (
                    step_action.get("parameters")
                    if isinstance(step_action.get("parameters"), dict)
                    else step_action
                )
                clicked_point = [
                    step_parameters.get("x"), step_parameters.get("y")]
                if any(value is None for value in clicked_point):
                    clicked_point = (
                        (step or {}).get("point")
                        or (step or {}).get("center")
                    )
                resolution = resolver.resolve(
                    shot,
                    source_id=str(source_id or ""),
                    clicked_label=str(step.get("name") or ""),
                    clicked_bbox=(
                        step.get("bbox")
                        or step.get("bbox_xywh")),
                    clicked_point=clicked_point,
                )
                self._router_diagnostic(
                    "router_identity_resolution",
                    source_id=source_id,
                    verdict=resolution.verdict,
                    state_id=resolution.state_id,
                    reason=resolution.reason,
                    exact=resolution.exact,
                )
                if not resolution.known:
                    return None
                return resolution.state_id
            els = self.perception.detect_and_name(shot) if shot else None
            return self._frame_state_id(obs, els)
        except Exception as exc:
            self._router_diagnostic(
                "router_identify_unknown", reason="identity_error",
                detail=str(exc)[:200])
            return None

    def _router_register_actual_landing(self, obs, source_id, step):
        """Adopt a fresh on-app landing that page-candidate matching missed."""
        shot = obs.get("screenshot") if isinstance(obs, dict) else None
        source_id = str(source_id or "")
        if not shot or source_id not in self._state_data:
            return None
        if (self.focus_guard is not None
                and self._is_target_app_foreground(shot) is not True):
            self._router_diagnostic(
                "router_actual_landing_rejected", source_id=source_id,
                reason=str(getattr(
                    self.focus_guard, "last_kind", "focus_unknown")))
            return None
        source = self._state_data[source_id]
        action = dict(step.get("action") or {})
        if not action:
            if (step.get("virtual_action")
                    or str(step.get("effect_kind") or "").casefold() in {
                        "return", "dismiss_overlay", "return_native_action",
                        "return_via_control"}):
                action = (
                    {"action_type": "navigate_back"}
                    if getattr(self, "_is_touch", True) else
                    {"action_type": "PRESS", "parameters": {"key": "esc"}}
                )
            else:
                action = {
                    "action_type": "CLICK",
                    "selector": {
                        "element_label": str(step.get("name") or ""),
                        "region": str(step.get("region") or ""),
                    },
                }
        label = str(step.get("name") or "").strip()
        if not label or label == "__NAVIGATE_BACK__":
            label = str(action.get("action_type") or "action")
        from .runtime.landing import register_landing
        try:
            landing = register_landing(
                self, obs,
                list(source.get("path") or []) + [action],
                list(source.get("replay_hints") or []) + [None],
                transition={
                    "source_id": source_id,
                    "clicked_label": label,
                    "clicked_bbox": (
                        step.get("bbox") or step.get("bbox_xywh")),
                    "clicked_point": (
                        step.get("point") or step.get("center")),
                    "requires_fresh_observation": bool(
                        step.get("requires_fresh_observation")),
                    "effect_kind": str(step.get("effect_kind") or "forward"),
                },
            )
        except PerceptionUnavailable as exc:
            self._router_diagnostic(
                "router_actual_landing_rejected", source_id=source_id,
                reason="perception_unavailable", detail=str(exc)[:200])
            return None
        self._router_diagnostic(
            "router_actual_landing_registered", source_id=source_id,
            state_id=landing.state_id, is_new=landing.is_new)
        if landing.is_new:
            self._route_blocked_targets.clear()
            self._route_target_failure_counts.clear()
        return landing.state_id

    @staticmethod
    def _is_close_control(el) -> bool:
        """A dialog CLOSE control: name is × / Close / 关闭 / Dismiss / Cancel / Done,
        or the element type is a window/close control. Used by the BACK hop to
        dismiss dialogs that ignore Esc."""
        name = (getattr(el, "name", "") or "").strip().lower()
        et = (getattr(el, "el_type", "") or "").strip().lower()
        if et in ("close",):
            return True
        return any(w in name for w in (
            "close", "×", "✕", "关闭", "dismiss", "cancel", "取消", "done", "完成"))

    def _router_back(self, obs, source_id=None):
        """Dismiss by an explicit control, with a legacy Esc/BACK fallback."""
        if bool(getattr(self.perception, "use_semantic_inventory", False)):
            return self._router_semantic_back(obs, source_id=source_id)
        shot = obs.get("screenshot") if obs else None
        if shot:
            try:
                els = self.perception.detect_and_name(shot)
                # [2026-07-07 用户] PREFER the grounder-flagged back control (top-left
                # ‹/Back/返回, or a dialog's OWN close) — a VLM semantic label, not a
                # position/name guess; it excludes the window-close × that quits the
                # app (that is category=dangerous, back=false). Fall back to the old
                # close-control heuristic, then Esc.
                close = next((e for e in els if getattr(e, "back", False)), None) \
                    or next((e for e in els if self._is_close_control(e)), None)
                if close is not None:
                    center = self._live_center_for(close, obs)
                    if center is None:
                        raise LookupError("back/close target failed live review")
                    cx, cy = center
                    obs2 = self.env.step(
                        {"action_type": "CLICK",
                         "parameters": {"x": cx, "y": cy, "button": "left"}},
                        pause=DEFAULT_PAUSE)
                    if self._settle_enabled:
                        obs2 = self._settle(obs2)
                    obs2, _r, _on = self._ensure_on_app(obs2)
                    return obs2
            except Exception:
                pass
        action = (
            {"action_type": "navigate_back"}
            if getattr(self, "_is_touch", True) else
            {"action_type": "PRESS", "parameters": {"key": "esc"}}
        )
        try:
            obs2 = self.env.step(action, pause=DEFAULT_PAUSE)
            obs2, _r, _on = self._ensure_on_app(obs2)
            return obs2
        except Exception:
            return obs

    def _router_semantic_back(self, obs, source_id=None):
        """Execute semantic Back without inventing a visual Region element.

        A visible Back/Close control is preferred when it can be grounded. On
        touch surfaces the platform Back primitive is the regionless fallback.
        The Router verifies the landing before recording either form as a
        virtual navigation edge.
        """
        shot = obs.get("screenshot") if isinstance(obs, dict) else None
        if not shot:
            self._router_diagnostic("router_back_no_progress", reason="no_screenshot")
            return obs
        if not source_id:
            source_id = self._router_identify(obs)
        state_data = getattr(self, "_state_data", {})
        elements = list((state_data.get(str(source_id)) or {}).get(
            "elements") or [])
        surface = next((
            str(getattr(element, "surface_kind", "") or "").casefold()
            for element in elements
            if str(getattr(element, "surface_kind", "") or "").strip()
        ), "page")
        close = next((e for e in elements if getattr(e, "back", False)), None) \
            or next((e for e in elements if self._is_close_control(e)), None)
        if close is not None:
            center = self._live_center_for(close, obs)
            if center is not None:
                try:
                    obs2 = self.env.step(
                        {"action_type": "CLICK",
                         "parameters": {"x": center[0], "y": center[1],
                                        "button": "left"}}, pause=DEFAULT_PAUSE)
                    if self._settle_enabled:
                        obs2 = self._settle(obs2)
                    return self._ensure_on_app(obs2)[0]
                except Exception as exc:
                    self._router_diagnostic("router_back_no_progress",
                                            reason="env_error",
                                            detail=str(exc)[:200], surface=surface)
                    return obs
            self._router_diagnostic("router_back_no_progress",
                                    reason="targeting_failed",
                                    target=getattr(close, "name", ""), surface=surface)
        # Android Back is a system navigation primitive, not a visually
        # grounded page control. Fullscreen/detail pages often expose no visible
        # Back element, so try the system primitive once and verify the landing.
        # If a true root page exits, _ensure_on_app keeps the existing recovery.
        action = (
            {"action_type": "navigate_back"}
            if getattr(self, "_is_touch", True) else
            {"action_type": "PRESS", "parameters": {"key": "esc"}}
        )
        try:
            obs2 = self.env.step(action, pause=DEFAULT_PAUSE)
            return self._ensure_on_app(obs2)[0]
        except Exception as exc:
            self._router_diagnostic("router_back_no_progress", reason="key_env_error",
                                    detail=str(exc)[:200], surface=surface)
            return obs

    def _router_hard_reset_root(self):
        """[M1] router primitive: relaunch and adopt only a known landing."""
        try:
            obs = self.relaunch_fn() if self.relaunch_fn else None
            if obs is None:
                return None, None
            obs, _r, on_app = self._ensure_on_app(obs)
            if not on_app:
                return None, obs
            landed_id, _path, _hints, _is_new = self._register_landed(obs)
            return landed_id, obs
        except Exception as e:
            logger.warning("[M1] router hard-reset-root failed: %s", e)
            return None, None

    def _router_click_button(self, source_id, name, region_id, region, obs):
        """Ask the live VLM to ground one graph-selected semantic action."""
        from .navigation.router import RouterClickResult, _norm as _rnorm
        def fail(reason, **extra):
            self._router_diagnostic(
                "router_click_not_attempted", source_id=source_id,
                region_id=region_id, target=name, reason=reason, **extra)
            return RouterClickResult.not_attempted(obs, reason)
        shot = obs.get("screenshot") if obs else None
        if not shot:
            return fail("no_screenshot")
        if bool(getattr(self.perception, "use_semantic_inventory", False)):
            state = self._state_data.get(source_id)
            if not isinstance(state, dict):
                return fail("missing_state")
            # The route edge already selected the stable action. Never bind it
            # by comparing its canonical label with a fresh raw inventory.
            # Current coordinates come from live grounding below.
            want = _rnorm(name)
            stored = [element for element in state.get("elements", []) or []
                      if _rnorm(getattr(element, "name", "")) == want
                      and (not region_id or str(getattr(
                          element, "region_id", "") or "") == str(region_id))]
            if len(stored) == 1:
                target = stored[0]
            else:
                target = VisualElement(
                    id=-1, name=str(name or ""), bbox_xywh=[0, 0, 0, 0],
                    center=[0, 0], el_type="target", interactive=True,
                    category="navigation", region=str(region or ""),
                    region_id=str(region_id or ""),
                    geometry_status="semantic_only")
            self._router_diagnostic(
                "router_click_binding", source_id=source_id,
                region_id=region_id, target=name,
                runtime_matches=len(stored))
        else:
            try:
                matches = self.perception.detect_and_name(shot)
            except Exception as exc:
                return fail("perception_error", detail=str(exc)[:200])
            want = _rnorm(name)
            matches = [element for element in matches
                       if _rnorm(getattr(element, "name", "")) == want]
            scoped = [element for element in matches
                      if region and _rnorm(getattr(element, "region", "")) == _rnorm(region)]
            if scoped:
                matches = scoped
            if len(matches) != 1:
                reason = "target_missing" if not matches else "target_ambiguous"
                return fail(reason, region_role=region, match_count=len(matches))
            target = matches[0]
        from .runtime.execution import _semantic_scroll_map_target
        map_result = _semantic_scroll_map_target(
            self, str(source_id), target, obs)
        if map_result is not None:
            obs = map_result["observation"]
            center = map_result["center"]
            if center is None:
                return fail(
                    "scroll_map_target_not_confirmed",
                    status=map_result.get("status"))
        else:
            center = self._live_center_for(target, obs)
        if center is None:
            return fail("targeting_failed")
        try:
            obs2 = self.env.step(
                {"action_type": "CLICK",
                 "parameters": {"x": center[0], "y": center[1], "button": "left"}},
                pause=DEFAULT_PAUSE)
            if self._settle_enabled:
                obs2 = self._settle(obs2)
            obs2, _r, on_app = self._ensure_on_app(obs2)
            if bool(getattr(
                    self, "_last_off_app_recovered_by_back", False)):
                self._router_diagnostic(
                    "router_click_dispatched", source_id=source_id,
                    region_id=region_id, target=name,
                    reason="off_app_recovered")
                return RouterClickResult(
                    "off_app_recovered", obs2,
                    self._last_off_app_kind or "unknown")
            if not on_app:
                self._router_diagnostic("router_click_dispatched", source_id=source_id,
                                        region_id=region_id, target=name, reason="off_app")
                return RouterClickResult.action_dispatched(obs2, "off_app")
            return RouterClickResult.action_dispatched(obs2)
        except Exception as exc:
            self._router_diagnostic("router_click_dispatched", source_id=source_id,
                                    region_id=region_id, target=name, reason="env_error",
                                    detail=str(exc)[:200])
            return RouterClickResult.dispatch_unknown(obs, "env_error")

    def _update_router_probe_attempt(
            self, step, *, status: str, outcome: str,
            detail: str = "", target: Optional[str] = None,
            landing_verified: Optional[bool] = None,
            committed: bool = False) -> None:
        """Update the pre-dispatch reverse-probe attempt, when present."""
        event_index = step.get("probe_event_index")
        if event_index is None:
            return
        try:
            attempt = self.graph.action_attempt(int(event_index))
            evidence = dict(attempt.get("evidence") or {})
            reverse = dict(evidence.get("reverse_probe") or {})
            reverse.update({
                "status": str(status or ""),
                "trigger_forward_attempt_id": str(
                    step.get("trigger_forward_attempt_id") or ""),
                "intended_target": str(step.get("intended_target") or ""),
            })
            if target is not None:
                reverse["actual_target"] = str(target or "")
            evidence["reverse_probe"] = reverse
            changes = {
                "outcome": str(outcome or status or ""),
                "detail": str(detail or ""),
                "landing_verified": landing_verified,
                "committed": bool(committed),
                "evidence": evidence,
            }
            if target is not None:
                changes["target"] = str(target or "")
            self.graph.update_action_event(int(event_index), **changes)
        except Exception as exc:
            logger.warning("failed to update reverse-probe attempt: %s", exc)

    def _save_action_attempt_screenshot(
            self, event_index: Optional[int], phase: str,
            screenshot_bytes: Optional[bytes]) -> Optional[str]:
        """Save one attempt frame and attach its relative path to graph evidence."""
        if event_index is None or not screenshot_bytes:
            return None
        writer = getattr(self, "writer", None)
        save = getattr(writer, "save_action_attempt_screenshot", None)
        if not callable(save):
            return None
        try:
            attempt = self.graph.action_attempt(int(event_index))
            source_id = str(attempt.get("source") or "")
            action = dict(attempt.get("action") or {})
            selector = dict(action.get("selector") or {})
            region_id = str(selector.get("region_id") or "")
            state = self._state_data.get(source_id) or {}
            region_description = ""
            for block in state.get("semantic_blocks", []) or []:
                if str(block.get("region_id") or "") != region_id:
                    continue
                region_description = str(
                    block.get("name") or block.get("role")
                    or block.get("description") or "")
                break
            element_description = str(
                attempt.get("element_label")
                or selector.get("element_label")
                or action.get("action_type")
                or "native action")
            path = save(
                source_state_id=source_id,
                page_description=str(
                    state.get("page_name") or source_id or "page"),
                region_id=region_id,
                region_description=region_description,
                element_id=str(attempt.get("element_id") or ""),
                element_description=element_description,
                attempt_id=str(
                    attempt.get("attempt_id") or event_index),
                phase=phase,
                screenshot_bytes=screenshot_bytes,
            )
            if not path:
                return None
            evidence = dict(attempt.get("evidence") or {})
            screenshots = dict(evidence.get("screenshots") or {})
            screenshots[str(phase)] = path
            evidence["screenshots"] = screenshots
            self.graph.update_action_event(
                int(event_index), evidence=evidence)
            return path
        except Exception as exc:
            logger.warning(
                "failed to persist action attempt %s screenshot: %s",
                phase, exc)
            return None

    @staticmethod
    def _router_attempt_event_index(step) -> Optional[int]:
        for key in ("probe_event_index", "route_event_index"):
            value = step.get(key)
            if value is not None:
                return int(value)
        return None

    @staticmethod
    def _router_action_material(step):
        effect_kind = str(step.get("effect_kind") or "forward")
        is_return = effect_kind in {"return", "dismiss_overlay"}
        step_name = str(step.get("name") or "").strip()
        has_control = bool(step_name) and not bool(step.get("virtual_action")) \
            and not step_name.startswith("__NATIVE_ACTION__") \
            and step_name != "__NAVIGATE_BACK__"
        label = step_name if has_control else ""
        region = str(step.get("region") or "") if has_control else ""
        description = (
            "Dismiss the current overlay and reveal the verified host surface"
            if effect_kind == "dismiss_overlay" else
            "Leave the current surface and return to the verified parent surface"
        ) if is_return else "verified peer-navigation route hop"
        action = dict(step.get("action") or {}) or (
            {"action_type": "BACK", "selector": {
                "virtual_action": "navigate_back",
                "description": description,
            }, "parameters": {
                "scope": "platform_navigation", "virtual": True}}
            if is_return else
            {"action_type": "CLICK", "selector": {
                "element_label": label, "region": region}}
        )
        return effect_kind, label, region, description, action

    def _ensure_router_action_attempt(self, step, action) -> int:
        event_index = self._router_attempt_event_index(step)
        if event_index is not None:
            return event_index
        _effect_kind, label, region, description, _stable_action = \
            self._router_action_material(step)
        evidence = {
            "route_context": str(step.get("route_context") or ""),
            "prediction_provenance": str(step.get("provenance") or ""),
            "predicted_target": str(step.get("dst") or ""),
        }
        event_index = self.graph.record_action_event(
            source=str(step.get("source_id") or ""),
            target="",
            action=action,
            element_id=_element_id_text(step.get("element_id")),
            element_label=label,
            semantic_description=description,
            region=region,
            outcome="attempted",
            detail="Router action ready for dispatch",
            landing_verified=None,
            committed=False,
            evidence=evidence,
        )
        step["route_event_index"] = int(event_index)
        return int(event_index)

    def _update_router_action_attempt(
            self, step, *, outcome: str, detail: str = "",
            target: Optional[str] = None,
            landing_verified: Optional[bool] = None,
            committed: bool = False) -> None:
        if step.get("probe_event_index") is not None:
            self._update_router_probe_attempt(
                step, status=outcome, outcome=outcome, detail=detail,
                target=target, landing_verified=landing_verified,
                committed=committed)
            return
        event_index = step.get("route_event_index")
        if event_index is None:
            return
        try:
            attempt = self.graph.action_attempt(int(event_index))
            evidence = dict(attempt.get("evidence") or {})
            evidence.update({
                "route_context": str(step.get("route_context") or ""),
                "prediction_provenance": str(
                    step.get("provenance") or ""),
                "predicted_target": str(step.get("dst") or ""),
            })
            if target is not None:
                evidence["actual_target"] = str(target or "")
            changes = {
                "outcome": str(outcome or ""),
                "detail": str(detail or ""),
                "landing_verified": landing_verified,
                "committed": bool(committed),
                "evidence": evidence,
            }
            if target is not None:
                changes["target"] = str(target or "")
            self.graph.update_action_event(int(event_index), **changes)
        except Exception as exc:
            logger.warning("failed to update Router action attempt: %s", exc)

    def _record_router_attempt_outcome(
            self, step, target_id: Optional[str], outcome: str) -> None:
        detail = {
            "no_effect": (
                "Router dispatched the action but live identity remained "
                "on the source State"),
            "identity_unknown": (
                "Router dispatched the action but could not identify "
                "the live landing"),
            "transitioned_consistent": (
                "Router replayed the verified action and confirmed "
                "the expected live landing"),
        }.get(str(outcome or ""), str(outcome or ""))
        committed = str(outcome or "") == "transitioned_consistent"
        self._update_router_action_attempt(
            step,
            outcome=str(outcome or ""),
            detail=detail,
            target=target_id,
            landing_verified=target_id is not None,
            committed=committed,
        )
        self._maybe_save()

    def _router_execute_action(self, step, obs):
        """Execute one VLM-selected native OSWorld/AndroidWorld action.

        A selected semantic control is rebound against the live frame before
        coordinates are attached.  Gesture/key actions remain native and are
        sent unchanged to the platform adapter.  No app-focus recovery runs
        here: the Router must identify the action's real landing first.
        """
        from .navigation.router import RouterClickResult, _norm as _rnorm

        action = dict(step.get("action") or {})
        action_type = str(action.get("action_type") or "").strip()
        if not action_type:
            self._update_router_probe_attempt(
                step, status="not_attempted", outcome="not_attempted",
                detail="missing_action_type", landing_verified=False)
            return RouterClickResult.not_attempted(obs, "missing_action_type")
        if action_type == "BACK" and not getattr(self, "_is_touch", False):
            action = {"action_type": "PRESS", "parameters": {"key": "esc"}}
            action_type = "PRESS"
        name = str(step.get("name") or "")
        region_id = str(step.get("source_region_id") or "")
        target_types = {
            "click", "double_tap", "long_press", "input_text",
            "MOVE_TO", "CLICK", "RIGHT_CLICK", "DOUBLE_CLICK",
            "TYPE", "TYPING",
        }
        if name and action_type in target_types:
            state = self._state_data.get(str(step.get("source_id") or "")) or {}
            stable_id = _element_id_text(step.get("element_id"))
            matches = [element for element in state.get("elements", [])
                       if ((stable_id and (
                                _element_id_text(
                                    getattr(element, "id", None)) == stable_id
                                or str(getattr(
                                    element, "uid", "") or "") == stable_id))
                           or (not stable_id and _rnorm(getattr(
                               element, "name", "")) == _rnorm(name)))
                       and (not region_id or str(getattr(
                           element, "region_id", "") or "") == region_id)]
            if len(matches) == 1:
                target = matches[0]
            elif stable_id:
                self._update_router_probe_attempt(
                    step, status="grounding_failed",
                    outcome="grounding_failed",
                    detail="stable_target_missing", landing_verified=False)
                return RouterClickResult.not_attempted(
                    obs, "stable_target_missing")
            else:
                # Shared predicted and legacy edges may not yet carry an element
                # id. Keep their durable semantic target, but never enumerate a
                # fresh raw inventory or match its transient wording here.
                target = VisualElement(
                    id=-1, name=name, bbox_xywh=[0, 0, 0, 0], center=[0, 0],
                    el_type="target", interactive=True, category="navigation",
                    region=str(step.get("region") or ""),
                    region_id=region_id, geometry_status="semantic_only")
            self._router_diagnostic(
                "router_native_binding",
                source_id=step.get("source_id"), region_id=region_id,
                target=name, element_id=stable_id,
                runtime_matches=len(matches))
            from .runtime.execution import _semantic_scroll_map_target
            map_result = _semantic_scroll_map_target(
                self, str(step.get("source_id") or ""), target, obs)
            if map_result is not None:
                obs = map_result["observation"]
                center = map_result["center"]
                if center is None:
                    self._update_router_probe_attempt(
                        step, status="grounding_failed",
                        outcome="grounding_failed",
                        detail="scroll_map_target_not_confirmed",
                        landing_verified=False)
                    return RouterClickResult.not_attempted(
                        obs, "scroll_map_target_not_confirmed")
            else:
                center = self._live_center_for(target, obs)
            if center is None:
                self._update_router_probe_attempt(
                    step, status="grounding_failed",
                    outcome="grounding_failed",
                    detail="targeting_failed", landing_verified=False)
                return RouterClickResult.not_attempted(obs, "targeting_failed")
            if action_type[:1].islower():
                action.update({"x": int(center[0]), "y": int(center[1])})
            else:
                parameters = dict(action.get("parameters") or {})
                parameters.update({"x": int(center[0]), "y": int(center[1])})
                action["parameters"] = parameters
        before_shot = (
            obs.get("screenshot") if isinstance(obs, dict) else None)
        step["_action_before_screenshot"] = before_shot
        event_index = self._ensure_router_action_attempt(step, action)
        self._save_action_attempt_screenshot(
            event_index, "before", before_shot)
        try:
            obs2 = self.env.step(action, pause=DEFAULT_PAUSE)
            self._update_router_action_attempt(
                step, outcome="executed",
                detail="action dispatched; awaiting fresh identity",
                landing_verified=None)
            if self._settle_enabled:
                obs2 = self._settle(obs2)
            after_shot = (
                obs2.get("screenshot") if isinstance(obs2, dict) else None)
            step["_action_after_screenshot"] = after_shot
            self._save_action_attempt_screenshot(
                event_index, "after", after_shot)
            return RouterClickResult.action_dispatched(obs2)
        except Exception as exc:
            self._update_router_action_attempt(
                step, outcome="dispatch_unknown",
                detail=str(exc)[:200], landing_verified=False)
            self._router_diagnostic(
                "router_native_action_dispatched",
                source_id=step.get("source_id"), action_type=action_type,
                reason="env_error", detail=str(exc)[:200])
            return RouterClickResult.dispatch_unknown(obs, "env_error")

    def _record_router_verified_transition(self, source_id, target_id, step):
        """Persist a Router hop only after live identity proved its landing."""
        effect_kind, label, region, description, action = \
            self._router_action_material(step)
        target_data = self._state_data.get(str(target_id)) or {}
        prediction_match = step.get("prediction_match")
        evidence = {
            "route_context": str(step.get("route_context") or ""),
            "prediction_provenance": str(step.get("provenance") or ""),
        }
        if step.get("predicted_target") is not None:
            evidence.update({
                "predicted_target": str(step.get("predicted_target") or ""),
                "actual_target": str(target_id),
                "prediction_match": prediction_match is True,
            })
        note = "Router executed the action and verified live landing identity"
        if prediction_match is False:
            note = (
                f"Router prediction {step.get('predicted_target')} mismatched; "
                f"live identity verified {target_id}")
        probe_event_index = step.get("probe_event_index")
        route_event_index = step.get("route_event_index")
        if probe_event_index is not None:
            try:
                prior = self.graph.action_attempt(int(probe_event_index))
                merged_evidence = dict(prior.get("evidence") or {})
                merged_evidence.update(evidence)
                reverse = dict(merged_evidence.get("reverse_probe") or {})
                intended = str(
                    reverse.get("intended_target")
                    or step.get("intended_target") or "")
                reverse.update({
                    "status": (
                        "verified_to_source"
                        if str(target_id) == intended
                        else "landed_elsewhere"),
                    "actual_target": str(target_id),
                })
                merged_evidence["reverse_probe"] = reverse
                self.graph.update_action_event(
                    int(probe_event_index),
                    target=str(target_id),
                    outcome="transitioned_consistent",
                    detail=note,
                    landing_verified=True,
                    target_page_name=str(target_data.get("page_name") or ""),
                    committed=False,
                    evidence=merged_evidence,
                )
                event_index = int(probe_event_index)
            except Exception as exc:
                logger.warning(
                    "failed to reuse reverse-probe attempt for verified "
                    "landing: %s", exc)
                event_index = self.graph.record_action_event(
                    source=str(source_id), target=str(target_id), action=action,
                    element_id=_element_id_text(step.get("element_id")),
                    element_label=label, semantic_description=description,
                    region=region, outcome="transitioned_consistent",
                    detail=note, landing_verified=True,
                    target_page_name=str(target_data.get("page_name") or ""),
                    committed=False, evidence=evidence,
                )
        elif route_event_index is not None:
            try:
                prior = self.graph.action_attempt(int(route_event_index))
                merged_evidence = dict(prior.get("evidence") or {})
                merged_evidence.update(evidence)
                self.graph.update_action_event(
                    int(route_event_index),
                    target=str(target_id),
                    outcome="transitioned_consistent",
                    detail=note,
                    landing_verified=True,
                    target_page_name=str(
                        target_data.get("page_name") or ""),
                    committed=False,
                    evidence=merged_evidence,
                )
                event_index = int(route_event_index)
            except Exception as exc:
                logger.warning(
                    "failed to reuse Router action attempt for verified "
                    "landing: %s", exc)
                event_index = self.graph.record_action_event(
                    source=str(source_id), target=str(target_id), action=action,
                    element_id=_element_id_text(step.get("element_id")),
                    element_label=label, semantic_description=description,
                    region=region, outcome="transitioned_consistent",
                    detail=note, landing_verified=True,
                    target_page_name=str(target_data.get("page_name") or ""),
                    committed=False, evidence=evidence,
                )
        else:
            event_index = self.graph.record_action_event(
                source=str(source_id), target=str(target_id), action=action,
                element_id=_element_id_text(step.get("element_id")),
                element_label=label, semantic_description=description,
                region=region, outcome="transitioned_consistent", detail=note,
                landing_verified=True,
                target_page_name=str(target_data.get("page_name") or ""),
                committed=False, evidence=evidence,
            )
        self._save_action_attempt_screenshot(
            event_index, "before", step.get("_action_before_screenshot"))
        self._save_action_attempt_screenshot(
            event_index, "after", step.get("_action_after_screenshot"))
        self.graph.add_transition(
            str(source_id), str(target_id), action,
            element_id=_element_id_text(step.get("element_id")),
            element_label=label,
            semantic_description=description,
            region=region,
            effect_verdict="transitioned_consistent",
            effect_note=note,
            landing_verified=True,
            target_page_name=str(target_data.get("page_name") or ""),
            event_index=event_index,
            transition_kind=("router_prediction_corrected"
                             if prediction_match is False else "router_verified"),
            effect_kind=effect_kind,
        )
        if step.get("explore_on_verify"):
            wanted_id = _element_id_text(step.get("element_id"))
            wanted_region = str(step.get("source_region_id") or "")
            matches = [
                element for element in
                (self._state_data.get(str(source_id)) or {}).get("elements", [])
                if (
                    (wanted_id and _element_id_text(
                        getattr(element, "id", None)) == wanted_id)
                    or (not wanted_id and _norm_name(
                        getattr(element, "name", "") or "")
                        == _norm_name(label))
                )
                and (
                    not wanted_region
                    or str(getattr(element, "region_id", "") or "")
                    == wanted_region
                )
                and _norm_name(getattr(element, "name", "") or "")
                == _norm_name(label)
            ]
            if len(matches) == 1:
                matched = matches[0]
                matched.exploration_status = "complete"
                matched.exploration_reason = (
                    "landing-verified reverse action")
                self._commit_explored(str(source_id), matched, False)
                persist = getattr(self, "_persist_exploration_state", None)
                if callable(persist):
                    persist(str(source_id))
            else:
                self._router_diagnostic(
                    "return_control_coverage_not_committed",
                    source_id=source_id, target=label,
                    match_count=len(matches))
        self._maybe_save()

    def _refresh_window_crop(self) -> None:
        """Refresh the real desktop app-window crop without changing the window."""
        if getattr(self, "_is_touch", True):
            return
        try:
            bbox = _get_app_window_bbox(self.env, self.app_name)
            self.perception.window_px_override = bbox
        except Exception as exc:
            logger.debug("window-crop refresh failed: %s", exc)

    def _ensure_on_app(
        self, obs: Dict[str, Any],
    ) -> Tuple[Dict[str, Any], bool, bool]:
        return ensure_on_app(self, obs, pause=DEFAULT_PAUSE)

    def _is_target_app_foreground(
        self, shot: bytes,
    ) -> Optional[bool]:
        """Return platform-owned foreground state without image inference."""
        if self.focus_guard is None:
            return None
        return self.focus_guard.on_app(shot)

    def _node_descriptor(self, state_id: str) -> Optional[Dict[str, Any]]:
        """Return a compact human-readable identity candidate description."""
        data = self._state_data.get(state_id)
        if not data:
            return None
        regions = []
        seen = set()
        for block in data.get("semantic_blocks") or []:
            name = " ".join(str(
                block.get("role") or block.get("name") or "").split())
            description = " ".join(str(
                block.get("description") or "").split())
            key = (name.casefold(), description.casefold())
            if key in seen or not (name or description):
                continue
            seen.add(key)
            regions.append({
                "name": name,
                "description": description,
            })
        descriptor = {
            "interface_name": str(data.get("page_name") or "").strip(),
        }
        if regions:
            descriptor["regions"] = regions
            return descriptor
        targets = []
        seen_targets = set()
        for element in data.get("elements") or []:
            name = " ".join(str(
                getattr(element, "name", "") or "").split())
            if name and name.casefold() not in seen_targets:
                seen_targets.add(name.casefold())
                targets.append(name)
        if not targets:
            return None
        descriptor["visible_entries"] = targets
        return descriptor

    def _arrival_region_set(self, obs, elements, *,
                            force_region_refresh: bool = False):
        """页面的 role-independent ``region:<rid>`` 区块集合身份。

        VLM groups numbered buttons and labels by local visual containment;
        (_segment_regions,同帧缓存复用、不额外调 VLM) 把元素按【真实 bbox】归到各区块,
        每个区块用其按钮名集合登记到 RegionRegistry 拿稳定 rid。**取代此前的几何 x-split
        (0.45 一刀切)**:几何切假设“侧栏永远在左 45%”,宽窗口/无侧栏/其他布局全错、还把
        content 框进空白+边界元素随坐标横跳,是同页分裂的根因。改用 VLM 真实边界后, 归属
        稳定。touch/无元素/seg 失败 -> 空集(register 回退 legacy pHash)。revert: `return set()`."""
        self._last_regions_desc = []
        try:
            # 身份看【全量元素】(含 display 标题等非交互项,最稳定);过滤后的候选只用于探索。
            _perc = getattr(self, "perception", None)
            all_els = (getattr(_perc, "last_all_elements", None) if _perc else None) or elements
            if getattr(self, "_is_touch", True) or not all_els:
                return set()
            shot = obs.get("screenshot") if obs else None
            if not shot:
                regions_px = []
            elif force_region_refresh:
                try:
                    regions_px = self._segment_regions_cached(
                        shot, all_els, force_refresh=True)
                except TypeError:
                    regions_px = self._segment_regions_cached(
                        shot, force_refresh=True)
            else:
                # Preserve compatibility with small test doubles/overrides that
                # still expose the historical one-argument method.
                try:
                    regions_px = self._segment_regions_cached(shot, all_els)
                except TypeError:
                    regions_px = self._segment_regions_cached(shot)
            regions_px = self._stabilize_region_observations(regions_px, all_els)
            if not regions_px:
                return set()                     # 无 VLM 区块 -> 回退 legacy
            amap = assign_elements_to_regions(all_els, regions_px)   # {region_idx: [els]}
            rset = set()
            dbg = {}                             # role -> (name, count, first3)
            desc = []                            # [2026-07-08 用户] 供合并质检看的区块描述
            for i, rpx in enumerate(regions_px):
                role = rpx.get("role", "other")
                names = [(e.name or "").strip() for e in amap.get(i, []) if (e.name or "").strip()]
                # 质检要看到【所有】非 chrome 区块(含被 <2 门槛丢弃的稀疏 content)——
                # 恰恰是稀疏 content 被丢导致的分裂,要让质检员有机会指出。
                if role not in _IDENTITY_CHROME_ROLES:
                    desc.append({"role": role, "note": rpx.get("note", ""), "names": names})
                if role in _IDENTITY_CHROME_ROLES:
                    continue                     # window chrome: 每页都一样, 不进身份(防抖动分裂)
                rid, _ = self.region_registry.register(
                    role, names, bbox=rpx.get("bbox"),
                    member_tokens=_region_member_tokens(amap.get(i, [])),
                    action_names=_region_action_names(amap.get(i, [])),
                    container_bbox=getattr(self.perception, "last_window_xywh", None))
                if not rid:
                    continue
                rset.add(f"region:{rid}")
                for element in amap.get(i, []):
                    element.region = role
                    element.region_id = rid
                # Any selected NAVIGATION member changes the available functional
                # surface, even when it lives inside a content list rather than a
                # formal tab bar (Applications: Accerciser vs Calendar).  Data
                # selections such as wallpaper thumbnails are not navigation and
                # therefore remain node-local values.
                for e in amap.get(i, []):
                    if (getattr(e, "selected", False)
                            and (getattr(e, "category", "") or "").lower()
                            == "navigation"):
                        selected_name = _norm_name(e.name)
                        if selected_name:
                            token = f"selected:{role}:{selected_name}"
                            rset.add(token)
                # Structurally-similar sibling tabs (notably IPv4 vs IPv6) can
                # share the exact same region ids and form controls.  The active
                # tab is therefore part of page identity.  Missing selection is a
                # one-token ambiguity; switching selection replaces one token
                # (symmetric diff=2) and is a definite distinct state.
                if role == "tab_bar":
                    for e in amap.get(i, []):
                        if getattr(e, "selected", False):
                            selected_name = _norm_name(e.name)
                            if selected_name:
                                token = f"tab_selected:{selected_name}"
                                rset.add(token)
                self.region_registry.set_name(rid, rpx.get("note", ""))
                dbg[role] = (self.region_registry.name_of(rid), len(names), names[:3])
            self._last_regions_desc = desc       # 合并质检用(review_with_regions)
            # 监视窗口 [所在]: 显示 nav_sidebar / content 的名字 + 成员(前3+总数)
            _nn, _ncnt, _nf = dbg.get("nav_sidebar", ("", 0, []))
            _cn, _ccnt, _cf = dbg.get("content", ("", 0, []))
            # [2026-07-08 用户] 监视窗口 [所在] 改显【整页概括名】(grounder 的 last_page_name,
            # 简洁如「打印机」),而非 segVLM 的区块描述句;区块分解降级为括号内极简计数
            # (侧栏N项/内容M项),仍保留可观测性但不再刷屏。模态无区块时也能显示页面名。
            _pg = (getattr(self.perception, "last_page_name", "") or "").strip()
            logger.info("[region-id] arrival page=「%s」 rset=%s | 侧栏[%s](%d)=%s | 内容[%s](%d)=%s (segVLM)",
                        _pg, sorted(rset), _nn, _ncnt, _nf, _cn, _ccnt, _cf)
            return rset
        except Exception as e:
            logger.warning("[region-id] arrival region-set FAILED (%s) -> legacy pHash "
                           "identity (this can cause a pHash false-match)", e)
            return set()

    @staticmethod
    def _review_subject_signature(elements, som=None) -> Tuple[Any, ...]:
        """Immutable identity of the exact annotation batch a review judged."""
        import hashlib
        try:
            som_digest = (hashlib.md5(som.tobytes()).hexdigest()
                          if som is not None else "")
        except Exception:
            som_digest = ""
        element_sig = tuple(
            (int(getattr(e, "id", -1)), str(getattr(e, "name", "") or ""),
             tuple(int(v) for v in (getattr(e, "bbox_xywh", None) or [])))
            for e in (elements or []))
        return som_digest, element_sig

    def _perception_meta_snapshot(self) -> Dict[str, Any]:
        """Capture mutable perception metadata paired with one grounding."""
        fields = (
            "last_window_xywh", "last_is_modal", "last_is_system_dialog",
            "last_surface_kind", "last_surface_scrollable",
            "last_is_interruption", "last_page_name", "last_all_elements",
            "last_node_local_functions", "last_som_image",
            "last_grounding_response",
        )
        return {
            name: copy.deepcopy(getattr(self.perception, name, None))
            for name in fields
        }

    def _restore_perception_meta(self, snapshot: Dict[str, Any]) -> None:
        for name, value in (snapshot or {}).items():
            setattr(self.perception, name, copy.deepcopy(value))

    def _heal_grounding_via_review(self, shot, elements, som,
                                   initial_review=None):
        """[2026-07-07 用户A] Active SELF-HEAL using the AnnotationReviewer (was
        log-only). If the reviewer flags WRONG boxes — Qwen occasionally mislocates
        controls, esp. on MODAL dialogs (observed fc13: IPv4/IPv6/Security tabs boxed
        in empty space right of the tabs -> clicks miss -> dead clicks) — RE-GROUND the
        frame and keep whichever grounding the reviewer likes better (fewer wrong).
        Gated to MODAL frames: a scrolled multi-frame aggregate cannot be re-derived by
        one re-ground without losing below-fold rows (that heal is a follow-up).
        Bounded (<=2 re-grounds), best-effort, never raises. revert: `return elements, som`."""
        original_meta = self._perception_meta_snapshot()
        try:
            if not getattr(self.perception, "last_is_modal", False):
                return elements, som, initial_review
            best_el, best_som = elements, som
            best_meta = self._perception_meta_snapshot()
            first_review = (initial_review if isinstance(initial_review, dict)
                            else self.reviewer.review(best_som, best_el))
            if isinstance(initial_review, dict):
                logger.info("review self-heal: reused merged-QA verdict for the "
                            "same annotation batch")
            best_n = len(first_review.get("wrong") or [])
            best_review = first_review
            prev_n, attempts = best_n, 0
            while best_n > 0 and attempts < 2:
                attempts += 1
                try:
                    re_el = self.perception.detect_and_name(
                        shot, force_refresh=True)
                except TypeError:
                    # Backward-compatible fake perceptions in offline tests.
                    re_el = self.perception.detect_and_name(shot)
                re_som = self.perception.last_som_image
                re_meta = self._perception_meta_snapshot()
                re_review = self.reviewer.review(re_som, re_el)
                re_n = len(re_review.get("wrong") or [])
                if re_el and re_n < best_n:
                    best_el, best_som, best_n = re_el, re_som, re_n
                    best_meta = re_meta
                    best_review = re_review
            if best_n < prev_n:
                logger.info("review self-heal (modal): wrong boxes %d -> %d via "
                            "re-ground (%d attempt(s))", prev_n, best_n, attempts)
            # Keep the metadata and elements from the SAME winning grounding.
            # Previously a rejected final re-ground leaked its page/window/modal
            # metadata into the node even when an earlier element set won.
            self._restore_perception_meta(best_meta)
            self.perception.last_som_image = best_som
            # Forced candidates are tentative until review chooses a winner.
            # Promote only the winning raw response to the exact-frame cache;
            # otherwise a rejected final attempt would poison later revisits.
            _winning_response = best_meta.get("last_grounding_response")
            _cache = getattr(self.perception, "cache", None)
            if _winning_response and _cache is not None:
                _cache.put_grounding(shot, _winning_response)
            return best_el, best_som, best_review
        except Exception as e:
            logger.debug("review self-heal failed (%s); keeping original grounding", e)
            self._restore_perception_meta(original_meta)
            return elements, som, initial_review

    def _judge_same_page(self, cand_sid: str, cand_path: str, cur_bytes: bytes) -> bool:
        """[2026-07-08 用户 根因C] 页身份 VLM judge, register 与 identify 共用。
        判断当前帧 cur_bytes 与候选节点 cand_sid(存图 cand_path)是否【同一功能页】,
        尽管数据/滚动位置有差异。把候选节点的功能描述(标题+功能集)作为 TEXT 上下文,
        让 judge 以【功能】而非像素定夺 —— 修 look-alike 兄弟(像素近/功能远, 别误合)
        与滚动/数据分裂(功能近/像素远, 该合)。cand_path 读不到 -> False(不冒险合并)。"""
        try:
            with open(cand_path, "rb") as f:
                cand_bytes = f.read()
        except OSError:
            return False
        _same = self.page_judge.same_page(
            cand_bytes, cur_bytes, cand_meta=self._node_descriptor(cand_sid))
        # [agent transcript] 记录 judge 的判定+理由(为何把本帧并入 cand_sid 或判不同),
        # 便于事后看 tab 切换是否被错误合并 / 正确保留。
        self.review_debug.record_agent(
            "page_identity", node=str(cand_sid), step=self._action_count,
            verdict=("same" if _same else "different"),
            reason=getattr(self.page_judge, "last_reason", ""))
        return _same

    def _register(self, obs: Dict[str, Any], path: List[Dict[str, Any]],
                  replay_hints: Optional[List[Optional[Dict[str, Any]]]] = None
                  ) -> Tuple[str, bool]:
        """Compatibility boundary; runtime callers may monkeypatch this method."""
        return register_observation(self, obs, path, replay_hints)

    def _retry_incomplete_scroll_audit(
            self, obs: Dict[str, Any], state_id: str) -> bool:
        return retry_semantic_scroll_audit(self, obs, state_id)

    def _register_landed(
        self, obs: Dict[str, Any], parent_id: Optional[str] = None,
        parent_action: Optional[Dict[str, Any]] = None, parent_label: str = "",
    ):
        """Compatibility wrapper for canonical recovery adoption."""
        return adopt_relaunch_landing(
            self, obs, parent_id, parent_action, parent_label)

    def _reconcile_position(self, current_id, current_obs, current_path, current_hints):
        """Keep the runtime cursor chosen by screenshot/VLM landing identity.

        The former implementation re-guessed the page from region and button
        sets after registration. That allowed transient inventory wording to
        override a confirmed screenshot identity. Position correction now occurs
        only in landing/Router verification, where the live screenshot is mapped
        to a stable page first.
        """
        return current_id, current_path, current_hints

    def _log_progress(self) -> None:
        """Report interactive occurrences separately from grouped function slots."""
        try:
            def _explored(e, sid) -> bool:
                return str(getattr(e, "exploration_status", "") or "") in {
                    "complete", "covered", "semantic_only", "terminal",
                }

            total = 0
            done = 0
            pend_nodes = 0
            function_slots: Dict[tuple, bool] = {}
            for _sid, d in self._state_data.items():
                npend = 0
                for e in (d.get("elements") or []):
                    name = str(getattr(e, "name", "") or "").strip()
                    if (
                        not name
                        or getattr(e, "interactive", None) is False
                    ):
                        continue
                    total += 1
                    done_e = _explored(e, _sid)
                    if done_e:
                        done += 1
                    else:
                        npend += 1
                    group = " ".join(
                        str(getattr(e, "group", "") or "")
                        .casefold().split())
                    if group:
                        function_key = (
                            str(_sid),
                            str(getattr(e, "region_id", "") or ""),
                            "group",
                            group,
                        )
                    else:
                        function_key = (
                            str(_sid),
                            str(getattr(e, "region_id", "") or ""),
                            "control",
                            _norm_name(name),
                            str(getattr(e, "category", "") or "").casefold(),
                        )
                    function_slots[function_key] = (
                        function_slots.get(function_key, True) and done_e)
                if npend:
                    pend_nodes += 1
            nb = self.graph.graph.number_of_nodes()
            nr = len(getattr(self.region_registry, "_regions", {}))
            pct = int(100 * done / total) if total else 0
            function_total = len(function_slots)
            function_done = sum(function_slots.values())
            function_pct = (
                int(100 * function_done / function_total)
                if function_total else 0
            )
            logger.info(
                "[进度] 节点 %d(%d待探) · 区块 %d · "
                "可交互记录 %d/%d完成(%d%%) · "
                "页面内功能位 %d/%d完成(%d%%)",
                nb, pend_nodes, nr, done, total, pct,
                function_done, function_total, function_pct,
            )
        except Exception as e:
            logger.debug("progress log failed: %s", e)

    def _unvisited_candidates(self, state_id: str) -> List[VisualElement]:
        return frontier_unvisited_candidates(
            state_id,
            FrontierContext(
                state_data=self._state_data,
                region_registry=self.region_registry,
                memory=self.mem,
                explored_groups=self._explored_groups,
                debug_sink=self.review_debug,
                stateful_discover_only=STATEFUL_DISCOVER_ONLY,
                record_abnormal_button=self._record_abnormal_button,
                is_abnormal_button=self._is_abnormal_button,
                stateful_scope_candidates=self._stateful_scope_candidates,
                is_generic_name=self._is_generic_name,
                is_chrome_name=self._is_chrome_name,
                has_direct_edge=(
                    lambda source_id, name, region_id:
                    bool(getattr(self, "router", None))
                    and self.router.has_direct_edge(
                        source_id, name, region_id)),
                live_observation_state_id=str(getattr(
                    self, "_last_live_observation_state_id", "") or ""),
                live_observation_elements=getattr(
                    self, "_last_live_observation_elements", None),
                normalize_name=_norm_name,
                has_complete_region_map=self._has_complete_region_map_target,
            ),
        )

    def _has_complete_region_map_target(
        self, state_id: str, element: VisualElement,
    ) -> bool:
        """Require both completed scroll evidence and its persisted image."""
        region_id = str(getattr(element, "region_id", "") or "")
        if not region_id:
            return False
        records = getattr(
            getattr(self, "graph", None), "scroll_ledger", {}) or {}
        complete = any(
            str(record.get("region_id") or "") == region_id
            and str(record.get("classification") or "") == "scrollable"
            and record.get("complete") is True
            and str(state_id) in {
                str(value) for value in (record.get("state_ids") or [])
            }
            for record in records.values()
            if isinstance(record, dict)
        )
        if not complete:
            return False
        loader = getattr(getattr(self, "writer", None), "load_region_image", None)
        if not callable(loader):
            return False
        return bool(loader(str(state_id), region_id))

    def _is_shared_button(self, name: str) -> bool:
        """A name in a SHARED region — a region (sidebar / tab bar) that recurs
        across >1 node (RegionRegistry seen_on>1, overlap≥0.6, NO node-count
        threshold). Explored once globally; matched by NAME (stable across the
        selected/highlighted state, unlike the appearance hash). [2026-07-07 用户
        三层框架] region-based, replaces the old common_buttons frequency method."""
        n = " ".join((name or "").lower().split())
        return bool(n) and hasattr(self, "region_registry") \
            and bool(self.region_registry) \
            and n in self.region_registry.shared_button_names()

    @staticmethod
    def _is_generic_name(name: str) -> bool:
        return (name or "").strip().lower() in _GENERIC_NAMES

    @staticmethod
    def _is_chrome_name(name: str) -> bool:
        low = (name or "").strip().lower()
        return bool(low) and any(c in low for c in _CHROME_NAMES)

    def _next_unvisited(self, state_id: str) -> Optional[VisualElement]:
        cands = self._unvisited_candidates(state_id)
        return cands[0] if cands else None

    @staticmethod
    def _edge_label(elem: VisualElement, reason: str) -> str:
        """The label to record on the edge for ``elem`` (root cause #2).

        Perception names drift on dense screenshots, so a generic/blank name is
        untrustworthy — prefer the scheduler's selection reason (the ``reason``
        from the VLM that looked at the real screenshot) in that case. When the
        perception name is a concrete, non-generic label we keep it (it is the
        most specific) but append the scheduler's description when they
        disagree, so the edge always carries the real target. General: keys only
        off name genericness, nothing app-specific."""
        name = (elem.name or "").strip()
        reason = (reason or "").strip()
        if not name or name.lower() in _GENERIC_NAMES:
            return reason or name or "(unnamed)"
        return name

    @staticmethod
    def _portable_graph_action(
        action: Dict[str, Any], elem: VisualElement
    ) -> Dict[str, Any]:
        """Attach live-groundable semantics without changing the env action."""
        result = copy.deepcopy(action or {})
        selector = dict(result.get("selector") or {})
        for key, value in (
            ("element_label", getattr(elem, "name", "")),
            ("region", getattr(elem, "region", "")),
            ("region_id", getattr(elem, "region_id", "")),
        ):
            if value:
                selector.setdefault(key, str(value))
        if selector:
            result["selector"] = selector
        return result


    def resume_from_graph(self, graph: "Any") -> bool:
        """[2026-07-08 用户 断点续跑] Rebuild ALL in-memory ledgers from a loaded
        StateGraph so traversal CONTINUES on an existing graph instead of re-
        exploring it. Everything needed is already persisted in the graph nodes
        (elements carry name/uid/visited/group/region/region_id; nodes carry
        action_path_from_root + visual_fingerprint pHash + screenshot_path), so
        no sidecar file is needed — we reconstruct: _state_data, VisualStateRegistry
        (_states/_buttons/_coverage/_clicked/_region_sets), RegionRegistry
        (names/seen_on/clicked), _visited_uids, _explored_groups, mem, _bfs_queue.

        Atomic/fail-closed: on ANY rebuild error we log and return False without
        publishing a half-built runtime.  Explicit-resume callers must abort rather
        than start fresh in the existing output directory. Returns True on success.
        """
        try:
            self._rebuild_from_graph(graph)
            return True
        except Exception:
            logger.exception(
                "resume_from_graph failed — runtime unchanged; caller must abort "
                "explicit resume")
            return False

    def _rebuild_from_graph(self, graph: "Any") -> None:
        """Build a complete resume snapshot, then publish it atomically.

        All parsing and ledger reconstruction happens on fresh temporary objects
        in ``visual_resume``.  Until ``build`` returns, neither this engine nor the
        loaded graph is mutated; a malformed graph therefore leaves the existing
        runtime usable as a fresh run.
        """
        rebuilt = self._resume_rebuilder.build(graph)
        resume_sync_live_to_graph(
            rebuilt.graph, rebuilt.state_data, rebuilt.visited_uids)
        assert_runtime_state_consistent(
            rebuilt.graph, rebuilt.state_data, registry=rebuilt.registry)

        # These are plain reference assignments and cannot invoke model/runtime
        # work.  Rebind every collaborating object before exposing the save hook.
        self.graph = rebuilt.graph
        self.registry = rebuilt.registry
        self.region_registry = rebuilt.region_registry
        self.mem = rebuilt.memory
        self._state_data = rebuilt.state_data
        self._visited_uids = rebuilt.visited_uids
        self._explored_groups = rebuilt.explored_groups
        self._abnormal_buttons = rebuilt.abnormal_buttons
        self._bfs_queue = rebuilt.frontier
        self._action_count = rebuilt.action_count
        probe_sources, active_mutation = resume_stateful_probe_state(
            list(getattr(graph, "transition_events", []) or []))
        self._stateful_probe_sources = probe_sources
        self._stateful_probe_count = len(probe_sources)
        self._active_state_mutation = active_mutation
        self._stateful_inflight = None
        getattr(self, "_targeting_corrections", {}).clear()
        self._route_blocked_targets.clear()
        self._route_failures.clear()
        self._route_target_failure_counts.clear()
        self._observer_unresolved_controls.clear()
        self._explorer_deferred_regions.clear()
        self._explorer_region_failure_counts.clear()
        self._element_exploration_task = None
        self._return_probe_status.clear()

        self.router.graph = self.graph
        self.router.regions = self.region_registry
        self.router.state_data = self._state_data
        self.identity_resolver.registry = self.registry
        self.identity_resolver.state_data = self._state_data
        self.graph._live_sync = self._sync_live_to_graph

        logger.info("resumed from graph: %d nodes, %d regions, %d visited-uids, "
                    "%d abnormal-buttons, action_count=%d, open-state-mutation=%s",
                    self.graph.graph.number_of_nodes(),
                    len(self.region_registry._regions), len(self._visited_uids),
                    len(self._abnormal_buttons), self._action_count,
                    bool(self._active_state_mutation))

    def _sync_live_to_graph(self, graph) -> None:
        """Compatibility callback used by ``StateGraph.save`` before JSON output."""
        resume_sync_live_to_graph(
            graph,
            self._state_data,
            getattr(self, "_visited_uids", set()) or set(),
        )
        assert_runtime_state_consistent(
            graph, self._state_data, registry=self.registry)

    def _maybe_save(self) -> None:
        if self._action_count % GRAPH_SAVE_INTERVAL == 0:
            self.graph.save(self.graph_save_path)
            try:
                self.vlm_ledger.save()
            except Exception as exc:
                logger.debug("vlm ledger save failed (%s)", exc)

    def _persist_exploration_state(self, state_id: str) -> None:
        """Persist Explorer-only outcomes even when no action increments the run."""
        data = self._state_data.get(str(state_id)) or {}
        elements = list(data.get("elements") or [])
        serialized = [
            dict(element) if isinstance(element, dict) else element.to_dict()
            for element in elements
        ]
        graph_node = self.graph.graph.nodes.get(str(state_id), {})
        graph_node["elements"] = copy.deepcopy(serialized)
        self.graph.save(self.graph_save_path)
        try:
            self.writer.update_node_observation(
                str(state_id), elements=serialized,
                page_name=str(data.get("page_name")
                              or graph_node.get("page_name") or ""),
                page_id=str(data.get("page_id")
                            or graph_node.get("page_id") or ""),
                variant_id=str(data.get("variant_id")
                               or graph_node.get("variant_id") or state_id),
                page_identity_version=str(
                    graph_node.get("page_identity_version") or ""),
                variant_signature=copy.deepcopy(
                    graph_node.get("variant_signature")),
                observed_facts=dict(data.get("observed_facts")
                                    or graph_node.get("observed_facts") or {}),
                visible_capabilities=list(
                    data.get("visible_capabilities")
                    or graph_node.get("visible_capabilities") or []),
                node_local_functions=list(
                    data.get("node_local_functions")
                    or graph_node.get("node_local_functions") or []),
                semantic_blocks=list(data.get("semantic_blocks")
                                     or graph_node.get("semantic_blocks") or []),
                perception_mode=str(data.get("perception_mode")
                                    or graph_node.get("perception_mode") or ""),
                geometry_mode=str(graph_node.get("geometry_mode") or ""),
            )
        except Exception as exc:
            logger.warning(
                "Explorer status sidecar update failed for %s: %s",
                state_id, exc)

    def _persist_online_capabilities(self, state_id: str) -> None:
        """Refresh one variant's portable capability sidecar from graph truth."""
        data = self._state_data.get(state_id) or {}
        capability_ids = list(data.get("visible_capabilities") or [])
        records = [
            copy.deepcopy(self.graph.capabilities[capability_id])
            for capability_id in capability_ids
            if capability_id in getattr(self.graph, "capabilities", {})
        ]
        try:
            self.writer.save_capabilities(
                state_id,
                app_id=self.app_name,
                page_name=str(data.get("page_name") or ""),
                page_id=str(data.get("page_id") or ""),
                variant_id=str(data.get("variant_id") or state_id),
                capabilities=records,
            )
        except Exception as exc:
            logger.warning("online capability sidecar update failed for %s: %s",
                           state_id, exc)

    # ── main loop ────────────────────────────────────────────────────────
    # If we land off-app this many times in a row (relaunch never recovers),
    # the target app is unlaunchable here (crashed for good / not installed) —
    # abort instead of looping forever registering / refusing junk screens.
    MAX_CONSECUTIVE_OFF_APP = 3

    def run(self, initial_obs: Dict[str, Any]) -> "Any":
        """Run the canonical staged traversal state machine."""
        return run_traversal(self, initial_obs)

    def _nearest_unexplored_node(self, current_id: str) -> Optional[str]:
        """[M1/B §11 Q1] The graph-NEAREST node (fewest router hops from current)
        that still has unexplored candidates. Replaces the FIFO/LIFO frontier queue
        when the router is on: after the current page is exhausted we route the
        SHORTEST path to the next work — a shared sidebar item is 0-1 hops away, a
        deep page a few, with no blind BACK/replay sibling confusion. None => no
        reachable node has work left (traversal complete)."""
        if self.router is None:
            return None
        work_nodes = []
        from .runtime.region_observation import pending_region_ids
        for nid in list(self.graph.graph.nodes()):
            if nid == current_id:
                continue
            if nid in self._route_blocked_targets:
                continue
            if (
                not pending_region_ids(self, nid)
                and not available_unvisited_candidates(self, nid)
            ):
                continue
            work_nodes.append(nid)
        if not work_nodes:
            return None
        nearest = self.router.nearest_reachable_target(
            current_id, work_nodes)
        # Graph-shortest wins when a path exists; otherwise fall back to ANY node
        # with work (early graph is incomplete; route_to's BACK/reset recovery may
        # still reach it). NEVER return None just because the graph has no path yet —
        # that mis-signals "frontier empty" and terminates the traversal early.
        return nearest or work_nodes[0]



def run(env, agent, perception, app_name, output_root, initial_obs,
        max_states=50, max_actions=200, relaunch_fn=None,
        focus_guard_enabled=True, scroll_aggregate=True, settle=True,
        stitch_node_image=False, region_dedup=False, resume_path=None,
        preserve_initial_surface=False, verify_navigation_effect=True,
        verify_return_paths=True, explorer_codex_model="",
        desktop_window_owner=None):
    """Convenience entry: build the engine and run it.

    ``resume_path`` (optional): a prior graph.json to CONTINUE. When given and it
    loads+rebuilds, the engine picks up on that graph (dedup/identity ledgers
    rehydrated).  Explicit resume is fail-closed: a damaged or incompatible graph
    raises before traversal, so its directory cannot be overwritten by a fresh run.
    """
    engine = VisualTraversalEngine(
        env=env, agent=agent, perception=perception, app_name=app_name,
        output_root=output_root, max_states=max_states, max_actions=max_actions,
        relaunch_fn=relaunch_fn, focus_guard_enabled=focus_guard_enabled,
        scroll_aggregate=scroll_aggregate, settle=settle,
        stitch_node_image=stitch_node_image, region_dedup=region_dedup,
        preserve_initial_surface=preserve_initial_surface,
        verify_navigation_effect=verify_navigation_effect,
        verify_return_paths=verify_return_paths,
        explorer_codex_model=explorer_codex_model,
        desktop_window_owner=desktop_window_owner,
    )
    if resume_path:
        from gui_rewalk.src.core.graph.state_graph import StateGraph
        loaded = StateGraph.load(resume_path)
        if not engine.resume_from_graph(loaded):
            raise RuntimeError(
                f"resume graph could not be rebuilt safely: {resume_path}")
        logger.info("resume: continuing from %s", resume_path)
    return engine.run(initial_obs)
