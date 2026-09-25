"""Visual adapter for :mod:`prerequisite_runtime`.

The adapter turns capability ``requires`` / ``setup_recipe`` dictionaries into
the typed prerequisite runtime contract.  It is screenshot-only at the
semantic boundary and delegates every live GUI operation to an injected app
adapter; it never imports or calls a VM implementation.

Typical collection integration::

    resolver = VisualPrerequisiteAgent(vlm_agent)
    executor = VisualCollectionExecutor(
        graphs, app_adapters, verifier, precondition_resolver=resolver)

``VisualCollectionExecutor`` supplies the current app adapter through its
precondition context.  Traversal may instead pass an adapter mapping or an
``adapter_provider`` when constructing this class.
"""

from __future__ import annotations

import inspect
import json
import re
from dataclasses import dataclass, field
from hashlib import sha256
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple, Union

from gui_rewalk.src.core.scenario.prerequisite_runtime import (
    ActionResult,
    CheckResult,
    CleanupReport,
    Evidence,
    Prerequisite,
    PrerequisiteKind,
    PrerequisiteRuntime,
    RuntimeAction,
    RuntimeContext,
    SetupRecipe,
)


class VisualPrerequisiteError(RuntimeError):
    """A fail-closed visual check/grounding contract failure."""


class PrerequisiteLiveAdapter(Protocol):
    """Minimum injected live boundary; observations remain opaque."""

    def capture(self) -> Any: ...

    def ground(self, action_spec: Mapping[str, Any], observation: Any) -> Any: ...

    def execute(self, grounded_action: Any) -> Any: ...

    def settle(self, execution_result: Any = None) -> Any: ...


@dataclass
class _VisualJudgement:
    kind: PrerequisiteKind
    satisfied: bool
    facts: Dict[str, Any] = field(default_factory=dict)
    bindings: Dict[str, Any] = field(default_factory=dict)
    evidence: List[Evidence] = field(default_factory=list)
    setup_recipes: Any = None
    cleanup: Any = None
    raw: Dict[str, Any] = field(default_factory=dict)

    def as_check_result(self) -> CheckResult:
        return CheckResult(
            satisfied=self.satisfied,
            facts=dict(self.facts),
            bindings=dict(self.bindings),
            evidence=list(self.evidence),
        )


@dataclass
class _Scope:
    prerequisite: Prerequisite
    requirement: Dict[str, Any]
    ref: Dict[str, Any]
    caller_context: Dict[str, Any]
    adapter: PrerequisiteLiveAdapter
    initial_judgement: Optional[_VisualJudgement]
    resource_slot: str


AgentLike = Any
AdapterProvider = Callable[..., PrerequisiteLiveAdapter]
ElementsProvider = Callable[..., Any]


