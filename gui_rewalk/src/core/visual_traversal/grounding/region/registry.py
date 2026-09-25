"""Region registry — cross-node visual-block identity and action coverage.

[REGION-SCROLL CHANGE 7 — NEW FILE, additive. Nothing imports it yet, so it
cannot affect existing behaviour. revert: delete this file.]

A GUI window is a set of visual blocks.  Block identity uses every meaningful
member (interactive controls plus titles/labels/status text), while action coverage
uses interactive controls only.  Keeping those sets separate prevents a display
label that stabilises identity from becoming a fake Router/click candidate.

Semantic roles such as ``nav_sidebar`` and ``content`` are hints.  Matching is by
member overlap plus normalised geometry, so a role-label drift cannot split an
otherwise identical block.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

_log = logging.getLogger(__name__)
# [2026-07-08] 区块匹配逐条打点(新块全名集/候选重叠分/命中者全名集/交集)—— 诊断
# 主从布局塌缩/区块误配的利器。默认关,GUIWALK_REGION_MATCH_DEBUG=1 开。
_MATCH_DEBUG = os.environ.get("GUIWALK_REGION_MATCH_DEBUG", "0") not in ("0", "", "false", "False")

_TOK = re.compile(r"[0-9a-z一-鿿]+")

def _norm(s: str) -> str:
    return " ".join(_TOK.findall((s or "").lower()))


def norm_names(names) -> Set[str]:
    out = set()
    for n in names or []:
        k = _norm(n)
        if k:
            out.add(k)
    return out


def element_member_token(element) -> str:
    """Typed block-identity token for one grounded element.

    The action/display prefix distinguishes a page title from a same-named button
    without depending on the VLM's noisier ``button`` versus ``link`` type label.
    """
    if getattr(element, "identity_anchor", None) is False:
        return ""
    name = _norm(getattr(element, "name", "") or "")
    if not name:
        return ""
    prefix = "action" if getattr(element, "interactive", None) is not False \
        else "display"
    return f"{prefix}:{name}"


def element_is_action(element) -> bool:
    """Whether an element may participate in action coverage/Router lookup."""
    return bool((getattr(element, "name", "") or "").strip()) \
        and getattr(element, "interactive", None) is not False


def _member_bases(tokens: Set[str]) -> Set[str]:
    """Back-compat identity view without the action/display type prefix."""
    out = set()
    for token in tokens:
        parts = token.split(" ", 1)
        if len(parts) == 2 and parts[0] in {"action", "display"}:
            out.add(parts[1])
        else:
            out.add(token)
    return out


def _canonical_bbox(bbox, container_xywh=None):
    """Return a comparable x0/y0/x1/y1 box.

    When an active-window/modal ``container_xywh`` is available the box is stored
    relative to it (0..1000).  This lets a confirmed region survive window moves
    and resize jitter while still giving singleton observations a geometry gate.
    """
    if not bbox or len(bbox) != 4:
        return None, False
    try:
        x0, y0, x1, y1 = (float(v) for v in bbox)
    except (TypeError, ValueError):
        return None, False
    if x1 <= x0 or y1 <= y0:
        return None, False
    if container_xywh and len(container_xywh) == 4:
        try:
            cx, cy, cw, ch = (float(v) for v in container_xywh)
        except (TypeError, ValueError):
            cw = ch = 0.0
        if cw > 0 and ch > 0:
            return (
                1000.0 * (x0 - cx) / cw,
                1000.0 * (y0 - cy) / ch,
                1000.0 * (x1 - cx) / cw,
                1000.0 * (y1 - cy) / ch,
            ), True
    return (x0, y0, x1, y1), False


def _bbox_overlap(a, b) -> float:
    """Intersection over the smaller box; a tight partial box can match its parent."""
    if not a or not b:
        return 0.0
    ix0, iy0 = max(a[0], b[0]), max(a[1], b[1])
    ix1, iy1 = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    aa = max(0.0, a[2] - a[0]) * max(0.0, a[3] - a[1])
    ab = max(0.0, b[2] - b[0]) * max(0.0, b[3] - b[1])
    return inter / max(min(aa, ab), 1.0)


def _bbox_to_pixels(bbox, relative: bool, container_xywh=None):
    if not bbox:
        return None
    if not relative:
        return [int(round(v)) for v in bbox]
    if not container_xywh or len(container_xywh) != 4:
        return None
    try:
        cx, cy, cw, ch = (float(v) for v in container_xywh)
    except (TypeError, ValueError):
        return None
    if cw <= 0 or ch <= 0:
        return None
    return [
        int(round(cx + bbox[0] * cw / 1000.0)),
        int(round(cy + bbox[1] * ch / 1000.0)),
        int(round(cx + bbox[2] * cw / 1000.0)),
        int(round(cy + bbox[3] * ch / 1000.0)),
    ]


@dataclass
class Region:
    id: str
    role: str
    names: Set[str]                     # all member names (compat/diagnostics)
    member_tokens: Set[str] = field(default_factory=set)  # identity incl. labels
    action_names: Set[str] = field(default_factory=set)   # interactive members only
    scrollable: bool = False
    clicked: Set[str] = field(default_factory=set)
    seen_on: Set[str] = field(default_factory=set)   # node ids that contain this region
    name: str = ""                      # VLM display label (region-seg `note`), cosmetic
                                        # only — identity is the button-name set, so name
                                        # drift is harmless. Set once (first-wins).
    bbox: Optional[Tuple[float, float, float, float]] = None
    bbox_relative: bool = False
    observations: int = 1
    confirmed: bool = True
    pending_names: Dict[str, int] = field(default_factory=dict)
    # Runtime-only visual evidence.  It is not part of semantic region identity
    # and is not serialized into the graph contract.
    visual_template: Any = None
    visual_map: Any = None
    # Semantic-inventory concepts are minted explicitly after a visual batch
    # alignment. Their crop/descriptor are runtime evidence, never graph geometry.
    semantic_concept: bool = False
    surface_kind: str = ""
    semantic_descriptor: Dict[str, Any] = field(default_factory=dict)
    semantic_representative: Optional[bytes] = None


class RegionRegistry:
    """Maps a visual member-set to a stable region id, shared across nodes."""

    def __init__(self, overlap_threshold: float = 0.6, min_names: int = 2):
        self.overlap_threshold = overlap_threshold
        self.min_names = min_names
        self._regions: Dict[str, Region] = {}
        self._n = 0

    def _match(self, role: str, identity: Set[str], bbox=None,
               bbox_relative: bool = False) -> Optional[str]:
        """Existing block whose member-set overlaps enough.

        ``role`` is deliberately a weak rank signal, not an equality gate.
        Overlap coefficient = |A∩B| / min(|A|,|B|) — a subset (scrolled viewport)
        of a known region scores 1.0, so partial views still match."""
        if not identity:
            return None
        partial = len(identity) < self.min_names
        best, best_rank = None, None
        scores = []
        for rid, r in self._regions.items():
            known = r.member_tokens or r.names
            if not known:
                continue
            # A one-item tab observation is allowed to RECOGNISE an established
            # multi-tab strip, but a historical one-item ghost is never a target.
            if role == "tab_bar" and not r.confirmed:
                continue
            incoming_view, known_view = identity, known
            token_inter = len(identity & known)
            base_incoming, base_known = (
                _member_bases(identity), _member_bases(known))
            base_inter = len(base_incoming & base_known)
            if base_inter > token_inter:
                incoming_view, known_view = base_incoming, base_known
            inter = len(incoming_view & known_view)
            denom = min(len(incoming_view), len(known_view)) or 1
            ov = inter / denom
            union = len(incoming_view | known_view) or 1
            jaccard = inter / union
            geom = (_bbox_overlap(bbox, r.bbox)
                    if bbox is not None and r.bbox is not None
                    and bbox_relative == r.bbox_relative else 0.0)
            role_agrees = int(bool(role) and role == r.role)
            scores.append((rid, ov, inter, len(known), geom, jaccard))
            if partial:
                # Sparse blocks are permitted, but they may only re-identify a
                # prototype with containment plus a strong geometry witness.
                if not incoming_view.issubset(known_view) or geom < 0.50:
                    continue
            elif ov < self.overlap_threshold:
                continue
            # When the optional role hint drifts, require some geometry support.
            # This prevents same-named blocks at unrelated positions from merging
            # while still allowing sidebar/navigation label drift.
            if role and r.role and role != r.role and geom < 0.25:
                continue
            rank = (ov, geom, role_agrees, jaccard, r.observations, len(known))
            if best_rank is None or rank > best_rank:
                best, best_rank = rid, rank
        if _MATCH_DEBUG and scores:
            hit = self._regions.get(best) if best else None
            _log.info(
                "[region-match] role=%s new(%d)=%s | cands=%s | -> %s%s",
                role, len(identity), sorted(identity),
                [(rid, round(ov, 3), f"inter={i}", f"|known|={k}",
                  f"geom={g:.2f}", f"J={j:.2f}")
                 for rid, ov, i, k, g, j in scores],
                best or "NEW/REJECT",
                (" | HIT∩=" + str(sorted(
                    identity & (hit.member_tokens or hit.names)))) if hit else "",
            )
        return best

    def mint_semantic_concept(
        self, *, role: str, names, action_names=None, surface_kind: str = "",
        descriptor=None, representative: Optional[bytes] = None,
    ) -> str:
        """Mint a stable concept id without content-hash/overlap authority."""
        self._n += 1
        rid = f"r{self._n}"
        ns = norm_names(names)
        self._regions[rid] = Region(
            id=rid, role=str(role or "other"), names=set(ns),
            member_tokens=set(ns),
            action_names=norm_names(action_names if action_names is not None else names),
            confirmed=True, semantic_concept=True,
            surface_kind=str(surface_kind or ""),
            semantic_descriptor=dict(descriptor or {}),
            semantic_representative=(bytes(representative)
                                     if isinstance(representative, (bytes, bytearray))
                                     else None),
        )
        return rid

    def observe_semantic_concept(
        self, region_id: str, *, names, action_names=None,
        descriptor=None, representative: Optional[bytes] = None,
    ) -> bool:
        """Accumulate one visually-confirmed occurrence on an existing concept."""
        region = self._regions.get(str(region_id or ""))
        if region is None:
            return False
        region.semantic_concept = True
        region.observations += 1
        region.names |= norm_names(names)
        region.member_tokens |= norm_names(names)
        region.action_names |= norm_names(
            action_names if action_names is not None else names)
        if descriptor and not region.semantic_descriptor:
            region.semantic_descriptor = dict(descriptor)
        if (isinstance(representative, (bytes, bytearray))
                and region.semantic_representative is None):
            region.semantic_representative = bytes(representative)
        return True

    def merge_semantic_concepts(self, keep_id: str, drop_id: str) -> bool:
        """Merge one VLM-confirmed Region identity into an older stable id."""
        keep_id, drop_id = str(keep_id or ""), str(drop_id or "")
        if not keep_id or not drop_id or keep_id == drop_id:
            return keep_id == drop_id and bool(keep_id)
        keep = self._regions.get(keep_id)
        drop = self._regions.get(drop_id)
        if keep is None or drop is None:
            return False
        keep.names |= drop.names
        keep.member_tokens |= drop.member_tokens
        keep.action_names |= drop.action_names
        keep.clicked |= drop.clicked
        keep.seen_on |= drop.seen_on
        keep.scrollable = keep.scrollable or drop.scrollable
        keep.observations += drop.observations
        keep.confirmed = keep.confirmed or drop.confirmed
        keep.semantic_concept = keep.semantic_concept or drop.semantic_concept
        if not keep.role or keep.role in {"block", "other"}:
            keep.role = drop.role or keep.role
        if not keep.surface_kind:
            keep.surface_kind = drop.surface_kind
        if not keep.semantic_descriptor:
            keep.semantic_descriptor = dict(drop.semantic_descriptor or {})
        if keep.semantic_representative is None:
            keep.semantic_representative = drop.semantic_representative
        del self._regions[drop_id]
        return True

    def discard_unobserved_semantic_concepts(self, region_ids) -> None:
        """Discard request-local Regions that never reached a registered State."""
        for region_id in region_ids or []:
            key = str(region_id or "")
            region = self._regions.get(key)
            if (region is not None and region.semantic_concept
                    and not region.seen_on):
                self._regions.pop(key, None)

    def record_mapped_elements(self, region_id: str, names) -> bool:
        """Record the canonical target descriptions of a stable Region table."""
        region = self._regions.get(str(region_id or ""))
        if region is None:
            return False
        canonical = norm_names(names)
        region.names |= canonical
        region.member_tokens |= canonical
        region.action_names |= canonical
        return True

    def mark_seen(self, region_id: str, node_id: str) -> None:
        region = self._regions.get(str(region_id or ""))
        if region is not None and node_id:
            region.seen_on.add(str(node_id))

    def semantic_candidate(self, region_id: str) -> Optional[Dict[str, Any]]:
        region = self._regions.get(str(region_id or ""))
        if region is None or not region.semantic_concept:
            return None
        return {
            "concept_id": region.id,
            "role": region.role,
            "surface_kind": region.surface_kind,
            "names": sorted(region.names),
            "descriptor": dict(region.semantic_descriptor or {}),
            "representative": region.semantic_representative,
            "seen_on": sorted(region.seen_on),
        }

    def semantic_candidates(self) -> List[Dict[str, Any]]:
        return [candidate for rid in self._regions
                if (candidate := self.semantic_candidate(rid)) is not None]

    def register(self, role: str, names, scrollable: bool = False,
                 node_id: str = "", bbox=None, member_tokens=None,
                 action_names=None,
                 container_bbox=None) -> Tuple[str, bool]:
        """Return (region_id, is_new). is_new False => this region was already seen
        on another node; caller should NOT re-scroll / re-explore it (reference it)."""
        ns = norm_names(names)
        identity = norm_names(member_tokens) if member_tokens is not None else set(ns)
        actions = norm_names(action_names) if action_names is not None else set(ns)
        obs_bbox, bbox_relative = _canonical_bbox(bbox, container_bbox)
        rid = self._match(role, identity, obs_bbox, bbox_relative)
        if rid is not None:
            r = self._regions[rid]
            r.observations += 1
            if role == "tab_bar":
                # A stable tab strip is a prototype, not a permanent union of every
                # hallucinated label.  New members need two matching observations;
                # subsets merely re-identify the prototype and never shrink it.
                for name in identity - (r.member_tokens or r.names):
                    r.pending_names[name] = r.pending_names.get(name, 0) + 1
                    if r.pending_names[name] >= 2:
                        r.member_tokens.add(name)
                        r.pending_names.pop(name, None)
            else:
                r.member_tokens |= identity
                r.names |= ns
            r.action_names |= actions
            if role and (not r.role or r.role in {"block", "other"}):
                r.role = role
            r.scrollable = r.scrollable or scrollable
            if obs_bbox is not None and (
                    r.bbox is None or len(identity) >= self.min_names):
                r.bbox, r.bbox_relative = obs_bbox, bbox_relative
            if node_id:
                r.seen_on.add(node_id)
            if len(r.member_tokens or r.names) >= self.min_names \
                    or (r.observations >= 2 and obs_bbox is not None):
                r.confirmed = True
            return rid, False
        if role == "tab_bar" and len(identity) < self.min_names:
            _log.info("region-dedup: reject tentative tab_bar names=%s (need >=%d "
                      "or geometry-backed match to a confirmed strip)",
                      sorted(identity), self.min_names)
            return "", False
        self._n += 1
        rid = f"r{self._n}"
        self._regions[rid] = Region(id=rid, role=role, names=set(ns),
                                    member_tokens=set(identity),
                                    action_names=set(actions),
                                    scrollable=scrollable,
                                    seen_on={node_id} if node_id else set(),
                                    bbox=obs_bbox, bbox_relative=bbox_relative,
                                    confirmed=(len(identity) >= self.min_names))
        return rid, True

    def is_confirmed(self, region_id: str) -> bool:
        r = self._regions.get(region_id)
        return bool(r is not None and r.confirmed)

    def confirmed_layouts(self, role: str, container_bbox=None) -> List[dict]:
        """Confirmed cached layouts projected into the current window/modal."""
        out = []
        for rid, r in self._regions.items():
            if r.role != role or not r.confirmed:
                continue
            px = _bbox_to_pixels(r.bbox, r.bbox_relative, container_bbox)
            if not px:
                continue
            out.append({"id": rid, "role": role, "bbox": px,
                        "scrollable": r.scrollable, "note": r.name,
                        "names": set(r.names), "cached": True})
        return out

    def extend(self, region_id: str, names, *, member_tokens=None,
               action_names=None) -> None:
        """Union below-fold members into a fully aggregated block."""
        if region_id in self._regions:
            r = self._regions[region_id]
            ns = norm_names(names)
            r.names |= ns
            r.member_tokens |= (
                norm_names(member_tokens) if member_tokens is not None else ns)
            r.action_names |= (
                norm_names(action_names) if action_names is not None else ns)
            if len(r.member_tokens or r.names) >= self.min_names:
                r.confirmed = True

    def set_name(self, region_id: str, name: str) -> None:
        """Attach a VLM display label (region-seg `note`) to a region. First-wins:
        only sets if still empty, so later-visit drift never overwrites. Cosmetic —
        does NOT affect identity (member-token set)."""
        r = self._regions.get(region_id)
        if r and not r.name and (name or "").strip():
            r.name = " ".join(str(name).split())[:40]

    def name_of(self, region_id: str) -> str:
        r = self._regions.get(region_id)
        return r.name if r else ""

    def remember_visual(self, region_id: str, *, template=None, visual_map=None) -> None:
        """Attach a first-view crop and/or tall composite to a known region."""
        r = self._regions.get(region_id)
        if r is None:
            return
        if template is not None and r.visual_template is None:
            r.visual_template = template
        if visual_map is not None:
            r.visual_map = visual_map

    def visual_of(self, region_id: str) -> Tuple[Any, Any]:
        r = self._regions.get(region_id)
        if r is None:
            return None, None
        return r.visual_template, r.visual_map

    def regions_of(self, node_id: str) -> Set[str]:
        """The node's role-independent structural tokens: ``region:<rid>``.

        Role hints are intentionally excluded so a VLM naming drift cannot split
        an otherwise identical page.
        seen on it. This IS the page's structural identity: two nodes with the same
        set are the same page (region-set identity). Empty until the node's regions
        have been registered (post scroll-dedup)."""
        return {f"region:{rid}" for rid, r in self._regions.items()
                if node_id in r.seen_on}

    def unregister_state(self, node_id: str) -> None:
        """Remove provisional-node membership from the shared-region index."""
        node_id = str(node_id or "")
        if not node_id:
            return
        for region_id, region in list(self._regions.items()):
            region.seen_on.discard(node_id)
            # A region observed only on a discarded provisional node has no live
            # graph provenance.  Numeric ids remain monotonic; they need not be
            # reused.
            if not region.seen_on:
                self._regions.pop(region_id, None)

    def buttons(self, region_id: str) -> Set[str]:
        r = self._regions.get(region_id)
        return set(r.action_names) if r else set()

    def unclicked(self, region_id: str) -> Set[str]:
        """A region's still-to-explore buttons — drained ONCE globally, so a shared
        region is not re-explored on every node that references it."""
        r = self._regions.get(region_id)
        return (r.action_names - r.clicked) if r else set()

    def mark_clicked(self, region_id: str, name: str) -> None:
        """[2026-07-08 用户 三层框架第2层] Record that ``name`` was explored in this
        region. This is the REGION-KEYED coverage ledger — the fix for the shared-
        sidebar re-click: a sidebar button clicked on page A is recorded against its
        region id (stable from first registration, matched back on page B by overlap),
        so ``is_clicked`` drops it on B WITHOUT waiting for the ``seen_on>1`` warm-up
        that the name-based global dedup needed. No-op when region_id is unknown."""
        r = self._regions.get(region_id)
        n = _norm(name)
        if r is not None and n:
            r.clicked.add(n)

    def rename_action(
        self, region_id: str, old_name: str, new_name: str,
    ) -> None:
        """Replace one Observer-corrected action name in a stable Region."""
        region = self._regions.get(str(region_id or ""))
        old = _norm(old_name)
        new = _norm(new_name)
        if region is None or not old or not new or old == new:
            return
        for values in (
                region.names, region.member_tokens,
                region.action_names, region.clicked):
            if old in values:
                values.remove(old)
                values.add(new)

    def is_clicked(self, region_id: str, name: str) -> bool:
        """True iff ``name`` was already explored anywhere this region was seen."""
        r = self._regions.get(region_id)
        n = _norm(name)
        return bool(r is not None and n and n in r.clicked)

    def shared_button_names(self) -> Set[str]:
        """[2026-07-07 用户 三层框架] Normalised names of every button living in a
        SHARED region (seen_on > 1) — the region-based replacement for the button-
        frequency ``common_buttons`` (which needed 4 nodes). A sidebar region is
        recognised as shared the moment a 2nd page overlaps it (≥0.6), so its
        entries are globally deduped from candidates without the 4-node warm-up
        that made the engine re-click the sidebar on the first few pages."""
        out: Set[str] = set()
        for r in self._regions.values():
            if len(r.seen_on) > 1:
                out |= r.action_names
        return out

    def rebuild_region(self, region_id: str, role: str, names, seen_on,
                       clicked, *, member_tokens=None,
                       action_names=None) -> None:
        """[2026-07-08 用户 断点续跑] Reinstate a Region from persisted facts (graph
        rebuild), preserving its ORIGINAL id so ``region:<rid>`` tokens still
        match what the graph stored. Names/clicked are normalised here so identity
        and the click ledger behave exactly as in a live run. Bumps the id counter
        past any numeric rid ("r7"->_n>=7) so freshly-registered regions never
        collide with a reinstated id."""
        r = self._regions.get(region_id) or Region(id=region_id, role=role, names=set())
        r.role = r.role or role
        ns = norm_names(names)
        r.names |= ns
        r.member_tokens |= (
            norm_names(member_tokens) if member_tokens is not None else ns)
        r.action_names |= (
            norm_names(action_names) if action_names is not None else ns)
        r.clicked |= norm_names(clicked)
        r.seen_on |= set(seen_on or set())
        r.confirmed = bool(len(r.member_tokens or r.names) >= self.min_names)
        self._regions[region_id] = r
        m = re.match(r"r(\d+)$", region_id or "")
        if m:
            self._n = max(self._n, int(m.group(1)))

    def summary(self) -> List[dict]:
        return [{"id": r.id, "role": r.role, "name": r.name,
                 "n_members": len(r.member_tokens or r.names),
                 "n_buttons": len(r.action_names),
                 "scrollable": r.scrollable, "seen_on_nodes": len(r.seen_on),
                 "shared": len(r.seen_on) > 1, "confirmed": r.confirmed,
                 "observations": r.observations} for r in self._regions.values()]


def assign_elements_to_regions(elements, regions_px):
    """Map elements by explicit member id, with legacy bbox fallback.
    ``regions_px`` = [{'role','bbox':[x0,y0,x1,y1]px,'scrollable'}]. Returns
    {region_index -> [elements]}; unassigned go to key -1."""
    out: Dict[int, list] = {}
    for e in elements:
        cx, cy = e.center
        best_i, best_area = -1, None
        explicit_candidates = []
        for i, r in enumerate(regions_px):
            explicit = r.get("member_ids")
            if explicit is None or getattr(e, "id", None) not in explicit:
                continue
            x0, y0, x1, y1 = r["bbox"]
            explicit_candidates.append(((x1 - x0) * (y1 - y0), i))
        if explicit_candidates:
            best_i = min(explicit_candidates)[1]
            out.setdefault(best_i, []).append(e)
            continue
        for i, r in enumerate(regions_px):
            explicit = r.get("member_ids")
            if explicit is not None:
                continue
            x0, y0, x1, y1 = r["bbox"]
            if x0 <= cx <= x1 and y0 <= cy <= y1:
                area = (x1 - x0) * (y1 - y0)
                # smallest containing region wins (dialog panel over background)
                if best_area is None or area < best_area:
                    best_i, best_area = i, area
        out.setdefault(best_i, []).append(e)
    return out
