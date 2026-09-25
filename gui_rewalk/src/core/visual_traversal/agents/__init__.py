"""Canonical public exports for visual-traversal agent roles."""

from .diagnostics import ReviewDebugSink, classify_edge_consistency, classify_scroll_waste
from .effects import StatefulRiskGuard
from .explorer import ExplorerAgent
from .focus import AppFocusGuard
from .identity import BlockIdentityJudge, PageIdentityJudge
from .interruption import InterruptionDismisser
from .memory import ExplorationMemory
from .observer import ObserverAgent
from .review import AnnotationReviewer

__all__ = [
    "AnnotationReviewer",
    "AppFocusGuard",
    "ExplorationMemory",
    "ExplorerAgent",
    "InterruptionDismisser",
    "ObserverAgent",
    "PageIdentityJudge",
    "BlockIdentityJudge",
    "ReviewDebugSink",
    "StatefulRiskGuard",
    "classify_edge_consistency",
    "classify_scroll_waste",
]
