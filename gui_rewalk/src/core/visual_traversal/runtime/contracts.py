"""Typed contracts shared by traversal runtime stages."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable, Dict, List, Optional, Protocol

class PerceptionUnavailable(RuntimeError):
    """A live frame contained no trustworthy visual elements."""

class StageDirective(str, Enum):
    CONTINUE = "continue"
    STOP = "stop"
    EXECUTION = "execution"
    LANDING = "landing"
    RECOVERY = "recovery"

@dataclass
class RunCursor:
    state_id: str
    observation: Dict[str, object]
    path: List[Dict[str, object]] = field(default_factory=list)
    replay_hints: List[Optional[Dict[str, object]]] = field(default_factory=list)
    off_app_streak: int = 0

@dataclass
class CandidateContext:
    element: object
    decision_reason: str
    is_seed: bool
    is_stateful: bool
    is_restore: bool
    mutation_id: str
    stateful_evidence: Dict[str, object]
    active_mutation: Optional[Dict[str, object]]
    pre_click_id: Optional[str]
    action: Dict[str, object] = field(default_factory=dict)
    targeted: bool = True
    direct_action: bool = False
    exploration_task_id: str = ""

@dataclass
class AttemptContext:
    candidate: CandidateContext
    observation: Dict[str, object]
    action: Dict[str, object]
    pre_actions: List[Dict[str, object]]
    before_shot: object
    verify_effect: bool
    attempt_label: str
    ledger_action: Dict[str, object]
    event_index: Optional[int]
    update_event: Callable[..., None]
    relaunched: bool
    on_app: bool

class TraversalRuntimeHost(Protocol):
    graph: object
    max_actions: int
    max_states: int
    def _register(self, observation, path, replay_hints=None): ...
    def _retry_incomplete_scroll_audit(self, observation, state_id): ...
    def _register_landed(self, observation, parent_id=None,
                         parent_action=None, parent_label=""): ...
    def _unvisited_candidates(self, state_id): ...
