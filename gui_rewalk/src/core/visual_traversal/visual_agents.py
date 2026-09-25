"""Compatibility re-export for canonical :mod:`visual_traversal.agents` roles."""

from .agents import (
    AnnotationReviewer,
    AppFocusGuard,
    BlockIdentityJudge,
    ExplorerAgent,
    ExplorationMemory,
    InterruptionDismisser,
    ObserverAgent,
    PageIdentityJudge,
    ReviewDebugSink,
    StatefulRiskGuard,
    classify_edge_consistency,
    classify_scroll_waste,
)

__all__ = [
    "AnnotationReviewer",
    "AppFocusGuard",
    "BlockIdentityJudge",
    "ExplorerAgent",
    "ExplorationMemory",
    "InterruptionDismisser",
    "ObserverAgent",
    "PageIdentityJudge",
    "ReviewDebugSink",
    "StatefulRiskGuard",
    "classify_edge_consistency",
    "classify_scroll_waste",
]
