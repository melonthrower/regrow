"""Federated capability catalog over independent application artifacts.

The catalog is a semantic composition layer, not a state-graph merger.  Each
application keeps its own node namespace and graph; composed instructions carry
an explicit ``app_id`` on every capability reference so the visual collection
executor can switch adapters at well-defined boundaries.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from .capability_instruction_gen import CapabilityRef, Instruction, RUNTIME_PLACEHOLDER


class CapabilityCatalogError(ValueError):
    """Base class for fail-closed catalog/composition errors."""


class CapabilityNotFoundError(CapabilityCatalogError):
    pass


class AmbiguousCapabilityError(CapabilityCatalogError):
    pass


@dataclass(frozen=True)
class FederatedCapabilityAtom:
    """One page capability with an application-qualified identity."""

    app_id: str
    node_id: str
    page_name: str
    capability_id: str
    name: str
    target_node: str
    page_id: str = ""
    semantic_key: str = ""
    region: str = ""
    param: Mapping[str, Any] = field(default_factory=dict)
    elements: Tuple[str, ...] = ()
    element_map: Mapping[str, Tuple[str, ...]] = field(default_factory=dict)
    requires: Tuple[Any, ...] = ()
    effects: Tuple[Any, ...] = ()
    success_predicate: str = ""
    observables: Tuple[Any, ...] = ()
    setup_recipe: Tuple[Any, ...] = ()
    execution_recipe: Tuple[Any, ...] = ()
    recovery: Tuple[Any, ...] = ()
    cleanup: Tuple[Any, ...] = ()
    availability_status: str = "verified"
    risk_level: str = "normal"
    action_steps: int = 1
    explain: str = ""
    source_path: str = ""
    source_paths: Tuple[str, ...] = ()
    evidence_variants: Tuple[str, ...] = ()
    entry_variants: Tuple[str, ...] = ()
    source_elements: Tuple[Any, ...] = ()
    target_pages: Tuple[str, ...] = ()
    target_variants: Tuple[str, ...] = ()
    action_edge_ids: Tuple[str, ...] = ()
    available_when: Mapping[str, Any] = field(default_factory=dict)

    @property
    def qualified_name(self) -> str:
        return f"{self.app_id}::{self.page_name}::{self.name}"

    @property
    def namespaced_id(self) -> str:
        return f"{self.app_id}::{self.capability_id}"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "app_id": self.app_id,
            "node_id": self.node_id,
            "page_name": self.page_name,
            "page_id": self.page_id,
            "capability_id": self.capability_id,
            "qualified_name": self.qualified_name,
            "name": self.name,
            "semantic_key": self.semantic_key,
            "target_node": self.target_node,
            "region": self.region,
            "param": dict(self.param),
            "elements": list(self.elements),
            "element_map": {key: list(values) for key, values in self.element_map.items()},
            "requires": list(self.requires),
            "effects": list(self.effects),
            "success_predicate": self.success_predicate,
            "observables": list(self.observables),
            "setup_recipe": list(self.setup_recipe),
            "execution_recipe": list(self.execution_recipe),
            "recovery": list(self.recovery),
            "cleanup": list(self.cleanup),
            "availability_status": self.availability_status,
            "risk_level": self.risk_level,
            "action_steps": self.action_steps,
            "explain": self.explain,
            "source_path": self.source_path,
            "source_paths": list(self.source_paths),
            "evidence_variants": list(self.evidence_variants),
            "entry_variants": list(self.entry_variants),
            "source_elements": list(self.source_elements),
            "target_pages": list(self.target_pages),
            "target_variants": list(self.target_variants),
            "action_edge_ids": list(self.action_edge_ids),
            "available_when": dict(self.available_when),
        }


@dataclass
class FederatedCapabilityRef(CapabilityRef):
    """CapabilityRef extension carrying M13's per-reference parameters/id."""

    ref_id: str = ""

    def to_dict(self) -> Dict[str, Any]:
        value = super().to_dict()
        value["ref_id"] = self.ref_id or self.capability_id
        value["params"] = dict(self.params)
        return value


