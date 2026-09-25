"""Region-aware scroll segmentation, stabilization, and deduplication.

This module owns region scroll orchestration while the engine supplies explicit
I/O and ledger callbacks through :class:`RegionScrollContext`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any, Callable, Dict, List, Optional

from ...visual_perception import VisualElement
from ...visual_state import ElementMatcher
from ... import visual_relocate as _reloc
from .registry import (
    assign_elements_to_regions,
    element_is_action,
    norm_names,
)
from ..scroll import (
    DESKTOP_MAX_SCROLL_STEPS,
    DESKTOP_WHEEL_CLICKS,
    SCROLL_PATIENCE,
    VIEW_STABLE_DISTANCE,
    _region_scroll_moved,
)

logger = logging.getLogger(__name__)


def _region_member_tokens(elements: List[VisualElement]) -> List[str]:
    from .registry import element_member_token
    return [token for token in (element_member_token(e) for e in elements) if token]


def _region_action_names(elements: List[VisualElement]) -> List[str]:
    return norm_names(e.name for e in elements if element_is_action(e))


def _attach_region_visual_memory(registry, rid, shot, region_bbox, elements):
    """Attach region-first and row-context evidence to runtime elements."""
    region_crop = _reloc.crop_region(shot, region_bbox)
    if region_crop is not None:
        registry.remember_visual(rid, template=region_crop)
    template, visual_map = registry.visual_of(rid)
    for element in elements:
        element._region_template = template
        element._region_map = visual_map
        saved = _reloc.save_context_template(
            shot, element.bbox_xywh, list(region_bbox))
        if saved is not None:
            element._context_template, element._context_center_offset = saved



@dataclass
class RegionScrollContext:
    perception: Any
    env: Any
    region_registry: Any
    review_debug: Any
    vlm_ledger: Any
    region_composites: Dict[str, Any]
    segment_regions_override: Optional[Callable[[bytes], List[dict]]]
    desktop_regional_scroll: Callable[..., List[VisualElement]]
    classify_scroll_waste: Callable[..., Any]
    record_scroll_evidence: Callable[..., None]
    begin_node_local_accumulation: Callable[[], None]
    accumulate_node_local_functions: Callable[[], None]
    cache_key_get: Callable[[], Any]
    cache_key_set: Callable[[Any], None]
    cache_value_get: Callable[[], Any]
    cache_value_set: Callable[[Any], None]


class RegionScrollRuntime:
    """Region scroll behavior with no dependency on the engine class."""

    def __init__(self, context: RegionScrollContext) -> None:
        self.context = context
        self.perception = context.perception
        self.env = context.env
        self.region_registry = context.region_registry
        self.review_debug = context.review_debug
        self.vlm_ledger = context.vlm_ledger
        self._region_composites = context.region_composites

    @property
    def _seg_cache_key(self) -> Any:
        return self.context.cache_key_get()

    @_seg_cache_key.setter
    def _seg_cache_key(self, value: Any) -> None:
        self.context.cache_key_set(value)

    @property
    def _seg_cache_val(self) -> Any:
        return self.context.cache_value_get()

    @_seg_cache_val.setter
    def _seg_cache_val(self, value: Any) -> None:
        self.context.cache_value_set(value)

    def _segment_regions(
        self, shot: bytes, elements: Optional[List[VisualElement]] = None,
    ) -> List[dict]:
        override = self.context.segment_regions_override
        if override is not None:
            return override(shot, elements)
        return []

    def _desktop_regional_scroll(self, *args: Any, **kwargs: Any) -> List[VisualElement]:
        return self.context.desktop_regional_scroll(*args, **kwargs)

    def _classify_scroll_waste(self, *args: Any, **kwargs: Any) -> Any:
        return self.context.classify_scroll_waste(*args, **kwargs)

    def _record_scroll_evidence(self, **payload: Any) -> None:
        self.context.record_scroll_evidence(**payload)

    def _begin_node_local_accumulation(self) -> None:
        self.context.begin_node_local_accumulation()

    def _accumulate_node_local_functions(self) -> None:
        self.context.accumulate_node_local_functions()

    @staticmethod
    def _region_element_signature(elements):
        if not elements:
            return None
        return tuple(
            (int(getattr(e, "id", -1)), str(getattr(e, "name", "") or ""),
             tuple(int(v) for v in (getattr(e, "bbox_xywh", None) or [])),
             bool(getattr(e, "interactive", False)))
            for e in elements
        )

    def _segment_regions_cached(self, shot, elements=None, *,
                                force_refresh: bool = False):
        """Cache a caller-supplied legacy Region partition for one exact frame."""
        if not shot:
            return []
        import hashlib
        element_signature = self._region_element_signature(elements)
        k = (hashlib.md5(shot).hexdigest(), element_signature)
        if not force_refresh and k == getattr(self, "_seg_cache_key", None):
            if getattr(self, "vlm_ledger", None) is not None:
                self.vlm_ledger.cache_hit("legacy_region_cache")
            return self._seg_cache_val
        cache = getattr(self, "vlm_cache", None)
        if cache is not None and not force_refresh:
            hit, regs = cache.lookup_regions(shot, element_signature)
            if hit:
                self._seg_cache_key, self._seg_cache_val = k, regs
                return regs
        segmenter = self._segment_regions
        try:
            regs = segmenter(shot, elements)
        except TypeError as exc:
            # Preserve small test doubles and downstream overrides that still
            # implement the historical one-argument segmentation hook.
            if "positional" not in str(exc) and "argument" not in str(exc):
                raise
            regs = segmenter(shot)
        if regs:
            self._seg_cache_key, self._seg_cache_val = k, regs
            if cache is not None:
                cache.put_regions(shot, regs, element_signature)
            return regs
        # Empty segmentation is commonly a transient timeout/parse failure. Do
        # not negative-cache it. A failed forced refresh preserves the previous
        # successful canonical value instead of poisoning later identity checks.
        if force_refresh and cache is not None:
            hit, prior = cache.lookup_regions(shot, element_signature)
            if hit and prior:
                self._seg_cache_key, self._seg_cache_val = k, prior
                return prior
        return []

    def _stabilize_region_observations(self, regions, elements):
        """Reconcile one noisy modal segmentation with confirmed region structure.

        A raw VLM region is only an observation.  For ``tab_bar`` specifically we
        enforce the structural prior (>=2 horizontally aligned members near the
        top of the modal).  A weak/singleton observation is dropped; if a confirmed
        tab layout already exists and the current grounding still sees at least two
        of its canonical names at that geometry, the cached layout is projected
        back into this frame.  This absorbs both "one tab" and "no tab_bar" jitter
        without carrying a tab strip into a different/non-modal page.
        """
        regions = [dict(r) for r in (regions or [])]
        if not getattr(self.perception, "last_is_modal", False):
            return regions
        container = getattr(self.perception, "last_window_xywh", None)
        if not container or not elements:
            return regions

        cx, cy, cw, ch = container
        accepted = []
        strong_tab = False
        for r in regions:
            if r.get("role") != "tab_bar":
                accepted.append(r)
                continue
            box = r.get("bbox") or []
            if len(box) != 4:
                continue
            x0, y0, x1, y1 = box
            members = [e for e in elements
                       if x0 <= e.center[0] <= x1 and y0 <= e.center[1] <= y1]
            names = norm_names(e.name for e in members)
            ys = [e.center[1] for e in members if (e.name or "").strip()]
            width, height = max(0, x1 - x0), max(1, y1 - y0)
            aligned = not ys or max(ys) - min(ys) <= max(36, int(height * 0.65))
            near_top = (y0 + y1) / 2.0 <= cy + ch * 0.48
            strip_shape = width >= height * 2.0
            if len(names) >= 2 and aligned and near_top and strip_shape:
                accepted.append(r)
                strong_tab = True
            else:
                logger.info("region-stability: reject weak tab_bar names=%s "
                            "aligned=%s near_top=%s strip=%s bbox=%s",
                            sorted(names), aligned, near_top, strip_shape, box)

        if strong_tab:
            return accepted

        # No trustworthy raw tab strip.  Reuse a confirmed prototype only when the
        # current frame independently grounds >=2 canonical tab labels inside it.
        for cached in self.region_registry.confirmed_layouts("tab_bar", container):
            x0, y0, x1, y1 = cached["bbox"]
            visible = norm_names(
                e.name for e in elements
                if x0 <= e.center[0] <= x1 and y0 <= e.center[1] <= y1)
            support = visible & cached["names"]
            if len(support) < 2:
                continue
            accepted.append({k: v for k, v in cached.items()
                             if k in ("role", "bbox", "scrollable", "note")})
            logger.info("region-stability: recovered confirmed tab_bar %s from "
                        "cached geometry; visible support=%s",
                        cached["id"], sorted(support))
            break
        return accepted

    def _regional_scroll_dedup(self, obs, first_elements, state_id):
        """Region-aware aggregation with cross-node dedup. Segment regions, register
        each in self.region_registry: a NEW scrollable region is scrolled to full and
        its rows aggregated; a region already seen on another node (MATCHED) is NOT
        re-scrolled and its elements are marked visited (not re-enqueued) — so shared
        chrome (the sidebar) is explored ONCE across the whole graph. Falls back to
        the plain regional scroll if segmentation yields nothing."""
        RegionScrollRuntime._begin_node_local_accumulation(self)
        import io as _io
        import numpy as _np
        from PIL import Image as _Image
        try:
            import imagehash as _ih
        except Exception:
            _ih = None
        shot0 = obs.get("screenshot")
        if not shot0:
            self._record_scroll_evidence(
                scope_id=f"state:{state_id}:page", state_id=state_id,
                role="page", classification="unknown",
                termination="error", top_restored=False,
                detail="initial screenshot missing")
            return first_elements
        # [2026-07-09 用户] 模态框 = 普通区块容器,不再整体早退。旧版模态帧直接 return,
        # 顺带跳过了"给子区块打 region_id + 登记"两步 → tab(IPv6/Security)拿不到
        # region_id、只能按外观 uid 去重(随高亮漂移)→ 同一 tab 在多个分裂节点上反复点。
        # 现让模态走下面同一条区块路:tab_bar/dialog_titlebar 不可滚(闸门自动跳过,不滚),
        # form_body 高时按可滚聚合 below-fold。原早退三条理由已被化解:(1)"模态单屏"是错的
        # (高模态有 below-fold);(2)"重复检测同控件"由 name-dedup(下方 _seen_names)解决;
        # (3)"拖入变暗背景"由区块内滚 + 感知层 modal-bbox 过滤(visual_perception 705-706)
        # 双重解决。revert: 恢复此处 last_is_modal 早退。
        _is_modal = getattr(self.perception, "last_is_modal", False)
        _seg_elements = (
            getattr(self.perception, "last_all_elements", None)
            or first_elements
        )
        try:
            regions = self._segment_regions_cached(
                shot0, _seg_elements)   # 复用 identity 同帧 block grouping
        except TypeError:
            regions = self._segment_regions_cached(shot0)
        regions = self._stabilize_region_observations(regions, first_elements)
        if _is_modal:
            logger.info("region-dedup: modal dialog — 走区块路(打 region_id/登记; "
                        "form_body 可滚则聚合,tab_bar/titlebar 跳过滚动) regions=%d",
                        len(regions))
        if not regions:
            # [2026-07-09 用户] 模态帧若分割不出子区块:无区块可打标,滚也无收益,保留旧行为
            # (原样返回,不做全帧滚动)。非模态页维持原有 _desktop_regional_scroll 兜底。
            if _is_modal:
                self._record_scroll_evidence(
                    scope_id=f"state:{state_id}:page", state_id=state_id,
                    role="page", classification="unknown",
                    termination="not_attempted", top_restored=True,
                    detail="modal region segmentation unavailable")
                return first_elements
            return self._desktop_regional_scroll(
                obs, first_elements, state_id=state_id)

        matcher = ElementMatcher()
        for e in first_elements:
            try:
                matcher.match_or_add(shot0, e.bbox_xywh)
                e.scroll_steps = 0
                e._template = _reloc.save_template(shot0, e.bbox_xywh)
            except Exception:
                pass
        aggregated = list(first_elements)
        amap = assign_elements_to_regions(first_elements, regions)
        # [REGION-SCROLL CHANGE 14] per-node region composites (role -> PNG bytes),
        # saved by _register for downstream capability synth / instruction viewing.
        self._region_composites = {}

        def crop_rgb(b, rect):
            im = _Image.open(_io.BytesIO(b)).convert("RGB").crop(tuple(int(v) for v in rect))
            return _np.asarray(im)

        def crop_ph(b, rect):
            if _ih is None:
                return None
            try:
                return _ih.phash(_Image.open(_io.BytesIO(b)).convert("RGB").crop(tuple(rect)))
            except Exception:
                return None

        def scroll_at(x, y, direction, n=1):
            for _ in range(n):
                try:
                    self.env.step({"action_type": "SCROLL",
                                   "parameters": {"x": int(x), "y": int(y),
                                                  "direction": direction,
                                                  "amount": DESKTOP_WHEEL_CLICKS}}, pause=0.3)
                except Exception as ex:
                    logger.debug("region-dedup scroll failed (%s)", ex); break

        def cur():
            try:
                return self.env._get_obs().get("screenshot")
            except Exception:
                return None

        for i, rpx in enumerate(regions):
            rel = amap.get(i, [])
            for e in rel:                       # [CHANGE 14] tag region on elements
                e.region = rpx["role"]
                e.region_bbox = list(rpx["bbox"])   # [2026-07-06 (c)] out-of-region click guard
            names = [e.name for e in rel if (e.name or "").strip()]
            if not names:
                continue
            rid, is_new = self.region_registry.register(
                rpx["role"], names, rpx["scrollable"], node_id=state_id,
                bbox=rpx.get("bbox"),
                member_tokens=_region_member_tokens(rel),
                action_names=_region_action_names(rel),
                container_bbox=getattr(self.perception, "last_window_xywh", None))
            if not rid:
                # A tentative tab observation is diagnostic-only.  It must not
                # acquire a ledger id or drive a click in this frame.
                logger.info("region-stability: no confirmed id for %s names=%s",
                            rpx["role"], sorted(norm_names(names)))
                continue
            # [2026-07-08 用户 三层框架第2层] tag the STABLE region id on every element
            # of this region (top frame here, below-fold at CHANGE 14 tag site) so the
            # click ledger (region_registry.mark_clicked/is_clicked) can dedup a shared
            # sidebar by region — matched back across pages with no seen_on warm-up.
            for e in rel:
                e.region_id = rid
            # [2026-07-07 用户] piggyback the VLM display name on this seg pass — zero
            # extra call. First-wins (set_name no-ops if already named); cosmetic only.
            self.region_registry.set_name(rid, rpx.get("note", ""))
            _attach_region_visual_memory(
                self.region_registry, rid, shot0, rpx["bbox"], rel)
            _scroll_scope = f"region:{rid}"
            if not is_new:
                # shared region already seen elsewhere -> skip RE-SCROLLING it (the
                # `continue` below does that). Do NOT mark its visible buttons
                # visited: "seen this region" != "clicked every button in it". A new
                # panel's sidebar carries genuinely-unexplored entries (Display/Sound/
                # Power) next to the recurring ones; blanket-visiting them starved BFS
                # to 3 nodes (G2). Let each button flow to the downstream per-button
                # dedup (_actionable_elements: global name-dedup for shared/chrome,
                # per-state for the rest) so explored ones skip by NAME and new ones
                # still enqueue.
                logger.info("region-dedup: %s region %s already known (shared) — "
                            "skip re-scroll (%d visible btns kept for per-button dedup)",
                            rpx["role"], rid, len(names))
                _existing_scroll = getattr(
                    getattr(self, "graph", None), "scroll_ledger", {}
                ).get(_scroll_scope, {})
                if _existing_scroll and _existing_scroll.get("complete") is True:
                    self._record_scroll_evidence(
                        scope_id=_scroll_scope, state_id=state_id,
                        region_id=rid, role=rpx["role"],
                        classification=_existing_scroll.get(
                            "classification", "unknown"),
                        termination=_existing_scroll.get(
                            "termination", "unknown"),
                        bottom_reached=bool(_existing_scroll.get(
                            "bottom_reached")),
                        top_restored=bool(_existing_scroll.get("top_restored")),
                        steps=int(_existing_scroll.get("steps", 0) or 0),
                        max_steps=int(_existing_scroll.get("max_steps", 0) or 0),
                        detail="shared region reuses prior scroll evidence")
                    continue
                logger.info(
                    "region-dedup: %s region %s lacks complete scroll evidence; "
                    "re-auditing instead of reusing it", rpx["role"], rid)
            # [2026-07-09 用户] 内容类区块(content/form_body)默认按可滚尝试,不完全信 VLM
            # 的 scrollable 标志 —— VLM 对高模态易漏报 scrollable → 重现"漏 below-fold 元素"。
            # 代价极小:真不可滚时,滚一下 pHash 不变,stale-patience(SCROLL_PATIENCE=2)即停。
            # 其余 chrome 类(tab_bar/dialog_titlebar/toolbar/statusbar)仍严格按 VLM 标志。
            _content_role = rpx["role"] in ("content", "form_body")
            if not rpx["scrollable"] and not _content_role:
                self._record_scroll_evidence(
                    scope_id=_scroll_scope, state_id=state_id,
                    region_id=rid, role=rpx["role"],
                    classification="static", termination="static",
                    bottom_reached=True, top_restored=True,
                    steps=0, max_steps=DESKTOP_MAX_SCROLL_STEPS,
                    detail="non-scrollable structural region")
                continue
            cy = (rpx["bbox"][1] + rpx["bbox"][3]) // 2
            # [2026-07-09 用户] 滚动锚点避开按钮/输入框:区块正中常压在控件上(form_body
            # 正中=Cloned Address 输入框)→ GNOME 弹 tooltip 气泡 → 遮挡真内容 + 改 pHash
            # 制造假"moved"信号 → 多滚+多 grounding+误收顶部 chrome(幽灵)。改停在区块内
            # 最左元素与左边缘之间的空白栏(padding)——够宽(≥24px)就用,否则退回正中。
            _rleft = rpx["bbox"][0]
            _elem_left = min([e.center[0] for e in rel], default=_rleft) if rel else _rleft
            _gutter = _elem_left - _rleft
            if _gutter >= 24:
                cx = _rleft + _gutter // 2
            else:
                cx = (rpx["bbox"][0] + rpx["bbox"][2]) // 2
            # [REGION-SCROLL CHANGE 11 / 2026-07-09 用户 互相关重叠判据] 每步只做便宜的帧间
            # 对齐(cv2 归一化互相关),VLM grounding 只在「自上次识别以来内容累计上移过半屏
            # (共同区块<50%)」或「真滚动过后到底补一枪」时触发,非每步。取代旧 pHash 判据:
            # pHash 是标量"变没变"、非平移不变,tooltip 局部叠加会骗出假 moved;互相关是"先对齐
            # 再看重叠",平移感知,tooltip 无一致位移→shift≈0/低分→不误判。
            from ..stitch import estimate_shift, SHIFT_MATCH_MIN, MIN_SHIFT_PX
            steps = 0; stale = 0; new_names = []; new_elements = []
            termination = "unknown"
            prev_crop = crop_rgb(shot0, rpx["bbox"])   # 上一帧区块裁剪(RGB),互相关基准
            scrolled_since_ground = 0                  # 自上次 grounding 以来内容累计上移(px)
            region_h = rpx["bbox"][3] - rpx["bbox"][1] # 区块高,用于 50% 重叠阈值
            # ever_moved:整段滚动里是否真产生过位移。不可滚区块 shift 恒<MIN_SHIFT_PX →
            # 全程 False → 不补尾部 grounding → 不重识别顶部固定 chrome(无幽灵)。
            ever_moved = False
            # [2026-07-06 用户: name-dedup, keep the FIRST (top-frame) sighting] A FIXED
            # item (a sidebar row) re-detected on later scroll steps — the appearance
            # matcher counts it new because the VLM bbox jitters — must NOT be re-added
            # as a phantom below-fold duplicate (Color ×3 with fake scroll_steps → the
            # below-fold servo then mis-clicks to the wrong spot). Drop any later
            # same-name detection; keep only the top-frame one (scroll_steps=0, real
            # coords, no servo). Seeded with this region's top-frame names; empty-name
            # icons still fall back to the appearance matcher.
            _seen_names = {n.strip().lower() for n in names if n and n.strip()}
            _crops = [crop_rgb(shot0, rpx["bbox"])]   # [CHANGE 14] cheap region crops for stitch
            # [2026-07-09 用户 已知位移拼图] 与 _crops 严格平行:_crop_shifts[i] = 第 i 帧相对
            # 第 i-1 帧内容上移的像素(互相关判据顺手已算,无需拼接器重推)。[0]=0(种子无前驱)。
            # 喂给 stitch_region_crops 直接用,免得它在稀疏表单上重跑 matchTemplate 分数过低而丢帧
            # → 长图塌成单屏。只有 append 成功的帧才追加对应 shift,保证两列表下标对齐。
            _crop_shifts = [0]
            while steps < DESKTOP_MAX_SCROLL_STEPS and stale < SCROLL_PATIENCE:
                scroll_at(cx, cy, "down", 1); steps += 1
                shot = cur()
                if not shot:
                    termination = "error"
                    break
                _appended = False
                try:
                    _crops.append(crop_rgb(shot, rpx["bbox"]))
                    _appended = True
                except Exception:
                    pass
                # [2026-07-09 用户 互相关重叠判据] 相邻帧对齐:测这一步内容上移了几像素。
                # 只测相邻两帧(重叠大、匹配稳),累加得"自上次 grounding 以来共移多少"——
                # 避开"当前 vs 上次识别帧"重叠过小时 matchTemplate 抓错的坑(见 stitch 注释)。
                cur_crop = _crops[-1] if _appended else crop_rgb(shot, rpx["bbox"])
                try:
                    step_shift, step_score = estimate_shift(prev_crop, cur_crop, 0, 0)
                except Exception:
                    step_shift, step_score = 0, 0.0
                moved = _region_scroll_moved(
                    prev_crop, cur_crop, step_shift, step_score,
                    min_shift=MIN_SHIFT_PX, min_score=SHIFT_MATCH_MIN)
                prev_crop = cur_crop
                # 真移动:位移够大、匹配可信且区域像素确有变化。tooltip/cursor
                # 局部叠加不会跨过像素比例门槛，空白页模板也不能伪造滚动。
                # 记录这帧的已知位移(与 _crops 平行);没动则记 0 → 拼接器视作无新内容不追加。
                if _appended:
                    _crop_shifts.append(int(step_shift) if moved else 0)
                if moved:
                    ever_moved = True
                    scrolled_since_ground += step_shift
                # grounding 触发:(a) 自上次识别以来累计上移 ≥ 半个区块高(共同区块<50%,过半是
                # 新内容,该重识别);或 (b) 真滚动过、这步停下了(到底),补最后一枪抓尾部。
                # 不可滚区块:从没动过→(b)被 ever_moved 挡→整轮 0 次 grounding→无幽灵。
                big = (region_h > 0 and scrolled_since_ground >= 0.5 * region_h)
                do_ground = big or (not moved and stale == 0 and ever_moved)
                added = 0
                if do_ground:
                    scrolled_since_ground = 0
                    try:
                        fresh = self.perception.detect_and_name(shot)
                        RegionScrollRuntime._accumulate_node_local_functions(self)
                    except Exception:
                        fresh = []
                    for e in fresh:
                        # [2026-07-09 用户 补 y 判据] grounding 喂的是整帧,返回整屏元素;归属
                        # 本区块要求中心同时落在区块 x 和 y 内。旧版只筛 x:竖排模态里顶部固定
                        # chrome(标题栏/tab)与 form_body 同宽(共享 x),滚动中重识别整帧时被
                        # 误收进来(cy 在区块上方却漏筛)→ 幽灵。真 below-fold 元素滚进视口后
                        # cy 落在区块 y 范围内,不受影响。x/y 各留 10px 余量吸收 bbox 抖动。
                        if not (rpx["bbox"][0] - 10 <= e.center[0] <= rpx["bbox"][2] + 10):
                            continue
                        if not (rpx["bbox"][1] - 10 <= e.center[1] <= rpx["bbox"][3] + 10):
                            continue
                        try:
                            _u, isn = matcher.match_or_add(shot, e.bbox_xywh)
                        except Exception:
                            isn = True
                        if isn:
                            # [2026-07-06 用户] name-dedup: a later scroll step that
                            # re-detects an ALREADY-SEEN name is a phantom duplicate of
                            # the top-frame item (VLM bbox jitter defeated the appearance
                            # matcher) — drop it. Only genuinely NEW names (real below-
                            # fold rows) pass; empty-name icons keep the matcher result.
                            _nk = (e.name or "").strip().lower()
                            if _nk and _nk in _seen_names:
                                continue
                            if _nk:
                                _seen_names.add(_nk)
                            e.scroll_steps = steps
                            try:
                                e._template = _reloc.save_template(shot, e.bbox_xywh)
                            except Exception:
                                pass
                            e.region = rpx["role"]      # [CHANGE 14] tag below-fold too
                            e.region_id = rid           # [三层框架第2层] stable region id
                            e.region_bbox = list(rpx["bbox"])   # [2026-07-06 (c)] out-of-region click guard
                            _attach_region_visual_memory(
                                self.region_registry, rid, shot,
                                rpx["bbox"], [e])
                            aggregated.append(e); new_names.append(e.name)
                            new_elements.append(e); added += 1
                # [2026-07-06] Terminate on CROP MOVEMENT alone, not `added`: VLM
                # grounding is non-deterministic, so a STATIC frame re-detects the
                # same controls (jittered bboxes → matcher counts each as new) →
                # added>0 forever → the old `and added == 0` scrolled a non-scrolling
                # region to max (dialog: 16 steps, 17 controls counted ~6×). Crop
                # unmoved for SCROLL_PATIENCE steps = no new content = stop.
                stale = stale + 1 if not moved else 0
            scroll_at(cx, cy, "up", steps + 1)
            if stale >= SCROLL_PATIENCE:
                termination = "viewport_stable"
            elif steps >= DESKTOP_MAX_SCROLL_STEPS:
                termination = "hard_cap"
            elif termination == "unknown":
                termination = "error"
            _restored_shot = cur()
            _initial_ph = crop_ph(shot0, rpx["bbox"])
            _restored_ph = (crop_ph(_restored_shot, rpx["bbox"])
                            if _restored_shot else None)
            _top_restored = bool(
                _initial_ph is not None and _restored_ph is not None
                and (_initial_ph - _restored_ph) <= VIEW_STABLE_DISTANCE)
            self._record_scroll_evidence(
                scope_id=_scroll_scope, state_id=state_id,
                region_id=rid, role=rpx["role"],
                classification=("scrollable" if ever_moved else "static"),
                termination=termination,
                bottom_reached=(termination == "viewport_stable"),
                top_restored=_top_restored, steps=steps,
                max_steps=DESKTOP_MAX_SCROLL_STEPS)
            # [spec B / Q4] repeated-scroll: hit the cap with 0 new names = the
            # over-scroll pattern (should be stopped by stale-patience). Record-only.
            if self.review_debug.enabled:
                _sw = self._classify_scroll_waste(steps, len(new_names),
                                                  DESKTOP_MAX_SCROLL_STEPS)
                if _sw:
                    self.review_debug.record_event(
                        "repeated_scroll", node=state_id, region=rpx.get("role", ""),
                        steps=steps, n_new=len(new_names), reason=_sw)
            if new_names:
                self.region_registry.extend(
                    rid, new_names,
                    member_tokens=_region_member_tokens(new_elements),
                    action_names=_region_action_names(new_elements))
            # [CHANGE 14] stitch the cheap region crops into one composite + stash it
            # (saved by _register) so downstream sees the full region, not just top.
            try:
                from ..stitch import stitch_region_crops
                comp = stitch_region_crops(_crops, shifts=_crop_shifts)
                if comp is not None:
                    import io as _io2
                    from PIL import Image as _Img2
                    _buf = _io2.BytesIO(); _Img2.fromarray(comp).save(_buf, "PNG")
                    self._region_composites[rpx["role"]] = _buf.getvalue()
                    self.region_registry.remember_visual(rid, visual_map=comp)
                    _template, _map = self.region_registry.visual_of(rid)
                    for _element in rel + new_elements:
                        _element._region_template = _template
                        _element._region_map = _map
            except Exception as _ex:
                logger.debug("region composite stitch failed (%s)", _ex)
            logger.info("region-dedup: %s region %s NEW — scrolled %d steps, +%d below-fold, "
                        "互相关实测可滚=%s, composite=%s", rpx["role"], rid, steps,
                        len(new_names), ever_moved,
                        rpx["role"] in self._region_composites)
        return aggregated
