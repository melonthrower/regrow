"""Shared prerequisite and fixture runtime for traversal and collection.

The runtime is deliberately independent from VM, VLM, and GUI implementations.
Callers inject two callbacks:

``check_callback(prerequisite, context)``
    Observes whether a prerequisite is already satisfied.  It may return a
    :class:`CheckResult`, a mapping, or a boolean.

``action_callback(action, prerequisite, context)``
    Executes one setup/cleanup GUI action.  It may return an
    :class:`ActionResult`, a mapping, or a boolean.

This module owns only orchestration state: world facts, resource bindings,
GUI-action accounting, and resources created by the current run.  It never
calls a VM or model by itself.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Union
from uuid import uuid4


class PrerequisiteKind(str, Enum):
    """Kinds understood by the shared runtime."""

    RESOURCE = "resource"
    STATE = "state"
    AUTHORIZATION = "authorization"
    LOGIN = "login"


@dataclass(frozen=True)
class Evidence:
    """Structured evidence emitted by checks, actions, and orchestration."""

    code: str
    message: str
    source: str = "runtime"
    details: Mapping[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "message": self.message,
            "source": self.source,
            "details": dict(self.details),
        }


EvidenceLike = Union[Evidence, str, Mapping[str, Any]]


def _normalise_evidence(items: Optional[Iterable[EvidenceLike]]) -> List[Evidence]:
    if isinstance(items, (Evidence, str, Mapping)):
        items = (items,)
    out: List[Evidence] = []
    for item in items or ():
        if isinstance(item, Evidence):
            out.append(item)
        elif isinstance(item, str):
            out.append(Evidence(code="callback_note", message=item, source="callback"))
        elif isinstance(item, Mapping):
            details = dict(item.get("details", {}) or {})
            out.append(Evidence(
                code=str(item.get("code", "callback_note") or "callback_note"),
                message=str(item.get("message", "") or ""),
                source=str(item.get("source", "callback") or "callback"),
                details=details,
            ))
        else:
            out.append(Evidence(
                code="callback_note",
                message=str(item),
                source="callback",
            ))
    return out


@dataclass(frozen=True)
class RuntimeAction:
    """One injected setup or cleanup action.

    ``gui_action_cost`` is used for recipe selection and as the default actual
    count when a callback returns only ``True``.  A callback can override the
    actual count through :class:`ActionResult`.
    """

    action_id: str
    name: str = ""
    payload: Mapping[str, Any] = field(default_factory=dict)
    requires: Mapping[str, Any] = field(default_factory=dict)
    gui_action_cost: int = 1

    def __post_init__(self) -> None:
        if not self.action_id:
            raise ValueError("RuntimeAction.action_id must not be empty")
        if self.gui_action_cost < 0:
            raise ValueError("RuntimeAction.gui_action_cost must be non-negative")

    def to_dict(self) -> Dict[str, Any]:
        return {
            "action_id": self.action_id,
            "name": self.name,
            "payload": dict(self.payload),
            "requires": dict(self.requires),
            "gui_action_cost": self.gui_action_cost,
        }


@dataclass(frozen=True)
class SetupRecipe:
    """A candidate way to satisfy a missing prerequisite."""

    recipe_id: str
    actions: Tuple[RuntimeAction, ...] = ()
    requires: Mapping[str, Any] = field(default_factory=dict)
    produces: Mapping[str, Any] = field(default_factory=dict)
    bindings: Mapping[str, Any] = field(default_factory=dict)
    cleanup_actions: Tuple[RuntimeAction, ...] = ()
    estimated_gui_actions: Optional[int] = None

    def __post_init__(self) -> None:
        if not self.recipe_id:
            raise ValueError("SetupRecipe.recipe_id must not be empty")
        object.__setattr__(self, "actions", tuple(self.actions))
        object.__setattr__(self, "cleanup_actions", tuple(self.cleanup_actions))
        if self.estimated_gui_actions is not None and self.estimated_gui_actions < 0:
            raise ValueError("estimated_gui_actions must be non-negative")

    @property
    def estimated_cost(self) -> int:
        if self.estimated_gui_actions is not None:
            return self.estimated_gui_actions
        return sum(action.gui_action_cost for action in self.actions)


@dataclass(frozen=True)
class Prerequisite:
    """A resource, state, authorization, or application-login requirement."""

    prerequisite_id: str
    kind: Union[PrerequisiteKind, str]
    description: str = ""
    check_key: str = ""
    resource_slot: str = ""
    requires: Mapping[str, Any] = field(default_factory=dict)
    produces: Mapping[str, Any] = field(default_factory=dict)
    setup_recipes: Tuple[SetupRecipe, ...] = ()
    cleanup_actions: Tuple[RuntimeAction, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        try:
            kind = self.kind if isinstance(self.kind, PrerequisiteKind) else PrerequisiteKind(self.kind)
        except ValueError as exc:
            raise ValueError(f"unsupported prerequisite kind: {self.kind!r}") from exc
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "setup_recipes", tuple(self.setup_recipes))
        object.__setattr__(self, "cleanup_actions", tuple(self.cleanup_actions))
        if not self.prerequisite_id:
            raise ValueError("Prerequisite.prerequisite_id must not be empty")
        if kind == PrerequisiteKind.RESOURCE and not self.resource_slot:
            raise ValueError("resource prerequisites require resource_slot")


@dataclass
class CheckResult:
    """Normalised result of a caller-provided prerequisite check."""

    satisfied: bool
    evidence: List[Evidence] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    bindings: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.evidence = _normalise_evidence(self.evidence)


@dataclass
class ActionResult:
    """Normalised result of one caller-provided GUI action."""

    success: bool
    gui_action_count: Optional[int] = None
    evidence: List[Evidence] = field(default_factory=list)
    facts: Dict[str, Any] = field(default_factory=dict)
    bindings: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.evidence = _normalise_evidence(self.evidence)
        if self.gui_action_count is not None and self.gui_action_count < 0:
            raise ValueError("gui_action_count must be non-negative")


@dataclass
class RuntimeContext:
    """Mutable world model shared by prerequisite checks and M13/traversal."""

    run_id: str = field(default_factory=lambda: uuid4().hex)
    world_facts: Dict[str, Any] = field(default_factory=dict)
    resource_bindings: Dict[str, Any] = field(default_factory=dict)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "world_facts": dict(self.world_facts),
            "resource_bindings": dict(self.resource_bindings),
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class AuthorizationPolicy:
    """Policy boundary for system authorization versus application login.

    The project default is a password-free sandbox where system authorization
    is allowed.  Application login is intentionally not covered by this grant.
    """

    sandbox: bool = True
    allow_system_authorization: bool = True
    password: Optional[str] = None


@dataclass
class PrerequisiteResult:
    prerequisite_id: str
    kind: str
    status: str
    satisfied: bool
    gui_action_count: int = 0
    evidence: List[Evidence] = field(default_factory=list)
    recipe_id: str = ""
    produced_facts: Dict[str, Any] = field(default_factory=dict)
    resource_bindings: Dict[str, Any] = field(default_factory=dict)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prerequisite_id": self.prerequisite_id,
            "kind": self.kind,
            "status": self.status,
            "satisfied": self.satisfied,
            "gui_action_count": self.gui_action_count,
            "evidence": [item.to_dict() for item in self.evidence],
            "recipe_id": self.recipe_id,
            "produced_facts": dict(self.produced_facts),
            "resource_bindings": dict(self.resource_bindings),
            "error": self.error,
        }


@dataclass
class ResolutionReport:
    status: str
    results: List[PrerequisiteResult]
    gui_action_count: int
    world_facts: Dict[str, Any]
    resource_bindings: Dict[str, Any]

    @property
    def ready(self) -> bool:
        return self.status == "ready"

    @property
    def evidence(self) -> List[Evidence]:
        return [item for result in self.results for item in result.evidence]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "ready": self.ready,
            "gui_action_count": self.gui_action_count,
            "world_facts": dict(self.world_facts),
            "resource_bindings": dict(self.resource_bindings),
            "results": [result.to_dict() for result in self.results],
        }


@dataclass
class _OwnedResource:
    prerequisite: Prerequisite
    recipe_id: str
    bindings: Dict[str, Any]
    cleanup_actions: Tuple[RuntimeAction, ...]
    before_facts: Dict[str, Any]
    before_bindings: Dict[str, Any]
    setup_facts: Dict[str, Any]
    setup_bindings: Dict[str, Any]
    cleanup_index: int = 0
    cleaned: bool = False

    def public_dict(self) -> Dict[str, Any]:
        return {
            "prerequisite_id": self.prerequisite.prerequisite_id,
            "resource_slot": self.prerequisite.resource_slot,
            "recipe_id": self.recipe_id,
            "bindings": dict(self.bindings),
            "cleanup_actions_remaining": max(
                0, len(self.cleanup_actions) - self.cleanup_index),
            "cleaned": self.cleaned,
        }


@dataclass
class CleanupResult:
    prerequisite_id: str
    status: str
    gui_action_count: int
    evidence: List[Evidence] = field(default_factory=list)
    error: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "prerequisite_id": self.prerequisite_id,
            "status": self.status,
            "gui_action_count": self.gui_action_count,
            "evidence": [item.to_dict() for item in self.evidence],
            "error": self.error,
        }


@dataclass
class CleanupReport:
    status: str
    results: List[CleanupResult]
    gui_action_count: int
    world_facts: Dict[str, Any]
    resource_bindings: Dict[str, Any]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "status": self.status,
            "gui_action_count": self.gui_action_count,
            "world_facts": dict(self.world_facts),
            "resource_bindings": dict(self.resource_bindings),
            "results": [result.to_dict() for result in self.results],
        }


CheckCallback = Callable[[Prerequisite, RuntimeContext], Union[CheckResult, Mapping[str, Any], bool]]
ActionCallback = Callable[
    [RuntimeAction, Prerequisite, RuntimeContext],
    Union[ActionResult, Mapping[str, Any], bool],
]


class PrerequisiteRuntime:
    """Resolve prerequisites and own fixtures created by the current run."""

    def __init__(
        self,
        *,
        check_callback: Optional[CheckCallback] = None,
        action_callback: Optional[ActionCallback] = None,
        context: Optional[RuntimeContext] = None,
        authorization_policy: Optional[AuthorizationPolicy] = None,
    ) -> None:
        self.check_callback = check_callback
        self.action_callback = action_callback
        self.context = context or RuntimeContext()
        self.authorization_policy = authorization_policy or AuthorizationPolicy()
        self._owned_resources: List[_OwnedResource] = []

    @property
    def owned_resources(self) -> Tuple[Mapping[str, Any], ...]:
        """Read-only public summaries of resources created by this run."""

        return tuple(resource.public_dict() for resource in self._owned_resources)

    @staticmethod
    def _facts_match(required: Mapping[str, Any], actual: Mapping[str, Any]) -> bool:
        return all(key in actual and actual[key] == expected
                   for key, expected in required.items())

    @staticmethod
    def _missing_facts(required: Mapping[str, Any], actual: Mapping[str, Any]) -> Dict[str, Any]:
        return {key: expected for key, expected in required.items()
                if key not in actual or actual[key] != expected}

    @staticmethod
    def _normalise_check(value: Union[CheckResult, Mapping[str, Any], bool]) -> CheckResult:
        if isinstance(value, CheckResult):
            return value
        if isinstance(value, bool):
            return CheckResult(satisfied=value)
        if isinstance(value, Mapping):
            return CheckResult(
                satisfied=bool(value.get("satisfied", value.get("ok", False))),
                evidence=_normalise_evidence(value.get("evidence", [])),
                facts=dict(value.get("facts", {}) or {}),
                bindings=dict(value.get("bindings", {}) or {}),
            )
        raise TypeError(f"unsupported check result: {type(value).__name__}")

    @staticmethod
    def _normalise_action(
        value: Union[ActionResult, Mapping[str, Any], bool],
        *,
        default_count: int,
    ) -> ActionResult:
        if isinstance(value, ActionResult):
            if value.gui_action_count is None:
                value.gui_action_count = default_count
            return value
        if isinstance(value, bool):
            return ActionResult(success=value, gui_action_count=default_count)
        if isinstance(value, Mapping):
            return ActionResult(
                success=bool(value.get("success", value.get("ok", False))),
                gui_action_count=int(value.get("gui_action_count", default_count)),
                evidence=_normalise_evidence(value.get("evidence", [])),
                facts=dict(value.get("facts", {}) or {}),
                bindings=dict(value.get("bindings", {}) or {}),
            )
        raise TypeError(f"unsupported action result: {type(value).__name__}")

    def _default_check(self, prerequisite: Prerequisite) -> CheckResult:
        if prerequisite.kind == PrerequisiteKind.RESOURCE:
            binding = self.context.resource_bindings.get(prerequisite.resource_slot)
            return CheckResult(
                satisfied=binding is not None,
                bindings=({prerequisite.resource_slot: binding}
                          if binding is not None else {}),
            )
        if prerequisite.kind == PrerequisiteKind.AUTHORIZATION:
            allowed = (
                self.authorization_policy.sandbox
                and self.authorization_policy.allow_system_authorization
            )
            return CheckResult(
                satisfied=allowed,
                evidence=[Evidence(
                    code=("sandbox_authorization_granted" if allowed
                          else "system_authorization_denied_by_policy"),
                    message=("Password-free system authorization is allowed in the sandbox."
                             if allowed else
                             "The runtime policy does not allow system authorization."),
                    details={
                        "sandbox": self.authorization_policy.sandbox,
                        "password_supplied": self.authorization_policy.password is not None,
                    },
                )],
            )
        if prerequisite.produces:
            return CheckResult(satisfied=self._facts_match(
                prerequisite.produces, self.context.world_facts))
        return CheckResult(satisfied=False)

    def _check(self, prerequisite: Prerequisite) -> Tuple[Optional[CheckResult], Optional[str]]:
        try:
            result = (
                self._normalise_check(self.check_callback(prerequisite, self.context))
                if self.check_callback is not None
                else self._default_check(prerequisite)
            )
            return result, None
        except Exception as exc:  # fail closed at the callback boundary
            return None, f"{type(exc).__name__}: {exc}"

    def _apply_observations(
        self,
        *,
        facts: Mapping[str, Any],
        bindings: Mapping[str, Any],
    ) -> None:
        self.context.world_facts.update(facts)
        self.context.resource_bindings.update(bindings)

    def _existing_result(
        self,
        prerequisite: Prerequisite,
        check: CheckResult,
    ) -> PrerequisiteResult:
        self._apply_observations(facts=check.facts, bindings=check.bindings)
        self.context.world_facts.update(prerequisite.produces)
        evidence = list(check.evidence)
        evidence.append(Evidence(
            code=("existing_resource_bound"
                  if prerequisite.kind == PrerequisiteKind.RESOURCE
                  else "prerequisite_already_satisfied"),
            message=("An existing resource was bound; setup was skipped."
                     if prerequisite.kind == PrerequisiteKind.RESOURCE
                     else "The prerequisite was already satisfied; setup was skipped."),
            details={"resource_slot": prerequisite.resource_slot}
            if prerequisite.resource_slot else {},
        ))
        result_bindings = dict(check.bindings)
        if (prerequisite.kind == PrerequisiteKind.RESOURCE
                and prerequisite.resource_slot in self.context.resource_bindings):
            result_bindings[prerequisite.resource_slot] = (
                self.context.resource_bindings[prerequisite.resource_slot])
        return PrerequisiteResult(
            prerequisite_id=prerequisite.prerequisite_id,
            kind=prerequisite.kind.value,
            status="satisfied",
            satisfied=True,
            gui_action_count=0,
            evidence=evidence,
            produced_facts=dict(prerequisite.produces),
            resource_bindings=result_bindings,
        )

    def _choose_recipe(self, prerequisite: Prerequisite) -> Optional[SetupRecipe]:
        feasible = [
            recipe for recipe in prerequisite.setup_recipes
            if self._facts_match(recipe.requires, self.context.world_facts)
        ]
        if not feasible:
            return None
        return min(feasible, key=lambda recipe: (
            recipe.estimated_cost, len(recipe.actions), recipe.recipe_id))

    def _execute_action(
        self,
        action: RuntimeAction,
        prerequisite: Prerequisite,
    ) -> Tuple[Optional[ActionResult], Optional[str]]:
        if not self._facts_match(action.requires, self.context.world_facts):
            missing = self._missing_facts(action.requires, self.context.world_facts)
            return None, f"action dependencies are not satisfied: {missing!r}"
        if self.action_callback is None:
            return None, "no action_callback was provided"
        try:
            result = self._normalise_action(
                self.action_callback(action, prerequisite, self.context),
                default_count=action.gui_action_cost,
            )
            # Facts/bindings are observations of possible side effects and are
            # retained even when success=False, allowing partial setup cleanup.
            self._apply_observations(facts=result.facts, bindings=result.bindings)
            return result, None
        except Exception as exc:  # fail closed at the callback boundary
            return None, f"{type(exc).__name__}: {exc}"

    def _track_owned_resource(
        self,
        prerequisite: Prerequisite,
        recipe: SetupRecipe,
        before_facts: Mapping[str, Any],
        before_bindings: Mapping[str, Any],
    ) -> None:
        if prerequisite.kind != PrerequisiteKind.RESOURCE:
            return
        slot = prerequisite.resource_slot
        if slot not in self.context.resource_bindings:
            return
        value = self.context.resource_bindings[slot]
        for owned in self._owned_resources:
            if (owned.prerequisite.prerequisite_id == prerequisite.prerequisite_id
                    and owned.bindings.get(slot) == value):
                return
        cleanup_actions = recipe.cleanup_actions or prerequisite.cleanup_actions
        self._owned_resources.append(_OwnedResource(
            prerequisite=prerequisite,
            recipe_id=recipe.recipe_id,
            bindings={slot: value},
            cleanup_actions=tuple(cleanup_actions),
            before_facts=dict(before_facts),
            before_bindings=dict(before_bindings),
            setup_facts=dict(self.context.world_facts),
            setup_bindings=dict(self.context.resource_bindings),
        ))

    def _resolve_one(self, prerequisite: Prerequisite) -> PrerequisiteResult:
        check, check_error = self._check(prerequisite)
        if check_error:
            return PrerequisiteResult(
                prerequisite_id=prerequisite.prerequisite_id,
                kind=prerequisite.kind.value,
                status="failed",
                satisfied=False,
                evidence=[Evidence(
                    code="check_callback_failed",
                    message="The prerequisite check failed closed.",
                    details={"error": check_error},
                )],
                error=check_error,
            )
        assert check is not None
        # Checks are observations even when the prerequisite is unmet.  Keep
        # their facts/bindings so recipe selection and partial-resource cleanup
        # operate on the real observed world state.
        self._apply_observations(facts=check.facts, bindings=check.bindings)
        if check.satisfied:
            if (prerequisite.kind == PrerequisiteKind.RESOURCE
                    and prerequisite.resource_slot not in check.bindings
                    and prerequisite.resource_slot not in self.context.resource_bindings):
                error = "resource check succeeded without a resource binding"
                return PrerequisiteResult(
                    prerequisite_id=prerequisite.prerequisite_id,
                    kind=prerequisite.kind.value,
                    status="failed",
                    satisfied=False,
                    evidence=list(check.evidence) + [Evidence(
                        code="resource_binding_missing",
                        message=error,
                        details={"resource_slot": prerequisite.resource_slot},
                    )],
                    error=error,
                )
            return self._existing_result(prerequisite, check)

        # Application login is a hard human boundary.  Recipes are never run
        # automatically for an unmet login prerequisite.
        if prerequisite.kind == PrerequisiteKind.LOGIN:
            return PrerequisiteResult(
                prerequisite_id=prerequisite.prerequisite_id,
                kind=prerequisite.kind.value,
                status="needs_user",
                satisfied=False,
                gui_action_count=0,
                evidence=list(check.evidence) + [Evidence(
                    code="application_login_requires_user",
                    message="Application login requires explicit user coordination.",
                    details={"check_key": prerequisite.check_key},
                )],
            )

        # The default sandbox policy grants system authorization without a
        # password.  If a concrete unlock recipe exists, it still has to run;
        # otherwise the prerequisite represents policy permission itself.
        if prerequisite.kind == PrerequisiteKind.AUTHORIZATION:
            if not (self.authorization_policy.sandbox
                    and self.authorization_policy.allow_system_authorization):
                return PrerequisiteResult(
                    prerequisite_id=prerequisite.prerequisite_id,
                    kind=prerequisite.kind.value,
                    status="blocked",
                    satisfied=False,
                    evidence=list(check.evidence) + [Evidence(
                        code="system_authorization_denied_by_policy",
                        message="The runtime policy does not allow system authorization.",
                    )],
                )
            if not prerequisite.setup_recipes:
                self.context.world_facts.update(prerequisite.produces)
                return PrerequisiteResult(
                    prerequisite_id=prerequisite.prerequisite_id,
                    kind=prerequisite.kind.value,
                    status="satisfied",
                    satisfied=True,
                    gui_action_count=0,
                    evidence=list(check.evidence) + [Evidence(
                        code="sandbox_authorization_granted",
                        message="Password-free system authorization is allowed in the sandbox.",
                        details={"password_supplied": self.authorization_policy.password is not None},
                    )],
                    produced_facts=dict(prerequisite.produces),
                )

        recipe = self._choose_recipe(prerequisite)
        if recipe is None:
            details = {
                recipe.recipe_id: self._missing_facts(
                    recipe.requires, self.context.world_facts)
                for recipe in prerequisite.setup_recipes
            }
            code = "no_feasible_setup_recipe" if prerequisite.setup_recipes else "setup_recipe_missing"
            return PrerequisiteResult(
                prerequisite_id=prerequisite.prerequisite_id,
                kind=prerequisite.kind.value,
                status="blocked",
                satisfied=False,
                evidence=list(check.evidence) + [Evidence(
                    code=code,
                    message="No setup recipe can currently satisfy the prerequisite.",
                    details={"missing_by_recipe": details},
                )],
            )

        cleanup_actions = recipe.cleanup_actions or prerequisite.cleanup_actions
        if (prerequisite.kind == PrerequisiteKind.RESOURCE
                and not cleanup_actions):
            error = "resource setup has no cleanup recipe"
            return PrerequisiteResult(
                prerequisite_id=prerequisite.prerequisite_id,
                kind=prerequisite.kind.value,
                status="failed",
                satisfied=False,
                recipe_id=recipe.recipe_id,
                evidence=list(check.evidence) + [Evidence(
                    code="resource_cleanup_missing",
                    message="Refusing to create an unowned resource without cleanup.",
                    details={"recipe_id": recipe.recipe_id},
                )],
                error=error,
            )

        before_facts = dict(self.context.world_facts)
        before_bindings = dict(self.context.resource_bindings)
        evidence = list(check.evidence)
        evidence.append(Evidence(
            code="minimum_setup_recipe_selected",
            message="Selected the feasible setup recipe with the fewest GUI actions.",
            details={
                "recipe_id": recipe.recipe_id,
                "estimated_gui_actions": recipe.estimated_cost,
            },
        ))
        action_count = 0
        for action in recipe.actions:
            action_result, action_error = self._execute_action(action, prerequisite)
            if action_error:
                self._track_owned_resource(
                    prerequisite, recipe, before_facts, before_bindings)
                return PrerequisiteResult(
                    prerequisite_id=prerequisite.prerequisite_id,
                    kind=prerequisite.kind.value,
                    status="failed",
                    satisfied=False,
                    gui_action_count=action_count,
                    recipe_id=recipe.recipe_id,
                    evidence=evidence + [Evidence(
                        code="setup_action_failed",
                        message="A setup action failed closed.",
                        details={"action_id": action.action_id, "error": action_error},
                    )],
                    error=action_error,
                )
            assert action_result is not None
            action_count += int(action_result.gui_action_count or 0)
            evidence.extend(action_result.evidence)
            evidence.append(Evidence(
                code=("setup_action_completed" if action_result.success
                      else "setup_action_rejected"),
                message=("The setup action completed."
                         if action_result.success else "The setup action did not complete."),
                details={
                    "action_id": action.action_id,
                    "gui_action_count": int(action_result.gui_action_count or 0),
                },
            ))
            if not action_result.success:
                self._track_owned_resource(
                    prerequisite, recipe, before_facts, before_bindings)
                return PrerequisiteResult(
                    prerequisite_id=prerequisite.prerequisite_id,
                    kind=prerequisite.kind.value,
                    status="failed",
                    satisfied=False,
                    gui_action_count=action_count,
                    recipe_id=recipe.recipe_id,
                    evidence=evidence,
                    error=f"setup action {action.action_id!r} was rejected",
                )

        self._apply_observations(facts=recipe.produces, bindings=recipe.bindings)

        # With a real checker, require post-setup evidence.  Without one, the
        # declarative recipe/action outputs are the authoritative offline fact.
        if self.check_callback is not None:
            post_check, post_error = self._check(prerequisite)
            if post_check is not None:
                self._apply_observations(
                    facts=post_check.facts, bindings=post_check.bindings)
            if post_error or post_check is None or not post_check.satisfied:
                self._track_owned_resource(
                    prerequisite, recipe, before_facts, before_bindings)
                error = post_error or "post-setup check remained unsatisfied"
                post_evidence = [] if post_check is None else list(post_check.evidence)
                return PrerequisiteResult(
                    prerequisite_id=prerequisite.prerequisite_id,
                    kind=prerequisite.kind.value,
                    status="failed",
                    satisfied=False,
                    gui_action_count=action_count,
                    recipe_id=recipe.recipe_id,
                    evidence=evidence + post_evidence + [Evidence(
                        code="post_setup_verification_failed",
                        message="Setup ran, but the prerequisite could not be verified.",
                        details={"error": error},
                    )],
                    error=error,
                )
            evidence.extend(post_check.evidence)

        self.context.world_facts.update(prerequisite.produces)
        self._track_owned_resource(
            prerequisite, recipe, before_facts, before_bindings)

        if (prerequisite.kind == PrerequisiteKind.RESOURCE
                and prerequisite.resource_slot not in self.context.resource_bindings):
            error = "resource setup completed without producing its required binding"
            return PrerequisiteResult(
                prerequisite_id=prerequisite.prerequisite_id,
                kind=prerequisite.kind.value,
                status="failed",
                satisfied=False,
                gui_action_count=action_count,
                recipe_id=recipe.recipe_id,
                evidence=evidence + [Evidence(
                    code="resource_binding_missing",
                    message=error,
                    details={"resource_slot": prerequisite.resource_slot},
                )],
                error=error,
            )

        bindings = ({prerequisite.resource_slot:
                     self.context.resource_bindings[prerequisite.resource_slot]}
                    if prerequisite.kind == PrerequisiteKind.RESOURCE else {})
        evidence.append(Evidence(
            code="setup_verified",
            message="The prerequisite was satisfied by the selected setup recipe.",
            details={"recipe_id": recipe.recipe_id},
        ))
        return PrerequisiteResult(
            prerequisite_id=prerequisite.prerequisite_id,
            kind=prerequisite.kind.value,
            status="setup_completed",
            satisfied=True,
            gui_action_count=action_count,
            evidence=evidence,
            recipe_id=recipe.recipe_id,
            produced_facts={**dict(recipe.produces), **dict(prerequisite.produces)},
            resource_bindings=bindings,
        )

    def resolve(self, prerequisites: Sequence[Prerequisite]) -> ResolutionReport:
        """Resolve prerequisites in dependency order and fail closed.

        ``Prerequisite.requires`` is matched against ``world_facts``.  Input
        order does not need to be topological: a prerequisite is delayed while
        another pending prerequisite can produce its missing facts.
        """

        pending = list(prerequisites)
        ids = [item.prerequisite_id for item in pending]
        if len(ids) != len(set(ids)):
            raise ValueError("prerequisite_id values must be unique within a resolve call")

        results: List[PrerequisiteResult] = []
        total_actions = 0
        while pending:
            ready_index = next((
                index for index, prerequisite in enumerate(pending)
                if self._facts_match(prerequisite.requires, self.context.world_facts)
            ), None)
            if ready_index is None:
                for prerequisite in pending:
                    missing = self._missing_facts(
                        prerequisite.requires, self.context.world_facts)
                    results.append(PrerequisiteResult(
                        prerequisite_id=prerequisite.prerequisite_id,
                        kind=prerequisite.kind.value,
                        status="blocked",
                        satisfied=False,
                        evidence=[Evidence(
                            code="prerequisite_dependencies_missing",
                            message="Required world facts were not produced.",
                            details={"missing": missing},
                        )],
                    ))
                return self._report("blocked", results, total_actions)

            prerequisite = pending.pop(ready_index)
            result = self._resolve_one(prerequisite)
            results.append(result)
            total_actions += result.gui_action_count
            if result.status == "needs_user":
                return self._report("needs_user", results, total_actions)
            if result.status in {"failed", "blocked"}:
                return self._report(result.status, results, total_actions)

        return self._report("ready", results, total_actions)

    def _report(
        self,
        status: str,
        results: List[PrerequisiteResult],
        gui_action_count: int,
    ) -> ResolutionReport:
        return ResolutionReport(
            status=status,
            results=results,
            gui_action_count=gui_action_count,
            world_facts=dict(self.context.world_facts),
            resource_bindings=dict(self.context.resource_bindings),
        )

    def _restore_resource_context(self, owned: _OwnedResource) -> None:
        # Restore only values that still equal the setup result; do not clobber
        # later work performed by traversal/M13 after fixture creation.
        all_fact_keys = set(owned.before_facts) | set(owned.setup_facts)
        for key in all_fact_keys:
            setup_value = owned.setup_facts.get(key, _MISSING)
            current_value = self.context.world_facts.get(key, _MISSING)
            if current_value != setup_value:
                continue
            if key in owned.before_facts:
                self.context.world_facts[key] = owned.before_facts[key]
            else:
                self.context.world_facts.pop(key, None)

        all_binding_keys = set(owned.before_bindings) | set(owned.setup_bindings)
        for key in all_binding_keys:
            setup_value = owned.setup_bindings.get(key, _MISSING)
            current_value = self.context.resource_bindings.get(key, _MISSING)
            if current_value != setup_value:
                continue
            if key in owned.before_bindings:
                self.context.resource_bindings[key] = owned.before_bindings[key]
            else:
                self.context.resource_bindings.pop(key, None)

    def cleanup(self) -> CleanupReport:
        """Clean run-owned resources in reverse creation order.

        Successful cleanup actions are checkpointed by ``cleanup_index`` and
        are never repeated.  Calling this method again after success performs
        zero GUI actions.  Failed resources remain retryable from the first
        action that did not complete.
        """

        results: List[CleanupResult] = []
        total_actions = 0
        for owned in reversed(self._owned_resources):
            if owned.cleaned:
                continue

            # Ensure callbacks see the exact run-owned resource even when a
            # later fixture reused the same slot.
            self.context.resource_bindings.update(owned.bindings)
            evidence: List[Evidence] = []
            resource_actions = 0
            error = ""
            while owned.cleanup_index < len(owned.cleanup_actions):
                action = owned.cleanup_actions[owned.cleanup_index]
                action_result, action_error = self._execute_action(
                    action, owned.prerequisite)
                if action_error:
                    error = action_error
                    evidence.append(Evidence(
                        code="cleanup_action_failed",
                        message="A cleanup action failed closed.",
                        details={"action_id": action.action_id, "error": action_error},
                    ))
                    break
                assert action_result is not None
                count = int(action_result.gui_action_count or 0)
                resource_actions += count
                total_actions += count
                evidence.extend(action_result.evidence)
                if not action_result.success:
                    error = f"cleanup action {action.action_id!r} was rejected"
                    evidence.append(Evidence(
                        code="cleanup_action_rejected",
                        message="The cleanup action did not complete.",
                        details={"action_id": action.action_id},
                    ))
                    break
                owned.cleanup_index += 1
                evidence.append(Evidence(
                    code="cleanup_action_completed",
                    message="The cleanup action completed.",
                    details={"action_id": action.action_id},
                ))

            if error:
                results.append(CleanupResult(
                    prerequisite_id=owned.prerequisite.prerequisite_id,
                    status="failed",
                    gui_action_count=resource_actions,
                    evidence=evidence,
                    error=error,
                ))
                continue

            owned.cleaned = True
            self._restore_resource_context(owned)
            evidence.append(Evidence(
                code="owned_resource_cleaned",
                message="The run-owned resource was cleaned and its binding released.",
                details={
                    "resource_slot": owned.prerequisite.resource_slot,
                    "recipe_id": owned.recipe_id,
                },
            ))
            results.append(CleanupResult(
                prerequisite_id=owned.prerequisite.prerequisite_id,
                status="cleaned",
                gui_action_count=resource_actions,
                evidence=evidence,
            ))

        if not results:
            return CleanupReport(
                status="already_clean",
                results=[],
                gui_action_count=0,
                world_facts=dict(self.context.world_facts),
                resource_bindings=dict(self.context.resource_bindings),
            )
        status = "partial_failure" if any(
            result.status == "failed" for result in results) else "complete"
        return CleanupReport(
            status=status,
            results=results,
            gui_action_count=total_actions,
            world_facts=dict(self.context.world_facts),
            resource_bindings=dict(self.context.resource_bindings),
        )


_MISSING = object()


__all__ = [
    "ActionResult",
    "AuthorizationPolicy",
    "CheckResult",
    "CleanupReport",
    "CleanupResult",
    "Evidence",
    "Prerequisite",
    "PrerequisiteKind",
    "PrerequisiteResult",
    "PrerequisiteRuntime",
    "ResolutionReport",
    "RuntimeAction",
    "RuntimeContext",
    "SetupRecipe",
]
