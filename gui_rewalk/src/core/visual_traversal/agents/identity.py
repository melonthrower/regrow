"""Visual-traversal agent role implementation."""

from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import re
from contextlib import contextmanager
from typing import Any, Dict, List, Optional

from .common import _img_arr, _parse_json
from ..action_space import is_android, normalize_native_action
from ..prompts.navigation import (
    build_return_path_prompt,
)
from ..prompts.identity_candidates import (
    build_region_correspondence_prompt,
    build_region_partition_mapping_prompt,
    build_page_candidate_selection_prompt,
    build_pair_page_identity_prompt,
)
logger = logging.getLogger(__name__)


@contextmanager
def _page_identity_thinking(agent):
    """Enable thinking only while comparing two full-page screenshots."""
    if agent is None or not hasattr(agent, "enable_thinking"):
        yield
        return
    previous = agent.enable_thinking
    agent.enable_thinking = True
    try:
        yield
    finally:
        agent.enable_thinking = previous


class PageIdentityJudge:
    """VLM judge for 'same functional page, different data'.

    Priority-4: a shared per-run cache (keyed by the ordered exact-frame pair) wraps the
    call so the identical (candidate, current) pair — fired up to 6x back-to-back
    during a single register, and again on every backtrack arrival check — costs
    one VLM call, not six.
    """

    def __init__(self, agent, cache=None, ledger=None):
        self.agent = agent
        self.cache = cache
        self.ledger = ledger
        self.last_reason = ""
        self.last_choice = "NEW"
        self.last_candidate_choice = "NEW"
        self.last_candidate_reason = ""
        self.last_candidate_page_ids = ()
        self.last_proposed_new_page_name = ""
        self.last_matched_candidate_state_ids = ()
        self.last_selection_status = "not_run"
        self.last_comparison_status = "unresolved"
        self.last_is_interruption = False

    def _judge_relationship(
        self, candidate_bytes: bytes, current_bytes: bytes,
        cand_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        if self.agent is None:
            self.last_comparison_status = "unresolved"
            self.last_reason = "page identity unavailable"
            return None
        prompt = build_pair_page_identity_prompt()
        try:
            from ..visual_cache import predict_mm_role
            with _page_identity_thinking(self.agent):
                resp, *_ = predict_mm_role(
                    self.agent, "page_identity", prompt,
                    [_img_arr(candidate_bytes), _img_arr(current_bytes)], self.ledger)
        except Exception as e:
            logger.warning("page-identity judge failed: %s", e)
            self.last_comparison_status = "unresolved"
            self.last_reason = f"page identity call failed: {e}"[:200]
            return None
        parsed = _parse_json(resp)
        relationship = ""
        if isinstance(parsed, dict) and parsed.get("is_interruption") is True:
            self.last_is_interruption = True
            self.last_reason = str(parsed.get("reason", ""))[:200]
            self.last_comparison_status = "interruption"
            logger.info("page-identity: current screenshot has interruption (%s)",
                        self.last_reason[:60])
            return None
        if (isinstance(parsed, dict)
                and parsed.get("is_interruption") is False
                and isinstance(parsed.get("same_page"), bool)):
            # The confirmed VLM contract is Page-level binary identity.
            relationship = (
                "same_page"
                if parsed["same_page"] else "different_page")
        if relationship:
            self.last_verdict = relationship != "different_page"
            self.last_reason = str(parsed.get("reason", ""))[:200]
            self.last_comparison_status = relationship
            logger.info("page-identity: relationship=%s (%s)", relationship,
                        str(parsed.get("reason", ""))[:60])
            return relationship
        self.last_comparison_status = "unresolved"
        self.last_reason = "invalid page identity response"
        return None

    def compare_relationship(
        self, candidate_bytes: bytes, current_bytes: bytes,
        cand_meta: Optional[Dict[str, Any]] = None,
    ) -> Optional[str]:
        """Return the three-way relationship, or None when unresolved."""
        self.last_comparison_status = "unresolved"
        self.last_is_interruption = False
        if self.cache is not None and hasattr(
                self.cache, "get_page_relationship_result"):
            result = self.cache.get_page_relationship_result(
                candidate_bytes, current_bytes,
                lambda: self._judge_relationship(
                    candidate_bytes, current_bytes, cand_meta))
            if result is not None and self.last_comparison_status == "unresolved":
                self.last_comparison_status = str(result)
                self.last_reason = "cached page identity relationship"
            return result
        return self._judge_relationship(
            candidate_bytes, current_bytes, cand_meta)

    def compare_page(self, candidate_bytes: bytes, current_bytes: bytes,
                     cand_meta: Optional[Dict[str, Any]] = None
                     ) -> Optional[bool]:
        """Return True/False for evidence, or None when identity is unresolved."""
        relationship = self.compare_relationship(
            candidate_bytes, current_bytes, cand_meta)
        if relationship is None:
            return None
        return relationship != "different_page"

    def same_page(self, candidate_bytes: bytes, current_bytes: bytes,
                  cand_meta: Optional[Dict[str, Any]] = None) -> bool:
        # Page identity sees only the two full screenshots, so their exact ordered
        # pair is the complete cache key. cand_meta remains a compatibility input.
        return bool(self.compare_page(
            candidate_bytes, current_bytes, cand_meta))

    def which_page(self, current_bytes: bytes, candidates,
                   transition=None, current_observation=None) -> str:
        """Shortlist stable Pages once, then verify at most two screenshots."""
        self.last_choice = "NEW"
        self.last_reason = ""
        self.last_candidate_choice = "NEW"
        self.last_candidate_reason = ""
        self.last_candidate_page_ids = ()
        self.last_proposed_new_page_name = ""
        self.last_matched_candidate_state_ids = ()
        self.last_selection_status = "not_run"
        self.last_is_interruption = False
        if self.agent is None or not current_bytes or not candidates:
            self.last_reason = "page identity unavailable"
            return "UNRESOLVED"
        candidates = list(candidates)
        labels = {}
        descriptions = []
        for index, candidate in enumerate(candidates, 1):
            label = f"C{index}"
            labels[label] = candidate
            descriptions.append({
                "candidate_page_id": label,
                "page": candidate.get("descriptor") or {},
            })

        transition = transition or {}
        opening_action = {
            "label": str(transition.get("clicked_label") or "").strip(),
        }
        for field in ("clicked_bbox", "clicked_point"):
            value = transition.get(field)
            if isinstance(value, (list, tuple)):
                opening_action[field] = list(value)
        source_bytes = b""
        source_path = str(
            transition.get("source_screenshot_path") or "").strip()
        if source_path:
            try:
                with open(source_path, "rb") as stream:
                    source_bytes = stream.read()
            except OSError:
                source_bytes = b""
        prompt = build_page_candidate_selection_prompt(
            descriptions,
            has_source_screenshot=bool(source_bytes),
            opening_action=opening_action,
        )

        selection_failed = False
        selection_exhaustive = False
        selected = []
        response = ""
        try:
            from ..visual_cache import predict_mm_role
            images = [_img_arr(current_bytes)]
            if source_bytes:
                images.append(_img_arr(source_bytes))
            response, *_ = predict_mm_role(
                self.agent, "page_identity_candidate_selection", prompt,
                images, self.ledger)
            parsed = _parse_json(response)
            raw_labels = (
                parsed.get("candidate_page_ids")
                if isinstance(parsed, dict) else None)
            if (
                not isinstance(raw_labels, list)
                or not 1 <= len(raw_labels) <= 2
            ):
                raise ValueError("invalid candidate_page_ids")
            clean_labels = [
                str(label).strip().upper() for label in raw_labels]
            if (
                len(clean_labels) != len(set(clean_labels))
                or any(label not in labels for label in clean_labels)
            ):
                raise ValueError("unknown or repeated Page candidate")
            selected = [labels[label] for label in clean_labels]
            self.last_candidate_choice = clean_labels[0]
            self.last_candidate_page_ids = tuple(
                str(candidate.get("page_id") or candidate.get("sid") or "")
                for candidate in selected)
            self.last_candidate_reason = str(
                parsed.get("reason") or "")[:200]
            proposed_name = " ".join(str(
                parsed.get("proposed_new_page_name") or "").split())[:120]
            if not proposed_name:
                raise ValueError("missing proposed_new_page_name")
            self.last_proposed_new_page_name = proposed_name
            self.last_selection_status = "selected"
        except Exception as exc:
            logger.warning(
                "page candidate selection failed: %s; response=%r",
                exc, str(response or "")[:500])
            # A failed selector cannot prove that the current screenshot is a
            # new Page. If the reply still supplied a valid fallback name and
            # there are at most two registered Pages, pairwise comparison can
            # exhaust the entire Page set without trusting the invalid
            # shortlist. Otherwise confirm only the first ordered Page and
            # keep a negative result unresolved.
            selection_failed = True
            fallback_parsed = _parse_json(response)
            proposed_name = " ".join(str(
                (fallback_parsed or {}).get("proposed_new_page_name") or ""
            ).split())[:120] if isinstance(fallback_parsed, dict) else ""
            if proposed_name:
                self.last_proposed_new_page_name = proposed_name
            self.last_candidate_reason = str(
                (fallback_parsed or {}).get("reason") or
                "candidate selection failed"
            )[:200] if isinstance(fallback_parsed, dict) else (
                "candidate selection failed")
            selection_exhaustive = bool(
                proposed_name and len(candidates) <= 2)
            selected = (
                list(candidates) if selection_exhaustive
                else [candidates[0]]
            )
            self.last_selection_status = (
                "fallback_exhaustive"
                if selection_exhaustive else "fallback")

        missing_evidence = False
        valid_comparisons = 0
        selection_reason = self.last_candidate_reason
        for candidate in selected:
            sid = str(candidate.get("sid") or "")
            path = str(candidate.get("screenshot_path") or "")
            if not sid or not path:
                missing_evidence = True
                continue
            try:
                with open(path, "rb") as stream:
                    candidate_bytes = stream.read()
            except OSError:
                missing_evidence = True
                continue
            relationship = self.compare_relationship(
                candidate_bytes, current_bytes)
            if relationship is None:
                return "UNRESOLVED"
            valid_comparisons += 1
            state_ids = tuple(str(value) for value in (
                candidate.get("state_ids") or [sid]) if str(value))
            if relationship == "same_page":
                self.last_choice = sid
                self.last_matched_candidate_state_ids = state_ids
                return sid

        if selection_failed and not (
            selection_exhaustive
            and not missing_evidence
            and valid_comparisons == len(candidates)
        ):
            self.last_reason = (
                self.last_reason or "candidate selection failed closed")
            return "UNRESOLVED"
        if missing_evidence or not valid_comparisons:
            self.last_reason = "selected candidate screenshots unavailable"
            return "UNRESOLVED"
        self.last_choice = "NEW"
        self.last_reason = (
            selection_reason or "selected Page screenshots differ")
        return "NEW"

    def choose_return(self, source_bytes: bytes, current_bytes: bytes, *,
                      source_name: str, target_name: str,
                      transition: str,
                      platform: str = "desktop") -> Dict[str, object]:
        """Choose one visible click or platform return action, or abstain."""
        abstain = {"action": None, "target": "", "reason": ""}
        if self.agent is None or not source_bytes or not current_bytes:
            return {**abstain, "reason": "return decision unavailable"}
        prompt = build_return_path_prompt(
            source_name, target_name, transition, platform=platform)
        try:
            from ..visual_cache import predict_mm_role
            resp, *_ = predict_mm_role(
                self.agent, "return_path", prompt,
                [_img_arr(source_bytes), _img_arr(current_bytes)], self.ledger)
        except Exception as exc:
            logger.warning("return-path judge failed: %s", exc)
            return {**abstain, "reason": f"judge failed: {exc}"[:200]}
        parsed = _parse_json(resp)
        if not isinstance(parsed, dict):
            return {**abstain, "reason": "invalid judge response"}
        raw_action = parsed.get("action")
        reason = str(parsed.get("reason") or "")[:200]
        if raw_action is None:
            return {**abstain, "reason": reason or "no reliable action"}
        if not isinstance(raw_action, dict):
            return {**abstain, "reason": reason or "invalid return action"}
        raw_action = dict(raw_action)
        action_type = str(raw_action.get("action_type") or "").strip()
        if action_type.upper() == "CLICK":
            target = str(raw_action.get("target") or "").strip()
            if not target:
                return {**abstain,
                        "reason": reason or "visible click lacks target"}
            return {
                "action": {"action_type": (
                    "click" if is_android(platform) else "CLICK")},
                "target": target,
                "reason": reason,
            }
        action, _error = normalize_native_action(
            raw_action, platform=platform)
        normalized_type = str((action or {}).get("action_type") or "")
        if is_android(platform):
            valid_platform_action = normalized_type == "navigate_back"
        else:
            params = (action or {}).get("parameters")
            valid_platform_action = (
                normalized_type == "PRESS"
                and isinstance(params, dict)
                and str(params.get("key") or "").strip().casefold() == "esc"
            )
        if not valid_platform_action:
            return {**abstain,
                    "reason": reason or "invalid platform return action"}
        return {"action": action, "target": "", "reason": reason}


class BlockIdentityJudge:
    """Text alignment of the recorded region tables of two known interfaces."""

    def __init__(self, agent, ledger=None):
        self.agent = agent
        self.ledger = ledger
        self.last_raw_response = ""

    def align_regions(self, interface_a: str, regions_a,
                      interface_b: str, regions_b) -> Optional[Dict[str, Any]]:
        """Return a validated request-local correspondence between two tables."""
        self.last_raw_response = ""
        if self.agent is None or not regions_a or not regions_b:
            return None
        prompt = build_region_correspondence_prompt(
            interface_a, regions_a, interface_b, regions_b)
        try:
            from ..visual_cache import predict_mm_role
            response, *_ = predict_mm_role(
                self.agent, "region_identity", prompt, [],
                self.ledger, max_attempts=1)
        except Exception as exc:
            logger.warning("region correspondence failed: %s", exc)
            return None
        self.last_raw_response = str(response or "")
        parsed = _parse_json(response)
        if not isinstance(parsed, dict):
            return None
        a_labels = {str(row.get("region") or "") for row in regions_a}
        b_labels = {str(row.get("region") or "") for row in regions_b}
        pairs = parsed.get("same_regions")
        final_a = parsed.get("interface_a_final_regions")
        final_b = parsed.get("interface_b_final_regions")
        if not isinstance(pairs, list) or not isinstance(final_a, list) \
                or not isinstance(final_b, list):
            return None
        used_a, used_b, shared = set(), set(), set()
        clean_pairs = []
        for row in pairs:
            if not isinstance(row, dict):
                return None
            shared_label = str(row.get("same_region") or "")
            a_label = str(row.get("interface_a_region") or "")
            b_label = str(row.get("interface_b_region") or "")
            if (not shared_label.startswith("S") or shared_label in shared
                    or a_label not in a_labels or b_label not in b_labels
                    or a_label in used_a or b_label in used_b):
                return None
            shared.add(shared_label)
            used_a.add(a_label)
            used_b.add(b_label)
            clean_pairs.append({
                "same_region": shared_label,
                "interface_a_region": a_label,
                "interface_b_region": b_label,
            })
        expected_a = (a_labels - used_a) | shared
        expected_b = (b_labels - used_b) | shared
        if (len(final_a) != len(set(map(str, final_a)))
                or len(final_b) != len(set(map(str, final_b)))
                or set(map(str, final_a)) != expected_a
                or set(map(str, final_b)) != expected_b):
            return None
        return {
            "same_regions": clean_pairs,
            "interface_a_final_regions": list(map(str, final_a)),
            "interface_b_final_regions": list(map(str, final_b)),
        }

    def align_region_partitions(
        self, interface_a: str, regions_a, interface_b: str, regions_b,
        screenshots=None, triggering_action: str = "",
    ) -> Optional[Dict[str, Any]]:
        """Return a validated set-to-set mapping for one fresh PageMap."""
        self.last_raw_response = ""
        if self.agent is None or not regions_b:
            return None
        screenshot_bytes = list(screenshots or [])
        images = []
        if len(screenshot_bytes) == 2 and all(screenshot_bytes):
            images = [_img_arr(value) for value in screenshot_bytes]
        prompt = build_region_partition_mapping_prompt(
            interface_a, regions_a, interface_b, regions_b,
            has_screenshots=bool(images),
            triggering_action=triggering_action)
        try:
            from ..visual_cache import predict_mm_role
            response, *_ = predict_mm_role(
                self.agent, "region_partition_mapping", prompt, images,
                self.ledger, max_attempts=1)
        except Exception as exc:
            logger.warning("region partition mapping failed: %s", exc)
            return None
        self.last_raw_response = str(response or "")
        parsed = _parse_json(response)
        if not isinstance(parsed, dict):
            return None
        a_labels = {str(row.get("region") or "") for row in regions_a}
        b_labels = {str(row.get("region") or "") for row in regions_b}
        matches = parsed.get("matches")
        new_current = parsed.get("new_current_region_ids")
        unresolved = parsed.get("unresolved_current_region_ids")
        if not isinstance(matches, list) or not isinstance(new_current, list) \
                or not isinstance(unresolved, list):
            return None
        used_a, used_b = set(), set()
        clean_matches = []
        for row in matches:
            if not isinstance(row, dict):
                return None
            known = [
                str(value) for value in row.get("known_region_ids") or []]
            current = [
                str(value) for value in row.get("current_region_ids") or []]
            if (not known or not current or len(known) != len(set(known))
                    or len(current) != len(set(current))
                    or not set(known) <= a_labels
                    or not set(current) <= b_labels
                    or used_a.intersection(known)
                    or used_b.intersection(current)):
                return None
            used_a.update(known)
            used_b.update(current)
            clean_matches.append({
                "known_region_ids": known,
                "current_region_ids": current,
                "reason": str(row.get("reason") or "")[:240],
            })
        clean_new = [str(value) for value in new_current]
        clean_unresolved = [str(value) for value in unresolved]
        if (len(clean_new) != len(set(clean_new))
                or len(clean_unresolved) != len(set(clean_unresolved))
                or set(clean_new).intersection(clean_unresolved)
                or used_b.intersection(clean_new)
                or used_b.intersection(clean_unresolved)
                or used_b | set(clean_new) | set(clean_unresolved) != b_labels):
            return None
        return {
            "matches": clean_matches,
            "new_current_region_ids": clean_new,
            "unresolved_current_region_ids": clean_unresolved,
            "unmatched_known_region_ids": sorted(a_labels - used_a),
        }

# ── App-focus guard ───────────────────────────────────────────────────────

# 通用 app-focus：只问"是否还在目标应用内",**不描述任何系统类型**(安卓/Linux)。系统是
# 固定的(一个 VM 一个系统、不会中途变)、跟"在不在 app 内"无关;之前分两套 + is_touch 选择,
# docker 桌面被 is_touch 判成 True → 套了安卓版"这是安卓手机截图"→ VLM 顺着把 Ubuntu 桌面
# 说成"安卓桌面"→ 误 OFF-APP。一套通用 prompt 通吃桌面/移动,不给 VLM 错的系统前提。