class FederatedCapabilityCatalog:
    """Load and compose atoms while preserving per-application boundaries."""

    def __init__(
        self,
        app_node_dirs: Optional[Mapping[str, Any]] = None,
        *,
        vlm: Any = None,
    ) -> None:
        self.app_node_dirs: Dict[str, Path] = {
            str(app_id): Path(path)
            for app_id, path in (app_node_dirs or {}).items()
        }
        self.vlm = vlm
        self._by_app: Dict[str, List[FederatedCapabilityAtom]] = defaultdict(list)
        self._by_qualified: Dict[str, List[FederatedCapabilityAtom]] = defaultdict(list)
        self._by_qualified_folded: Dict[str, List[FederatedCapabilityAtom]] = defaultdict(list)
        self._by_capability_id: Dict[str, List[FederatedCapabilityAtom]] = defaultdict(list)
        self._by_namespaced_id: Dict[str, FederatedCapabilityAtom] = {}
        if app_node_dirs:
            self.load()

    @classmethod
    def from_node_dirs(
        cls,
        app_node_dirs: Mapping[str, Any],
        *,
        vlm: Any = None,
    ) -> "FederatedCapabilityCatalog":
        return cls(app_node_dirs, vlm=vlm)

    @property
    def app_ids(self) -> Tuple[str, ...]:
        return tuple(self.app_node_dirs)

    @property
    def capability_id_index(self) -> Mapping[str, Tuple[FederatedCapabilityAtom, ...]]:
        return {key: tuple(values) for key, values in self._by_capability_id.items()}

    @property
    def qualified_name_index(self) -> Mapping[str, Tuple[FederatedCapabilityAtom, ...]]:
        return {key: tuple(values) for key, values in self._by_qualified.items()}

    def load(self) -> int:
        """Reload every ``*/page_capabilities.json`` under each app node dir."""
        self._by_app.clear()
        self._by_qualified.clear()
        self._by_qualified_folded.clear()
        self._by_capability_id.clear()
        self._by_namespaced_id.clear()

        for app_id, node_dir in self.app_node_dirs.items():
            paths = sorted(node_dir.glob("*/page_capabilities.json"))
            direct = node_dir / "page_capabilities.json"
            if direct.is_file():
                paths.insert(0, direct)
            for path in paths:
                self._load_page(app_id, path)
        return sum(len(atoms) for atoms in self._by_app.values())

    def _load_page(self, app_id: str, path: Path) -> None:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise CapabilityCatalogError(f"cannot load {path}: {exc}") from exc
        if not isinstance(data, Mapping):
            raise CapabilityCatalogError(f"page capability artifact is not an object: {path}")

        node_id = str(data.get("node_id") or path.parent.name).strip()
        page_name = str(data.get("page_name") or node_id).strip()
        page_id = str(data.get("page_id") or "").strip()
        variant_id = str(data.get("variant_id") or "").strip()
        capabilities = data.get("capabilities") or []
        if not isinstance(capabilities, Sequence) or isinstance(capabilities, (str, bytes)):
            raise CapabilityCatalogError(f"capabilities is not a list: {path}")
        for raw in capabilities:
            if not isinstance(raw, Mapping):
                continue
            atom = self._atom_from_raw(
                app_id,
                node_id,
                page_name,
                raw,
                path,
                artifact_page_id=page_id,
                artifact_variant_id=variant_id,
            )
            if not atom.name:
                continue
            prior = self._by_namespaced_id.get(atom.namespaced_id)
            if prior is not None:
                atom = self._merge_variant_atom(prior, atom)
                self._remove_indexed_atom(prior)
            self._index_atom(atom)

    def _index_atom(self, atom: FederatedCapabilityAtom) -> None:
        self._by_app[atom.app_id].append(atom)
        self._by_qualified[atom.qualified_name].append(atom)
        self._by_qualified_folded[atom.qualified_name.casefold()].append(atom)
        self._by_capability_id[atom.capability_id].append(atom)
        self._by_namespaced_id[atom.namespaced_id] = atom

    def _remove_indexed_atom(self, atom: FederatedCapabilityAtom) -> None:
        for index, key in (
            (self._by_app, atom.app_id),
            (self._by_qualified, atom.qualified_name),
            (self._by_qualified_folded, atom.qualified_name.casefold()),
            (self._by_capability_id, atom.capability_id),
        ):
            bucket = index.get(key)
            if bucket is None:
                continue
            bucket[:] = [candidate for candidate in bucket if candidate is not atom]
            if not bucket:
                index.pop(key, None)
        self._by_namespaced_id.pop(atom.namespaced_id, None)

    @staticmethod
    def _merge_variant_atom(
        prior: FederatedCapabilityAtom,
        incoming: FederatedCapabilityAtom,
    ) -> FederatedCapabilityAtom:
        """Fold repeated Page@Variant sidecars into one page capability.

        Online traversal emits one sidecar per execution variant, while the
        stable capability id is page-scoped.  A duplicate is therefore valid
        only when both the stable page and semantic action identity agree.
        """
        sources = sorted(set((*prior.source_paths, prior.source_path,
                              *incoming.source_paths, incoming.source_path)))
        source_text = ", ".join(value for value in sources if value)
        if not prior.page_id or not incoming.page_id:
            raise CapabilityCatalogError(
                f"duplicate capability id in app {prior.app_id!r} lacks a "
                f"stable page_id: {prior.capability_id!r} ({source_text})"
            )
        if prior.page_id != incoming.page_id:
            raise CapabilityCatalogError(
                f"duplicate capability id in app {prior.app_id!r} crosses pages: "
                f"{prior.capability_id!r} ({prior.page_id!r} != "
                f"{incoming.page_id!r}; {source_text})"
            )
        prior_semantic = _normalized_semantic_identity(prior.semantic_key)
        incoming_semantic = _normalized_semantic_identity(incoming.semantic_key)
        if not prior_semantic or not incoming_semantic \
                or prior_semantic != incoming_semantic:
            raise CapabilityCatalogError(
                f"duplicate capability id in app {prior.app_id!r} has conflicting "
                f"semantic identity: {prior.capability_id!r} "
                f"({prior.semantic_key!r} != {incoming.semantic_key!r}; "
                f"{source_text})"
            )

        preferred, secondary = sorted(
            (prior, incoming), key=_atom_preference_key)
        available_when = _merge_available_when(
            preferred.available_when, secondary.available_when)
        return replace(
            preferred,
            elements=_union_text(prior.elements, incoming.elements),
            element_map=_merge_element_maps(prior.element_map, incoming.element_map),
            requires=_compatible_requires(prior, incoming, available_when),
            effects=_union_json(prior.effects, incoming.effects),
            observables=_union_json(prior.observables, incoming.observables),
            success_predicate=(
                preferred.success_predicate or secondary.success_predicate),
            execution_recipe=(
                preferred.execution_recipe or secondary.execution_recipe),
            availability_status=_merge_availability_status(
                prior.availability_status, incoming.availability_status),
            source_paths=tuple(value for value in sources if value),
            evidence_variants=_union_text(
                prior.evidence_variants, incoming.evidence_variants),
            entry_variants=_union_text(
                prior.entry_variants, incoming.entry_variants),
            source_elements=_union_json(
                prior.source_elements, incoming.source_elements),
            target_pages=_union_text(prior.target_pages, incoming.target_pages),
            target_variants=_union_text(
                prior.target_variants, incoming.target_variants),
            action_edge_ids=_union_text(
                prior.action_edge_ids, incoming.action_edge_ids),
            available_when=available_when,
        )

    @staticmethod
    def _atom_from_raw(
        app_id: str,
        node_id: str,
        page_name: str,
        raw: Mapping[str, Any],
        path: Path,
        *,
        artifact_page_id: str = "",
        artifact_variant_id: str = "",
    ) -> FederatedCapabilityAtom:
        name = str(raw.get("name") or "").strip()
        raw_page_id = str(raw.get("page_id") or "").strip()
        if raw_page_id and artifact_page_id and raw_page_id != artifact_page_id:
            raise CapabilityCatalogError(
                f"capability page_id disagrees with sidecar {path}: "
                f"{raw_page_id!r} != {artifact_page_id!r}"
            )
        page_id = raw_page_id or str(artifact_page_id or "").strip()
        semantic_key = str(raw.get("semantic_key") or name).strip()
        capability_id = str(raw.get("capability_id") or "").strip()
        if not capability_id:
            digest_input = f"{app_id}\0{node_id}\0{page_name}\0{name}".encode("utf-8")
            capability_id = f"cap_{hashlib.sha256(digest_input).hexdigest()[:16]}"
        param = raw.get("param") or {}
        if not isinstance(param, Mapping):
            param = {}
        element_map = raw.get("element_map") or param.get("element_map") or {}
        if not isinstance(element_map, Mapping):
            element_map = {}
        execution_recipe = _execution_recipe_from_mapping(raw)
        available_when = raw.get("available_when") or {}
        if not isinstance(available_when, Mapping):
            available_when = {}
        available_when = dict(available_when)
        variant_ids = list(available_when.get("variant_ids") or [])
        if artifact_variant_id and artifact_variant_id not in variant_ids:
            variant_ids.append(artifact_variant_id)
        available_when["variant_ids"] = list(_union_text(variant_ids))
        evidence_variants = list(raw.get("evidence_variants") or variant_ids)
        entry_variants = list(raw.get("entry_variants") or variant_ids)
        return FederatedCapabilityAtom(
            app_id=app_id,
            node_id=node_id,
            page_name=page_name,
            capability_id=capability_id,
            name=name,
            target_node=str(raw.get("target_node") or node_id),
            page_id=page_id,
            semantic_key=semantic_key,
            region=str(raw.get("region") or ""),
            param=dict(param),
            elements=tuple(str(value) for value in (raw.get("elements") or [])),
            element_map={
                str(key): tuple(str(value) for value in (values or []))
                for key, values in element_map.items()
            },
            requires=_as_tuple(raw.get("requires")),
            effects=_as_tuple(raw.get("effects")),
            success_predicate=str(raw.get("success_predicate") or ""),
            observables=_as_tuple(raw.get("observables")),
            setup_recipe=_as_tuple(raw.get("setup_recipe")),
            execution_recipe=tuple(execution_recipe),
            recovery=_as_tuple(raw.get("recovery")),
            cleanup=_as_tuple(raw.get("cleanup")),
            availability_status=_availability_status_from_raw(raw),
            risk_level=str(raw.get("risk_level") or "normal"),
            action_steps=_nonnegative_int(
                raw.get("action_steps"), default=len(execution_recipe) or 1),
            explain=str(raw.get("explain") or ""),
            source_path=str(path),
            source_paths=(str(path),),
            evidence_variants=_union_text(evidence_variants),
            entry_variants=_union_text(entry_variants),
            source_elements=_union_json(raw.get("source_elements") or ()),
            target_pages=_union_text(raw.get("target_pages") or ()),
            target_variants=_union_text(raw.get("target_variants") or ()),
            action_edge_ids=_union_text(raw.get("action_edge_ids") or ()),
            available_when=available_when,
        )

    def atoms_for_app(self, app_id: str) -> Tuple[FederatedCapabilityAtom, ...]:
        return tuple(self._by_app.get(app_id, ()))

    def all_atoms(self) -> Tuple[FederatedCapabilityAtom, ...]:
        return tuple(
            atom
            for app_id in self.app_node_dirs
            for atom in self._by_app.get(app_id, ())
        )

    def get_by_capability_id(
        self,
        capability_id: str,
        *,
        app_id: Optional[str] = None,
    ) -> FederatedCapabilityAtom:
        if app_id:
            atom = self._by_namespaced_id.get(f"{app_id}::{capability_id}")
            if atom is None:
                raise CapabilityNotFoundError(f"unknown capability {app_id}::{capability_id}")
            return atom
        matches = self._by_capability_id.get(capability_id, [])
        return _one_match(matches, capability_id)

    def get_by_qualified_name(self, qualified_name: str) -> FederatedCapabilityAtom:
        matches = self._by_qualified.get(qualified_name, [])
        if not matches:
            matches = self._by_qualified_folded.get(qualified_name.casefold(), [])
        return _one_match(matches, qualified_name)

    def resolve(
        self,
        identifier: str,
        *,
        app_id: Optional[str] = None,
    ) -> FederatedCapabilityAtom:
        identifier = str(identifier or "").strip()
        if not identifier:
            raise CapabilityNotFoundError("empty capability identifier")
        if identifier.count("::") >= 2:
            return self.get_by_qualified_name(identifier)
        if identifier.count("::") == 1:
            prefix, capability_id = identifier.split("::", 1)
            if prefix in self.app_node_dirs:
                return self.get_by_capability_id(capability_id, app_id=prefix)
        return self.get_by_capability_id(identifier, app_id=app_id)

    # -- composition -------------------------------------------------------

    def compose_instruction(
        self,
        atom_refs: Sequence[Any],
        *,
        instruction_text: str = "",
        instruction_id: str = "FED001",
        instruction_type: str = "",
    ) -> Instruction:
        """Deterministically compose explicit atoms in the supplied order."""
        if not atom_refs:
            raise CapabilityCatalogError("explicit atom_refs must not be empty")
        resolved: List[Tuple[FederatedCapabilityAtom, Dict[str, Any]]] = []
        for item in atom_refs:
            atom, options = self._resolve_ref_spec(item)
            resolved.append((atom, options))
        return self._build_instruction(
            resolved,
            instruction_text=instruction_text,
            instruction_id=instruction_id,
            instruction_type=instruction_type,
        )

    def compose_with_vlm(
        self,
        goal: str,
        *,
        candidate_atom_refs: Optional[Sequence[Any]] = None,
        instruction_id: str = "FED001",
    ) -> Instruction:
        """Ask an injected VLM to select/order known atoms, then ground strictly."""
        if self.vlm is None:
            raise CapabilityCatalogError("VLM composition requested without an injected VLM")
        if candidate_atom_refs:
            candidates = [self._resolve_ref_spec(item)[0] for item in candidate_atom_refs]
        else:
            candidates = list(self.all_atoms())
        if not candidates:
            raise CapabilityCatalogError("catalog has no candidate atoms")

        inventory = [
            {
                "atom_ref": atom.qualified_name,
                "capability_id": atom.capability_id,
                "app_id": atom.app_id,
                "node_id": atom.node_id,
                "target_node": atom.target_node,
                "requires": list(atom.requires),
                "action_steps": atom.action_steps,
            }
            for atom in candidates
        ]
        prompt = (
            "Compose one feasible ordered GUI instruction from the known capability atoms. "
            "Never invent an atom. Preserve application boundaries. Return only JSON: "
            "{\"instruction\":\"...\",\"ordered_atom_refs\":["
            "{\"atom_ref\":\"app::page::name\",\"params\":{}}]}.\n"
            f"Goal: {goal}\nKnown atoms:\n"
            f"{json.dumps(inventory, ensure_ascii=False)}"
        )
        data = _call_vlm_json(self.vlm, prompt)
        raw_refs = (
            data.get("ordered_atom_refs")
            or data.get("atom_refs")
            or data.get("capability_refs")
            or []
        )
        if not isinstance(raw_refs, Sequence) or isinstance(raw_refs, (str, bytes)) or not raw_refs:
            raise CapabilityCatalogError("VLM returned no ordered atom refs")
        allowed = {atom.namespaced_id for atom in candidates}
        resolved: List[Tuple[FederatedCapabilityAtom, Dict[str, Any]]] = []
        for raw_ref in raw_refs:
            atom, options = self._resolve_ref_spec(raw_ref)
            if atom.namespaced_id not in allowed:
                raise CapabilityCatalogError(
                    f"VLM selected atom outside the supplied candidates: {atom.qualified_name}"
                )
            resolved.append((atom, options))
        return self._build_instruction(
            resolved,
            instruction_text=str(data.get("instruction") or goal),
            instruction_id=instruction_id,
            instruction_type=str(data.get("type") or ""),
        )

    def _resolve_ref_spec(
        self, spec: Any
    ) -> Tuple[FederatedCapabilityAtom, Dict[str, Any]]:
        if isinstance(spec, str):
            return self.resolve(spec), {}
        if not isinstance(spec, Mapping):
            raise CapabilityCatalogError(f"invalid atom ref: {spec!r}")
        options = dict(spec)
        app_id = str(spec.get("app_id") or "").strip() or None
        identifier = str(
            spec.get("atom_ref")
            or spec.get("qualified_name")
            or spec.get("capability_id")
            or spec.get("id")
            or ""
        ).strip()
        if not identifier and app_id and spec.get("page_name") and spec.get("name"):
            identifier = f"{app_id}::{spec['page_name']}::{spec['name']}"
        if not identifier:
            raise CapabilityCatalogError(f"atom ref has no catalog identifier: {spec!r}")
        return self.resolve(identifier, app_id=app_id), options

    def _build_instruction(
        self,
        resolved: Sequence[Tuple[FederatedCapabilityAtom, Dict[str, Any]]],
        *,
        instruction_text: str,
        instruction_id: str,
        instruction_type: str,
    ) -> Instruction:
        refs: List[FederatedCapabilityRef] = []
        used_ref_ids: Dict[str, int] = defaultdict(int)
        runtime_slots: List[str] = []
        instruction_params: Dict[str, str] = {}
        apps_involved: List[str] = []

        for atom, options in resolved:
            if atom.app_id not in apps_involved:
                apps_involved.append(atom.app_id)
            base_ref_id = str(options.get("ref_id") or atom.capability_id)
            used_ref_ids[base_ref_id] += 1
            ref_id = base_ref_id
            if used_ref_ids[base_ref_id] > 1:
                ref_id = f"{base_ref_id}#{used_ref_ids[base_ref_id]}"

            params = options.get("params") or {}
            if not isinstance(params, Mapping):
                raise CapabilityCatalogError(f"params for {atom.qualified_name} must be an object")
            params = dict(params)
            param_type = str(atom.param.get("type") or "none")
            slot = str(atom.param.get("slot") or "")
            source = str(atom.param.get("source") or "")
            value: Any = params.get(slot, "") if slot else ""
            runtime = bool(source == "discover_at_runtime" and not value)
            if runtime:
                value = RUNTIME_PLACEHOLDER
                if slot and slot not in runtime_slots:
                    runtime_slots.append(slot)
            if slot and value != "":
                key = slot
                if key in instruction_params and instruction_params[key] != str(value):
                    key = f"{ref_id}.{slot}"
                instruction_params[key] = str(value)

            requires = list(atom.requires)
            extra_requires = options.get("requires") or []
            if isinstance(extra_requires, (str, Mapping)):
                extra_requires = [extra_requires]
            requires.extend(extra_requires)
            depends_on = options.get("depends_on") or []
            if isinstance(depends_on, str):
                depends_on = [depends_on]

            refs.append(
                FederatedCapabilityRef(
                    node_id=atom.node_id,
                    page_name=atom.page_name,
                    name=atom.name,
                    param_type=param_type,
                    slot=slot,
                    value=str(value),
                    runtime=runtime,
                    elements=list(atom.elements),
                    element_map={key: list(values) for key, values in atom.element_map.items()},
                    target_node=str(options.get("target_node") or atom.target_node),
                    app_id=atom.app_id,
                    capability_id=atom.capability_id,
                    requires=requires,
                    effects=list(atom.effects),
                    success_predicate=atom.success_predicate,
                    observables=list(atom.observables),
                    setup_recipe=list(atom.setup_recipe),
                    execution_recipe=list(atom.execution_recipe),
                    recovery=list(atom.recovery),
                    cleanup=list(atom.cleanup),
                    availability_status=atom.availability_status,
                    risk_level=atom.risk_level,
                    action_steps=_nonnegative_int(
                        options.get("action_steps"), default=atom.action_steps
                    ),
                    depends_on=[str(value) for value in depends_on],
                    ref_id=ref_id,
                    params=params,
                    desired_outcome=options.get("desired_outcome"),
                )
            )

        if not instruction_text:
            clauses = [f"在 {atom.app_id} 中{atom.name}" for atom, _options in resolved]
            instruction_text = "，然后".join(clauses)
        if not instruction_type:
            if len(apps_involved) > 1:
                instruction_type = "cross_app"
            elif len(refs) > 1:
                instruction_type = "cross_page"
            else:
                instruction_type = "single"
        return Instruction(
            instruction_id=instruction_id,
            type=instruction_type,
            instruction=instruction_text,
            capability_refs=refs,
            runtime_slots=runtime_slots,
            params=instruction_params,
            apps_involved=apps_involved,
            fixed_order=True,
        )


