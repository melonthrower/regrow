import io
from pathlib import Path

from PIL import Image

from gui_rewalk.src.core.visual_traversal.agents.identity import (
    PageIdentityJudge,
)
from gui_rewalk.src.core.visual_traversal.state.resolver import (
    IdentityResolver,
)
from gui_rewalk.src.core.visual_traversal.state.map_guided import (
    page_candidate_payloads,
)


class _Registry:
    def __init__(self, paths, exact=(), page_ids=None):
        self.paths = paths
        self.exact = tuple(exact)
        self.page_ids = dict(page_ids or {})

    def exact_frame_state_ids(self, _shot):
        return self.exact

    def known_path(self, state_id):
        return self.paths.get(state_id)

    def variant_id_of(self, _state_id):
        return ""

    def page_id_of(self, state_id):
        return self.page_ids.get(state_id, "")


class _Judge:
    def __init__(self, choice, reason="evidence", proposed_name=""):
        self.choice = choice
        self.last_reason = reason
        self.last_proposed_new_page_name = proposed_name
        self.calls = []

    def which_page(self, shot, candidates, transition=None,
                   current_observation=None):
        self.calls.append({
            "shot": shot,
            "candidates": [item["sid"] for item in candidates],
            "candidate_pages": [item.get("page_id") for item in candidates],
            "candidate_states": [
                tuple(item.get("state_ids") or []) for item in candidates],
            "transition": transition,
            "current_observation": current_observation,
        })
        return self.choice


class _SequenceJudge(_Judge):
    def __init__(self, *choices):
        super().__init__("")
        self.choices = iter(choices)

    def which_page(self, shot, candidates, transition=None,
                   current_observation=None):
        self.choice = next(self.choices)
        return super().which_page(
            shot, candidates, transition=transition,
            current_observation=current_observation)


def _descriptor(state_id):
    return {"name": state_id, "targets": []}


def _png_bytes() -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", (2, 2), color="white").save(stream, format="PNG")
    return stream.getvalue()


def test_pair_page_identity_enables_thinking_only_for_the_call():
    class _Agent:
        def __init__(self):
            self.enable_thinking = False
            self.seen = []

        def predict_mm(self, _prompt, _images):
            self.seen.append(self.enable_thinking)
            return (
                '{"is_interruption":false,"same_page":false,'
                '"reason":"different surfaces"}',
                None,
            )

    agent = _Agent()
    judge = PageIdentityJudge(agent)

    assert judge.compare_relationship(_png_bytes(), _png_bytes()) \
        == "different_page"
    assert agent.seen == [True]
    assert agent.enable_thinking is False


def test_binary_page_match_returns_same_page():
    class _Agent:
        enable_thinking = False

        def predict_mm(self, _prompt, _images):
            return (
                '{"is_interruption":false,"same_page":true,'
                '"reason":"same operable page"}', None)

    judge = PageIdentityJudge(_Agent())

    assert judge.compare_relationship(_png_bytes(), _png_bytes()) \
        == "same_page"


def test_page_identity_interruption_defers_page_verdict():
    class _Agent:
        enable_thinking = False

        def predict_mm(self, _prompt, _images):
            return (
                '{"is_interruption":true,"same_page":null,'
                '"reason":"external foreground notification"}', None)

    judge = PageIdentityJudge(_Agent())

    assert judge.compare_relationship(_png_bytes(), _png_bytes()) is None
    assert judge.last_comparison_status == "interruption"
    assert judge.last_is_interruption is True


def test_legacy_three_way_page_identity_reply_fails_closed():
    class _Agent:
        enable_thinking = False

        def predict_mm(self, _prompt, _images):
            return (
                '{"relationship":"same_page_variant",'
                '"reason":"legacy reply"}',
                None,
            )

    judge = PageIdentityJudge(_Agent())

    assert judge.compare_relationship(_png_bytes(), _png_bytes()) is None
    assert judge.last_comparison_status == "unresolved"


