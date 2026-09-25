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
from ..prompts.navigation import INTERRUPTION_DISMISS_PROMPT
logger = logging.getLogger(__name__)

class InterruptionDismisser:
    """VLM decision: which control closes the current interruption popup.

    Second half of the two-layer popup handling (用户 2026-07-05). The grounding
    perception agent flags ``is_interruption`` on a frame; when set, THIS agent
    looks at that frame and picks the control that dismisses the popup / returns
    the app to a normal page. NO hard-coded close-word list — the VLM decides, so
    non-standard keys (only "稍后"), multi-step popups, and "decline-don't-accept"
    (cookie/subscription) cases are handled. The engine clicks the chosen control,
    re-observes, and re-checks ``is_interruption`` in a bounded loop until the
    popup is gone (``_dismiss_interruptions``). Fails to ``done`` on any error so a
    flaky judge never blocks exploration.
    """

    def __init__(self, agent, ledger=None):
        self.agent = agent
        self.ledger = ledger

    def decide(self, screenshot_bytes: bytes,
               candidates: List["Any"]) -> Dict[str, Any]:
        """candidates: VisualElement list on the current (popup) frame.

        Returns {"action": "click"|"done", "button": elem|None, "reason": str}.
        ``done`` means "no dismiss control chosen / already normal" — the engine
        then stops the dismiss loop and proceeds."""
        done = {"action": "done", "button": None, "reason": "no-op"}
        if self.agent is None or not candidates:
            return done
        by_id = {pid: e for pid, e in enumerate(candidates)}
        cand_lines = "\n".join(
            f"  [{pid}] {e.name or '(无名)'}  "
            f"用途={getattr(e, 'purpose', '') or '(未知)'}  "
            f"预期即时效果={getattr(e, 'expected_immediate_effect', '') or '(未知)'}"
            for pid, e in enumerate(candidates))
        prompt = INTERRUPTION_DISMISS_PROMPT.format(candidates=cand_lines)
        try:
            from ..visual_cache import predict_mm_role
            resp, *_ = predict_mm_role(
                self.agent, "interruption_dismisser", prompt,
                [_img_arr(screenshot_bytes)], self.ledger)
        except Exception as e:
            logger.warning("interruption-dismisser failed: %s", e)
            return done
        parsed = _parse_json(resp)
        if not isinstance(parsed, dict):
            return done
        reason = str(parsed.get("reason", ""))[:80]
        # Fail closed: force-first startup inspection may ask on a normal page,
        # so a click is authorized only by two explicit structured facts.  Old
        # responses, strings such as "true", and uncertain/missing fields are
        # no-ops.  Names and UI types are deliberately not used as authorization.
        authorized = (
            parsed.get("surface_is_temporary") is True
            and parsed.get("target_is_close_control") is True
        )
        if (authorized
                and str(parsed.get("action", "done")).strip().lower() == "click"):
            btn = by_id.get(parsed.get("button_id"))
            if btn is not None:
                logger.info("dismiss: click '%s' (%s)", btn.name, reason)
                return {"action": "click", "button": btn, "reason": reason}
        logger.info("dismiss: done (%s)", reason)
        return {"action": "done", "button": None, "reason": reason}


# ── Annotation reviewer (QA over grounding's boxes) ────────────────────────

# 用户 2026-07-06: grounding 每帧标注后,本 agent 站在**人类视角**质检 —— 覆盖 grounding
# 的三类错误(错标 / 漏标 / 重复标)。通用 prompt,不写死"什么算异常",让 VLM 像质检员
# 一样看这批框对不对。引擎消费:去重复框、日志暴露漏标/错标(供分析),重复严重可作
# "该停止滚动"的语义信号(补 moved-termination 的像素信号)。


# [2026-07-08 用户] 合并质检:区块检测 + 按钮检测【一次调用】,跑在区块分割后、节点命名前。
# 除了原三类框错误,再让质检员核对【区块分割】——尤其"明明有右侧详情面板却没被分出来"
# (稀疏 content 面板被 <2 名门槛丢弃 / segVLM 抖动漏切),这是同页分裂→hard-reset 的根因。
# regions 文本给出当前分割(role + 备注 + 成员前几项),VLM 对照截图判分割对不对。
