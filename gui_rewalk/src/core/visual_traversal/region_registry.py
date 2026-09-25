"""Compatibility import for the canonical grounding region module."""

from .grounding.region import (
    Region,
    RegionRegistry,
    assign_elements_to_regions,
    element_is_action,
    element_member_token,
    norm_names,
)

__all__ = [
    "Region",
    "RegionRegistry",
    "assign_elements_to_regions",
    "element_is_action",
    "element_member_token",
    "norm_names",
]