def instruction_from_dict(data: Mapping[str, Any]) -> Instruction:
    """Rebuild a federated Instruction without consulting a live catalog."""
    if not isinstance(data, Mapping):
        raise CapabilityCatalogError("instruction JSON must be an object")
    refs: List[FederatedCapabilityRef] = []
    for raw in data.get("capability_refs") or []:
        if not isinstance(raw, Mapping):
            raise CapabilityCatalogError("capability_refs must contain objects")
        refs.append(
            FederatedCapabilityRef(
                node_id=str(raw.get("node_id") or ""),
                page_name=str(raw.get("page_name") or ""),
                name=str(raw.get("name") or ""),
                param_type=str(raw.get("param_type") or "none"),
                slot=str(raw.get("slot") or ""),
                value=str(raw.get("value") or ""),
                runtime=bool(raw.get("runtime")),
                elements=[str(value) for value in (raw.get("elements") or [])],
                element_map={
                    str(key): [str(value) for value in (values or [])]
                    for key, values in (raw.get("element_map") or {}).items()
                },
                target_node=str(raw.get("target_node") or raw.get("node_id") or ""),
                app_id=str(raw.get("app_id") or ""),
                capability_id=str(raw.get("capability_id") or ""),
                requires=list(raw.get("requires") or []),
                effects=list(raw.get("effects") or []),
                success_predicate=str(raw.get("success_predicate") or ""),
                observables=list(raw.get("observables") or []),
                setup_recipe=list(raw.get("setup_recipe") or []),
                execution_recipe=_execution_recipe_from_mapping(raw),
                recovery=list(raw.get("recovery") or []),
                cleanup=list(raw.get("cleanup") or []),
                availability_status=str(raw.get("availability_status") or "verified"),
                verification_level=str(raw.get("verification_level") or ""),
                risk_level=str(raw.get("risk_level") or "normal"),
                action_steps=_nonnegative_int(raw.get("action_steps"), default=1),
                depends_on=[str(value) for value in (raw.get("depends_on") or [])],
                ref_id=str(raw.get("ref_id") or raw.get("capability_id") or ""),
                params=dict(raw.get("params") or {}),
                desired_outcome=raw.get("desired_outcome"),
            )
        )
    return Instruction(
        instruction_id=str(data.get("instruction_id") or ""),
        type=str(data.get("type") or "cross_app"),
        instruction=str(data.get("instruction") or ""),
        capability_refs=refs,
        runtime_slots=[str(value) for value in (data.get("runtime_slots") or [])],
        params={str(key): str(value) for key, value in (data.get("params") or {}).items()},
        apps_involved=[str(value) for value in (data.get("apps_involved") or [])],
        fixed_order=bool(data.get("fixed_order", True)),
    )