def test_page_candidates_deduplicate_states_and_keep_region_descriptions(
        tmp_path):
    first = Path(tmp_path) / "first.png"
    richer = Path(tmp_path) / "richer.png"
    other = Path(tmp_path) / "other.png"
    for path in (first, richer, other):
        path.write_bytes(path.name.encode())
    descriptors = {
        "s1": {
            "interface_name": "Clock",
            "regions": [{"name": "Alarm list", "description": "Lists alarms."}],
        },
        "s2": {
            "interface_name": "Clock",
            "regions": [
                {"name": "Alarm list", "description": "Lists alarms."},
                {"name": "Mode navigation", "description": "Switches modes."},
            ],
        },
        "s3": {
            "interface_name": "Settings",
            "regions": [{
                "name": "Network",
                "description": "Configures network access.",
            }],
        },
    }
    registry = _Registry(
        {"s1": str(first), "s2": str(richer), "s3": str(other)},
        page_ids={"s1": "clock", "s2": "clock", "s3": "settings"},
    )

    payloads = page_candidate_payloads(
        ["s1", "s2", "s3"], registry, descriptors.get)

    assert [item["page_id"] for item in payloads] == [
        "clock", "settings"]
    assert payloads[0]["sid"] == "s2"
    assert payloads[0]["state_ids"] == ["s1", "s2"]
    assert payloads[0]["descriptor"]["regions"][1] == {
        "name": "Mode navigation",
        "description": "Switches modes.",
    }


def test_unique_exact_frame_resolves_without_vlm(tmp_path):
    judge = _Judge("s1")
    resolver = IdentityResolver(
        registry=_Registry({}, exact=("s1",)),
        state_data={"s1": {}},
        judge=judge,
        descriptor_fn=_descriptor,
    )

    result = resolver.resolve(b"frame")

    assert result.verdict == "known"
    assert result.state_id == "s1"
    assert result.exact is True
    assert judge.calls == []


def test_identity_first_uses_screenshots_without_semantic_observation(tmp_path):
    first = Path(tmp_path) / "s1.png"
    second = Path(tmp_path) / "s2.png"
    first.write_bytes(b"first")
    second.write_bytes(b"second")
    judge = _Judge("s2")
    resolver = IdentityResolver(
        registry=_Registry({"s1": str(first), "s2": str(second)}),
        state_data={"s1": {}, "s2": {}},
        judge=judge,
        descriptor_fn=_descriptor,
        local_candidates_fn=lambda _source, _label: ["s2"],
    )

    result = resolver.resolve(
        b"current", source_id="s2", clicked_label="open")

    assert result.verdict == "known"
    assert result.state_id == "s2"
    assert judge.calls[0]["candidates"] == ["s2", "s1"]
    assert judge.calls[0]["current_observation"] is None
    assert judge.calls[0]["transition"]["source_screenshot_path"] == str(second)


def test_all_valid_differences_are_new(tmp_path):
    screenshot = Path(tmp_path) / "s1.png"
    screenshot.write_bytes(b"first")
    resolver = IdentityResolver(
        registry=_Registry({"s1": str(screenshot)}),
        state_data={"s1": {}},
        judge=_Judge(
            "NEW", "selected screenshots differ",
            proposed_name="Advanced network settings"),
        descriptor_fn=_descriptor,
    )

    result = resolver.resolve(b"current")

    assert result.verdict == "new"
    assert result.proposed_new_page_name == "Advanced network settings"


def test_same_page_persistent_change_reuses_known_state(tmp_path):
    screenshot = Path(tmp_path) / "empty.png"
    screenshot.write_bytes(b"empty")
    resolver = IdentityResolver(
        registry=_Registry({"empty": str(screenshot)}),
        state_data={"empty": {}},
        judge=_Judge("empty", "a created item is now visible"),
        descriptor_fn=_descriptor,
    )

    result = resolver.resolve(b"populated", source_id="empty")

    assert result.verdict == "known"
    assert result.state_id == "empty"
    assert result.known is True


