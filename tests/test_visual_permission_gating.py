"""Offline tests for visual availability parsing and permission candidate gates."""

from __future__ import annotations

import io
import os
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gui_rewalk.src.core.visual_traversal.visual_agents import ExplorationMemory
from gui_rewalk.src.core.visual_traversal.visual_engine import VisualTraversalEngine
from gui_rewalk.src.core.visual_traversal.visual_filter import (
    candidate_access_outcome,
    is_enqueueable,
)
from gui_rewalk.src.core.visual_traversal.prompts.grounding import (
    VLM_GROUNDING_PROMPT,
    VLM_NAMING_PROMPT,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import (
    VisualElement,
    VisualPerception,
    _availability_from_item,
)


def _png(width: int = 100, height: int = 100) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (width, height), "white").save(out, format="PNG")
    return out.getvalue()


def test_prompts_request_structured_availability_context() -> None:
    for prompt in (VLM_NAMING_PROMPT, VLM_GROUNDING_PROMPT):
        assert "enabled" in prompt
        assert "requires_permission" in prompt
        assert "blocked_reason" in prompt
        assert "不要仅凭" in prompt


def test_availability_parser_is_backward_compatible_and_boolean_safe() -> None:
    legacy = VisualElement(
        7, "Legacy", [0, 0, 10, 10], [5, 5], "link", True, "navigation"
    )
    assert legacy.category == "navigation"
    assert legacy.enabled is None and not legacy.requires_permission
    assert legacy.blocked_reason == ""
    assert _availability_from_item(None) == (None, False, "")
    assert _availability_from_item({}) == (None, False, "")
    assert _availability_from_item({
        "enabled": "false",
        "requires_permission": "true",
        "blocked_reason": " Application_Login ",
    }) == (False, True, "application_login")
    assert _availability_from_item({
        "enabled": "unknown",
        "requires_permission": "false",
    }) == (None, False, "")


def test_both_grounding_and_som_naming_populate_availability_fields() -> None:
    # Grounding path: use an exact-frame cache hit so the test has no model call.
    class _Cache:
        def lookup_grounding(self, _frame):
            return True, (
                '{"window":[0,0,1000,1000],"is_modal":false,"elements":['
                '{"name":"Sign in","type":"button","bbox":[100,100,300,200],'
                '"interactive":true,"enabled":true,"requires_permission":true,'
                '"blocked_reason":"application_login","category":"navigation"}]}'
            )

    perception = VisualPerception(None, agent=object(), use_ocr=False)
    perception.cache = _Cache()
    perception._cur_frame_bytes = b"exact-frame"
    image = Image.new("RGB", (100, 100), "white")
    grounded = perception._ground_with_vlm(
        image, np.asarray(image), 100, 100
    )
    assert len(grounded) == 1
    assert grounded[0].enabled is True
    assert grounded[0].requires_permission is True
    assert grounded[0].blocked_reason == "application_login"

    # SoM naming path: stub only detection/naming, leaving the production parser
    # and VisualElement construction under test.
    perception = VisualPerception(None, agent=None, use_ocr=False)
    perception.detect = lambda _image: [{
        "bbox": [0.1, 0.1, 0.3, 0.2],
        "_score": 0.9,
        "content": "",
        "type": "icon",
    }]
    perception._name_with_vlm = lambda _som, _n: ({
        0: {
            "name": "Unavailable option",
            "type": "button",
            "interactive": True,
            "enabled": False,
            "requires_permission": False,
            "blocked_reason": "disabled",
            "category": "navigation",
        }
    }, {"window": [0, 0, 1, 1], "is_modal": False, "modal": None})
    named = perception._yolo_detect_name(
        image, np.asarray(image), 100, 100
    )
    assert named and named[0].enabled is False
    assert named[0].requires_permission is False
    assert named[0].blocked_reason == "disabled"


def test_access_gate_is_fail_closed_without_structured_exceptions() -> None:
    assert candidate_access_outcome() is None  # legacy/missing fields
    assert candidate_access_outcome(
        enabled=False, category="navigation", el_type="button"
    ) == "disabled"
    assert candidate_access_outcome(
        enabled=True, requires_permission=True,
        blocked_reason="application_login",
        category="navigation", el_type="button",
    ) == "permission_blocked"
    assert candidate_access_outcome(
        enabled=True, requires_permission=True,
        blocked_reason="some_unknown_permission",
        category="navigation", el_type="button",
    ) == "permission_blocked"

    protected = dict(
        enabled=True,
        requires_permission=True,
        blocked_reason="configuration_authorization",
        category="navigation",
        el_type="button",
    )
    assert candidate_access_outcome(**protected) == "permission_blocked"
    assert not is_enqueueable("navigation", "Arbitrary label", **{
        key: value for key, value in protected.items() if key != "category"
    })


def test_perception_retains_unavailable_controls_for_audit() -> None:
    perception = VisualPerception(None, use_ocr=False)
    perception.use_vlm_grounding = True

    def _ground(*_args, **_kwargs):
        perception.last_is_modal = False
        perception.last_window_xywh = [0, 0, 100, 100]
        return [VisualElement(
            0, "Disabled destructive option", [10, 10, 30, 20], [25, 20],
            el_type="button", category="dangerous", enabled=False,
            blocked_reason="disabled",
        )]

    perception._ground_with_vlm = _ground
    result = perception.detect_and_name(_png())
    assert len(result) == 1
    assert result[0].priority == 98


class _NoRegions:
    def shared_button_names(self):
        return frozenset()

    def is_clicked(self, _region_id, _name):
        return False


class _Graph:
    def __init__(self):
        self.records = []

    def record_abnormal_button(self, **payload):
        self.records.append(payload)
        return payload


class _Debug:
    enabled = False

    def record_event(self, *_args, **_kwargs):
        return None


def test_engine_retires_visibly_disabled_control() -> None:
    disabled = VisualElement(
        0, "Unavailable feature", [0, 0, 20, 20], [10, 10],
        el_type="button", category="navigation", enabled=False,
        blocked_reason="disabled", uid="disabled",
    )
    engine = object.__new__(VisualTraversalEngine)
    engine._state_data = {"settings": {
        "elements": [disabled]
    }}
    engine._visited_uids = set()
    engine._explored_groups = set()
    engine._abnormal_buttons = set()
    engine.region_registry = _NoRegions()
    engine.mem = ExplorationMemory()
    engine.graph = _Graph()
    engine.review_debug = _Debug()

    candidates = VisualTraversalEngine._unvisited_candidates(engine, "settings")
    assert candidates == []
    assert disabled.visited and disabled.abnormal_reason == "disabled"
    assert [r["reason"] for r in engine.graph.records] == ["disabled"]

    # Re-querying is idempotent: terminal controls stay retired and are not
    # duplicated in the audit ledger.
    candidates = VisualTraversalEngine._unvisited_candidates(engine, "settings")
    assert candidates == []
    assert len(engine.graph.records) == 1


def main() -> None:
    tests = [
        test_prompts_request_structured_availability_context,
        test_availability_parser_is_backward_compatible_and_boolean_safe,
        test_both_grounding_and_som_naming_populate_availability_fields,
        test_access_gate_is_fail_closed_without_structured_exceptions,
        test_perception_retains_unavailable_controls_for_audit,
        test_engine_retires_visibly_disabled_control,
    ]
    for test in tests:
        test()
    print(f"visual permission gating: {len(tests)} tests passed")


if __name__ == "__main__":
    main()