def dumps_instruction(instruction: Instruction, *, indent: Optional[int] = None) -> str:
    return json.dumps(instruction.to_dict(), ensure_ascii=False, indent=indent)


def loads_instruction(payload: str) -> Instruction:
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise CapabilityCatalogError(f"invalid instruction JSON: {exc}") from exc
    return instruction_from_dict(data)


def _as_tuple(value: Any) -> Tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, Mapping)):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


_AVAILABILITY_PRIORITY = {
    "verified": 0,
    "discovered": 1,
    "conditional": 2,
    "blocked": 3,
    "unknown": 4,
}


def _availability_status_from_raw(raw: Mapping[str, Any]) -> str:
    lifecycle = str(raw.get("status") or "").strip().casefold()
    availability = str(raw.get("availability_status") or "").strip().casefold()
    if lifecycle == "verified" or availability == "verified":
        return "verified"
    if availability:
        return availability
    if lifecycle:
        return lifecycle
    # Historical synthesized artifacts predate explicit lifecycle state and
    # were treated as executable by this catalog. Keep that read compatibility.
    return "verified"


def _merge_availability_status(*values: str) -> str:
    normalized = [str(value or "unknown").strip().casefold() for value in values]
    return min(
        normalized,
        key=lambda value: (_AVAILABILITY_PRIORITY.get(value, 5), value),
    )


