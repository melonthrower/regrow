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

class ExplorationMemory:
    """Records explored button *functions* across the whole traversal.

    Keyed by semantic function name (normalised), not pixel/coords, so a button
    whose function was already explored — on THIS page or any OTHER page — is not
    clicked again. Navigation functions that genuinely repeat across pages (a
    shared 'Settings' gear, a 'Back' arrow) are deduped globally; the engine
    still keeps per-node visited uids for the appearance-level check.
    """

    def __init__(self):
        self._explored_fn: set[str] = set()       # function name -> explored
        self._explored_fn_per_state: Dict[str, set] = {}

    def mark_explored(self, state_id: str, name: str, *,
                      global_scope: bool = True) -> None:
        """Record ``name`` as explored. Always recorded per-state; only added to
        the GLOBAL cross-page set when ``global_scope`` is True. The engine passes
        ``global_scope=True`` only for genuine cross-page chrome controls
        (Back/Home/Close) and ``False`` for ordinary list rows, so a row on page A
        never prunes a same-named row on page B (root cause #3)."""
        fn = _norm_fn(name)
        if not fn:
            return
        if global_scope:
            self._explored_fn.add(fn)
        self._explored_fn_per_state.setdefault(state_id, set()).add(fn)

    def is_explored(self, name: str) -> bool:
        """True iff ``name``'s function was explored GLOBALLY (cross-page chrome)."""
        fn = _norm_fn(name)
        return bool(fn) and fn in self._explored_fn

    def is_explored_in_state(self, state_id: str, name: str) -> bool:
        """True iff ``name`` was already explored ON THIS state (per-page dedup)."""
        fn = _norm_fn(name)
        if not fn:
            return False
        return fn in self._explored_fn_per_state.get(state_id, set())

    def explored_names(self) -> List[str]:
        return sorted(self._explored_fn)


# ── Interruption dismisser (exception-handling agent) ──────────────────────

# 两层设计(用户 2026-07-05):判断层 = grounding agent 出 is_interruption;处置层 =
# 本 agent。VLM 看截图自己决定点哪个能关掉浮层/让应用回到正常界面 —— **不用硬编码
# 关闭词表**(换语言/非标准键"稍后"/需先拒绝 cookie 就失效),所以能应付多步、非标准、
# "该拒绝而非接受"的弹窗。引擎点掉后重新观察、再判 is_interruption,有界循环到回正常。
