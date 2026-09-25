"""Conservative engine-independent recognition of post-click revisit frames."""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional, Tuple


def _norm(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())




def _template(element: Any):
    if isinstance(element, dict):
        return element.get("_template") or element.get("template")
    return getattr(element, "_template", None)


def candidate_payloads(candidate_ids: Iterable[str], registry,
                       descriptor_fn: Callable[[str], Optional[Dict[str, Any]]],
                       *, page_name: str = "",
                       limit: Optional[int] = None) -> List[Dict[str, Any]]:
    """Build one text description and screenshot reference per known variant."""
    payloads = []
    candidate_ids = list(dict.fromkeys(str(item) for item in candidate_ids))
    # Several execution states may already belong to one stable operable
    # variant. Show one representative screenshot for that identity; the VLM
    # still decides between distinct variants.
    variant_id_of = getattr(registry, "variant_id_of", None)
    deduped_ids = []
    seen_identities = set()
    for sid in candidate_ids:
        variant_id = str(variant_id_of(sid) or "") \
            if callable(variant_id_of) else ""
        identity = ("variant", variant_id) if variant_id else ("state", sid)
        if identity in seen_identities:
            continue
        seen_identities.add(identity)
        deduped_ids.append(sid)
    candidate_ids = deduped_ids
    if limit is not None:
        candidate_ids = candidate_ids[:max(0, int(limit))]
    for sid in candidate_ids:
        descriptor = descriptor_fn(sid) or {}
        if not descriptor:
            continue
        known_path = getattr(registry, "known_path", None)
        screenshot_path = known_path(sid) if callable(known_path) else None
        payloads.append({
            "sid": sid,
            "descriptor": descriptor,
            "screenshot_path": str(screenshot_path or ""),
        })
    return payloads


def page_candidate_payloads(
    candidate_ids: Iterable[str],
    registry,
    descriptor_fn: Callable[[str], Optional[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Build one description and representative screenshot per stable Page."""
    groups: Dict[str, List[str]] = {}
    page_id_of = getattr(registry, "page_id_of", None)
    for state_id in dict.fromkeys(str(item) for item in candidate_ids):
        page_id = str(page_id_of(state_id) or "") \
            if callable(page_id_of) else ""
        groups.setdefault(page_id or state_id, []).append(state_id)

    result = []
    known_path = getattr(registry, "known_path", None)
    for page_id, state_ids in groups.items():
        options = []
        for state_id in state_ids:
            descriptor = descriptor_fn(state_id) or {}
            if not descriptor:
                continue
            screenshot_path = (
                known_path(state_id) if callable(known_path) else None)
            payload = {
                "page_id": page_id,
                "state_ids": list(state_ids),
                "sid": state_id,
                "descriptor": descriptor,
                "screenshot_path": str(screenshot_path or ""),
            }
            options.append(payload)
        if options:
            result.append(max(
                options,
                key=lambda item: (
                    bool(item["screenshot_path"]),
                    len((item["descriptor"] or {}).get("regions") or []),
                ),
            ))
    return result


def confirm_arrival(state_data: Dict[str, Dict[str, Any]], registry, reloc,
                    candidate_ids: Iterable[str], shot: bytes, judge,
                    descriptor_fn: Callable[[str], Optional[Dict[str, Any]]],
                    transition=None, current_observation=None, *,
                    fallback_candidate_ids: Optional[Iterable[str]] = None
                    ) -> Tuple[Optional[str], str]:
    """Judge every local candidate, then expand to all supplied pages on NEW."""
    candidate_ids = list(dict.fromkeys(
        str(item) for item in candidate_ids))
    fallback_ids = list(dict.fromkeys(
        [*candidate_ids, *(str(item) for item in
                           (fallback_candidate_ids or []))]))
    if not candidate_ids:
        candidate_ids = list(fallback_ids)
    if not shot or not candidate_ids:
        return None, "no-decision:empty candidate set or screenshot"

    page_name = str((current_observation or {}).get("page") or "")
    payloads = candidate_payloads(
        candidate_ids, registry, descriptor_fn, page_name=page_name)
    if not payloads and fallback_ids == candidate_ids:
        return None, "vlm:NEW:no candidate evidence"
    try:
        choice = judge.which_page(
            shot, payloads, transition=transition,
            current_observation=current_observation)
    except TypeError as exc:
        if "current_observation" not in str(exc):
            raise
        choice = judge.which_page(shot, payloads, transition=transition)
    reason = str(getattr(judge, "last_reason", "") or "")
    if choice in {item["sid"] for item in payloads}:
        return choice, f"vlm:{choice}:{reason}"

    if fallback_ids != candidate_ids:
        expanded = candidate_payloads(
            fallback_ids, registry, descriptor_fn, page_name=page_name)
        if ([item["sid"] for item in expanded]
                == [item["sid"] for item in payloads]):
            return None, f"vlm:NEW:{reason or 'no distinct global candidate'}"
        try:
            choice = judge.which_page(
                shot, expanded, transition=transition,
                current_observation=current_observation)
        except TypeError as exc:
            if "current_observation" not in str(exc):
                raise
            choice = judge.which_page(shot, expanded, transition=transition)
        reason = str(getattr(judge, "last_reason", "") or "")
        if choice in {item["sid"] for item in expanded}:
            return choice, f"global-vlm:{choice}:{reason}"
        return None, f"vlm:NEW:all-pages:{reason}"
    return None, f"vlm:NEW:{reason or 'invalid candidate choice'}"


__all__ = [
    "candidate_payloads",
    "confirm_arrival",
    "page_candidate_payloads",
]