def _normalized_semantic_identity(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        default=str,
    )


def _sequence_values(value: Any) -> Tuple[Any, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, Mapping)):
        return (value,)
    if isinstance(value, Iterable):
        return tuple(value)
    return (value,)


def _union_json(*groups: Any) -> Tuple[Any, ...]:
    by_key: Dict[str, Any] = {}
    for group in groups:
        for value in _sequence_values(group):
            by_key.setdefault(_canonical_json(value), value)
    return tuple(by_key[key] for key in sorted(by_key))


def _union_text(*groups: Any) -> Tuple[str, ...]:
    values = {
        str(value).strip()
        for group in groups
        for value in _sequence_values(group)
        if str(value).strip()
    }
    return tuple(sorted(values))


def _merge_element_maps(
    prior: Mapping[str, Tuple[str, ...]],
    incoming: Mapping[str, Tuple[str, ...]],
) -> Mapping[str, Tuple[str, ...]]:
    merged: Dict[str, Tuple[str, ...]] = {}
    for key in sorted(set((*prior.keys(), *incoming.keys()))):
        merged[str(key)] = _union_text(prior.get(key), incoming.get(key))
    return merged


def _merge_fact_mapping(
    preferred: Mapping[str, Any], secondary: Mapping[str, Any]
) -> Dict[str, Any]:
    """Union additive fact fields while keeping deterministic scalar truth."""
    merged: Dict[str, Any] = {}
    for key in sorted(set((*preferred.keys(), *secondary.keys()))):
        if key not in preferred:
            merged[str(key)] = secondary[key]
            continue
        if key not in secondary:
            merged[str(key)] = preferred[key]
            continue
        left = preferred[key]
        right = secondary[key]
        if isinstance(left, Mapping) and isinstance(right, Mapping):
            merged[str(key)] = _merge_fact_mapping(left, right)
        elif isinstance(left, (list, tuple)) and isinstance(right, (list, tuple)):
            merged[str(key)] = list(_union_json(left, right))
        else:
            # ``preferred`` is selected independently of load order, so a
            # repeated observation with a different scalar remains stable.
            merged[str(key)] = left
    return merged


