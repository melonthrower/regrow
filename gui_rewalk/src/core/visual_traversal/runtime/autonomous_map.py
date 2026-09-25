"""Framework-owned natural Page/Variant map for Qwen exploration."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
import json
import os
from typing import Any, Dict, List, Mapping, Optional, Sequence

MAP_TOOL_NAMES = {
    "page_identity", "report_record_error", "finish_exploration",
}


@dataclass
class ToolEvidence:
    status: str
    data: Dict[str, Any]
    image_labels: List[str] = field(default_factory=list)
    images: List[bytes] = field(default_factory=list)


def _key(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


class NaturalExplorationMap:
    """Agent-authored semantic memory; stable framework graph IDs stay private."""

    def __init__(self) -> None:
        self.pages: Dict[str, Dict[str, Any]] = {}
        self.connections: List[Dict[str, Any]] = []
        self.record_errors: List[Dict[str, str]] = []
        self.current_page = ""
        self.current_variant = ""
        self._variant_images: Dict[tuple[str, str], bytes] = {}

    def _find_name(self, name: str) -> str:
        wanted = _key(name)
        for page_name in self.pages:
            if _key(page_name) == wanted:
                return page_name
        return ""

    def observe(
        self,
        *,
        name: str,
        summary: str,
        identity: str,
        matched_page_name: str,
        surface_kind: str,
        regions: Sequence[Dict[str, Any]],
        screenshot: bytes,
        variant_name: str = "",
        variant_identity: str = "",
        visible_predicates: Sequence[str] = (),
        commit_regions: bool = True,
    ) -> tuple[str, str]:
        canonical = ""
        issue = ""
        if identity == "known":
            canonical = self._find_name(matched_page_name)
            if not canonical:
                self.current_page = ""
                self.current_variant = ""
                return str(name or "未确认页面").strip(), (
                    f"known page is not registered: {matched_page_name}")
        elif identity == "new":
            if self._find_name(name):
                self.current_page = ""
                self.current_variant = ""
                return str(name or "未确认页面").strip(), (
                    "new page reuses an existing natural name; rename it or "
                    "mark it known")
            canonical = str(name).strip()
        elif identity == "uncertain":
            self.current_page = ""
            self.current_variant = ""
            return str(name or "未确认页面").strip(), (
                "page identity remains uncertain; compare before registration")
        if not canonical:
            canonical = str(name or "未确认页面").strip()

        existing_page = self.pages.get(canonical)
        requested_variant = str(variant_name or "default").strip()[:160]
        resolved_variant_identity = str(
            variant_identity or "").strip().casefold()
        if not resolved_variant_identity:
            resolved_variant_identity = (
                "new" if existing_page is None else "known")
        existing_variants = (
            (existing_page or {}).get("variants") or {}
        )
        matched_variant = next((
            item for item in existing_variants
            if _key(item) == _key(requested_variant)
        ), "")
        if resolved_variant_identity == "known" and not matched_variant:
            self.current_page = ""
            self.current_variant = ""
            return canonical, (
                f"known variant is not registered on {canonical}: "
                f"{requested_variant}")
        if resolved_variant_identity == "new" and matched_variant:
            self.current_page = ""
            self.current_variant = ""
            return canonical, (
                "new variant reuses an existing natural name; rename it or "
                "mark it known")
        if resolved_variant_identity not in {"known", "new"}:
            self.current_page = ""
            self.current_variant = ""
            return canonical, (
                "variant identity remains uncertain; compare before registration")
        if identity == "new" and resolved_variant_identity != "new":
            self.current_page = ""
            self.current_variant = ""
            return canonical, "a new Page requires a new initial Variant"

        page = self.pages.setdefault(canonical, {
            "name": canonical,
            "internal_page_id": f"auto_page_{len(self.pages) + 1}",
            "summary": "",
            "surface_kind": "other",
            "identity_status": identity,
            "variants": {},
            "regions": {},
            "unreachable_evidence": [],
        })
        page.setdefault("internal_page_id", f"auto_page_{len(self.pages)}")
        page.setdefault("variants", {})
        page["summary"] = str(summary or page["summary"]).strip()[:500]
        page["surface_kind"] = str(surface_kind or "other").strip()
        page["identity_status"] = identity
        canonical_variant = matched_variant or requested_variant
        variant = page["variants"].setdefault(canonical_variant, {
            "name": canonical_variant,
            "internal_variant_id": (
                f"auto_variant_{page['internal_page_id']}_"
                f"{len(page['variants']) + 1}"
            ),
            "visible_predicates": [],
        })
        predicates = []
        for raw_predicate in visible_predicates:
            predicate = str(raw_predicate or "").strip()[:240]
            if predicate and predicate not in predicates:
                predicates.append(predicate)
        if predicates:
            variant["visible_predicates"] = predicates
        for raw_region in regions if commit_regions else ():
            region_name = str(raw_region.get("name") or "").strip()
            if not region_name:
                continue
            existing_name = next((item for item in page["regions"]
                                  if _key(item) == _key(region_name)), region_name)
            region = page["regions"].setdefault(existing_name, {
                "name": existing_name, "summary": "", "controls": [],
            })
            region["summary"] = str(
                raw_region.get("summary") or region["summary"]).strip()[:500]
            for control in raw_region.get("controls") or []:
                control_name = str(control or "").strip()[:160]
                if control_name and not any(
                        _key(item) == _key(control_name)
                        for item in region["controls"]):
                    region["controls"].append(control_name)
        self.current_page = canonical
        self.current_variant = canonical_variant
        if screenshot:
            self._variant_images.setdefault(
                (canonical, canonical_variant), screenshot)
        return canonical, issue

    def connect(self, source: str, target: str, action: str, control: str) -> None:
        if not source or not target:
            return
        record = {
            "from": source,
            "via": control or action,
            "action": action,
            "to": target,
            "provenance": "observed",
        }
        existing = next((edge for edge in self.connections if all(
            edge.get(key) == record.get(key)
            for key in ("from", "via", "action", "to")
        )), None)
        if existing is None:
            self.connections.append(record)
        else:
            existing["provenance"] = "observed"

    def connect_inferred(
        self,
        source: str,
        target: str,
        control: str,
        *,
        entry_id: str,
        equivalent_to_entry_id: str,
        reason: str,
    ) -> None:
        """Persist only an Agent-declared equivalence relation as an infer edge."""
        if not source or not target:
            return
        if any(
            edge.get("from") == source
            and edge.get("to") == target
            and edge.get("via") == control
            for edge in self.connections
        ):
            return
        self.connections.append({
            "from": source,
            "via": control,
            "action": "CLICK",
            "to": target,
            "provenance": "agent_inferred_equivalence",
            "entry_id": entry_id,
            "equivalent_to_entry_id": equivalent_to_entry_id,
            "reason": str(reason or "")[:500],
        })

    def upsert_regions(
        self, page_name: str, regions: Sequence[Dict[str, Any]],
    ) -> List[str]:
        """Apply accepted Region deltas without replacing unrelated memory."""
        page = self._page(page_name)
        if page is None:
            return []
        updated: List[str] = []
        for raw_region in regions:
            region_name = str(
                raw_region.get("name") or raw_region.get("region_name") or ""
            ).strip()
            if not region_name:
                continue
            existing_name = next((
                item for item in page["regions"]
                if _key(item) == _key(region_name)
            ), region_name)
            region = page["regions"].setdefault(existing_name, {
                "name": existing_name,
                "summary": "",
                "controls": [],
                "scrollable": None,
                "observation_status": "partial",
            })
            region["summary"] = str(
                raw_region.get("summary") or region.get("summary") or ""
            ).strip()[:500]
            if raw_region.get("scrollable") is not None:
                region["scrollable"] = bool(raw_region["scrollable"])
            region["observation_status"] = "partial"
            known = {_key(item) for item in region.get("controls") or []}
            for raw_control in raw_region.get("controls") or []:
                control = str(raw_control or "").strip()[:160]
                if control and _key(control) not in known:
                    known.add(_key(control))
                    region.setdefault("controls", []).append(control)
            updated.append(region["name"])
        return updated

    def prompt_view(self) -> Dict[str, Any]:
        return {
            "current_page": self.current_page,
            "current_variant": self.current_variant,
            "pages": [{
                "name": page["name"],
                "summary": page["summary"],
                "surface_kind": page["surface_kind"],
                "identity_status": page["identity_status"],
                "variants": [{
                    "name": variant["name"],
                    "visible_predicates": list(
                        variant.get("visible_predicates") or []),
                } for variant in page.get("variants", {}).values()],
            } for page in self.pages.values()],
            "connections": list(self.connections),
            "record_errors": list(self.record_errors[-20:]),
        }

    def canonical_page_name(self, requested: str) -> str:
        """Return the registered natural page name, or an empty string."""
        return self._find_name(requested)

    def representative_screenshot(
        self, requested: str, variant_name: str,
    ) -> bytes:
        """Return the stored full screenshot for an exact Page Variant."""
        page_name = self._find_name(requested)
        canonical_variant = self.canonical_variant_name(
            page_name, variant_name)
        if not page_name or not canonical_variant:
            return b""
        return self._variant_images.get(
            (page_name, canonical_variant), b"")

    def unique_variant_owner(self, requested: str) -> str:
        """Return one Page owning this Variant name, or empty if ambiguous."""
        wanted = _key(requested)
        if not wanted:
            return ""
        owners = [
            page_name for page_name, page in self.pages.items()
            if any(
                _key(variant_name) == wanted
                for variant_name in (page.get("variants") or {})
            )
        ]
        return owners[0] if len(owners) == 1 else ""

    def neighboring_connections(self, requested: str) -> List[Dict[str, str]]:
        """Return the small local graph around one registered page."""
        page_name = self._find_name(requested)
        if not page_name:
            return []
        return [
            dict(edge) for edge in self.connections
            if edge.get("from") == page_name or edge.get("to") == page_name
        ]

    def record_unreachable_evidence(
        self, records: Sequence[Dict[str, Any]],
    ) -> List[str]:
        """Attach model-provided debug evidence to its declared page owner."""
        issues: List[str] = []
        for raw in records:
            page_name = self._find_name(str(raw.get("page_name") or ""))
            if not page_name:
                issues.append(
                    "unreachable evidence references an unregistered page: "
                    f"{str(raw.get('page_name') or '<empty>')[:160]}"
                )
                continue
            record = {
                "page_name": page_name,
                "entry_id": str(raw.get("entry_id") or "").strip()[:80],
                "subject": str(raw.get("subject") or "").strip()[:200],
                "evidence": str(raw.get("evidence") or "").strip()[:500],
            }
            page = self.pages[page_name]
            stored = page.setdefault("unreachable_evidence", [])
            if record not in stored:
                stored.append(record)
        return issues

    def serializable(self) -> Dict[str, Any]:
        return {
            "schema": "gui_rewalk.autonomous_natural_map.v2",
            **self.prompt_view(),
            "page_details": [{
                **{
                    key: value for key, value in page.items()
                    if key not in {"regions", "variants"}
                },
                "variants": list(page.get("variants", {}).values()),
                "regions": list(page["regions"].values()),
            } for page in self.pages.values()],
        }

    @classmethod
    def from_output(
        cls,
        output_root: str,
        graph: Any = None,
    ) -> "NaturalExplorationMap":
        restored = cls()
        path = os.path.join(output_root, "autonomous_natural_map.json")
        payload: Dict[str, Any] = {}
        if os.path.isfile(path):
            with open(path, "r", encoding="utf-8") as stream:
                loaded = json.load(stream)
            if isinstance(loaded, dict):
                payload = loaded
        details = payload.get("page_details") or []
        for raw in details:
            if not isinstance(raw, Mapping):
                continue
            name = str(raw.get("name") or "").strip()
            if not name:
                continue
            page = {
                key: value for key, value in raw.items()
                if key not in {"regions", "variants"}
            }
            page.setdefault("internal_page_id", f"auto_page_{len(restored.pages) + 1}")
            page.setdefault("summary", "")
            page.setdefault("surface_kind", "other")
            page.setdefault("identity_status", "known")
            page.setdefault("unreachable_evidence", [])
            page["variants"] = {}
            raw_variants = raw.get("variants") or []
            if isinstance(raw_variants, Mapping):
                raw_variants = raw_variants.values()
            for variant_raw in raw_variants:
                if not isinstance(variant_raw, Mapping):
                    continue
                variant_name = str(variant_raw.get("name") or "").strip()
                if not variant_name:
                    continue
                variant = dict(variant_raw)
                variant.pop("identity_status", None)
                variant.setdefault(
                    "internal_variant_id",
                    f"auto_variant_{page['internal_page_id']}_"
                    f"{len(page['variants']) + 1}",
                )
                variant.setdefault("visible_predicates", [])
                page["variants"][variant_name] = variant
            page["regions"] = {}
            for region_raw in raw.get("regions") or []:
                if not isinstance(region_raw, Mapping):
                    continue
                region_name = str(region_raw.get("name") or "").strip()
                if region_name:
                    page["regions"][region_name] = dict(region_raw)
            restored.pages[name] = page
        if graph is not None:
            for _state_id, node in graph.graph.nodes(data=True):
                name = str(node.get("page_name") or "").strip()
                if not name:
                    continue
                page = restored.pages.setdefault(name, {
                    "name": name,
                    "internal_page_id": str(
                        node.get("page_id") or f"auto_page_{len(restored.pages) + 1}"),
                    "summary": str(
                        (node.get("observed_facts") or {}).get("summary") or ""),
                    "surface_kind": "other",
                    "identity_status": "known",
                    "variants": {},
                    "regions": {},
                    "unreachable_evidence": [],
                })
                page.setdefault("variants", {})
                facts = node.get("observed_facts") or {}
                internal_variant_id = str(
                    node.get("variant_id") or _state_id)
                known_variant = next((
                    item for item, variant in page["variants"].items()
                    if str(variant.get("internal_variant_id") or "")
                    == internal_variant_id
                ), "")
                variant_name = str(
                    facts.get("variant_name") or known_variant or "default"
                ).strip()
                if variant_name not in page["variants"]:
                    page["variants"][variant_name] = {
                        "name": variant_name,
                        "internal_variant_id": internal_variant_id,
                        "visible_predicates": list(
                            facts.get("visible_predicates") or []),
                    }
        restored.connections = [
            dict(item) for item in payload.get("connections") or []
            if isinstance(item, Mapping)
        ]
        restored.record_errors = [
            dict(item) for item in payload.get("record_errors") or []
            if isinstance(item, Mapping)
        ]
        restored.current_page = ""
        restored.current_variant = ""
        if graph is not None:
            for _state_id, node in graph.graph.nodes(data=True):
                name = str(node.get("page_name") or "").strip()
                screenshot_path = str(
                    node.get("screenshot_path") or "").strip()
                if not name or not screenshot_path:
                    continue
                candidate = (
                    screenshot_path if os.path.isabs(screenshot_path)
                    else os.path.join(output_root, screenshot_path)
                )
                if os.path.isfile(candidate):
                    with open(candidate, "rb") as stream:
                        screenshot = stream.read()
                    internal_variant_id = str(
                        node.get("variant_id") or _state_id)
                    page = restored.pages.get(name) or {}
                    variant_name = next((
                        item for item, variant
                        in (page.get("variants") or {}).items()
                        if str(variant.get("internal_variant_id") or "")
                        == internal_variant_id
                    ), "")
                    if variant_name:
                        restored._variant_images.setdefault(
                            (name, variant_name), screenshot)
        return restored

    def _page(self, requested: str) -> Dict[str, Any] | None:
        name = self._find_name(requested)
        return self.pages.get(name) if name else None

    def page_id(self, requested: str) -> str:
        page = self._page(requested)
        return str((page or {}).get("internal_page_id") or "")

    def canonical_variant_name(
        self, page_name: str, requested: str,
    ) -> str:
        page = self._page(page_name)
        if page is None:
            return ""
        wanted = _key(requested)
        return next((
            name for name in (page.get("variants") or {})
            if _key(name) == wanted
        ), "")

    def variant_id(self, page_name: str, requested: str) -> str:
        page = self._page(page_name)
        if page is None:
            return ""
        canonical = self.canonical_variant_name(page_name, requested)
        if not canonical:
            return ""
        return str(
            ((page.get("variants") or {}).get(canonical) or {}).get(
                "internal_variant_id"
            ) or ""
        )

    def variant_facts(
        self, page_name: str, requested: str,
    ) -> Dict[str, Any]:
        page = self._page(page_name)
        if page is None:
            return {}
        canonical = self.canonical_variant_name(page_name, requested)
        if not canonical:
            return {}
        return dict((page.get("variants") or {}).get(canonical) or {})

    def _route(
        self, target_name: str, *, source_name: str = "",
    ) -> List[Dict[str, str]]:
        target = self._find_name(target_name)
        source = self._find_name(source_name or self.current_page)
        if not source or not target:
            return []
        queue = deque([(source, [])])
        visited = {source}
        while queue:
            page, path = queue.popleft()
            if page == target:
                return path
            for edge in self.connections:
                if edge["from"] != page or edge["to"] in visited:
                    continue
                visited.add(edge["to"])
                queue.append((edge["to"], path + [edge]))
        return []

    def route_hint(self, target_name: str) -> List[Dict[str, str]]:
        """Return a compact advisory route from the currently bound page."""
        return [dict(step) for step in self._route(target_name)]

    def call_tool(
        self,
        name: str,
        arguments: Dict[str, Any],
        current_screenshot: bytes,
        *,
        page_identity_resolver: Any = None,
        identity_feedback: Optional[Dict[str, str]] = None,
        page_identity_context: Optional[Dict[str, Any]] = None,
    ) -> ToolEvidence:
        if name == "report_record_error":
            record = {
                "kind": str(arguments["kind"]).strip(),
                "subject": str(arguments["subject"]).strip()[:200],
                "observed_problem": str(
                    arguments["observed_problem"]).strip()[:500],
                "problem_type": str(
                    arguments.get("problem_type") or "semantic_mismatch"
                ).strip()[:80],
                "proposed_correction": str(
                    arguments.get("proposed_correction") or "").strip()[:500],
            }
            record["feedback"] = (
                f"账本未修改：{record['subject']} 的 {record['kind']} 争议已进入调试记录；"
                "继续决策时仍以当前账本为准。"
            )
            self.record_errors.append(record)
            return ToolEvidence("reported", dict(record))
        if name == "page_identity":
            return self._page_identity(
                arguments,
                current_screenshot,
                resolver=page_identity_resolver,
                identity_feedback=identity_feedback,
                arrival_context=page_identity_context,
            )
        return ToolEvidence(
            "unknown_tool", {
                "known_tools": sorted(MAP_TOOL_NAMES),
            })

    def _page_identity(
        self,
        arguments: Dict[str, Any],
        current_screenshot: bytes,
        *,
        resolver: Any,
        identity_feedback: Optional[Dict[str, str]],
        arrival_context: Optional[Dict[str, Any]],
    ) -> ToolEvidence:
        suspected = arguments.get("suspected_pages")
        proposed_name = str(arguments.get("proposed_new_name") or "").strip()
        reason = str(arguments.get("reason") or "").strip()
        context = dict(arrival_context or {})
        identity_stage = str(
            context.get("identity_stage") or "combined"
        ).strip().casefold()
        if identity_stage not in {"page", "variant"}:
            identity_stage = "combined"
        selected_page = context.get("selected_page")
        if not isinstance(selected_page, dict):
            selected_page = {}
        selected_page_name = str(
            selected_page.get("page_name")
            or selected_page.get("name")
            or ""
        ).strip()
        selected_page_identity = str(
            selected_page.get("identity") or ""
        ).strip().casefold()
        if not isinstance(suspected, list) or not all(
                isinstance(item, str) for item in suspected):
            return ToolEvidence("invalid_arguments", {
                "reason": "suspected_pages must be an array of page names",
            })
        requested_names: List[str] = []
        for raw_name in suspected:
            canonical = self._find_name(raw_name)
            if canonical and canonical not in requested_names:
                requested_names.append(canonical)
        if not requested_names:
            requested_names = list(self.pages)
        if identity_stage == "variant":
            canonical_selected = self._find_name(selected_page_name)
            requested_names = (
                [canonical_selected]
                if selected_page_identity == "known" and canonical_selected
                else []
            )
        candidates = []
        for page_name in requested_names:
            page = self.pages[page_name]
            candidate = {
                "page_name": page_name,
                "summary": page["summary"],
                "surface_kind": page["surface_kind"],
                "regions": [{
                    "name": region["name"],
                    "summary": region["summary"],
                } for region in page["regions"].values()],
            }
            if identity_stage == "page":
                candidate["representative_screenshot"] = next((
                    self._variant_images.get((page_name, variant_name), b"")
                    for variant_name in (page.get("variants") or {})
                    if self._variant_images.get(
                        (page_name, variant_name), b"")
                ), b"")
            else:
                candidate["variants"] = [{
                    "variant_name": variant_name,
                    "visible_predicates": list(
                        variant.get("visible_predicates") or []),
                    "representative_screenshot": self._variant_images.get(
                        (page_name, variant_name), b""),
                } for variant_name, variant
                in (page.get("variants") or {}).items()]
            candidates.append(candidate)
        request = {
            "current_screenshot": current_screenshot,
            "suspected_pages": list(suspected),
            "proposed_new_name": proposed_name,
            "reason": reason,
            "registered_pages": candidates,
            "registered_page_count": len(self.pages),
            "arrival_context": {
                key: value for key, value in context.items()
                if key not in {
                    "source_screenshot", "identity_stage", "selected_page",
                }
            },
            "source_screenshot": (
                context.get("source_screenshot") or b""),
            "previous_tool_feedback": dict(identity_feedback or {}),
            "identity_stage": identity_stage,
            "selected_page": dict(selected_page),
        }
        if not callable(resolver):
            raw_result: Any = {
                "status": "uncertain",
                "summary": "Page identity was not evaluated.",
                "surface_kind": "other",
                "supporting_evidence": [],
                "conflicting_evidence": [],
                "checked_candidates": requested_names,
                "reason": (
                    "page identity resolver is not configured; no model was called"
                ),
            }
        else:
            try:
                raw_result = resolver(request)
            except Exception as exc:
                raw_result = {
                    "status": "uncertain",
                    "reason": (
                        "独立 Page Identity specialist 本轮没有返回可用判断；"
                        "当前页面身份保持未决，页面账本没有改变。"
                    ),
                }
        if not isinstance(raw_result, dict):
            raw_result = {
                "status": "uncertain",
                "reason": (
                    "独立 Page Identity specialist 本轮没有给出完整的页面身份判断。"),
            }
        if not str(raw_result.get("reason") or "").strip():
            raw_result = {
                **raw_result,
                "status": "uncertain",
                "matched_page_name": "",
                "page_name": "",
                "reason": (
                    "独立 Page Identity specialist 没有说明判断依据，页面身份保持未决。"),
            }
        if identity_stage == "variant":
            page_identity_status = selected_page_identity
            matched_name = selected_page_name
            status = str(
                raw_result.get("variant_identity")
                or raw_result.get("status")
                or ""
            ).strip().casefold()
            variant_identity = status
            variant_name = str(
                raw_result.get("variant_name") or "").strip()[:160]
            if (
                page_identity_status not in {"known", "new"}
                or not matched_name
            ):
                status = variant_identity = "uncertain"
                raw_result = {
                    **raw_result,
                    "reason": "variant identity has no resolved Page owner",
                }
            elif status == "known":
                canonical_variant = self.canonical_variant_name(
                    matched_name, variant_name)
                if page_identity_status != "known" or not canonical_variant:
                    status = variant_identity = "uncertain"
                    raw_result = {
                        **raw_result,
                        "reason": (
                            "known Variant did not name a registered Variant "
                            "on the selected Page"
                        ),
                    }
                else:
                    variant_name = canonical_variant
            elif status == "new":
                if (
                    not variant_name
                    or self.canonical_variant_name(
                        matched_name, variant_name)
                ):
                    status = variant_identity = "uncertain"
                    raw_result = {
                        **raw_result,
                        "reason": (
                            "new Variant requires a non-empty unregistered "
                            "name on the selected Page"
                        ),
                    }
            else:
                status = variant_identity = "uncertain"
                variant_name = ""
                raw_result = {
                    **raw_result,
                    "reason": "variant identity resolver returned an invalid status",
                }
        else:
            status = str(
                raw_result.get("status") or raw_result.get("decision") or ""
            ).strip().casefold()
            if status not in {"known", "new", "uncertain"}:
                status = "uncertain"
                raw_result = {
                    **raw_result,
                    "reason": "page identity resolver returned an invalid status",
                }
            page_identity_status = status
            matched_name = str(
                raw_result.get("matched_page_name")
                or raw_result.get("page_name")
                or ""
            ).strip()
            if status == "known":
                canonical = self._find_name(matched_name)
                if not canonical:
                    status = page_identity_status = "uncertain"
                    matched_name = ""
                    raw_result = {
                        **raw_result,
                        "reason": "known result did not name a registered page",
                    }
                else:
                    matched_name = canonical
            elif status == "new":
                matched_name = str(
                    raw_result.get("page_name") or proposed_name
                ).strip()
                if not matched_name or self._find_name(matched_name):
                    status = page_identity_status = "uncertain"
                    matched_name = ""
                    raw_result = {
                        **raw_result,
                        "reason": (
                            "new result requires a non-empty unregistered "
                            "page name"
                        ),
                    }
            else:
                matched_name = ""

            variant_identity = str(
                raw_result.get("variant_identity") or "").strip().casefold()
            variant_name = str(
                raw_result.get("variant_name") or "").strip()[:160]
            if identity_stage == "page":
                variant_identity = ""
                variant_name = ""
            else:
                if status in {"known", "new"} and not variant_identity:
                    variant_identity = "new" if status == "new" else "known"
                if status == "known" and not variant_name:
                    variant_name = next(iter(
                        (self._page(matched_name) or {}).get("variants") or {}
                    ), "")
                elif status == "new" and not variant_name:
                    variant_name = "default"
                if status in {"known", "new"}:
                    if status == "new" and variant_identity != "new":
                        status = page_identity_status = "uncertain"
                        raw_result = {
                            **raw_result,
                            "reason": "a new Page requires a new initial Variant",
                        }
                    elif variant_identity == "known":
                        canonical_variant = self.canonical_variant_name(
                            matched_name, variant_name)
                        if not canonical_variant:
                            status = page_identity_status = "uncertain"
                            raw_result = {
                                **raw_result,
                                "reason": (
                                    "known Variant did not name a registered "
                                    "Variant on the matched Page"
                                ),
                            }
                        else:
                            variant_name = canonical_variant
                    elif variant_identity == "new":
                        if (
                            not variant_name
                            or (
                                status == "known"
                                and self.canonical_variant_name(
                                    matched_name, variant_name)
                            )
                        ):
                            status = page_identity_status = "uncertain"
                            raw_result = {
                                **raw_result,
                                "reason": (
                                    "new Variant requires a non-empty "
                                    "unregistered name on the matched Page"
                                ),
                            }
                    else:
                        status = page_identity_status = "uncertain"
                        raw_result = {
                            **raw_result,
                            "reason": "variant identity remains uncertain",
                        }
            if status == "uncertain":
                matched_name = ""
                variant_name = ""
                variant_identity = (
                    "" if identity_stage == "page" else "uncertain")

        def _evidence_list(key: str) -> List[str]:
            value = raw_result.get(key)
            if not isinstance(value, list):
                return []
            return [str(item).strip()[:300] for item in value[:20]
                    if str(item).strip()]

        checked = raw_result.get("checked_candidates")
        if not isinstance(checked, list):
            checked = requested_names
        checked_names = [str(item).strip()[:160] for item in checked[:40]]
        data = {
            "page_name": matched_name,
            "matched_page_name": (
                matched_name if page_identity_status == "known" else ""
            ),
            "variant_name": variant_name,
            "variant_identity": variant_identity,
            "visible_predicates": [
                str(item).strip()[:240]
                for item in (raw_result.get("visible_predicates") or [])[:12]
                if str(item).strip()
            ],
            "surface_kind": str(
                raw_result.get("surface_kind") or "other"
            ).strip().casefold(),
            "summary": str(raw_result.get("summary") or "").strip()[:500],
            "supporting_evidence": _evidence_list("supporting_evidence"),
            "conflicting_evidence": _evidence_list("conflicting_evidence"),
            "checked_candidates": checked_names,
            "reason": str(raw_result.get("reason") or "").strip()[:500],
        }
        if identity_stage != "combined":
            data["identity_stage"] = identity_stage
        if data["surface_kind"] not in {
                "page", "dialog", "menu", "drawer", "other"}:
            data["surface_kind"] = "other"
        return ToolEvidence(status, data)

    def save(self, output_root: str) -> None:
        path = os.path.join(output_root, "autonomous_natural_map.json")
        os.makedirs(output_root, exist_ok=True)
        temporary = path + ".tmp"
        with open(temporary, "w", encoding="utf-8") as stream:
            json.dump(self.serializable(), stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
