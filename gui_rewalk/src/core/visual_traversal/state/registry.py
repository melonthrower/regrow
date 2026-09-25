"""Canonical visual state registry and region-set reconciliation."""
from __future__ import annotations

import logging
import os
from typing import Any, Dict, Mapping, Optional, Tuple

import imagehash

from .identity import (
    _canonical_fact_value, _merge_observed_variant_facts, canonical_page_name,
    compute_page_id, compute_variant_id, observed_variant_facts,
    semantic_page_key, signature_names,
 )
from .matching import (
    PHASH_DISTANCE_THRESHOLD, SSIM_CONFIRM_THRESHOLD, normalize_button_names,
)

logger = logging.getLogger(__name__)

from .regions import (
    _button_set_id, _most_overlapping_rset, _region_set_id, region_set_verdict,
)

class VisualStateRegistry:
    """Stores stable states and supporting visual/semantic evidence."""

    def __init__(
        self,
        phash_threshold: int = PHASH_DISTANCE_THRESHOLD,
        ssim_threshold: float = SSIM_CONFIRM_THRESHOLD,
        namespace: str = "",
    ):
        self.phash_threshold = phash_threshold
        self.ssim_threshold = ssim_threshold
        # Page ids must stay in one namespace through initial registration,
        # richer observation refinement and resume.  Letting engine call sites
        # alternate between an empty and app-qualified namespace makes the same
        # state oscillate between two page/variant hashes.
        self.namespace = str(namespace or "")
        # state_id -> (phash object, screenshot_path). pHash is retained for
        # diagnostics and change evidence, never for identity selection.
        self._states: Dict[str, Tuple[imagehash.ImageHash, str]] = {}
        # state_id -> group-folded functional summary. It supports Variant facts,
        # function-set comparison and shared-chrome reporting; semantic State
        # selection never reads it by itself.
        self._buttons: Dict[str, frozenset] = {}
        # state_id -> full element-name set for the coverage ledger. It stays
        # separate because the functional summary folds repeated group members,
        # while coverage must retain every app/item name for the explorer.
        self._coverage: Dict[str, frozenset] = {}
        # state_id -> set of button names already clicked (the ledger's progress).
        self._clicked: Dict[str, set] = {}
        # [2026-07-07 用户: region-集合身份为唯一合并判据, pHash 退出] state_id -> its
        # REGION SET {"region:<rid>"} (RegionRegistry ids, computed by the engine). When
        # the caller supplies a non-empty region_set to register()/identify(), it is
        # the SOLE merge discriminator — pHash NEVER merges (it false-merged similar-
        # layout pages: Privacy≈Bluetooth pHash-dist 4 -> stranded-click desync).
        self._region_sets: Dict[str, set] = {}
        # Page labels are supporting semantic evidence, not primary identity.
        # They are persisted in graph nodes and rebuilt on resume; the registry
        # uses them only to prevent an unconditional same-region merge.
        self._page_names: Dict[str, str] = {}
        # Two-level identity projection. Existing state ids remain executable
        # variant nodes; these maps only group them under stable semantic pages.
        self._state_page_ids: Dict[str, str] = {}
        self._state_variant_ids: Dict[str, str] = {}
        self._state_page_keys: Dict[str, str] = {}
        self._variant_facts: Dict[str, Dict[str, Any]] = {}
        self._page_states: Dict[str, set] = {}
        self._variant_states: Dict[str, set] = {}

    def record_page_variant(
        self,
        state_id: str,
        page_name: str,
        elements=None,
        observed_facts: Optional[Mapping[str, Any]] = None,
        *,
        semantic_page_key: str = "",
        namespace: str = "",
        persisted_page_id: str = "",
    ) -> Tuple[str, str]:
        """Record the semantic page and functional variant for an execution node.

        Page identity is assigned once. A known execution state keeps its existing
        Page id on every revisit; resume may install the already-persisted id. Page
        observations can enrich elements and variant facts, but can never re-hash
        the Page identity. New states still receive a deterministic initial id from
        their first semantic decision.
        """
        state_id = str(state_id or "")
        if not state_id:
            raise ValueError("state_id is required")

        supplied_key = canonical_page_name(
            semantic_page_key or globals()["semantic_page_key"](page_name, elements)
        )
        page_key = supplied_key or f"state:{state_id}"
        effective_namespace = str(namespace or self.namespace)
        candidate_page_id = compute_page_id(
            page_name,
            semantic_key=page_key,
            namespace=effective_namespace,
        )
        old_page_id = self._state_page_ids.get(state_id)
        old_page_key = self._state_page_keys.get(state_id, "")
        restored_page_id = str(persisted_page_id or "")

        if old_page_id:
            # Revisit observations can add controls and variant evidence, but the
            # graph/VLM identity decision for this execution state is immutable.
            page_id = old_page_id
            page_key = old_page_key
        else:
            page_id = restored_page_id or candidate_page_id
            self._state_page_ids[state_id] = page_id
            self._state_page_keys[state_id] = page_key
            self._page_states.setdefault(page_id, set()).add(state_id)

        old_variant_id = self._state_variant_ids.get(state_id)
        facts = observed_variant_facts(elements, observed_facts)
        if old_variant_id and old_page_id == page_id:
            facts = _merge_observed_variant_facts(
                self._variant_facts.get(old_variant_id, {}), facts)
        variant_id = compute_variant_id(page_id, facts)
        if old_variant_id and old_variant_id != variant_id:
            self._variant_states.get(old_variant_id, set()).discard(state_id)
        self._state_variant_ids[state_id] = variant_id
        self._variant_states.setdefault(variant_id, set()).add(state_id)
        self._variant_facts[variant_id] = facts

        # Keep reverse maps coherent for the stable-existing branch too.
        self._state_page_ids.setdefault(state_id, page_id)
        self._state_page_keys.setdefault(state_id, page_key)
        self._page_states.setdefault(page_id, set()).add(state_id)
        self._state_variant_ids[state_id] = variant_id
        self._variant_states.setdefault(variant_id, set()).add(state_id)
        self._variant_facts[variant_id] = facts
        return page_id, variant_id

    def _ensure_page_variant(self, state_id: str) -> None:
        if state_id in self._state_page_ids and state_id in self._state_variant_ids:
            return
        if state_id not in self._states and state_id not in self._page_names:
            return
        self.record_page_variant(
            state_id,
            self._page_names.get(state_id, ""),
            elements=sorted(self._buttons.get(state_id, frozenset())),
        )

    def page_id_of(self, state_id: str) -> Optional[str]:
        self._ensure_page_variant(state_id)
        return self._state_page_ids.get(state_id)

    def page_id_for_state(self, state_id: str) -> Optional[str]:
        return self.page_id_of(state_id)

    def variant_id_of(self, state_id: str) -> Optional[str]:
        self._ensure_page_variant(state_id)
        return self._state_variant_ids.get(state_id)

    def variant_id_for_state(self, state_id: str) -> Optional[str]:
        return self.variant_id_of(state_id)

    def variant_facts_of(self, state_id: str) -> Dict[str, Any]:
        variant_id = self.variant_id_of(state_id)
        if not variant_id:
            return {}
        return _canonical_fact_value(self._variant_facts.get(variant_id, {}))

    def observed_facts_of(self, state_id: str) -> Dict[str, Any]:
        return self.variant_facts_of(state_id)

    def states_for_page(self, page_id: str) -> Tuple[str, ...]:
        return tuple(sorted(self._page_states.get(str(page_id or ""), set())))

    def variants_for_page(self, page_id: str) -> Tuple[str, ...]:
        return tuple(sorted({
            self._state_variant_ids[state_id]
            for state_id in self._page_states.get(str(page_id or ""), set())
            if state_id in self._state_variant_ids
        }))

    def states_for_variant(self, variant_id: str) -> Tuple[str, ...]:
        return tuple(sorted(self._variant_states.get(str(variant_id or ""), set())))

    def unregister_state(self, state_id: str) -> bool:
        """Remove one provisional execution state from every registry index.

        Traversal registers a post-click frame before semantic verification so
        that the verifier can inspect structured page/variant facts.  When a
        stateful control is then *proven* to have had no effect, that provisional
        frame can be a cursor/annotation jitter duplicate of its source.  The
        engine may discard it only after the graph has independently confirmed
        that the node has no committed references; this method performs the
        registry half of that transaction.
        """
        state_id = str(state_id or "")
        if not state_id:
            return False
        present = any(
            state_id in mapping
            for mapping in (
                self._states,
                self._buttons,
                self._coverage,
                self._clicked,
                self._region_sets,
                self._page_names,
                self._state_page_ids,
                self._state_variant_ids,
                self._state_page_keys,
            )
        )
        if not present:
            return False

        page_id = self._state_page_ids.pop(state_id, None)
        variant_id = self._state_variant_ids.pop(state_id, None)
        self._state_page_keys.pop(state_id, None)
        for mapping in (
            self._states,
            self._buttons,
            self._coverage,
            self._clicked,
            self._region_sets,
            self._page_names,
        ):
            mapping.pop(state_id, None)

        if page_id:
            members = self._page_states.get(page_id)
            if members is not None:
                members.discard(state_id)
                if not members:
                    self._page_states.pop(page_id, None)
        else:
            for known_page, members in list(self._page_states.items()):
                members.discard(state_id)
                if not members:
                    self._page_states.pop(known_page, None)

        if variant_id:
            members = self._variant_states.get(variant_id)
            if members is not None:
                members.discard(state_id)
                if not members:
                    self._variant_states.pop(variant_id, None)
                    self._variant_facts.pop(variant_id, None)
        else:
            for known_variant, members in list(self._variant_states.items()):
                members.discard(state_id)
                if not members:
                    self._variant_states.pop(known_variant, None)
                    self._variant_facts.pop(known_variant, None)
        return True

    @staticmethod
    def _normal_page_name(value) -> str:
        return " ".join(str(value or "").lower().split())

    def _region_function_verdict(self, button_names, cand_id,
                                 page_name: str = "") -> str:
        """same/different/ambiguous functional surface under one region set.

        Region geometry is a candidate-retrieval signal.  Identity is the
        available function set: an identical layout with a different selected
        navigation item or substantially different controls is a different
        node.  A Jaccard comparison (rather than subset overlap) is deliberate:
        one gate value is often a strict subset of the other, but a change in
        reachable functions means the states must split.
        """
        common = self._common_buttons()
        current = frozenset(normalize_button_names(button_names or [])) - common
        known = self._buttons.get(cand_id, frozenset()) - common
        if not current or not known:
            return "ambiguous"

        selected_current = {x for x in current if x.startswith("selected:")}
        selected_known = {x for x in known if x.startswith("selected:")}
        if selected_current and selected_known \
                and selected_current != selected_known:
            return "different"

        def _state_modes(tokens):
            modes = {}
            for token in tokens:
                if not token.startswith("state:") or "=" not in token:
                    continue
                key, value = token[len("state:"):].split("=", 1)
                if key:
                    modes[key] = value
            return modes

        state_current = _state_modes(current)
        state_known = _state_modes(known)
        shared_state_keys = set(state_current) & set(state_known)
        if any(state_current[key] != state_known[key]
               for key in shared_state_keys):
            return "different"
        # A missing state token is schema/grounding uncertainty, never enough to
        # auto-merge a legacy node with a state-aware functional surface.
        if bool(state_current) != bool(state_known) \
                or set(state_current) != set(state_known):
            return "ambiguous"

        def _availability_modes(tokens):
            modes = {}
            for token in tokens:
                if not token.startswith("availability:") or "=" not in token:
                    continue
                key, value = token[len("availability:"):].split("=", 1)
                if key:
                    modes[key] = value
            return modes

        availability_current = _availability_modes(current)
        availability_known = _availability_modes(known)
        shared_availability = set(availability_current) & set(availability_known)
        if any(availability_current[key] != availability_known[key]
               for key in shared_availability):
            return "different"
        if bool(availability_current) != bool(availability_known) \
                or set(availability_current) != set(availability_known):
            return "ambiguous"

        # Selected mode is handled above; compare the remaining available
        # controls/content skeleton without letting one extra token dominate.
        current_core = current - selected_current - {
            x for x in current
            if x.startswith("state:") or x.startswith("availability:")}
        known_core = known - selected_known - {
            x for x in known
            if x.startswith("state:") or x.startswith("availability:")}
        if not current_core or not known_core:
            return "ambiguous"
        jaccard = len(current_core & known_core) / len(current_core | known_core)
        current_page = self._normal_page_name(page_name)
        known_page = self._normal_page_name(self._page_names.get(cand_id, ""))
        if current_page and known_page and current_page != known_page:
            if jaccard <= 0.70:
                return "different"
            return "ambiguous"
        if jaccard >= 0.78:
            return "same"
        if jaccard <= 0.45:
            return "different"
        return "ambiguous"

    def exact_frame_state_ids(self, screenshot_bytes: bytes) -> Tuple[str, ...]:
        """Return states whose stored screenshot pixels are strictly identical."""
        from gui_rewalk.src.core.graph.state_graph import StateGraph

        try:
            current_hash = StateGraph.compute_exact_screenshot_hash(
                screenshot_bytes)
        except Exception:
            return ()
        matches = []
        for state_id, (_phash, screenshot_path) in self._states.items():
            if not screenshot_path or not os.path.exists(screenshot_path):
                continue
            try:
                with open(screenshot_path, "rb") as handle:
                    known_hash = StateGraph.compute_exact_screenshot_hash(
                        handle.read())
            except Exception:
                continue
            if known_hash == current_hash:
                matches.append(str(state_id))
        return tuple(matches)

    def region_set_of(self, sid: str) -> set:
        """[2026-07-07 用户 问题1] 某节点登记时的区块集(身份 rset)。空 = 无身份。"""
        return set(self._region_sets.get(sid, set()))

    def register(self, screenshot_bytes: bytes, screenshot_path: str,
                 judge=None, button_names=None, region_set=None,
                 page_name: str = "",
                 region_set_authoritative: bool = True,
                 preferred_page_id: str = "",
                 preferred_state_id: str = "",
                 force_new: bool = False) -> Tuple[str, bool]:
        """Return (state_id, is_new).

        A unique strict screenshot match may return immediately. When the
        candidate VLM already chose an old state or explicitly chose NEW, that
        decision is authoritative. Legacy callers without that decision retain
        the region/content compatibility path below.
        """
        from gui_rewalk.src.core.graph.state_graph import StateGraph

        phash_hex = StateGraph.compute_visual_state_id(screenshot_bytes)
        ph = imagehash.hex_to_hash(phash_hex)

        def _result(state_id: str, is_new: bool) -> Tuple[str, bool]:
            if region_set:
                self._region_sets[state_id] = (
                    self._region_sets.get(state_id, set()) | set(region_set))
            self.record_page_variant(
                state_id,
                page_name,
                elements=button_names,
                persisted_page_id=str(preferred_page_id or ""),
            )
            return state_id, is_new

        preferred_state_id = str(preferred_state_id or "")
        if preferred_state_id in self._states:
            return _result(preferred_state_id, False)

        if force_new:
            if region_set:
                base_id = _region_set_id(set(region_set))
            elif button_names:
                base_id = _button_set_id(button_names)
            else:
                base_id = phash_hex
            new_id = base_id
            suffix = 2
            while new_id in self._states:
                new_id = f"{base_id}-{suffix}"
                suffix += 1
            self._states[new_id] = (ph, screenshot_path)
            self._page_names[new_id] = str(page_name or "")
            return _result(new_id, True)

        exact_ids = self.exact_frame_state_ids(screenshot_bytes)
        if len(exact_ids) == 1:
            return _result(exact_ids[0], False)

        # Legacy callers without an explicit semantic State decision may still
        # use an authoritative Region set. Production semantic registration
        # supplies preferred_state_id or force_new, so observation structure
        # cannot silently override the VLM-selected Page/Variant.
        if region_set and region_set_authoritative:
            rs = set(region_set)
            ambiguous_sids = []
            for sid, known_rs in self._region_sets.items():
                v = region_set_verdict(rs, known_rs)
                if v == "same":
                    functional = self._region_function_verdict(
                        button_names, sid, page_name)
                    if functional == "different":
                        logger.info(
                            "[region-id] rset same as %s but available function "
                            "set differs -> SPLIT", sid[:8])
                        continue
                    if functional == "ambiguous" and judge is not None:
                        cand_path = self._states.get(sid, (None, None))[1]
                        try:
                            functional = (
                                "same" if cand_path and os.path.exists(cand_path)
                                and judge(sid, cand_path, screenshot_bytes)
                                else "different")
                        except Exception as e:
                            logger.debug("same-rset function judge errored: %s", e)
                            functional = "different"
                    # Backward-compatible callers without a function signature
                    # retain exact-region behavior; production always supplies
                    # grounded names and a judge.
                    if functional == "different":
                        continue
                    self._region_sets[sid] = known_rs | rs          # grow shared regions
                    if page_name and not self._page_names.get(sid):
                        self._page_names[sid] = page_name
                    # [身份质检] 疑似过度合并: 判了同页, 但两帧视觉差异其实很大
                    _kp = self._states.get(sid, (None, None))[0]
                    if _kp is not None and (ph - _kp) >= 20:
                        logger.warning("[身份质检] 疑似过度合并: 本帧并入 %s 但视觉差异大"
                                       "(pHash=%d) —— 区块集可能误判同页", sid[:8], ph - _kp)
                    logger.info("[region-id] register: rset=%s SAME as %s -> MERGE",
                                sorted(rs), sid[:8])
                    return _result(sid, False)
                if v == "ambiguous":
                    ambiguous_sids.append(sid)
            if judge is not None:
                for sid in ambiguous_sids:
                    cand_path = self._states.get(sid, (None, None))[1]
                    if cand_path and os.path.exists(cand_path):
                        try:
                            if judge(sid, cand_path, screenshot_bytes):
                                self._region_sets[sid] = self._region_sets.get(sid, set()) | rs
                                return _result(sid, False)
                        except Exception as e:
                            logger.debug("region-set ambiguous judge errored: %s", e)
            # [2026-07-07 用户] state_id 从【区块集】派生, 不再用 pHash: 同一区块集恒
            # 同 id, 不同区块集必不同 id。修 pHash 撞车让两个【真不同页】(搜索/屏幕设置
            # pHash 近)共享 id 前缀 → 统计/质检误判。派生自 sorted(rset) 的稳定哈希。
            new_id = _region_set_id(rs)
            n = 2
            while new_id in self._states:
                new_id = f"{new_id}-{n}"
                n += 1
            self._states[new_id] = (ph, screenshot_path)
            self._region_sets[new_id] = rs
            self._page_names[new_id] = str(page_name or "")
            # [身份质检] 疑似过度分裂: 判了新页, 但和某已有节点【区块集高度重叠】(共享
            # content 区块却判不同)→ 可能该合并。用【区块集重叠】而非 pHash(pHash 在同框架
            # 桌面页上恒近 → 系统性误报: 搜索 vs 屏幕设置 pHash=6 但 content 区块完全不同)。
            _susp = _most_overlapping_rset(rs, self._region_sets, exclude=new_id)
            if _susp is not None:
                _osid, _jac = _susp
                _known_rs = self._region_sets.get(_osid, set())
                _sel = {x for x in rs if str(x).startswith("tab_selected:")}
                _known_sel = {x for x in _known_rs
                              if str(x).startswith("tab_selected:")}
                # Sibling tab states intentionally share almost their entire
                # region set.  A different explicit active-tab token is strong
                # evidence of a real state transition, not suspicious splitting.
                _intentional_tab_sibling = (
                    bool(_sel) and bool(_known_sel) and _sel != _known_sel)
                if _jac >= 0.6 and not _intentional_tab_sibling:
                    logger.warning("[身份质检] 疑似过度分裂: 新页 %s 与 %s 区块集高度重叠"
                                   "(Jaccard=%.2f)却判不同页 —— 可能该合并",
                                   new_id[:8], _osid[:8], _jac)
            logger.info("[region-id] register: rset=%s matched NO node -> NEW %s",
                        sorted(rs), new_id[:8])
            return _result(new_id, True)

        # Without an authoritative Region set or semantic State decision, only
        # the unique exact-frame match above may reuse a State. Content supplies
        # a readable deterministic base for a new id; it never selects an old
        # State, and a collision receives a suffix instead of merging.
        logger.info(
            "[region-id] register: no semantic state decision -> mint new state")
        base_id = _button_set_id(button_names) if button_names else phash_hex
        new_id = base_id
        n = 2
        while new_id in self._states:
            new_id = f"{base_id}-{n}"
            n += 1
        self._states[new_id] = (ph, screenshot_path)   # 存 pHash: 仅供诊断/全同判定, 不判身份
        self._page_names[new_id] = str(page_name or "")
        logger.info("[region-id] register: minted unbound state %s", new_id[:8])
        return _result(new_id, True)

    # ── functional summary + coverage ledger ─────────────────────────────
    def set_buttons(self, state_id: str, elements) -> None:
        """Record a folded functional summary and the full coverage universe.

        ``elements`` may contain VisualElements or bare names from a revisit
        top-up. Repeated group members collapse in the summary used by Variant
        facts and function comparison, while coverage keeps every name for
        exploration. Neither ledger independently selects a semantic State.
        """
        # [REGION-SCROLL CHANGE 3a] UNION, not overwrite: a revisit / later scroll
        # that reveals more rows must EXTEND both ledgers, never clobber them with a
        # partial viewport. First call seeds (empty | set = set); top-ups grow.
        sig = signature_names(elements)                    # functional summary
        full = [(e if isinstance(e, str) else getattr(e, "name", ""))
                for e in (elements or [])]                           # coverage (full)
        self._buttons[state_id] = (self._buttons.get(state_id, frozenset())
                                   | frozenset(normalize_button_names(sig)))
        self._coverage[state_id] = (self._coverage.get(state_id, frozenset())
                                    | frozenset(normalize_button_names(full)))
        self._clicked.setdefault(state_id, set())

    def rename_button(self, state_id: str, old_name: str, new_name: str) -> None:
        """Replace one corrected button name in this state's existing ledgers."""
        old = " ".join(str(old_name or "").casefold().split())
        new = " ".join(str(new_name or "").casefold().split())
        if not old or not new or old == new:
            return
        for ledger in (self._buttons, self._coverage, self._clicked):
            values = set(ledger.get(state_id, ()))
            if old not in values:
                continue
            values.remove(old)
            values.add(new)
            ledger[state_id] = (
                values if ledger is self._clicked else frozenset(values))

    def _common_buttons(self, min_frac: float = 0.5, min_nodes: int = 4) -> frozenset:
        """Button names shared across MANY nodes — app chrome that carries NO page
        identity: the desktop Settings LEFT SIDEBAR (Network / Bluetooth / Sound /
        Display / … repeated on every panel), a persistent top toolbar, a bottom
        nav bar. A name is common when it appears in >= max(min_nodes, min_frac *
        #nodes) nodes. Empty until enough nodes exist; mobile pages (which share no
        sidebar — each page's rows are its own) never accumulate a common set, so
        this is a no-op there and only kicks in on shared-chrome apps."""
        n = len(self._buttons)
        if n < min_nodes:
            return frozenset()
        thresh = max(min_nodes, int(min_frac * n + 0.999))
        counts: Dict[str, int] = {}
        for node_set in self._buttons.values():
            for name in node_set:
                counts[name] = counts.get(name, 0) + 1
        return frozenset(name for name, c in counts.items() if c >= thresh)

    def mark_clicked(self, state_id: str, name) -> None:
        """Ledger: record that a button was clicked on this node (for coverage)."""
        n = " ".join(str(name or "").lower().split())
        if n:
            self._clicked.setdefault(state_id, set()).add(n)

    def coverage(self, state_id: str) -> Tuple[int, int]:
        """(#clicked, #total) PAGE-UNIQUE buttons for a node — shared chrome (the
        sidebar / toolbar, counted once globally) is excluded so a node's coverage
        reflects its own functions, not the sidebar repeated on every page."""
        total = self._coverage.get(state_id, frozenset()) - self._common_buttons()
        clicked = self._clicked.get(state_id, set()) & total
        return len(clicked), len(total)

    def common_buttons(self) -> frozenset:
        """Shared chrome excluded from functional comparison and node coverage."""
        return self._common_buttons()

    def known_path(self, state_id: str) -> Optional[str]:
        rec = self._states.get(state_id)
        return rec[1] if rec else None

    def identify(self, screenshot_bytes: bytes,
                 screenshot_path: Optional[str] = None,
                 button_names=None, region_set=None, judge=None,
                 page_name: str = "") -> Optional[str]:
        """Read-only state lookup: which EXISTING state is this frame, if any?

        Unlike :meth:`register`, this NEVER mutates the registry (no new id is
        minted). It MAY call the optional ``judge`` VLM to arbitrate a region-set
        that is 'ambiguous' (±1 region seg jitter) against a known node — the SAME
        asymmetry-fix register already has (用户 2026-07-08 根因C): without it a
        back-navigation that lands on a known page whose seg flickered by one
        region returned None -> the router thought it was lost -> hard-reset.
        Returns the matched ``state_id`` or ``None`` when nothing confidently
        matches.

        Used by the engine and router to VERIFY where the app actually is before
        recording an edge or accepting a route hop. This replaced the historical
        SSIM-only arrival rule that confused near-identical sibling tabs.

        IDENTITY SIGNAL (see the branches below — keep this in sync when editing):
          * region_set NON-EMPTY (desktop / segmented pages): the REGION SET is
            the SOLE judge (``region_set_verdict`` == 'same'). pHash does NOT
            decide here — it false-confirmed Privacy as Bluetooth (pHash-dist 4)
            and caused stranded-click desync, which is exactly what this replaced.
          * region_set EMPTY (touch / modal / sparse): only one unique exact
            normalized-pixel match is accepted. Content wording never selects
            an existing State.
        """
        from gui_rewalk.src.core.graph.state_graph import StateGraph

        phash_hex = StateGraph.compute_visual_state_id(screenshot_bytes)
        ph = imagehash.hex_to_hash(phash_hex)
        # [2026-07-07 用户] REGION-SET identity for this read-only check (router hop /
        # pre-click "where am I"): when the caller supplies the frame's region set it
        # is the SOLE signal — pHash does NOT decide (it false-confirmed Privacy as
        # Bluetooth, pHash-dist 4 -> stranded-click desync). Return the node whose
        # region set is 'same'; None when nothing matches (frame is an other/unseen
        # page -> the router treats None as "NOT arrived" and hard-resets to root).
        # revert: delete this `if region_set:` block.
        if region_set:
            rs = set(region_set)
            ambiguous_sids = []
            for sid, known_rs in self._region_sets.items():
                v = region_set_verdict(rs, known_rs)
                if v == "same":
                    functional = self._region_function_verdict(
                        button_names, sid, page_name)
                    if functional == "same" or button_names is None:
                        return sid
                    if functional == "ambiguous":
                        ambiguous_sids.append(sid)
                    continue
                if v == "ambiguous":
                    ambiguous_sids.append(sid)
            # [2026-07-08 用户 根因C] ±1 区块抖动 = ambiguous:register 会交 VLM judge
            # 仲裁, identify 从前直接 return None -> back 落到抖了一格的已知页却认不出 ->
            # 误判迷路 -> hard-reset。这里补上同一个 judge(只读, 不改 registry, 不 mint),
            # judge 说是同页就认回。judge=None(无 VLM / 兜底) -> 仍 return None(旧行为)。
            # revert: 删掉这个 `if judge is not None:` 块, 保留上面的 same-only 循环。
            if judge is not None:
                for sid in ambiguous_sids:
                    cand_path = self._states.get(sid, (None, None))[1]
                    if cand_path and os.path.exists(cand_path):
                        try:
                            if judge(sid, cand_path, screenshot_bytes):
                                return sid
                        except Exception as e:
                            logger.debug("identify ambiguous judge errored: %s", e)
            return None
        # Without a Region set, only strict normalized-pixel equality may bypass
        # semantic Page/Variant identity.
        exact_ids = self.exact_frame_state_ids(screenshot_bytes)
        if len(exact_ids) == 1:
            return exact_ids[0]
        return None