def _merge_available_when(
    preferred: Mapping[str, Any], secondary: Mapping[str, Any]
) -> Mapping[str, Any]:
    merged = _merge_fact_mapping(
        dict(preferred or {}), dict(secondary or {}))
    merged["variant_ids"] = list(_union_text(
        (preferred or {}).get("variant_ids") or (),
        (secondary or {}).get("variant_ids") or (),
    ))
    preferred_facts = (preferred or {}).get("facts_by_variant") or {}
    secondary_facts = (secondary or {}).get("facts_by_variant") or {}
    if isinstance(preferred_facts, Mapping) and isinstance(secondary_facts, Mapping):
        facts_by_variant: Dict[str, Any] = {}
        for variant_id in sorted(set((*preferred_facts.keys(),
                                      *secondary_facts.keys()))):
            left = preferred_facts.get(variant_id)
            right = secondary_facts.get(variant_id)
            if isinstance(left, Mapping) and isinstance(right, Mapping):
                facts_by_variant[str(variant_id)] = _merge_fact_mapping(left, right)
            elif variant_id in preferred_facts:
                facts_by_variant[str(variant_id)] = left
            else:
                facts_by_variant[str(variant_id)] = right
        merged["facts_by_variant"] = facts_by_variant

    preferred_requires = (preferred or {}).get("requires_by_variant") or {}
    secondary_requires = (secondary or {}).get("requires_by_variant") or {}
    if isinstance(preferred_requires, Mapping) \
            and isinstance(secondary_requires, Mapping) \
            and (preferred_requires or secondary_requires):
        requires_by_variant: Dict[str, Any] = {}
        conflict_variants = set(_union_text(
            (preferred or {}).get("requires_conflict_variants") or (),
            (secondary or {}).get("requires_conflict_variants") or (),
        ))
        for variant_id in sorted(set((*preferred_requires.keys(),
                                      *secondary_requires.keys()))):
            left_present = variant_id in preferred_requires
            right_present = variant_id in secondary_requires
            left = _union_json(preferred_requires.get(variant_id) or ())
            right = _union_json(secondary_requires.get(variant_id) or ())
            if left_present and right_present \
                    and _canonical_json(left) != _canonical_json(right):
                conflict_variants.add(str(variant_id))
            chosen = left if left_present else right
            requires_by_variant[str(variant_id)] = list(chosen)
        merged["requires_by_variant"] = requires_by_variant
        if conflict_variants:
            merged["requires_conflict_variants"] = sorted(conflict_variants)
        else:
            merged.pop("requires_conflict_variants", None)
    return merged