class VisualPrerequisiteAgent:
    """VLM-backed prerequisite resolver shared by traversal and M13.

    VLM output is advisory until it passes the strict schema below.  A missing
    boolean, invalid/mismatched prerequisite kind, malformed JSON, capture
    failure, grounding failure, or adapter exception can never approve a gate.
    """

    _JSON_OBJECT = re.compile(r"\{.*\}", re.S)
    _KINDS = {kind.value for kind in PrerequisiteKind}
    _SECRET_KEYS = {
        "password", "passwd", "credential", "credentials", "token",
        "api_key", "secret", "username",
    }
    _LOGIN_TERMS = (
        "signed_in", "logged_in", "login_required", "app_login",
        "sign in", "log in", "login", "enter password", "submit credentials",
        "登录", "登入", "账号登录",
    )

    def __init__(
        self,
        vlm_agent: AgentLike,
        *,
        app_adapters: Optional[Mapping[str, PrerequisiteLiveAdapter]] = None,
        adapter_provider: Optional[AdapterProvider] = None,
        elements_provider: Optional[ElementsProvider] = None,
        runtime: Optional[PrerequisiteRuntime] = None,
        runtime_context: Optional[RuntimeContext] = None,
    ) -> None:
        self.vlm_agent = vlm_agent
        self.app_adapters = dict(app_adapters or {})
        self.adapter_provider = adapter_provider
        self.elements_provider = elements_provider
        self.runtime = runtime or PrerequisiteRuntime(context=runtime_context)
        # The runtime is the authority for ownership and cleanup; this adapter
        # only supplies its visual check/action boundaries.
        self.runtime.check_callback = self._check_callback
        self.runtime.action_callback = self._action_callback
        self._scopes: Dict[str, _Scope] = {}
        # Append-only, per-prerequisite GUI action evidence.  ResolutionReport
        # intentionally owns orchestration state only, so the visual boundary
        # keeps the concrete grounded actions and before/after observations for
        # traversal/M13 trajectory writers.
        self._action_events: Dict[str, List[Dict[str, Any]]] = {}

    @property
    def action_events(self) -> Tuple[Mapping[str, Any], ...]:
        """Return a read-only snapshot of all live prerequisite action events."""

        return tuple(
            dict(event)
            for events in self._action_events.values()
            for event in events
        )

    def __call__(
        self,
        requirement: Any,
        ref: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        return self.resolve(requirement, ref=ref, context=context)

    def resolve(
        self,
        requirement: Any,
        *,
        ref: Optional[Mapping[str, Any]] = None,
        context: Optional[Mapping[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Resolve one capability requirement and return executor-friendly data."""

        requirement_map: Dict[str, Any] = {}
        try:
            requirement_map = self._normalise_requirement(requirement)
            ref_map = dict(ref or {})
            caller_context = dict(context or {})
            adapter = self._resolve_adapter(ref_map, caller_context)
            observation = self._capture(adapter)
            elements = self._grounded_elements(
                observation, adapter, requirement_map, ref_map, caller_context)
            judgement = self._judge(
                requirement_map, ref_map, observation, elements)
            prerequisite = self._build_prerequisite(
                requirement_map, ref_map, judgement)
        except Exception as exc:
            return self._failed_result(
                requirement_map,
                reason=f"visual prerequisite check failed: {type(exc).__name__}: {exc}",
                code="visual_check_failed",
            )

        self._merge_caller_world(caller_context, prerequisite.resource_slot)
        scope = _Scope(
            prerequisite=prerequisite,
            requirement=requirement_map,
            ref=ref_map,
            caller_context=caller_context,
            adapter=adapter,
            initial_judgement=judgement,
            resource_slot=prerequisite.resource_slot,
        )
        self._scopes[prerequisite.prerequisite_id] = scope
        self._action_events[prerequisite.prerequisite_id] = []
        report = self.runtime.resolve([prerequisite])
        output = report.to_dict()
        output["satisfied"] = report.ready
        output["action_steps"] = report.gui_action_count
        output["needs_user"] = report.status == "needs_user"
        if self._report_has_evidence_code(
                output, {"automatic_login_forbidden", "login_action_forbidden"}):
            output["status"] = "needs_user"
            output["ready"] = False
            output["satisfied"] = False
            output["needs_user"] = True
        output["owned_by_run"] = any(
            item.get("prerequisite_id") == prerequisite.prerequisite_id
            and not item.get("cleaned")
            for item in self.runtime.owned_resources
        )
        output["owned_resources"] = [
            dict(item) for item in self.runtime.owned_resources]
        output["action_events"] = [
            dict(item)
            for item in self._action_events.get(prerequisite.prerequisite_id, [])
        ]
        output["reason"] = self._report_reason(output)
        return output

    def cleanup(self) -> CleanupReport:
        """Delegate inverse, idempotent run-owned cleanup to the runtime."""

        return self.runtime.cleanup()

    # -- requirement / recipe conversion ---------------------------------

    @staticmethod
    def _normalise_requirement(requirement: Any) -> Dict[str, Any]:
        if isinstance(requirement, Mapping):
            value = dict(requirement)
        elif isinstance(requirement, str) and requirement.strip():
            value = {"fact": requirement.strip(), "description": requirement.strip()}
        else:
            raise VisualPrerequisiteError("requirement must be a non-empty string or mapping")
        fact = str(
            value.get("fact")
            or value.get("name")
            or value.get("description")
            or ""
        ).strip()
        if not fact:
            raise VisualPrerequisiteError("requirement has no fact/name/description")
        value["fact"] = fact
        return value

    def _resolve_adapter(
        self,
        ref: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> PrerequisiteLiveAdapter:
        adapter = context.get("adapter")
        app_id = str(
            ref.get("app_id") or ref.get("app")
            or context.get("current_app_id") or ""
        )
        if adapter is None and app_id in self.app_adapters:
            adapter = self.app_adapters[app_id]
        if adapter is None and self.adapter_provider is not None:
            adapter = _call_compatible(
                self.adapter_provider, app_id, dict(ref), dict(context))
        if adapter is None:
            raise VisualPrerequisiteError(f"no live adapter for app {app_id!r}")
        for method in ("capture", "ground", "execute"):
            if not callable(getattr(adapter, method, None)):
                raise VisualPrerequisiteError(
                    f"live adapter is missing callable {method}()")
        return adapter

    @staticmethod
    def _capture(adapter: PrerequisiteLiveAdapter) -> Any:
        observation = _call_compatible(adapter.capture)
        if observation is None:
            raise VisualPrerequisiteError("live capture returned no observation")
        return observation

    def _grounded_elements(
        self,
        observation: Any,
        adapter: PrerequisiteLiveAdapter,
        requirement: Mapping[str, Any],
        ref: Mapping[str, Any],
        context: Mapping[str, Any],
    ) -> Any:
        if self.elements_provider is not None:
            elements = _call_compatible(
                self.elements_provider,
                observation,
                adapter,
                dict(requirement),
                dict(ref),
                dict(context),
            )
            if elements is None:
                raise VisualPrerequisiteError("elements provider returned no result")
            return elements
        for source in (context, ref):
            for key in ("grounded_elements", "elements"):
                if key in source and source.get(key) is not None:
                    return source.get(key)
        for name in ("grounded_elements", "get_elements", "perceive"):
            provider = getattr(adapter, name, None)
            if callable(provider):
                elements = _call_compatible(provider, observation)
                if elements is None:
                    raise VisualPrerequisiteError(
                        f"adapter {name}() returned no grounding result")
                return elements
        # Empty grounding is valid for screenshot-visible state text; action
        # execution still requires adapter.ground() to return a concrete target.
        return []

    def _build_prerequisite(
        self,
        requirement: Mapping[str, Any],
        ref: Mapping[str, Any],
        judgement: _VisualJudgement,
    ) -> Prerequisite:
        declared_kind = str(requirement.get("kind") or "").strip().lower()
        login_boundary = self._looks_like_login_boundary(requirement, ref)
        if declared_kind:
            if declared_kind not in self._KINDS:
                raise VisualPrerequisiteError(
                    f"unsupported declared prerequisite kind {declared_kind!r}")
            if declared_kind != PrerequisiteKind.LOGIN.value \
                    and judgement.kind.value != declared_kind:
                raise VisualPrerequisiteError(
                    "VLM kind mismatch: "
                    f"declared={declared_kind!r}, observed={judgement.kind.value!r}")
            kind = PrerequisiteKind(declared_kind)
        else:
            kind = judgement.kind
        # Application login is a user boundary even when a VLM mistakenly
        # describes it as a generic state/resource gate.
        if login_boundary:
            kind = PrerequisiteKind.LOGIN

        fact = str(requirement["fact"])
        expected = requirement.get("expected", requirement.get("value", True))
        resource_slot = ""
        if kind == PrerequisiteKind.RESOURCE:
            resource_slot = str(
                requirement.get("resource_slot")
                or requirement.get("slot")
                or judgement.raw.get("resource_slot")
                or self._slot_from_fact(fact)
            ).strip()
            if not resource_slot:
                raise VisualPrerequisiteError("resource prerequisite has no binding slot")
            judgement.bindings = self._normalise_resource_binding(
                judgement.bindings, judgement.raw, resource_slot)

        requirement_id = self._prerequisite_id(
            requirement, ref, fact=fact, kind=kind.value)
        declared_setup = requirement.get("setup_recipes")
        if declared_setup is None:
            declared_setup = requirement.get("setup_recipe")
        if not declared_setup:
            declared_setup = ref.get("setup_recipe") or ref.get("setup_recipes")
        generated_setup = judgement.setup_recipes
        setup_source = declared_setup if declared_setup else generated_setup

        declared_cleanup = requirement.get("cleanup") or ref.get("cleanup")
        cleanup_source = declared_cleanup if declared_cleanup else judgement.cleanup
        # Login is a hard user boundary.  Ignore even malformed or credential-
        # bearing recipes from capability/VLM data so an unmet login always
        # reaches PrerequisiteRuntime's explicit ``needs_user`` result.
        if kind == PrerequisiteKind.LOGIN:
            setup_recipes: Tuple[SetupRecipe, ...] = ()
        else:
            setup_recipes = self._parse_recipes(
                setup_source,
                prerequisite_id=requirement_id,
                fact=fact,
                kind=kind,
                global_cleanup=cleanup_source,
            )

        # A visibly locked system surface may always attempt a password-free
        # Unlock in the sandbox.  This is never synthesized for app login.
        if (kind == PrerequisiteKind.AUTHORIZATION
                and not judgement.satisfied
                and not setup_recipes):
            setup_recipes = (self._unlock_recipe(requirement_id),)

        dependency_facts = requirement.get("requires_facts")
        if dependency_facts is None:
            dependency_facts = requirement.get("world_requires")
        if not isinstance(dependency_facts, Mapping):
            dependency_facts = {}
        produces = {fact: expected}
        explicit_produces = requirement.get("produces")
        if isinstance(explicit_produces, Mapping):
            produces.update(explicit_produces)
        return Prerequisite(
            prerequisite_id=requirement_id,
            kind=kind,
            description=str(requirement.get("description") or fact),
            check_key=str(requirement.get("check_key") or fact),
            resource_slot=resource_slot,
            requires=dict(dependency_facts),
            produces=produces,
            setup_recipes=setup_recipes,
            metadata={
                "app_id": str(ref.get("app_id") or ref.get("app") or ""),
                "capability_id": str(ref.get("capability_id") or ref.get("ref_id") or ""),
                "owned_by_run": kind == PrerequisiteKind.RESOURCE,
            },
        )

    def _parse_recipes(
        self,
        raw: Any,
        *,
        prerequisite_id: str,
        fact: str,
        kind: PrerequisiteKind,
        global_cleanup: Any,
    ) -> Tuple[SetupRecipe, ...]:
        if not raw:
            return ()
        recipe_specs: List[Any]
        if isinstance(raw, Mapping):
            nested = raw.get("recipes")
            if isinstance(nested, Sequence) and not isinstance(nested, (str, bytes)):
                recipe_specs = list(nested)
            else:
                recipe_specs = [raw]
        elif isinstance(raw, Sequence) and not isinstance(raw, (str, bytes)):
            values = list(raw)
            if values and all(
                isinstance(item, Mapping)
                and any(key in item for key in (
                    "actions", "steps", "setup_steps", "recipe_id"))
                for item in values
            ):
                recipe_specs = values
            else:
                recipe_specs = [{"recipe_id": "declared_setup", "actions": values}]
        else:
            recipe_specs = [{"recipe_id": "declared_setup", "actions": [raw]}]

        recipes: List[SetupRecipe] = []
        for index, item in enumerate(recipe_specs):
            spec = dict(item) if isinstance(item, Mapping) else {"actions": [item]}
            target_fact = str(
                spec.get("fact") or spec.get("prerequisite")
                or spec.get("prerequisite_id") or ""
            ).strip()
            if target_fact and target_fact not in {fact, prerequisite_id}:
                continue
            action_source = (
                spec.get("actions")
                or spec.get("steps")
                or spec.get("setup_steps")
                or []
            )
            cleanup_source = (
                spec.get("cleanup_actions")
                or spec.get("cleanup")
                or global_cleanup
                or []
            )
            actions = self._parse_actions(
                action_source,
                prefix=f"{prerequisite_id}:setup:{index}",
                phase="setup",
                owned_by_run=kind == PrerequisiteKind.RESOURCE,
            )
            if kind == PrerequisiteKind.RESOURCE and actions:
                actions = self._mark_resource_creation(actions)
            cleanup_actions = self._parse_actions(
                cleanup_source,
                prefix=f"{prerequisite_id}:cleanup:{index}",
                phase="cleanup",
                owned_by_run=kind == PrerequisiteKind.RESOURCE,
            )
            if not actions:
                continue
            estimated = spec.get(
                "estimated_gui_actions", spec.get("action_steps"))
            try:
                estimated_value = max(0, int(estimated)) if estimated is not None else None
            except (TypeError, ValueError):
                estimated_value = None
            recipe_id = str(
                spec.get("recipe_id") or spec.get("id") or f"recipe_{index + 1}")
            requires = spec.get("requires") if isinstance(spec.get("requires"), Mapping) else {}
            produces = spec.get("produces") if isinstance(spec.get("produces"), Mapping) else {}
            bindings = spec.get("bindings") if isinstance(spec.get("bindings"), Mapping) else {}
            recipes.append(SetupRecipe(
                recipe_id=recipe_id,
                actions=actions,
                requires=dict(requires),
                produces=dict(produces),
                bindings=dict(bindings),
                cleanup_actions=cleanup_actions,
                estimated_gui_actions=estimated_value,
            ))
        return tuple(recipes)

    @staticmethod
    def _mark_resource_creation(
        actions: Tuple[RuntimeAction, ...],
    ) -> Tuple[RuntimeAction, ...]:
        """Ensure one setup action establishes provisional run ownership.

        A schema may explicitly mark the actual create/save action with
        ``creates_resource``.  Otherwise the final setup action is the safest
        default.  The provisional binding lets the runtime clean a resource
        even when the mandatory post-create VLM check fails before it can name
        the concrete instance.
        """

        if any(bool(action.payload.get("creates_resource")) for action in actions):
            return actions
        last = actions[-1]
        payload = dict(last.payload)
        payload["creates_resource"] = True
        replacement = RuntimeAction(
            action_id=last.action_id,
            name=last.name,
            payload=payload,
            requires=dict(last.requires),
            gui_action_cost=last.gui_action_cost,
        )
        return tuple(actions[:-1]) + (replacement,)

    def _parse_actions(
        self,
        raw: Any,
        *,
        prefix: str,
        phase: str,
        owned_by_run: bool,
    ) -> Tuple[RuntimeAction, ...]:
        if not raw:
            return ()
        if isinstance(raw, (str, Mapping)):
            values: List[Any] = [raw]
        elif isinstance(raw, Sequence):
            values = list(raw)
        else:
            values = [raw]
        actions: List[RuntimeAction] = []
        for index, item in enumerate(values):
            if isinstance(item, Mapping):
                payload = dict(item)
            elif isinstance(item, str) and item.strip():
                payload = {"instruction": item.strip(), "action": item.strip()}
            else:
                raise VisualPrerequisiteError(
                    f"invalid {phase} action at index {index}: {item!r}")
            if self._contains_secret_field(payload):
                raise VisualPrerequisiteError(
                    f"{phase} action contains a credential-like field")
            payload.setdefault("phase", phase)
            payload.setdefault("owned_by_run", owned_by_run)
            action_id = str(
                payload.get("action_id") or payload.get("id")
                or f"{prefix}:{index}"
            )
            name = str(
                payload.get("name") or payload.get("instruction")
                or payload.get("element_label") or payload.get("action") or action_id
            )
            cost = payload.get(
                "gui_action_cost", payload.get("action_steps", 1))
            try:
                cost_value = max(0, int(cost))
            except (TypeError, ValueError):
                cost_value = 1
            requires = payload.get("requires")
            if not isinstance(requires, Mapping):
                requires = {}
            actions.append(RuntimeAction(
                action_id=action_id,
                name=name,
                payload=payload,
                requires=dict(requires),
                gui_action_cost=cost_value,
            ))
        return tuple(actions)

    @classmethod
    def _contains_secret_field(cls, value: Any) -> bool:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if str(key).strip().lower() in cls._SECRET_KEYS:
                    return True
                if cls._contains_secret_field(child):
                    return True
        elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return any(cls._contains_secret_field(item) for item in value)
        return False

    @classmethod
    def _looks_like_login_boundary(
        cls, requirement: Mapping[str, Any], ref: Mapping[str, Any]
    ) -> bool:
        values = [
            requirement.get("fact"), requirement.get("name"),
            requirement.get("description"), requirement.get("blocked_reason"),
            ref.get("requires_login"), ref.get("login_required"),
        ]
        if ref.get("requires_login") is True or ref.get("login_required") is True:
            return True
        text = " ".join(str(value or "") for value in values).casefold()
        return any(term in text for term in cls._LOGIN_TERMS)

    @classmethod
    def _contains_login_action(cls, value: Any) -> bool:
        if isinstance(value, Mapping):
            return any(cls._contains_login_action(child) for child in value.values())
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return any(cls._contains_login_action(child) for child in value)
        if isinstance(value, str):
            text = value.casefold()
            return any(term in text for term in cls._LOGIN_TERMS)
        return False

    @staticmethod
    def _unlock_recipe(prerequisite_id: str) -> SetupRecipe:
        action = RuntimeAction(
            action_id=f"{prerequisite_id}:system_unlock",
            name="Unlock system settings",
            payload={
                "action": "click",
                "element_label": "Unlock",
                "phase": "setup",
                "owned_by_run": False,
                "authorization_mode": "password_free",
                "password_required": False,
            },
            gui_action_cost=1,
        )
        return SetupRecipe(
            recipe_id="sandbox_password_free_unlock",
            actions=(action,),
            estimated_gui_actions=1,
        )

    @staticmethod
    def _slot_from_fact(fact: str) -> str:
        match = re.search(r"exists\s*\(\s*([^\)]+)\s*\)", fact, re.I)
        if match:
            value = re.sub(r"[^a-zA-Z0-9_]+", "_", match.group(1)).strip("_")
            return value or "resource_ref"
        cleaned = re.sub(r"[^a-zA-Z0-9_]+", "_", fact).strip("_").lower()
        if cleaned.endswith("_exists"):
            cleaned = cleaned[:-7]
        if cleaned.endswith("_ref"):
            return cleaned
        return f"{cleaned or 'resource'}_ref"

    @staticmethod
    def _normalise_resource_binding(
        bindings: Mapping[str, Any],
        raw: Mapping[str, Any],
        slot: str,
    ) -> Dict[str, Any]:
        result = dict(bindings)
        if slot in result:
            return result
        binding = raw.get("binding")
        if isinstance(binding, Mapping):
            binding_slot = str(binding.get("slot") or slot)
            if "value" in binding:
                result[binding_slot] = binding.get("value")
            elif binding_slot in binding:
                result[binding_slot] = binding.get(binding_slot)
        elif binding is not None:
            result[slot] = binding
        if slot not in result and "binding_value" in raw:
            result[slot] = raw.get("binding_value")
        if slot not in result and len(result) == 1:
            result[slot] = next(iter(result.values()))
        return result

    @staticmethod
    def _prerequisite_id(
        requirement: Mapping[str, Any],
        ref: Mapping[str, Any],
        *,
        fact: str,
        kind: str,
    ) -> str:
        explicit = str(
            requirement.get("prerequisite_id") or requirement.get("id") or ""
        ).strip()
        app_id = str(ref.get("app_id") or ref.get("app") or "")
        capability_id = str(
            ref.get("capability_id") or ref.get("ref_id")
            or ref.get("name") or ""
        )
        seed = "|".join((app_id, capability_id, fact, kind))
        suffix = sha256(seed.encode("utf-8")).hexdigest()[:12]
        return f"{explicit or fact}:{suffix}"

    # -- visual check -----------------------------------------------------

    def _judge(
        self,
        requirement: Mapping[str, Any],
        ref: Mapping[str, Any],
        observation: Any,
        elements: Any,
    ) -> _VisualJudgement:
        prompt = self._check_prompt(requirement, ref, elements)
        raw = self._invoke_vlm(prompt, [self._image_payload(observation)])
        kind_raw = str(raw.get("kind") or "").strip().lower()
        if kind_raw not in self._KINDS:
            raise VisualPrerequisiteError(
                "VLM prerequisite output omitted a valid resource/state/authorization/login kind")
        satisfied = raw.get("satisfied")
        if not isinstance(satisfied, bool):
            aliases = {
                PrerequisiteKind.RESOURCE.value: "resource_exists",
                PrerequisiteKind.STATE.value: "state_satisfied",
                PrerequisiteKind.AUTHORIZATION.value: "authorized",
                PrerequisiteKind.LOGIN.value: "logged_in",
            }
            candidate = raw.get(aliases[kind_raw])
            if isinstance(candidate, bool):
                satisfied = candidate
        if not isinstance(satisfied, bool):
            raise VisualPrerequisiteError("VLM prerequisite output omitted boolean satisfied")
        facts = dict(raw.get("facts", {}) or {}) if isinstance(raw.get("facts", {}), Mapping) else {}
        bindings = dict(raw.get("bindings", {}) or {}) if isinstance(raw.get("bindings", {}), Mapping) else {}
        evidence_raw = raw.get("evidence")
        if isinstance(evidence_raw, Sequence) and not isinstance(evidence_raw, (str, bytes)):
            evidence_values: Iterable[Any] = evidence_raw
        else:
            evidence_values = [evidence_raw] if evidence_raw is not None else []
        evidence = [self._evidence_from_vlm(item, raw) for item in evidence_values]
        if not evidence:
            evidence = [Evidence(
                code="visual_prerequisite_judgement",
                message=str(raw.get("reason") or "VLM returned a structured prerequisite judgement."),
                source="vlm",
                details={"kind": kind_raw, "satisfied": satisfied},
            )]
        return _VisualJudgement(
            kind=PrerequisiteKind(kind_raw),
            satisfied=satisfied,
            facts=facts,
            bindings=bindings,
            evidence=evidence,
            setup_recipes=raw.get("setup_recipes") or raw.get("setup_recipe"),
            cleanup=raw.get("cleanup") or raw.get("cleanup_actions"),
            raw=dict(raw),
        )

    @staticmethod
    def _evidence_from_vlm(value: Any, raw: Mapping[str, Any]) -> Evidence:
        if isinstance(value, Mapping):
            return Evidence(
                code=str(value.get("code") or "visual_prerequisite_judgement"),
                message=str(value.get("message") or value.get("reason") or ""),
                source="vlm",
                details=dict(value.get("details", {}) or {}),
            )
        return Evidence(
            code="visual_prerequisite_judgement",
            message=str(value or raw.get("reason") or ""),
            source="vlm",
            details={
                "kind": str(raw.get("kind") or ""),
                "satisfied": raw.get("satisfied"),
            },
        )

    def _check_prompt(
        self,
        requirement: Mapping[str, Any],
        ref: Mapping[str, Any],
        elements: Any,
    ) -> str:
        requirement_json = _safe_json(requirement, limit=8000)
        ref_summary = {
            key: ref.get(key) for key in (
                "app_id", "capability_id", "name", "node_id", "page_name",
                "params", "elements",
            ) if key in ref
        }
        return (
            "Judge one GUI prerequisite using only the current screenshot and grounded elements.\n"
            "Return exactly one JSON object. Required fields:\n"
            '{"kind":"resource|state|authorization|login",'
            '"satisfied":true|false,"facts":{},"bindings":{},'
            '"evidence":{"message":"visible evidence"},'
            '"setup_recipes":[],"cleanup":[]}\n'
            "Rules:\n"
            "- resource: satisfied only when a suitable existing resource is visibly available; "
            "if true, bindings must contain a stable visible resource value.\n"
            "- state: satisfied only when the requested visible state already holds.\n"
            "- authorization: system Unlock/permission gate only. The sandbox has no password.\n"
            "- login: application account/session gate. Never propose credentials or automatic login.\n"
            "- If unmet and no declared setup recipe is available, you may propose 1-3 GUI-only "
            "setup_recipes, each with recipe_id, estimated_gui_actions and grounded actions. "
            "Minimize GUI actions. Every created resource recipe must include cleanup actions.\n"
            "- Actions may refer only to visible grounded ids/labels or explicit keyboard/back/scroll. "
            "Do not infer hidden success and do not emit passwords/tokens.\n"
            f"Requirement: {requirement_json}\n"
            f"Capability: {_safe_json(ref_summary, limit=8000)}\n"
            f"Grounded elements: {_safe_json(elements, limit=16000)}"
        )

    def _invoke_vlm(self, prompt: str, images: Sequence[Any]) -> Dict[str, Any]:
        try:
            if hasattr(self.vlm_agent, "predict_mm"):
                raw = self.vlm_agent.predict_mm(prompt, list(images))
            elif callable(self.vlm_agent):
                raw = self.vlm_agent(prompt, list(images))
            else:
                raise VisualPrerequisiteError("VLM agent is not callable")
            if isinstance(raw, tuple):
                raw = raw[0] if raw else ""
            if isinstance(raw, Mapping):
                return dict(raw)
            text = str(raw or "").strip()
            match = self._JSON_OBJECT.search(text)
            if match:
                text = match.group(0)
            parsed = json.loads(text)
            if not isinstance(parsed, Mapping):
                raise ValueError("VLM output is not a JSON object")
            return dict(parsed)
        except VisualPrerequisiteError:
            raise
        except Exception as exc:
            raise VisualPrerequisiteError(
                f"VLM transport/parse failure: {type(exc).__name__}: {exc}") from exc

    @staticmethod
    def _image_payload(observation: Any) -> Any:
        if isinstance(observation, Mapping):
            for key in ("screenshot", "image", "frame"):
                if observation.get(key) is not None:
                    return observation.get(key)
        return observation

    # -- callbacks consumed by PrerequisiteRuntime -----------------------

    def _check_callback(
        self,
        prerequisite: Prerequisite,
        _runtime_context: RuntimeContext,
    ) -> CheckResult:
        scope = self._scopes.get(prerequisite.prerequisite_id)
        if scope is None:
            raise VisualPrerequisiteError(
                f"no visual scope for prerequisite {prerequisite.prerequisite_id!r}")
        if scope.initial_judgement is not None:
            judgement = scope.initial_judgement
            scope.initial_judgement = None
        else:
            observation = self._capture(scope.adapter)
            elements = self._grounded_elements(
                observation,
                scope.adapter,
                scope.requirement,
                scope.ref,
                scope.caller_context,
            )
            judgement = self._judge(
                scope.requirement, scope.ref, observation, elements)
            if judgement.kind != prerequisite.kind:
                raise VisualPrerequisiteError(
                    "post-setup VLM kind changed from "
                    f"{prerequisite.kind.value!r} to {judgement.kind.value!r}")
        if prerequisite.kind == PrerequisiteKind.RESOURCE:
            judgement.bindings = self._normalise_resource_binding(
                judgement.bindings, judgement.raw, scope.resource_slot)
        return judgement.as_check_result()

    def _action_callback(
        self,
        action: RuntimeAction,
        prerequisite: Prerequisite,
        runtime_context: RuntimeContext,
    ) -> ActionResult:
        scope = self._scopes.get(prerequisite.prerequisite_id)
        if scope is None:
            raise VisualPrerequisiteError(
                f"no live scope for prerequisite {prerequisite.prerequisite_id!r}")
        payload = dict(action.payload)
        if prerequisite.kind == PrerequisiteKind.LOGIN:
            return ActionResult(
                success=False,
                gui_action_count=0,
                evidence=[Evidence(
                    code="automatic_login_forbidden",
                    message="Application login actions require the user.",
                )],
            )
        if self._contains_secret_field(payload):
            return ActionResult(
                success=False,
                gui_action_count=0,
                evidence=[Evidence(
                    code="credential_action_forbidden",
                    message="Credential-bearing prerequisite actions are not executed.",
                )],
            )
        if self._contains_login_action(payload):
            return ActionResult(
                success=False,
                gui_action_count=0,
                evidence=[Evidence(
                    code="login_action_forbidden",
                    message="Application sign-in actions require the user.",
                )],
            )
        observation = None
        grounded = None
        execution = None
        settled = None
        try:
            if payload.get("phase") == "cleanup":
                activate = getattr(scope.adapter, "activate", None)
                if callable(activate):
                    activation = _call_compatible(activate)
                    if activation is False or (
                        isinstance(activation, Mapping)
                        and activation.get("success") is False
                    ):
                        return ActionResult(
                            success=False,
                            gui_action_count=0,
                            evidence=[Evidence(
                                code="cleanup_app_activation_failed",
                                message="The resource-owning app could not be activated for cleanup.",
                                details={"action_id": action.action_id},
                            )],
                        )
                    activation_settle = getattr(scope.adapter, "settle", None)
                    if callable(activation_settle):
                        _call_compatible(activation_settle, activation)
            observation = self._capture(scope.adapter)
            grounded = _call_compatible(
                scope.adapter.ground, payload, observation)
            if grounded is None or grounded is False:
                return ActionResult(
                    success=False,
                    gui_action_count=0,
                    evidence=[Evidence(
                        code="prerequisite_grounding_failed",
                        message="The live adapter could not ground the prerequisite action.",
                        details={"action_id": action.action_id},
                    )],
                )
            if isinstance(grounded, Mapping) and (
                grounded.get("grounded") is False
                or grounded.get("success") is False
            ):
                return ActionResult(
                    success=False,
                    gui_action_count=0,
                    evidence=[Evidence(
                        code="prerequisite_grounding_failed",
                        message="The live adapter explicitly rejected grounding.",
                        details={"action_id": action.action_id},
                    )],
                )
            execution = _call_compatible(scope.adapter.execute, grounded)
            settle = getattr(scope.adapter, "settle", None)
            if callable(settle):
                settled = _call_compatible(settle, execution)
            if settled is None:
                # Capture the concrete landing for graph/trajectory attribution;
                # this is a screenshot read, not an extra GUI action.
                settled = self._capture(scope.adapter)
        except Exception as exc:
            # Once execute() has been entered an adapter may have completed a
            # prefix before raising.  Preserve the attempted GUI event instead
            # of silently losing it from the trajectory.
            if grounded is not None:
                self._append_action_events(
                    prerequisite.prerequisite_id,
                    action=action,
                    payload=payload,
                    grounded=grounded,
                    before=observation,
                    after=settled if settled is not None else execution,
                    outcome="execution_failed",
                    committed=False,
                    gui_action_count=max(1, int(action.gui_action_cost)),
                    detail=f"{type(exc).__name__}: {exc}",
                )
            return ActionResult(
                success=False,
                gui_action_count=0,
                evidence=[Evidence(
                    code="prerequisite_live_action_failed",
                    message="The injected live action failed closed.",
                    details={
                        "action_id": action.action_id,
                        "error": f"{type(exc).__name__}: {exc}",
                    },
                )],
            )

        success, count, facts, bindings, note = self._normalise_execution(
            execution, action.gui_action_cost, scope.resource_slot)
        self._append_action_events(
            prerequisite.prerequisite_id,
            action=action,
            payload=payload,
            grounded=grounded,
            before=observation,
            after=settled if settled is not None else execution,
            outcome=("executed" if success else "adapter_rejected"),
            committed=bool(success),
            gui_action_count=count,
            detail=note,
        )
        if (success
                and prerequisite.kind == PrerequisiteKind.RESOURCE
                and payload.get("phase") == "setup"
                and payload.get("owned_by_run")
                and payload.get("creates_resource")
                and scope.resource_slot
                and scope.resource_slot not in bindings):
            bindings[scope.resource_slot] = {
                "owned_by_run": True,
                "run_id": runtime_context.run_id,
                "prerequisite_id": prerequisite.prerequisite_id,
                "selector": (
                    payload.get("resource_selector")
                    or payload.get("element_label")
                    or payload.get("name")
                    or payload.get("instruction")
                    or action.name
                ),
            }
        return ActionResult(
            success=success,
            gui_action_count=count,
            facts=facts,
            bindings=bindings,
            evidence=[Evidence(
                code=("prerequisite_live_action_executed" if success
                      else "prerequisite_live_action_rejected"),
                message=note or (
                    "The injected live prerequisite action executed; visual post-check is pending."
                    if success else "The injected live adapter rejected the action."),
                details={
                    "action_id": action.action_id,
                    "phase": payload.get("phase", "setup"),
                    "owned_by_run": bool(payload.get("owned_by_run")),
                },
            )],
        )

    def _append_action_events(
        self,
        prerequisite_id: str,
        *,
        action: RuntimeAction,
        payload: Mapping[str, Any],
        grounded: Any,
        before: Any,
        after: Any,
        outcome: str,
        committed: bool,
        gui_action_count: int,
        detail: str = "",
    ) -> None:
        """Record concrete GUI operations without inventing semantic edges.

        A live adapter may ground one runtime recipe item to several primitive
        actions (for example CLICK then TYPE).  Emit one event per primitive so
        M13 and traversal retain an honest action ledger.  Observations remain
        in-memory only; writers decide how to persist screenshots.
        """

        count = max(0, int(gui_action_count or 0))
        primitives: List[Any] = []
        if isinstance(grounded, Mapping):
            raw_actions = grounded.get("actions")
            if isinstance(raw_actions, Sequence) and not isinstance(
                    raw_actions, (str, bytes)):
                primitives = list(raw_actions)
            elif isinstance(grounded.get("action"), Mapping):
                primitives = [grounded.get("action")]
        if not primitives:
            primitives = [dict(payload)]

        # Normally adapters report one count per primitive.  If they report a
        # different total, preserve the total deterministically on the last
        # event instead of adding a fictitious GUI action.
        per_event = [1 if count else 0 for _ in primitives]
        if per_event:
            per_event[-1] += count - sum(per_event)
            if per_event[-1] < 0:
                per_event = [0 for _ in primitives]
                for index in range(min(count, len(per_event))):
                    per_event[index] = 1

        bucket = self._action_events.setdefault(prerequisite_id, [])
        scope = self._scopes.get(prerequisite_id)
        event_app_id = str(
            (scope.ref.get("app_id") or scope.ref.get("app") or "")
            if scope is not None else "")
        for index, primitive in enumerate(primitives):
            bucket.append({
                "event_index": len(bucket),
                "prerequisite_id": prerequisite_id,
                "app_id": event_app_id,
                "action_id": action.action_id,
                "action_name": action.name,
                "phase": str(payload.get("phase") or "setup"),
                "action_spec": (
                    dict(primitive) if isinstance(primitive, Mapping)
                    else {"action": primitive}
                ),
                "grounding": _public_grounding(grounded),
                "gui_action_count": per_event[index],
                "action_steps": per_event[index],
                "outcome": str(outcome),
                "committed": bool(committed),
                "detail": str(detail or ""),
                "observation_before": before if index == 0 else None,
                "observation_after": after if index == len(primitives) - 1 else None,
            })

    @staticmethod
    def _normalise_execution(
        execution: Any,
        default_count: int,
        resource_slot: str,
    ) -> Tuple[bool, int, Dict[str, Any], Dict[str, Any], str]:
        if isinstance(execution, bool):
            return execution, default_count, {}, {}, ""
        if not isinstance(execution, Mapping):
            # No exception means dispatch succeeded.  The runtime's mandatory
            # post-setup visual check remains the semantic commit gate.
            return True, default_count, {}, {}, ""
        explicit = execution.get("success", execution.get("ok", True))
        success = explicit if isinstance(explicit, bool) else False
        raw_count = execution.get(
            "gui_action_count", execution.get("action_steps", default_count))
        try:
            count = max(0, int(raw_count))
        except (TypeError, ValueError):
            count = default_count
        facts = dict(execution.get("facts", {}) or {}) if isinstance(
            execution.get("facts", {}), Mapping) else {}
        bindings = dict(execution.get("bindings", {}) or {}) if isinstance(
            execution.get("bindings", {}), Mapping) else {}
        created = execution.get("created_resource")
        if resource_slot and created is not None and resource_slot not in bindings:
            bindings[resource_slot] = created
        note = str(execution.get("reason") or execution.get("evidence") or "")
        return success, count, facts, bindings, note

    def _merge_caller_world(
        self,
        context: Mapping[str, Any],
        resource_slot: str,
    ) -> None:
        facts = context.get("world_facts")
        if isinstance(facts, Mapping):
            self.runtime.context.world_facts.update(facts)
        bindings = context.get("resource_bindings")
        if isinstance(bindings, Mapping):
            self.runtime.context.resource_bindings.update(bindings)
        blackboard = context.get("blackboard")
        if isinstance(blackboard, Mapping):
            self.runtime.context.world_facts.update(blackboard)
            if resource_slot and resource_slot in blackboard:
                self.runtime.context.resource_bindings[resource_slot] = blackboard[resource_slot]

    def _failed_result(
        self,
        requirement: Mapping[str, Any],
        *,
        reason: str,
        code: str,
    ) -> Dict[str, Any]:
        return {
            "status": "failed",
            "satisfied": False,
            "ready": False,
            "needs_user": False,
            "reason": reason,
            "gui_action_count": 0,
            "action_steps": 0,
            "world_facts": dict(self.runtime.context.world_facts),
            "resource_bindings": dict(self.runtime.context.resource_bindings),
            "owned_by_run": False,
            "action_events": [],
            "evidence": [{
                "code": code,
                "message": reason,
                "source": "visual_prerequisite_agent",
                "details": {"fact": str(requirement.get("fact") or "")},
            }],
            "results": [],
        }

    @staticmethod
    def _report_reason(report: Mapping[str, Any]) -> str:
        results = report.get("results") or []
        if isinstance(results, Sequence) and results:
            last = results[-1]
            if isinstance(last, Mapping):
                if last.get("error"):
                    return str(last.get("error"))
                evidence = last.get("evidence") or []
                if isinstance(evidence, Sequence) and evidence:
                    item = evidence[-1]
                    if isinstance(item, Mapping) and item.get("message"):
                        return str(item.get("message"))
        return str(report.get("status") or "")

    @staticmethod
    def _report_has_evidence_code(
        report: Mapping[str, Any], codes: set[str]
    ) -> bool:
        for result in report.get("results") or []:
            if not isinstance(result, Mapping):
                continue
            for evidence in result.get("evidence") or []:
                if isinstance(evidence, Mapping) \
                        and str(evidence.get("code") or "") in codes:
                    return True
        return False


def _call_compatible(function: Callable[..., Any], *args: Any) -> Any:
    """Call an injected boundary with the longest signature-compatible prefix."""

    try:
        signature = inspect.signature(function)
    except (TypeError, ValueError):
        return function(*args)
    for count in range(len(args), -1, -1):
        candidate = args[:count]
        try:
            signature.bind(*candidate)
        except TypeError:
            continue
        return function(*candidate)
    return function(*args)


def _safe_json(value: Any, *, limit: int) -> str:
    try:
        text = json.dumps(value, ensure_ascii=False, default=str)
    except Exception:
        text = repr(value)
    if len(text) > limit:
        return text[:limit] + "...<truncated>"
    return text


def _public_grounding(value: Any) -> Any:
    """Return a bounded JSON-friendly grounding summary for trajectory output."""

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        return {"type": "bytes", "size": len(value)}
    if isinstance(value, Mapping):
        return {
            str(key): _public_grounding(child)
            for key, child in value.items()
            if str(key).lower() not in {"screenshot", "image", "frame"}
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        return [_public_grounding(child) for child in value]
    return repr(value)[:500]


__all__ = [
    "PrerequisiteLiveAdapter",
    "VisualPrerequisiteAgent",
    "VisualPrerequisiteError",
]
