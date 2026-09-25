"""Region identity, coverage, and region-aware scrolling."""

from .registry import (
    Region,
    RegionRegistry,
    assign_elements_to_regions,
    element_is_action,
    element_member_token,
    norm_names,
)
from .scroll import RegionScrollContext, RegionScrollRuntime

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