def _compatible_requires(
    prior: FederatedCapabilityAtom,
    incoming: FederatedCapabilityAtom,
    available_when: Mapping[str, Any],
) -> Tuple[Any, ...]:
    """Keep a legacy global precondition only when every variant agrees."""
    requires_by_variant = (available_when or {}).get("requires_by_variant") or {}
    if isinstance(requires_by_variant, Mapping) and requires_by_variant:
        if (available_when or {}).get("requires_conflict_variants"):
            return ()
        variant_ids = _union_text(
            (available_when or {}).get("variant_ids") or (),
            requires_by_variant.keys(),
        )
        if any(variant_id not in requires_by_variant for variant_id in variant_ids):
            return ()
        normalized = [
            _union_json(requires_by_variant.get(variant_id) or ())
            for variant_id in variant_ids
        ]
        if not normalized:
            return ()
        first = normalized[0]
        if all(_canonical_json(value) == _canonical_json(first)
               for value in normalized[1:]):
            return first
        return ()

    prior_requires = _union_json(prior.requires)
    incoming_requires = _union_json(incoming.requires)
    if _canonical_json(prior_requires) == _canonical_json(incoming_requires):
        return prior_requires
    return ()


def _atom_preference_key(atom: FederatedCapabilityAtom) -> Tuple[Any, ...]:
    """Choose a stable representative; verified action evidence wins."""
    status = str(atom.availability_status or "unknown").casefold()
    return (
        _AVAILABILITY_PRIORITY.get(status, 5),
        0 if atom.action_edge_ids else 1,
        0 if atom.execution_recipe else 1,
        atom.node_id,
        atom.target_node,
        atom.source_path,
    )


