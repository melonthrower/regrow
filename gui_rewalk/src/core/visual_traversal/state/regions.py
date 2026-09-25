"""Region-set identity helpers and reconciliation verdicts."""
from __future__ import annotations

import hashlib

from .matching import normalize_button_names

def _region_set_id(rset) -> str:
    """[2026-07-07 用户] state_id 从【区块集】派生: 对 sorted(rset) 取稳定哈希。
    同一区块集恒得同 id, 不同区块集必不同 id —— 取代 pHash 派生(pHash 在同框架
    桌面页上恒撞, 让两个真不同页共享 id 前缀)。首次登记时区块集固定该 id。"""
    raw = "|".join(sorted(str(x) for x in (rset or ())))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _button_set_id(names) -> str:
    """Return a deterministic base id for an unbound content observation.

    The caller adds a suffix on collision; equal wording therefore never merges
    distinct screenshots or replaces an explicit semantic State decision.
    """
    norm = normalize_button_names(names) if names else set()
    raw = "|".join(sorted(str(x) for x in norm))
    return "b" + hashlib.sha256(raw.encode("utf-8")).hexdigest()[:11]


def _most_overlapping_rset(rs, known_sets, exclude=None):
    """[2026-07-07 用户 身份质检] 已登记节点里, 与 rs 区块集重叠最高的 (sid, Jaccard)。
    过度分裂质检用【区块集重叠】而非 pHash —— 独立于判定口径? 不: 判定看 verdict
    (相等/差1/差≥2), 质检看连续 Jaccard, 能抓到"差≥2 判不同、但其实大半区块共享"的
    可疑分裂(如 content 区块相同只是侧栏 seg 抖动多切一块)。None = 无可比。"""
    best = None
    a = set(rs or ())
    if not a:
        return None
    for sid, known in (known_sets or {}).items():
        if sid == exclude:
            continue
        b = set(known or ())
        if not b:
            continue
        jac = len(a & b) / len(a | b)
        if best is None or jac > best[1]:
            best = (sid, jac)
    return best


def region_set_verdict(set_a, set_b) -> str:
    """[2026-07-06 用户] Page identity by REGION-ID SET. Each region maps to a
    stable ``region:<rid>`` (RegionRegistry, shared across nodes); a page's identity is
    the SET of its regions. Returns 'same' / 'different' / 'ambiguous'.

      * equal sets                        -> same
      * symmetric difference of exactly 1 -> ambiguous (one region added/dropped:
                                             grounding jitter; let the VLM decide)
      * otherwise (>=2 regions differ, or a discriminating region swapped)
                                          -> different
    Empty on either side -> ambiguous (nothing segmented; cannot decide)."""
    a, b = set(set_a or ()), set(set_b or ())
    if not a or not b:
        return "ambiguous"
    if a == b:
        return "same"
    if len(a ^ b) == 1:
        return "ambiguous"
    return "different"
