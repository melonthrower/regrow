"""Public prompt catalog for visual traversal."""

from .grounding import (
    ANNOTATION_REVIEW_PROMPT,
    ANNOTATION_REVIEW_WITH_REGIONS_PROMPT,
    VLM_GROUNDING_PROMPT,
    VLM_NAMING_PROMPT,
)
from .navigation import (
    INTERRUPTION_DISMISS_PROMPT,
    STATEFUL_RISK_PROMPT,
)
from .identity_candidates import (
    build_page_candidate_selection_prompt,
    build_region_correspondence_prompt,
    build_pair_page_identity_prompt,
    build_region_partition_mapping_prompt,
)
from .exploration import build_explorer_prompt, build_route_choice_prompt
from .interface_scope import (
    CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH,
    REGION_PRESENTATION_DEFINITION_ZH,
)

__all__ = [
    "ANNOTATION_REVIEW_PROMPT",
    "ANNOTATION_REVIEW_WITH_REGIONS_PROMPT",
    "INTERRUPTION_DISMISS_PROMPT",
    "STATEFUL_RISK_PROMPT",
    "VLM_GROUNDING_PROMPT",
    "VLM_NAMING_PROMPT",
    "CURRENT_OPERABLE_INTERFACE_DEFINITION_ZH",
    "REGION_PRESENTATION_DEFINITION_ZH",
    "build_page_candidate_selection_prompt",
    "build_region_correspondence_prompt",
    "build_pair_page_identity_prompt",
    "build_region_partition_mapping_prompt",
    "build_explorer_prompt",
    "build_route_choice_prompt",
]
