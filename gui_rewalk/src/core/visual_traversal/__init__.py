"""Screenshot-only traversal package.

The public surface is perception/state plus ``VisualTraversalEngine``. Routing
and recovery use ``VisualRouter`` internally; legacy replay/backtrack is removed.
"""

from .visual_perception import VisualElement, VisualPerception
from .visual_state import (VisualStateRegistry, compute_element_uid,
                           assign_element_uids, ElementMatcher,
                           compute_page_id, compute_variant_id,
                           observed_variant_facts, semantic_page_key)
from .capability_discovery import discover_capabilities
from .visual_engine import VisualTraversalEngine, run

__all__ = [
    "VisualElement",
    "VisualPerception",
    "VisualStateRegistry",
    "compute_element_uid",
    "assign_element_uids",
    "ElementMatcher",
    "compute_page_id",
    "compute_variant_id",
    "observed_variant_facts",
    "semantic_page_key",
    "discover_capabilities",
    "VisualTraversalEngine",
    "run",
]