def test_page_shortlist_can_choose_a_global_page_over_a_local_neighbor(tmp_path):
    local = Path(tmp_path) / "local.png"
    existing = Path(tmp_path) / "existing.png"
    local.write_bytes(b"local")
    existing.write_bytes(b"existing")
    judge = _Judge("existing")
    resolver = IdentityResolver(
        registry=_Registry({
            "local": str(local),
            "existing": str(existing),
        }),
        state_data={"existing": {}, "local": {}},
        judge=judge,
        descriptor_fn=_descriptor,
        local_candidates_fn=lambda _source, _label: ["local"],
    )

    result = resolver.resolve(
        b"current", source_id="source", clicked_label="return")

    assert result.verdict == "known"
    assert result.state_id == "existing"
    assert [call["candidates"] for call in judge.calls] == [
        ["local", "existing"],
    ]


def test_local_same_page_match_is_used_after_other_states_are_ruled_out(
        tmp_path):
    local = Path(tmp_path) / "local.png"
    other = Path(tmp_path) / "other.png"
    local.write_bytes(b"local")
    other.write_bytes(b"other")
    judge = _SequenceJudge("local", "NEW")
    resolver = IdentityResolver(
        registry=_Registry({
            "local": str(local),
            "other": str(other),
        }),
        state_data={"other": {}, "local": {}},
        judge=judge,
        descriptor_fn=_descriptor,
        local_candidates_fn=lambda _source, _label: ["local"],
    )

    result = resolver.resolve(
        b"current", source_id="source", clicked_label="open")

    assert result.verdict == "known"
    assert result.state_id == "local"


def test_same_page_match_directly_reuses_selected_candidate(
        tmp_path):
    local = Path(tmp_path) / "local.png"
    canonical = Path(tmp_path) / "canonical.png"
    local.write_bytes(b"local")
    canonical.write_bytes(b"canonical")
    judge = _Judge("local")
    resolver = IdentityResolver(
        registry=_Registry(
            {"local": str(local), "canonical": str(canonical)},
            page_ids={"local": "alarm", "canonical": "alarm"}),
        state_data={"canonical": {}, "local": {}},
        judge=judge,
        descriptor_fn=_descriptor,
        local_candidates_fn=lambda _source, _label: ["local"],
    )

    result = resolver.resolve(
        b"current", source_id="source", clicked_label="return")

    assert result.verdict == "known"
    assert result.state_id == "local"
    assert judge.calls[0]["candidate_pages"] == ["alarm"]
    assert judge.calls[0]["candidate_states"] == [
        ("local", "canonical"),
    ]


def test_judge_failure_stays_unresolved(tmp_path):
    screenshot = Path(tmp_path) / "s1.png"
    screenshot.write_bytes(b"first")
    resolver = IdentityResolver(
        registry=_Registry({"s1": str(screenshot)}),
        state_data={"s1": {}},
        judge=_Judge("UNRESOLVED", "model unavailable"),
        descriptor_fn=_descriptor,
    )

    result = resolver.resolve(b"current")

    assert result.verdict == "unresolved"
    assert "unavailable" in result.reason


def test_identity_resolution_preserves_interruption_signal(tmp_path):
    screenshot = Path(tmp_path) / "s1.png"
    screenshot.write_bytes(b"first")
    judge = _Judge("UNRESOLVED", "external foreground notification")
    judge.last_is_interruption = True
    resolver = IdentityResolver(
        registry=_Registry({"s1": str(screenshot)}),
        state_data={"s1": {}},
        judge=judge,
        descriptor_fn=_descriptor,
    )

    result = resolver.resolve(b"current")

    assert result.verdict == "unresolved"
    assert result.is_interruption is True
