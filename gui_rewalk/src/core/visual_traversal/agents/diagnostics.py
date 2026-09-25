"""Visual-traversal agent role implementation."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import numpy as np

from .common import _img_arr, _norm_fn, _parse_json

logger = logging.getLogger(__name__)

def classify_edge_consistency(seen: Dict[Any, Any], src: str, name: str,
                              dst: str) -> Optional[str]:
    """[spec B / Q4] Non-deterministic edge detector. Keyed by (src, button name):
    the SAME button clicked from the SAME page should reach the SAME destination.
    Returns the PRIOR (different) dst if this click contradicts a remembered edge
    (a mis-click / flaky page / broken replay), else None. Mutates ``seen`` to
    remember the first dst per (src, name). Per-source keying so a shared button
    name on another page is independent."""
    key = (src, name)
    prev = seen.get(key)
    if prev is not None and prev != dst:
        return prev
    if prev is None:
        seen[key] = dst
    return None

def classify_scroll_waste(steps: int, n_new: int,
                          max_steps: int) -> Optional[str]:
    """[spec B / Q4] Repeated-scroll detector. A region that scrolled all the way
    to the CAP while finding ZERO new names is the over-scroll pattern (a modal /
    non-scrolling region dragged to max re-detecting the same controls) — a
    regression signal now that stale-patience should stop it. Hitting the cap WHILE
    finding new rows is a legit long page (not flagged). Returns a reason or None."""
    if steps >= max_steps and n_new == 0:
        return "hit_max_no_new"
    return None

class ReviewDebugSink:
    """Turns the (log-only) AnnotationReviewer into a DEBUG agent: persists each
    node's grounding + review verdict AND engine mis-click/retarget events as
    structured JSONL, so a run's quality is inspectable without grepping a giant,
    mojibake-prone log (用户 2026-07-06: "把检测异常的 agent 输出记录下来当 debug").

    One line per record: {kind:"node"|"event", ...}. UTF-8, ensure_ascii=False so
    Chinese element / missing names survive (the log garbled them). ``path=None``
    -> disabled no-op (production default). Best-effort: never raises into the BFS
    loop. Enable from the engine via env GUIWALK_REVIEW_DEBUG=1."""

    def __init__(self, path: Optional[str]):
        self.path = path
        self._fh = None
        if path:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
                self._fh = open(path, "a", encoding="utf-8")
            except Exception as e:  # pragma: no cover - disk error
                logger.warning("ReviewDebugSink open failed (%s); disabled", e)
                self._fh = None

    @property
    def enabled(self) -> bool:
        return self._fh is not None

    def _write(self, rec: Dict[str, Any]) -> None:
        if self._fh is None:
            return
        try:
            rec.setdefault("ts", _dt.datetime.now().isoformat(timespec="seconds"))
            self._fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._fh.flush()
        except Exception as e:  # pragma: no cover
            logger.debug("ReviewDebugSink write failed: %s", e)

    def record_node(self, node_id: str, elements, review: Dict[str, Any]) -> None:
        """Snapshot a registered node: its final elements (name/coords/region/
        scroll_steps/source) paired with the reviewer's verdict. NOTE the review
        ids are SoM-image ids (pre-filter) and may not index this element list —
        that id-space gap is itself a finding, so we record both verbatim."""
        if self._fh is None:
            return
        els = []
        for e in (elements or []):
            get = (lambda k, d=None: getattr(e, k, d)) if not isinstance(e, dict) \
                else (lambda k, d=None: e.get(k, d))
            els.append({"id": get("id"), "name": get("name", ""),
                        "center": list(get("center") or []),
                        "bbox_xywh": list(get("bbox_xywh") or []),
                        "region": get("region", ""),
                        "scroll_steps": get("scroll_steps", 0),
                        "source": get("source", "")})
        self._write({"kind": "node", "node": node_id,
                     "n_elements": len(els), "elements": els,
                     "review": review or {}})

    def record_event(self, event_type: str, **fields: Any) -> None:
        """Log an engine-level anomaly (retarget_rejected / fly-click / off-app /
        early-stop) with arbitrary structured fields."""
        if self._fh is None:
            return
        self._write({"kind": "event", "type": event_type, **fields})

    def record_agent(self, agent: str, node: str = "", step: Optional[int] = None,
                     verdict: Any = None, reason: str = "", **extra: Any) -> None:
        """[spec: structured agent transcript] Record ONE agent role's parsed reply
        (verdict + reason) tagged with the node + step, so the analyzer can line up
        what each agent SAID around a click (e.g. the deterministic frontier
        scheduler selected 'Open detail') against the ACTUAL outcome
        (click_effect) and judge accuracy. Not the
        raw VLM text — the parsed decision, which is what tells us if it ran right."""
        if self._fh is None:
            return
        rec = {"kind": "agent", "agent": agent, "node": node,
               "verdict": verdict, "reason": reason}
        if step is not None:
            rec["step"] = step
        rec.update(extra)
        self._write(rec)

    def record_candidate_breakdown(self, node_id: str, kept, dropped) -> None:
        """[spec A] Neutral per-node record: of this node's elements, which were
        DROPPED from the explorable pool and WHY, plus how many remain. ``dropped``
        is a list of (name, reason) tuples collected in-place by
        _unvisited_candidates (single source of truth — the reason recorded IS the
        reason used). Makes an early-stop legible: e.g. "root: 22 dropped by
        shared_global_explored". No judgment here (Q1) — the analyzer/human spots
        the suspicious pattern."""
        if self._fh is None:
            return
        det = [{"name": n, "reason": r} for (n, r) in (dropped or [])]
        by_reason: Dict[str, int] = {}
        for d in det:
            by_reason[d["reason"]] = by_reason.get(d["reason"], 0) + 1
        self._write({"kind": "candidate_breakdown", "node": node_id,
                     "n_kept": len(kept or []), "n_dropped": len(det),
                     "by_reason": by_reason,
                     "kept": list(kept or []), "dropped": det})

    def save_click_shots(self, tag: str, before_bytes: Optional[bytes],
                         after_bytes: Optional[bytes]) -> Optional[Dict[str, str]]:
        """Save before/after PNGs for an ANOMALOUS click (no_change /
        transitioned_inconsistent) so the verdict carries visual proof — you can
        SEE whether the screen was the believed page or a stuck overlay when the
        click landed. Returns {"before":path,"after":path} or None. Files go in
        <jsonl_dir>/_click_shots/. Disabled sink / missing bytes -> None."""
        if self._fh is None or not before_bytes or not after_bytes:
            return None
        try:
            shots_dir = os.path.join(os.path.dirname(os.path.abspath(self.path)),
                                     "_click_shots")
            os.makedirs(shots_dir, exist_ok=True)
            safe = re.sub(r"[^0-9A-Za-z_.-]+", "_", str(tag))[:80]
            bp = os.path.join(shots_dir, f"{safe}_before.png")
            ap = os.path.join(shots_dir, f"{safe}_after.png")
            with open(bp, "wb") as f:
                f.write(before_bytes)
            with open(ap, "wb") as f:
                f.write(after_bytes)
            return {"before": bp, "after": ap}
        except Exception as e:  # pragma: no cover
            logger.debug("save_click_shots failed: %s", e)
            return None

    def close(self) -> None:
        if self._fh is not None:
            try:
                self._fh.close()
            except Exception:
                pass
            self._fh = None