def _execution_recipe_from_mapping(raw: Mapping[str, Any]) -> List[Dict[str, Any]]:
    recipe: Any = raw.get("execution_recipe")
    if recipe is None:
        recipe = raw.get("action_recipe")
    if recipe is None:
        recipe = raw.get("actions")
    if isinstance(recipe, Mapping):
        recipe = [recipe]
    if not isinstance(recipe, Sequence) or isinstance(recipe, (str, bytes)):
        return []
    return [dict(step) for step in recipe if isinstance(step, Mapping)]


def _nonnegative_int(value: Any, *, default: int) -> int:
    try:
        result = int(value)
    except (TypeError, ValueError):
        result = default
    return max(0, result)


def _one_match(
    matches: Sequence[FederatedCapabilityAtom], identifier: str
) -> FederatedCapabilityAtom:
    if not matches:
        raise CapabilityNotFoundError(f"unknown capability {identifier!r}")
    if len(matches) > 1:
        names = [atom.qualified_name for atom in matches]
        raise AmbiguousCapabilityError(
            f"ambiguous capability {identifier!r}; use an app-qualified key: {names}"
        )
    return matches[0]


def _call_vlm_json(vlm: Any, prompt: str) -> Mapping[str, Any]:
    try:
        if hasattr(vlm, "predict_mm"):
            raw = vlm.predict_mm(prompt, [])
        elif callable(vlm):
            raw = vlm(prompt)
        else:
            raise CapabilityCatalogError("injected VLM is not callable")
        if isinstance(raw, tuple):
            raw = raw[0] if raw else ""
        if isinstance(raw, Mapping):
            return raw
        text = str(raw or "").strip()
        match = re.search(r"\{.*\}", text, re.S)
        if match:
            text = match.group(0)
        data = json.loads(text)
        if not isinstance(data, Mapping):
            raise CapabilityCatalogError("VLM output is not a JSON object")
        return data
    except CapabilityCatalogError:
        raise
    except Exception as exc:
        raise CapabilityCatalogError(f"VLM composition failed: {exc}") from exc


__all__ = [
    "AmbiguousCapabilityError",
    "CapabilityCatalogError",
    "CapabilityNotFoundError",
    "FederatedCapabilityAtom",
    "FederatedCapabilityCatalog",
    "FederatedCapabilityRef",
    "dumps_instruction",
    "instruction_from_dict",
    "loads_instruction",
]
