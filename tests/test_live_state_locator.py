from __future__ import annotations

import copy
import json

import pytest

from gui_rewalk.src.core.scenario.live_state_locator import KnownPageStateLocator


def _candidates():
    return [{
        "state_ref": "s1",
        "page_ref": "p1",
        "state_name": "Initial",
        "state_summary": "The list is collapsed.",
        "regions": [{"name": "List", "operations": ["Expand"]}],
        "screenshot": b"state-one",
    }, {
        "state_ref": "s2",
        "page_ref": "p1",
        "state_name": "Expanded",
        "state_summary": "The list is expanded.",
        "regions": [{"name": "List", "operations": ["Collapse"]}],
        "screenshot": b"state-two",
    }, {
        "state_ref": "s3",
        "page_ref": "p2",
        "state_name": "Other page",
        "state_summary": "A different function page.",
        "regions": [],
        "screenshot": b"other-page",
    }]


class _LocatorVLM:
    def __init__(self, response=None, *, error=None):
        self.response = response
        self.error = error
        self.calls = 0
        self.prompts = []
        self.images = []

    def predict_mm(self, prompt, images):
        self.calls += 1
        self.prompts.append(prompt)
        self.images.append(list(images))
        if self.error is not None:
            raise self.error
        if isinstance(self.response, dict):
            return json.dumps(self.response), 0, 0, 0
        return self.response


def test_locator_returns_unique_page_local_byte_match_without_vlm():
    candidates = _candidates()
    before = copy.deepcopy(candidates)
    vlm = _LocatorVLM()
    locator = KnownPageStateLocator(vlm)

    assert locator.locate(
        b"state-one", candidates, page_ref="p1") == "s1"
    assert vlm.calls == 0
    assert candidates == before


def test_locator_accepts_only_a_known_state_from_the_requested_page():
    candidates = _candidates()
    before = copy.deepcopy(candidates)
    vlm = _LocatorVLM({
        "status": "known",
        "state_ref": "s2",
        "reason": "The expanded Region and operation match s2.",
    })
    locator = KnownPageStateLocator(vlm)

    assert locator.locate(b"live", candidates, page_ref="p1") == "s2"
    assert vlm.calls == 1
    assert vlm.images == [[b"live", b"state-one", b"state-two"]]
    assert '"state_ref": "s1"' in vlm.prompts[0]
    assert '"state_ref": "s2"' in vlm.prompts[0]
    assert '"state_ref": "s3"' not in vlm.prompts[0]
    assert locator.last_reason == "The expanded Region and operation match s2."
    assert candidates == before


@pytest.mark.parametrize("response", [
    {
        "status": "known", "state_ref": "s3",
        "reason": "This ref belongs to another Page.",
    },
    {
        "status": "unresolved", "state_ref": "",
        "reason": "The frame is ambiguous.",
    },
    {
        "status": "new", "state_ref": "",
        "reason": "Collection must not create a State.",
    },
    "not-json",
])
def test_locator_fails_closed_for_unusable_model_results(response):
    locator = KnownPageStateLocator(_LocatorVLM(response))

    assert locator.locate(b"live", _candidates(), page_ref="p1") is None


def test_locator_rejects_duplicate_exact_frames_without_model_guessing():
    candidates = _candidates()
    candidates[1]["screenshot"] = b"state-one"
    vlm = _LocatorVLM()

    assert KnownPageStateLocator(vlm).locate(
        b"state-one", candidates, page_ref="p1") is None
    assert vlm.calls == 0


@pytest.mark.parametrize(("live_screenshot", "candidate_screenshot"), [
    (b"live", None),
    (b"live", b""),
    (None, b"state-two"),
])
def test_locator_rejects_missing_screenshot_without_model_call(
    live_screenshot, candidate_screenshot,
):
    candidates = _candidates()
    candidates[1]["screenshot"] = candidate_screenshot
    vlm = _LocatorVLM()

    assert KnownPageStateLocator(vlm).locate(
        live_screenshot, candidates, page_ref="p1") is None
    assert vlm.calls == 0


def test_locator_returns_unresolved_when_transport_raises():
    locator = KnownPageStateLocator(
        _LocatorVLM(error=RuntimeError("transport unavailable")))

    assert locator.locate(b"live", _candidates(), page_ref="p1") is None
