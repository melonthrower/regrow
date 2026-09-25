"""Canonical grounding primitives for visual traversal."""

from .region import (
    Region,
    RegionRegistry,
    RegionScrollContext,
    RegionScrollRuntime,
    assign_elements_to_regions,
    element_is_action,
    element_member_token,
    norm_names,
)

__all__ = [
    "Region",
    "RegionRegistry",
    "RegionScrollContext",
    "RegionScrollRuntime",
    "assign_elements_to_regions",
    "element_is_action",
    "element_member_token",
    "norm_names",
]
