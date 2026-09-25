from __future__ import annotations

import copy
import hashlib
import http.client
import importlib.util
import json
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import threading

import pytest


MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "mobile_graph_annotator.py"
SPEC = importlib.util.spec_from_file_location("mobile_graph_annotator", MODULE_PATH)
assert SPEC and SPEC.loader
annotator = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(annotator)


def png(width: int = 100, height: int = 200, suffix: bytes = b"") -> bytes:
    return (
        b"\x89PNG\r\n\x1a\n"
        + struct.pack(">I", 13)
        + b"IHDR"
        + struct.pack(">II", width, height)
        + b"\x08\x06\x00\x00\x00"
        + b"fake-crc"
        + suffix
    )


class FakeHash(int):
    def __sub__(self, other):
        return abs(int(self) - int(other))


def fake_auto_contract(max_steps: int = 14):
    return {
        "scroll_frac": 0.42,
        "max_steps": max_steps,
        "patience": 2,
        "stable_distance": 4,
        "phash": lambda data: FakeHash(data[-1]),
    }


class ScreenshotQueue:
    def __init__(self, values):
        self.values = list(values)

    def __call__(self):
        if not self.values:
            raise AssertionError("unexpected screenshot")
        value = self.values.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def auto_service(store, screenshots, swipes, *, foreground=None, max_steps=14):
    return annotator.AnnotatorService(
        store,
        capture_frame=lambda: None,
        screenshot=ScreenshotQueue(screenshots),
        stitcher=lambda frames: (png(101, 500 + len(frames), b"z"), {"sticky_top_h": 3}),
        tap=lambda *_args: None,
        swipe=lambda *args: swipes.append(args),
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
        foreground=foreground,
        auto_contract_loader=lambda: fake_auto_contract(max_steps),
    )


def write_session(root: Path, count: int = 2) -> tuple[Path, list[bytes]]:
    session = root / "capture-session"
    images = session / "images"
    frames_dir = session / "frames"
    images.mkdir(parents=True)
    frames_dir.mkdir()
    payloads = []
    frames = []
    for index in range(1, count + 1):
        payload = png(100 + index, 200 + index, bytes([index]))
        payloads.append(payload)
        image = images / f"frame_{index:06d}.png"
        image.write_bytes(payload)
        frames.append(
            {
                "index": index,
                "label": f"source-only-{index}",
                "image": image.relative_to(session).as_posix(),
                "sidecar": f"frames/frame_{index:06d}.json",
                "width": 100 + index,
                "height": 200 + index,
                "sha256": hashlib.sha256(payload).hexdigest(),
            }
        )
    manifest = {
        "schema": annotator.CAPTURE_SCHEMA,
        "session": {"id": "capture-session"},
        "device": {"serial": "fake-1"},
        "frames": frames,
    }
    (session / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return session, payloads


def assert_no_text_fields(value):
    if isinstance(value, dict):
        assert "name" not in value
        assert "label" not in value
        for child in value.values():
            assert_no_text_fields(child)
    elif isinstance(value, list):
        for child in value:
            assert_no_text_fields(child)


def test_manifest_sync_is_deterministic_and_original_pngs_remain_unchanged(tmp_path):
    session, payloads = write_session(tmp_path)
    before = [hashlib.sha256(payload).hexdigest() for payload in payloads]
    store = annotator.GraphStore(session)
    assert store.graph["schema"] == annotator.GRAPH_SCHEMA
    assert [state["id"] for state in store.graph["states"]] == ["s000001", "s000002"]
    assert [(s["viewport"]["width"], s["viewport"]["height"]) for s in store.graph["states"]] == [
        (101, 201),
        (102, 202),
    ]
    assert_no_text_fields(store.graph)
    store_again = annotator.GraphStore(session)
    assert [state["id"] for state in store_again.graph["states"]] == ["s000001", "s000002"]
    after = [hashlib.sha256((session / "images" / f"frame_{i:06d}.png").read_bytes()).hexdigest() for i in (1, 2)]
    assert before == after


def test_old_v1_graph_is_migrated_with_empty_action_edges(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    graph = json.loads(store.graph_path.read_text(encoding="utf-8"))
    graph.pop("scroll_edges")
    graph.pop("back_edges")
    graph.pop("same_page_links")
    graph.pop("pending_device_action")
    graph.pop("capture_floor_index")
    store.graph_path.write_text(json.dumps(graph), encoding="utf-8")
    migrated = annotator.GraphStore(session)
    assert migrated.graph["scroll_edges"] == []
    assert migrated.graph["back_edges"] == []
    assert migrated.graph["same_page_links"] == []
    assert migrated.graph["pending_device_action"] is None
    assert migrated.graph["capture_floor_index"] == 0


def test_manifest_schema_and_paths_are_validated(tmp_path):
    session, _ = write_session(tmp_path)
    manifest_path = session / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["schema"] = "wrong"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(annotator.GraphError, match="Unsupported capture"):
        annotator.GraphStore(session)

    manifest["schema"] = annotator.CAPTURE_SCHEMA
    manifest["frames"][0]["image"] = "../outside.png"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(annotator.GraphError, match="escapes|outside images"):
        annotator.GraphStore(session)


def test_coordinate_conversion_clamps_and_rejects_zero_area():
    pixels, norm = annotator.normalize_bbox([-10, 20, 120, 220], 100, 200)
    assert pixels == [0, 20, 100, 200]
    assert norm == [0, 100, 1000, 1000]
    restored, restored_norm = annotator.bbox_from_norm(norm, 200, 400)
    assert restored == [0, 40, 200, 400]
    assert restored_norm == norm
    assert annotator.normalize_point([-4, 999], 100, 200) == ([0, 199], [0, 995])
    with pytest.raises(annotator.GraphError, match="positive area"):
        annotator.normalize_bbox([1, 1, 1, 50], 100, 200)


def test_button_region_crud_fullpage_rules_and_undo(tmp_path):
    session, _ = write_session(tmp_path)
    store = annotator.GraphStore(session)
    button = store.add_annotation("s000001", "button", "viewport", [10, 20, 40, 50])
    region = store.add_annotation("s000001", "region", "viewport", [0, 0, 90, 100])
    assert button["id"] == "a000001"
    assert region["id"] == "a000002"
    with pytest.raises(annotator.GraphError, match="no fullpage"):
        store.add_annotation("s000001", "region", "fullpage", [1, 1, 10, 10])
    store.set_fullpage("s000001", png(100, 500), {"method": "upload"})
    with pytest.raises(annotator.GraphError, match="region boxes only"):
        store.add_annotation("s000001", "button", "fullpage", [1, 1, 10, 10])
    long_region = store.add_annotation("s000001", "region", "fullpage", [1, 2, 30, 400])
    removed = store.delete_annotation("s000001", long_region["id"])
    assert removed["id"] == long_region["id"]
    assert store.undo()
    assert any(item["id"] == long_region["id"] for item in store._state("s000001")["annotations"])
    assert_no_text_fields(store.graph)


def test_pending_click_completes_to_existing_state(tmp_path):
    session, _ = write_session(tmp_path)
    store = annotator.GraphStore(session)
    pending = store.set_pending_click("s000001", [50, 100])
    edge = store.complete_pending("s000002")
    assert edge["source"] == "s000001"
    assert edge["target"] == "s000002"
    assert edge["point_pixel"] == pending["point_pixel"]
    assert store.graph["pending_click"] is None
    assert_no_text_fields(edge)


def test_back_edge_store_ids_and_manifest_sync_prunes_invalid_edges(tmp_path):
    session, _ = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    edge = store.add_back_edge("s000001", "s000002")
    store.link_same_page("s000002", "s000001")
    store.stage_device_action({"kind": "back", "source": "s000002"})
    assert edge == {"id": "be000001", "source": "s000001", "target": "s000002"}
    assert_no_text_fields(edge)

    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    manifest["frames"] = manifest["frames"][:1]
    store.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    store.sync_capture_manifest()
    assert store.graph["back_edges"] == []
    assert store.graph["same_page_links"] == []
    assert store.graph["pending_device_action"] is None


def test_same_page_link_is_canonical_idempotent_validated_and_undoable(tmp_path):
    session, _ = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    before = copy.deepcopy(store.graph)

    link = store.link_same_page("s000002", "s000001")
    assert link == {"id": "sp000001", "states": ["s000001", "s000002"]}
    history_size = len(store._history)
    assert store.link_same_page("s000001", "s000002") is link
    assert len(store._history) == history_size
    assert len(store.graph["same_page_links"]) == 1

    with pytest.raises(annotator.GraphError, match="different"):
        store.link_same_page("s000001", "s000001")
    with pytest.raises(annotator.GraphError, match="Unknown state"):
        store.link_same_page("s000001", "s999999")

    assert store.undo()
    restored = copy.deepcopy(store.graph)
    restored.pop("updated_utc", None)
    before.pop("updated_utc", None)
    assert restored == before


def append_capture_frame(session: Path, index: int) -> None:
    data = png(110, 210, b"live")
    relative = f"images/frame_{index:06d}.png"
    (session / relative).write_bytes(data)
    manifest_path = session / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["frames"].append({"index": index, "label": "capture-sidecar-only", "image": relative})
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_fake_live_capture_creates_state_and_edge_only_when_pending(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    next_index = iter([2, 3])
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: append_capture_frame(session, next(next_index)),
        screenshot=lambda: png(),
    )
    first = service.live_capture()
    assert first == {"state_id": "s000002", "edge": None}
    assert store.graph["click_edges"] == []
    store.set_pending_click("s000002", [20, 30])
    second = service.live_capture()
    assert second["state_id"] == "s000003"
    assert second["edge"]["source"] == "s000002"
    assert second["edge"]["target"] == "s000003"
    assert len(store.graph["click_edges"]) == 1


def test_live_refresh_deduplicates_latest_state_and_preserves_pending(tmp_path):
    session, payloads = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    store.set_pending_click("s000001", [20, 30])
    captures = []
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: captures.append(True),
        screenshot=lambda: payloads[-1],
        auto_contract_loader=lambda: fake_auto_contract(),
    )

    result = service.live_refresh()

    assert result == {"state_id": "s000002", "captured": False}
    assert captures == []
    assert store.graph["pending_click"]["source"] == "s000001"
    assert store.graph["click_edges"] == []


def test_live_refresh_captures_changed_view_without_consuming_pending(tmp_path):
    session, _ = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    store.set_pending_click("s000001", [20, 30])
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: append_capture_frame(session, 3),
        screenshot=lambda: png(102, 202, b"changed"),
        auto_contract_loader=lambda: fake_auto_contract(),
    )

    result = service.live_refresh()

    assert result == {"state_id": "s000003", "captured": True}
    assert store.graph["pending_click"]["source"] == "s000001"
    assert store.graph["click_edges"] == []


def test_live_refresh_on_empty_graph_captures_first_active_state(tmp_path):
    session, _ = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    store.clear_graph()
    screenshot_calls = []
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: append_capture_frame(session, 3),
        screenshot=lambda: screenshot_calls.append(True),
        auto_contract_loader=lambda: fake_auto_contract(),
    )

    result = service.live_refresh()

    assert result == {"state_id": "s000003", "captured": True}
    assert [state["id"] for state in store.graph["states"]] == ["s000003"]
    assert screenshot_calls == []
    assert store.graph["capture_floor_index"] == 2


def test_live_refresh_disabled_and_busy_return_conflicts(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    disabled = annotator.AnnotatorService(annotator.GraphStore(session))
    with pytest.raises(annotator.GraphError) as error:
        disabled.live_refresh()
    assert error.value.status == 409

    busy = annotator.AnnotatorService(
        annotator.GraphStore(session),
        capture_frame=lambda: None,
        screenshot=lambda: png(),
    )
    assert busy._action_lock.acquire(blocking=False)
    try:
        with pytest.raises(annotator.GraphError) as error:
            busy.live_refresh()
        assert error.value.status == 409
    finally:
        busy._action_lock.release()


def test_control_disabled_returns_409(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    service = annotator.AnnotatorService(annotator.GraphStore(session))
    with pytest.raises(annotator.GraphError) as error:
        service.control_tap("s000001", [10, 20])
    assert error.value.status == 409


def test_control_tap_stages_then_generate_captures_edge_and_preserves_pending_click(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    (session / "images" / "frame_000001.png").write_bytes(png(100, 200))
    store = annotator.GraphStore(session)
    store.set_pending_click("s000001", [7, 8])
    manifest_before = store.manifest_path.read_bytes()
    taps = []
    sleeps = []
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: append_capture_frame(session, 2),
        screenshot=lambda: png(),
        tap=lambda x, y: taps.append((x, y)),
        swipe=lambda *_args: None,
        action_settle_seconds=0.25,
        sleeper=sleeps.append,
    )
    result = service.control_tap("s000001", [999, -5])
    assert taps == [(99, 0)]
    assert sleeps == [0.25]
    assert result["pending_device_action"] == {
        "kind": "click", "source": "s000001",
        "point_pixel": [99, 0], "point_norm": [990, 0],
    }
    assert [state["id"] for state in store.graph["states"]] == ["s000001"]
    assert store.manifest_path.read_bytes() == manifest_before
    assert store.graph["click_edges"] == []
    assert store.graph["pending_click"]["source"] == "s000001"

    generated = service.generate_state()
    assert generated["state_id"] == "s000002"
    assert generated["edge"]["source"] == "s000001"
    assert generated["edge"]["target"] == "s000002"
    assert generated["edge"]["point_pixel"] == [99, 0]
    assert generated["edge"]["point_norm"] == [990, 0]
    assert store.graph["pending_device_action"] is None
    assert store.graph["pending_click"]["source"] == "s000001"
    service.control_back("s000003")
    canceled = service.cancel_device_action()
    assert canceled == {"kind": "back", "source": "s000003"}
    assert store.graph["pending_device_action"] is None


def test_control_back_stages_then_generate_captures_edge_and_preserves_pending(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    store.set_pending_click("s000001", [10, 20])
    calls = []
    sleeps = []
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: append_capture_frame(session, 2),
        back=lambda: calls.append("back"),
        action_settle_seconds=0.25,
        sleeper=sleeps.append,
    )

    result = service.control_back("s000001")

    assert calls == ["back"]
    assert sleeps == [0.25]
    assert result == {"pending_device_action": {"kind": "back", "source": "s000001"}}
    assert [state["id"] for state in store.graph["states"]] == ["s000001"]
    assert store.graph["back_edges"] == []
    assert store.graph["pending_click"]["source"] == "s000001"
    assert store.graph["click_edges"] == []
    generated = service.generate_state()
    assert generated == {
        "state_id": "s000002",
        "edge": {"id": "be000001", "source": "s000001", "target": "s000002"},
    }
    assert store.graph["pending_click"]["source"] == "s000001"


@pytest.mark.parametrize("failure_stage", ["back", "capture"])
def test_control_back_failure_does_not_create_success_edge(tmp_path, failure_stage):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)

    def send_back():
        if failure_stage == "back":
            raise RuntimeError("back unavailable")

    def capture_after_back():
        if failure_stage == "capture":
            raise RuntimeError("capture unavailable")
        append_capture_frame(session, 2)

    service = annotator.AnnotatorService(
        store,
        capture_frame=capture_after_back,
        back=send_back,
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
    )
    with pytest.raises(annotator.GraphError) as error:
        if failure_stage == "back":
            service.control_back("s000001")
        else:
            service.control_back("s000001")
            service.generate_state()
    assert error.value.status == 502
    assert store.graph["back_edges"] == []
    if failure_stage == "back":
        assert store.graph["pending_device_action"] is None
    else:
        assert store.graph["pending_device_action"]["kind"] == "back"


def test_control_back_disabled_busy_and_fullpage_conflicts(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    disabled = annotator.AnnotatorService(
        annotator.GraphStore(session), capture_frame=lambda: None
    )
    with pytest.raises(annotator.GraphError) as error:
        disabled.control_back("s000001")
    assert error.value.status == 409

    service = annotator.AnnotatorService(
        annotator.GraphStore(session), capture_frame=lambda: None, back=lambda: None
    )
    with pytest.raises(annotator.GraphError, match="forbidden"):
        service.control_back("s000001", "fullpage")

    assert service._action_lock.acquire(blocking=False)
    try:
        with pytest.raises(annotator.GraphError) as error:
            service.control_back("s000001")
        assert error.value.status == 409
    finally:
        service._action_lock.release()


@pytest.mark.parametrize("failure_stage", ["tap", "capture"])
def test_control_tap_failure_does_not_create_success_edge(tmp_path, failure_stage):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)

    def fail_tap(_x, _y):
        if failure_stage == "tap":
            raise RuntimeError("tap unavailable")

    def fail_capture():
        if failure_stage == "capture":
            raise RuntimeError("capture unavailable")
        append_capture_frame(session, 2)

    service = annotator.AnnotatorService(
        store,
        capture_frame=fail_capture,
        screenshot=lambda: png(),
        tap=fail_tap,
        swipe=lambda *_args: None,
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
    )
    with pytest.raises(annotator.GraphError) as error:
        if failure_stage == "tap":
            service.control_tap("s000001", [10, 20])
        else:
            service.control_tap("s000001", [10, 20])
            service.generate_state()
    assert error.value.status == 502
    assert store.graph["click_edges"] == []
    if failure_stage == "tap":
        assert store.graph["pending_device_action"] is None
    else:
        assert store.graph["pending_device_action"]["kind"] == "click"


@pytest.mark.parametrize(
    ("delta_y", "direction", "start_above_end"),
    [(120, "down", True), (-120, "up", False)],
)
def test_control_scroll_stages_then_generate_creates_scroll_edge(tmp_path, delta_y, direction, start_above_end):
    session, _ = write_session(tmp_path, count=1)
    (session / "images" / "frame_000001.png").write_bytes(png(100, 200))
    store = annotator.GraphStore(session)
    swipes = []
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: append_capture_frame(session, 2),
        screenshot=lambda: png(),
        tap=lambda *_args: None,
        swipe=lambda *args: swipes.append(args),
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
    )
    result = service.control_scroll("s000001", [-50, 999], delta_y)
    pending = result["pending_device_action"]
    assert pending["direction"] == direction
    assert pending["anchor_pixel"] == [0, 199]
    assert pending["anchor_norm"] == [0, 995]
    assert swipes == [(*pending["swipe_start_pixel"], *pending["swipe_end_pixel"], 300)]
    assert all(0 <= point[0] < 100 and 0 <= point[1] < 200 for point in (
        pending["swipe_start_pixel"], pending["swipe_end_pixel"]
    ))
    assert (pending["swipe_start_pixel"][1] > pending["swipe_end_pixel"][1]) is start_above_end
    assert [state["id"] for state in store.graph["states"]] == ["s000001"]
    assert store.graph["scroll_edges"] == []
    generated = service.generate_state()
    assert generated["state_id"] == "s000002"
    assert generated["edge"]["direction"] == direction
    assert len(store.graph["scroll_edges"]) == 1


def test_latest_device_action_wins_and_pending_still_blocks_capture_and_longpage(tmp_path):
    session, _ = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    store.set_pending_click("s000001", [5, 6])
    taps, swipes, backs = [], [], []
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: append_capture_frame(session, 3),
        screenshot=lambda: png(101, 201, b"\x01"),
        tap=lambda *args: taps.append(args),
        swipe=lambda *args: swipes.append(args),
        back=lambda: backs.append(True),
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
        auto_contract_loader=lambda: fake_auto_contract(),
    )
    service.control_tap("s000001", [10, 20])
    assert store.graph["pending_device_action"]["kind"] == "click"
    service.control_back("s000002")
    assert store.graph["pending_device_action"] == {"kind": "back", "source": "s000002"}
    assert len(taps) == 1 and backs == [True]

    for action in (
        lambda: service.live_capture(),
        lambda: service.live_refresh(),
        lambda: service.start_scroll("s000002"),
        lambda: service.append_scroll("s000002"),
        lambda: service.auto_scroll_fullpage("s000002"),
    ):
        with pytest.raises(annotator.GraphError) as error:
            action()
        assert error.value.status == 409
    generated = service.generate_state()
    assert generated["state_id"] == "s000003"
    assert generated["edge"] == {
        "id": "be000001", "source": "s000002", "target": "s000003"
    }
    assert store.graph["click_edges"] == []
    assert len(store.graph["back_edges"]) == 1
    assert store.graph["pending_device_action"] is None
    assert store.graph["pending_click"]["source"] == "s000001"


def test_latest_device_action_adb_failure_preserves_previous_pending(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: None,
        tap=lambda *_args: None,
        swipe=lambda *_args: None,
        back=lambda: (_ for _ in ()).throw(RuntimeError("back failed")),
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
    )
    service.control_tap("s000001", [10, 20])
    previous = copy.deepcopy(store.graph["pending_device_action"])
    with pytest.raises(annotator.GraphError, match="ADB Back failed"):
        service.control_back("s000001")
    assert store.graph["pending_device_action"] == previous


def test_latest_device_action_overwrite_save_failure_restores_previous_pending(tmp_path, monkeypatch):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    backs = []
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: None,
        tap=lambda *_args: None,
        swipe=lambda *_args: None,
        back=lambda: backs.append(True),
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
    )
    service.control_tap("s000001", [10, 20])
    graph_before = copy.deepcopy(store.graph)
    history_before = copy.deepcopy(store._history)
    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        service.control_back("s000001")
    assert backs == [True]
    assert store.graph == graph_before
    assert store._history == history_before


def test_generate_without_pending_always_appends_isolated_states(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    next_index = iter([2, 3])
    service = annotator.AnnotatorService(
        annotator.GraphStore(session),
        capture_frame=lambda: append_capture_frame(session, next(next_index)),
    )
    first = service.generate_state()
    second = service.generate_state()
    assert first == {"state_id": "s000002", "edge": None}
    assert second == {"state_id": "s000003", "edge": None}
    assert [state["id"] for state in service.store.graph["states"]] == [
        "s000001", "s000002", "s000003"
    ]
    assert service.store.graph["click_edges"] == []
    assert service.store.graph["scroll_edges"] == []
    assert service.store.graph["back_edges"] == []


def test_stage_and_generate_save_failures_restore_graph_and_history(tmp_path, monkeypatch):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    taps = []
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: append_capture_frame(session, 2),
        tap=lambda *args: taps.append(args),
        swipe=lambda *_args: None,
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
    )
    graph_before = copy.deepcopy(store.graph)
    history_before = copy.deepcopy(store._history)
    real_save = store._save
    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        service.control_tap("s000001", [10, 20])
    assert taps == [(10, 20)]
    assert store.graph == graph_before
    assert store._history == history_before

    monkeypatch.setattr(store, "_save", real_save)
    service.control_tap("s000001", [10, 20])
    staged_graph = copy.deepcopy(store.graph)
    staged_history = copy.deepcopy(store._history)
    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        service.generate_state()
    assert store.graph == staged_graph
    assert store._history == staged_history
    assert store.graph["pending_device_action"]["kind"] == "click"
    assert store.graph["click_edges"] == []
    manifest = json.loads(store.manifest_path.read_text(encoding="utf-8"))
    assert [frame["index"] for frame in manifest["frames"]] == [1, 2]


def test_control_action_lock_returns_busy_conflict(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    service = annotator.AnnotatorService(
        annotator.GraphStore(session),
        capture_frame=lambda: None,
        screenshot=lambda: png(),
        tap=lambda *_args: None,
        swipe=lambda *_args: None,
    )
    assert service._action_lock.acquire(blocking=False)
    try:
        with pytest.raises(annotator.GraphError) as error:
            service.control_tap("s000001", [10, 20])
        assert error.value.status == 409
        assert "in progress" in str(error.value)
    finally:
        service._action_lock.release()


def test_real_actions_are_rejected_for_fullpage_canvas(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    service = annotator.AnnotatorService(
        annotator.GraphStore(session),
        capture_frame=lambda: None,
        screenshot=lambda: png(),
        tap=lambda *_args: None,
        swipe=lambda *_args: None,
    )
    with pytest.raises(annotator.GraphError, match="forbidden"):
        service.control_tap("s000001", [10, 20], "fullpage")


def test_auto_scroll_static_page_stops_after_two_stable_views_and_undoes_once(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    graph_before = copy.deepcopy(store.graph)
    manifest_before = store.manifest_path.read_bytes()
    frame = png(101, 201, b"\x01")
    swipes = []
    service = auto_service(store, [frame, frame, frame, frame], swipes)
    result = service.auto_scroll_fullpage("s000001")

    assert result["frame_count"] == 1
    assert result["steps"] == 2
    assert result["termination"] == "stable"
    assert result["top_restored"] is True
    assert result["source_match_distance"] == 0
    assert [call[-1] for call in swipes] == [750, 750, 400]
    sequence = store.sequence("s000001")
    assert sequence["method"] == "auto_scroll"
    assert sequence["bottom_reached"] is True
    assert sequence["frame_count"] == 1
    assert len(sequence["frames"]) == 1
    assert store.manifest_path.read_bytes() == manifest_before
    assert [state["id"] for state in store.graph["states"]] == ["s000001"]
    assert store.graph["click_edges"] == [] and store.graph["scroll_edges"] == []
    generated_path = session / result["fullpage"]["source_image"]
    assert generated_path.exists()

    assert store.undo()
    restored = copy.deepcopy(store.graph)
    restored.pop("updated_utc", None)
    graph_before.pop("updated_utc", None)
    assert restored == graph_before
    assert generated_path.exists()  # retained as a diagnostic orphan


def test_auto_scroll_moving_then_stable_deduplicates_and_records_parameters(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    frames = [png(101, 201, bytes([value])) for value in (1, 11, 21, 21, 21, 11, 1)]
    swipes = []
    result = auto_service(store, frames, swipes).auto_scroll_fullpage("s000001")
    assert result["steps"] == 4
    assert result["frame_count"] == 3
    assert result["termination"] == "stable"
    assert result["top_restored"] is True
    assert swipes[:4] == [(50, 142, 50, 58, 750)] * 4
    assert swipes[4:] == [(50, 16, 50, 184, 400)] * 2
    sequence = store.sequence("s000001")
    assert sequence["max_steps"] == 14
    assert sequence["patience"] == 2
    assert sequence["stable_distance"] == 4
    assert sequence["scroll_frac"] == 0.42
    assert sequence["source_match_distance"] == 0
    generation = store._state("s000001")["fullpage"]["generation"]
    assert generation["frame_count"] == 3
    assert generation["top_restored"] is True
    assert len(generation["source_frames"]) == 3


def test_auto_scroll_hard_cap_and_restore(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    moving = [png(101, 201, bytes([value])) for value in range(1, 142, 10)]
    screenshots = moving + [moving[0]]
    swipes = []
    result = auto_service(store, screenshots, swipes).auto_scroll_fullpage("s000001")
    assert result["steps"] == 14
    assert result["frame_count"] == 15
    assert result["termination"] == "hard_cap"
    assert result["top_restored"] is True
    assert store.sequence("s000001")["bottom_reached"] is False


def test_auto_scroll_foreground_change_discards_off_app_frame(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    packages = iter([{"package": "pkg.a"}, {"package": "pkg.b"}])
    frame0, frame1 = png(101, 201, b"\x01"), png(101, 201, b"\x20")
    swipes = []
    service = auto_service(store, [frame0, frame1, frame0], swipes, foreground=lambda: next(packages))
    result = service.auto_scroll_fullpage("s000001")
    assert result["termination"] == "off_app"
    assert result["frame_count"] == 1
    assert store.sequence("s000001")["bottom_reached"] is False


def test_auto_scroll_restore_failure_still_generates_with_warning_metadata(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    # One moving frame, two stable frames, then five restore views that never match top.
    screenshots = [png(101, 201, bytes([v])) for v in (1, 11, 11, 11, 90, 90, 90, 90, 90, 90, 90)]
    swipes = []
    result = auto_service(store, screenshots, swipes).auto_scroll_fullpage("s000001")
    assert result["top_restored"] is False
    assert store.sequence("s000001")["top_restored"] is False
    assert store._state("s000001")["fullpage"]["generation"]["top_restored"] is False


def test_auto_scroll_exception_attempts_restore_and_releases_lock(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    frame = png(101, 201, b"\x01")
    swipes = []
    service = auto_service(store, [frame, RuntimeError("capture broke"), frame], swipes)
    with pytest.raises(annotator.GraphError, match="capture broke"):
        service.auto_scroll_fullpage("s000001")
    assert [call[-1] for call in swipes] == [750, 400]
    assert service._action_lock.acquire(blocking=False)
    service._action_lock.release()
    assert store._state("s000001")["fullpage"] is None


def test_auto_scroll_disabled_and_busy_return_409(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    disabled = annotator.AnnotatorService(annotator.GraphStore(session))
    with pytest.raises(annotator.GraphError) as error:
        disabled.auto_scroll_fullpage("s000001")
    assert error.value.status == 409

    store = annotator.GraphStore(session)
    service = auto_service(store, [], [])
    assert service._action_lock.acquire(blocking=False)
    try:
        with pytest.raises(annotator.GraphError) as busy:
            service.auto_scroll_fullpage("s000001")
        assert busy.value.status == 409
    finally:
        service._action_lock.release()


def test_auto_scroll_rejects_live_view_that_does_not_match_selected_state(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    graph_before = copy.deepcopy(store.graph)
    swipes = []
    service = auto_service(store, [png(101, 201, b"\x40")], swipes)
    with pytest.raises(annotator.GraphError) as error:
        service.auto_scroll_fullpage("s000001")
    assert error.value.status == 409
    assert "selected viewport state" in str(error.value)
    assert swipes == []
    assert store.graph == graph_before


def test_auto_scroll_default_contract_uses_real_imagehash_phash():
    from PIL import Image
    import io

    image = Image.new("RGB", (32, 32), "white")
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    contract = annotator.auto_scroll_contract()
    assert contract["scroll_frac"] == 0.42
    assert contract["max_steps"] == 14
    assert contract["patience"] == 2
    assert contract["stable_distance"] == 4
    assert contract["phash"](buffer.getvalue()) - contract["phash"](buffer.getvalue()) == 0


def test_lazy_grounding_imports_work_outside_repo_without_pythonpath(tmp_path):
    script = f"""
import importlib.util
import json
import sys
from pathlib import Path

module_path = Path({str(MODULE_PATH)!r})
spec = importlib.util.spec_from_file_location('isolated_mobile_graph_annotator', module_path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
contract = module.auto_scroll_contract()
from gui_rewalk.src.core.visual_traversal.grounding import stitch
print(json.dumps({{
    'repo_root': str(module.REPO_ROOT),
    'repo_on_path': str(module.REPO_ROOT) in sys.path,
    'tools_on_path': str(module.TOOLS_DIR) in sys.path,
    'stable_distance': contract['stable_distance'],
    'stitch_module': stitch.__name__,
}}))
"""
    env = dict(os.environ)
    env.pop("PYTHONPATH", None)
    completed = subprocess.run(
        [sys.executable, "-I", "-c", script],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    payload = json.loads(completed.stdout)
    assert payload == {
        "repo_root": str(MODULE_PATH.parents[1]),
        "repo_on_path": True,
        "tools_on_path": True,
        "stable_distance": 4,
        "stitch_module": "gui_rewalk.src.core.visual_traversal.grounding.stitch",
    }


def test_shared_region_create_reuse_delete_and_canvas_mismatch(tmp_path):
    session, _ = write_session(tmp_path)
    store = annotator.GraphStore(session)
    region = store.add_annotation("s000001", "region", "viewport", [10, 20, 90, 180])
    shared = store.create_shared_region("s000001", region["id"])
    reused = store.reuse_shared_region("s000002", shared["id"])
    assert reused["shared_region_id"] == shared["id"]
    assert reused["bbox_norm"] == region["bbox_norm"]
    store.delete_annotation("s000002", reused["id"])
    assert shared["members"] == [{"state_id": "s000001", "annotation_id": region["id"]}]
    button = store.add_annotation("s000001", "button", "viewport", [1, 1, 20, 20])
    with pytest.raises(annotator.GraphError, match="Only region"):
        store.create_shared_region("s000001", button["id"])

    store.set_fullpage("s000001", png(100, 400), {"method": "upload"})
    long_region = store.add_annotation("s000001", "region", "fullpage", [1, 1, 99, 399])
    long_shared = store.create_shared_region("s000001", long_region["id"])
    with pytest.raises(annotator.GraphError, match="no fullpage"):
        store.reuse_shared_region("s000002", long_shared["id"])


def test_fullpage_upload_and_fake_scroll_stitch_success_and_failure(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: None,
        screenshot=lambda: png(101, 201, b"scroll"),
        stitcher=lambda frames: (
            png(101, 600, b"stitched"),
            {"sticky_top_h": 12, "sticky_bottom_h": 8, "frame_top_in_composite": [0, 180]},
        ),
    )
    uploaded = service.upload_fullpage("s000001", png(101, 450, b"upload"))
    assert uploaded["generation"] == {"method": "upload"}
    service.start_scroll("s000001")
    service.append_scroll("s000001")
    stitched = service.generate_fullpage("s000001")
    assert (stitched["width"], stitched["height"]) == (101, 600)
    assert stitched["generation"]["sticky_top_h"] == 12
    assert len(stitched["generation"]["source_frames"]) == 2
    fullpage_path = session / stitched["source_image"]
    good_hash = hashlib.sha256(fullpage_path.read_bytes()).hexdigest()

    failing = annotator.AnnotatorService(
        store,
        capture_frame=lambda: None,
        screenshot=lambda: png(),
        stitcher=lambda _frames: (_ for _ in ()).throw(RuntimeError("bad overlap")),
    )
    store.start_sequence("s000001")
    with pytest.raises(annotator.GraphError, match="source frames were retained"):
        failing.generate_fullpage("s000001")
    assert hashlib.sha256(fullpage_path.read_bytes()).hexdigest() == good_hash
    assert store.sequence("s000001")["active"] is True


def test_fullpage_upload_rejects_invalid_png_without_replacing_existing(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    service = annotator.AnnotatorService(store)
    canvas = service.upload_fullpage("s000001", png(100, 400, b"good"))
    path = session / canvas["source_image"]
    before = path.read_bytes()
    with pytest.raises(annotator.CaptureError):
        service.upload_fullpage("s000001", b"not-png")
    assert path.read_bytes() == before


def test_fullpage_save_failure_restores_canvas_annotation_and_png(tmp_path, monkeypatch):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    old_canvas = store.set_fullpage("s000001", png(100, 400, b"old"), {"method": "upload"})
    region = store.add_annotation("s000001", "region", "fullpage", [10, 20, 90, 300])
    old_canvas_snapshot = dict(old_canvas)
    old_bbox = list(region["bbox_xyxy"])
    fullpage_path = session / old_canvas["source_image"]
    old_png = fullpage_path.read_bytes()

    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        store.set_fullpage("s000001", png(200, 800, b"new"), {"method": "upload"})

    restored_state = store._state("s000001")
    restored_region = next(item for item in restored_state["annotations"] if item["id"] == region["id"])
    assert restored_state["fullpage"] == old_canvas_snapshot
    assert restored_region["bbox_xyxy"] == old_bbox
    assert fullpage_path.read_bytes() == old_png


def test_clear_graph_hides_capture_states_keeps_files_and_undo_restores_everything(tmp_path):
    session, payloads = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    fullpage = store.set_fullpage("s000001", png(100, 500, b"full"), {"method": "upload"})
    store.add_annotation("s000001", "region", "fullpage", [1, 2, 90, 450])
    shared_member = store.add_annotation("s000001", "region", "viewport", [3, 4, 70, 150])
    store.create_shared_region("s000001", shared_member["id"])
    store.set_pending_click("s000001", [10, 20])
    store.complete_pending("s000002")
    store.add_scroll_edge("s000002", "s000001", "up", [5, 6], [50, 30], [5, 1], [5, 100])
    store.add_back_edge("s000002", "s000001")
    store.link_same_page("s000002", "s000001")
    store.set_pending_click("s000002", [30, 40])
    sequence = store.start_sequence("s000001")
    store.append_sequence_frame("s000001", png(101, 201, b"scroll"))
    store.stage_device_action({"kind": "back", "source": "s000002"})

    graph_before = copy.deepcopy(store.graph)
    state_ids = [state["id"] for state in store.graph["states"]]
    viewports = copy.deepcopy([state["viewport"] for state in store.graph["states"]])
    manifest_before = store.manifest_path.read_bytes()
    image_hashes = [hashlib.sha256(payload).hexdigest() for payload in payloads]
    fullpage_path = session / fullpage["source_image"]
    fullpage_bytes = fullpage_path.read_bytes()
    scroll_paths = [session / relative for relative in store.sequence("s000001")["frames"]]
    scroll_bytes = [path.read_bytes() for path in scroll_paths]

    summary = store.clear_graph()
    assert summary == {
        "states": 2,
        "annotations": 2,
        "fullpages": 1,
        "click_edges": 1,
        "scroll_edges": 1,
        "back_edges": 1,
        "same_page_links": 1,
        "shared_regions": 1,
        "pending_clicks": 1,
        "pending_device_actions": 1,
        "scroll_sequences": 1,
    }
    assert store.graph["states"] == []
    assert store.graph["capture_floor_index"] == 2
    assert store.graph["click_edges"] == []
    assert store.graph["scroll_edges"] == []
    assert store.graph["back_edges"] == []
    assert store.graph["same_page_links"] == []
    assert store.graph["shared_regions"] == []
    assert store.graph["pending_click"] is None
    assert store.graph["pending_device_action"] is None
    assert store.graph["scroll_sequences"] == {}
    assert store.manifest_path.read_bytes() == manifest_before
    assert [hashlib.sha256((session / "images" / f"frame_{i:06d}.png").read_bytes()).hexdigest() for i in (1, 2)] == image_hashes
    assert fullpage_path.read_bytes() == fullpage_bytes
    assert [path.read_bytes() for path in scroll_paths] == scroll_bytes

    store.sync_capture_manifest()
    assert store.graph["states"] == []

    assert store.undo()
    restored = copy.deepcopy(store.graph)
    restored.pop("updated_utc", None)
    graph_before.pop("updated_utc", None)
    assert restored == graph_before


def test_capture_after_clear_becomes_first_active_state_without_renumbering(tmp_path):
    session, _ = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    store.clear_graph()
    append_capture_frame(session, 3)

    assert store.sync_capture_manifest() == ["s000003"]
    assert [state["id"] for state in store.graph["states"]] == ["s000003"]
    reloaded = annotator.GraphStore(session)
    assert [state["id"] for state in reloaded.graph["states"]] == ["s000003"]


def test_clear_graph_save_failure_restores_graph_and_history(tmp_path, monkeypatch):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    store.add_annotation("s000001", "button", "viewport", [1, 2, 20, 30])
    graph_before = copy.deepcopy(store.graph)
    history_before = copy.deepcopy(store._history)
    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        store.clear_graph()
    assert store.graph == graph_before
    assert store._history == history_before


def test_undo_save_failure_restores_graph_and_history(tmp_path, monkeypatch):
    session, _ = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    store.clear_graph()
    graph_before = copy.deepcopy(store.graph)
    history_before = copy.deepcopy(store._history)
    monkeypatch.setattr(store, "_save", lambda: (_ for _ in ()).throw(OSError("disk full")))
    with pytest.raises(OSError, match="disk full"):
        store.undo()
    assert store.graph == graph_before
    assert store._history == history_before


def test_clear_graph_shares_action_lock_and_returns_busy_conflict(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    service = annotator.AnnotatorService(annotator.GraphStore(session))
    assert service._action_lock.acquire(blocking=False)
    try:
        with pytest.raises(annotator.GraphError) as error:
            service.clear_graph()
        assert error.value.status == 409
    finally:
        service._action_lock.release()


def request_json(connection: http.client.HTTPConnection, method: str, path: str, value=None):
    body = json.dumps(value or {}).encode()
    connection.request(method, path, body=body, headers={"Content-Type": "application/json"})
    response = connection.getresponse()
    payload = response.read()
    return response.status, json.loads(payload) if payload else None


def test_http_get_json_write_image_oversize_and_path_routes(tmp_path):
    session, payloads = write_session(tmp_path, count=1)
    store = annotator.GraphStore(session)
    service = annotator.AnnotatorService(store)
    server = annotator.make_server(service, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    try:
        connection.request("GET", "/api/graph")
        response = connection.getresponse()
        graph_payload = json.loads(response.read())
        assert response.status == 200
        assert graph_payload["graph"]["schema"] == annotator.GRAPH_SCHEMA

        assert service._action_lock.acquire(blocking=False)
        busy_connection = http.client.HTTPConnection(*server.server_address, timeout=3)
        try:
            status, value = request_json(
                busy_connection,
                "POST",
                "/api/annotations",
                {"state_id": "s000001", "kind": "region", "canvas": "viewport", "bbox_xyxy": [1, 2, 50, 70]},
            )
            assert status == 409
            assert "in progress" in value["error"]
            assert store._state("s000001")["annotations"] == []
        finally:
            busy_connection.close()
            service._action_lock.release()

        status, value = request_json(
            connection,
            "POST",
            "/api/annotations",
            {"state_id": "s000001", "kind": "region", "canvas": "viewport", "bbox_xyxy": [1, 2, 50, 70]},
        )
        assert status == 200 and value["result"]["id"] == "a000001"

        status, value = request_json(
            connection,
            "POST",
            "/api/control/tap",
            {"state_id": "s000001", "canvas": "viewport", "point_pixel": [10, 20]},
        )
        assert status == 409
        assert "--live-control" in value["error"]

        status, value = request_json(connection, "POST", "/api/scroll/auto", {"state_id": "s000001"})
        assert status == 409
        assert "--live-control" in value["error"]

        status, value = request_json(connection, "POST", "/api/clear", {})
        assert status == 200
        assert value["result"]["annotations"] == 1
        assert value["result"]["states"] == 1
        assert value["graph"]["states"] == []
        assert value["graph"]["capture_floor_index"] == 1

        connection.request("GET", "/api/image/s000001/viewport")
        response = connection.getresponse()
        assert response.status == 404
        response.read()

        connection.request("GET", "/api/image/../../manifest.json")
        response = connection.getresponse()
        assert response.status == 404
        response.read()

        connection.putrequest("POST", "/api/annotations")
        connection.putheader("Content-Type", "application/json")
        connection.putheader("Content-Length", str(annotator.MAX_JSON_BODY + 1))
        connection.endheaders()
        response = connection.getresponse()
        assert response.status == 413
        assert "size limit" in json.loads(response.read())["error"]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_http_live_refresh_route_returns_deduplicated_latest_state(tmp_path):
    session, payloads = write_session(tmp_path, count=2)
    store = annotator.GraphStore(session)
    service = annotator.AnnotatorService(
        store,
        capture_frame=lambda: (_ for _ in ()).throw(AssertionError("must not capture")),
        screenshot=lambda: payloads[-1],
        auto_contract_loader=lambda: fake_auto_contract(),
    )
    server = annotator.make_server(service, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    try:
        status, value = request_json(connection, "POST", "/api/live-refresh", {})
        assert status == 200
        assert value["result"] == {"state_id": "s000002", "captured": False}
        assert [state["id"] for state in value["graph"]["states"]] == ["s000001", "s000002"]
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_http_back_flag_and_control_route(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    calls = []
    service = annotator.AnnotatorService(
        annotator.GraphStore(session),
        capture_frame=lambda: append_capture_frame(session, 2),
        back=lambda: calls.append("back"),
        action_settle_seconds=0,
        sleeper=lambda _seconds: None,
    )
    server = annotator.make_server(service, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    try:
        connection.request("GET", "/api/graph")
        response = connection.getresponse()
        payload = json.loads(response.read())
        assert response.status == 200
        assert payload["back_enabled"] is True
        assert payload["control_enabled"] is False

        status, value = request_json(
            connection, "POST", "/api/control/back",
            {"state_id": "s000001", "canvas": "viewport"},
        )
        assert status == 200
        assert value["result"]["pending_device_action"] == {
            "kind": "back", "source": "s000001"
        }
        assert calls == ["back"]
        status, value = request_json(connection, "POST", "/api/state/generate", {})
        assert status == 200
        assert value["result"]["state_id"] == "s000002"
        assert value["result"]["edge"]["id"] == "be000001"

        status, value = request_json(
            connection, "POST", "/api/control/back",
            {"state_id": "s000002", "canvas": "viewport"},
        )
        assert status == 200
        status, value = request_json(connection, "POST", "/api/device-action/cancel", {})
        assert status == 200
        assert value["result"] == {"kind": "back", "source": "s000002"}
        assert value["graph"]["pending_device_action"] is None
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_http_same_page_link_route_is_undirected_and_idempotent(tmp_path):
    session, _ = write_session(tmp_path, count=2)
    service = annotator.AnnotatorService(annotator.GraphStore(session))
    server = annotator.make_server(service, "127.0.0.1", 0)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    connection = http.client.HTTPConnection(*server.server_address, timeout=3)
    try:
        status, value = request_json(
            connection, "POST", "/api/same-page/link",
            {"state_id": "s000002", "peer_state_id": "s000001"},
        )
        assert status == 200
        assert value["result"] == {
            "id": "sp000001", "states": ["s000001", "s000002"]
        }
        status, value = request_json(
            connection, "POST", "/api/same-page/link",
            {"state_id": "s000001", "peer_state_id": "s000002"},
        )
        assert status == 200
        assert len(value["graph"]["same_page_links"]) == 1
    finally:
        connection.close()
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


def test_server_rejects_non_loopback_binding(tmp_path):
    session, _ = write_session(tmp_path, count=1)
    service = annotator.AnnotatorService(annotator.GraphStore(session))
    with pytest.raises(annotator.GraphError, match="outside loopback"):
        annotator.make_server(service, "0.0.0.0", 0)


def test_html_static_contract_has_geometry_workflows_and_no_text_annotation_input():
    html = (MODULE_PATH.parent / "mobile_graph_annotator.html").read_text(encoding="utf-8")
    for required in (
        "buttonMode",
        "regionMode",
        "clickMode",
        "makeShared",
        "reuseShared",
        "captureTarget",
        "setExistingTarget",
        "uploadFullpage",
        "startScroll",
        "appendScroll",
        "stitchScroll",
        "状态图",
        "vmControl",
        "vmBack",
        "虚拟机返回（Back）",
        "/api/control/back",
        "backAvailable",
        "j.back_enabled",
        "samePagePeer",
        "linkSamePage",
        "标为同一页面",
        "/api/same-page/link",
        "same-page ${link.states[0]} ↔ ${link.states[1]}",
        "modal、drawer、popup 等不同活跃表面不要标为同页",
        "/api/control/tap",
        "/api/control/scroll",
        "addEventListener('wheel'",
        "preventDefault()",
        "controlAvailable",
        "generateState",
        "/api/state/generate",
        "生成状态",
        "状态图为空；点击“生成状态”开始",
        "deviceActionText",
        "cancelDeviceAction",
        "/api/device-action/cancel",
        "取消待生成（不回退设备）",
        "按钮仅标当前前景/活跃区块内可操作项",
        "没有局部前景区时整页视为活跃区",
        "clearGraph",
        "/api/clear",
        "window.confirm",
        "原始截图文件与 capture manifest 保留不变",
        "从活动状态图隐藏所有 states",
        "清除所有框、点击点/待完成点、待生成设备动作、click/scroll/back 边、同页关系、共享区块、长图关联和滚动采集记录",
        "autoScroll",
        "/api/scroll/auto",
        "一键生成滚动长图",
        "最多执行14次向下小步滑动",
        "正在自动滚动并拼接…",
        "设备未确认回顶",
        "if(ui.busy)return",
    ):
        assert required in html
    assert not re.search(r"<input[^>]+type=[\"'](?:text|search)[\"']", html, re.IGNORECASE)
    assert "bbox_xyxy" in html
    assert "selectedIndex=sharedOptions.length-1" in html
    assert "reuseShared').disabled=ui.busy||sharedOptions.length===0" in html
    assert "ui.control=false" in html
    assert "$('clearGraph').disabled=ui.busy||!hasState" in html
    assert "$('autoScroll').disabled=!ui.controlAvailable||!hasState||ui.busy||!!devicePending" in html
    assert "$('vmBack').disabled=!ui.backAvailable||!hasState||full||ui.busy" in html
    assert "$('generateState').disabled=!ui.live||ui.busy" in html
    assert "$('cancelDeviceAction').disabled=ui.busy||!devicePending" in html
    assert "back ${e.source} → ${e.target}" in html
    assert "stageControlAction('/api/control/back'" in html
    assert "stageControlAction('/api/control/tap'" in html
    assert "stageControlAction('/api/control/scroll'" in html
    assert "$('linkSamePage').disabled=ui.busy||peerOptions.length===0" in html
    assert "filter(s=>s.id!==state().id)" in html
    assert "ui.index=Math.max(0,j.graph.states.length-1)" in html
    assert "$('screen').removeAttribute('src')" in html
    assert "$('overlay').replaceChildren()" in html
    assert "$('nodes').replaceChildren" in html
    assert "$('edges').replaceChildren" in html
    assert "fetch('/api/graph')" in html
    assert "/api/live-refresh" not in html
    for control_id in (
        "deleteSelection", "undo", "captureTarget", "setExistingTarget",
        "makeShared", "reuseShared", "uploadFullpage", "fullpageFile",
        "startScroll", "appendScroll", "stitchScroll",
    ):
        assert control_id in html


def test_local_graph_one_hop_induced_subgraph_and_layout_with_node(tmp_path):
    html = (MODULE_PATH.parent / "mobile_graph_annotator.html").read_text(encoding="utf-8")
    match = re.search(
        r"// LOCAL_GRAPH_HELPERS_START\s*(.*?)\s*// LOCAL_GRAPH_HELPERS_END",
        html,
        re.DOTALL,
    )
    assert match
    node = shutil.which("node")
    assert node, "Node.js is required for the local-graph pure-JS contract test"
    assertions = r"""
const assert = require('assert');
const graph = {
  states: ['A','B','C','D','E'].map((id, i) => ({id, frame_index:i+1})),
  click_edges: [
    {id:'AB', source:'A', target:'B'},
    {id:'AC', source:'A', target:'C'},
    {id:'AE', source:'A', target:'E'},
  ],
  scroll_edges: [{id:'BC', source:'B', target:'C'}],
  back_edges: [{id:'BD', source:'B', target:'D'}],
  same_page_links: [{id:'AD', states:['A','D']}],
};
const sub = oneHopSubgraph(graph, 'B');
assert.deepStrictEqual(sub.nodes, ['A','B','C','D']);
assert.deepStrictEqual(sub.relations.map(r => r.id).sort(), ['AB','AC','AD','BC','BD']);
assert(!sub.nodes.includes('E'));
assert(!sub.relations.some(r => r.id === 'AE'));
assert(sub.relations.some(r => r.id === 'AC'));
assert(sub.relations.some(r => r.id === 'AD' && r.directed === false && r.type === 'same-page'));
assert(sub.relations.some(r => r.id === 'BC' && r.directed === true && r.source === 'B' && r.target === 'C'));
assert.deepStrictEqual(oneHopSubgraph({states:[]}, null), {nodes:[], relations:[]});
const isolated = oneHopSubgraph({states:[{id:'B'}]}, 'B');
assert.deepStrictEqual(isolated, {nodes:['B'], relations:[]});
const isolatedLayout = localGraphLayout(isolated.nodes, 'B');
assert.strictEqual(Object.keys(isolatedLayout.positions).length, 1);
assert.deepStrictEqual(clipLocalGraphPoint({x:0,y:0},{x:100,y:0},10,20), {x:10,y:0});
const two = localGraphLayout(['B','A','C'], 'B');
assert(Math.abs(two.positions.A.y-two.positions.B.y) < 1e-9);
assert(Math.abs(two.positions.C.y-two.positions.B.y) < 1e-9);
assert(two.positions.A.x < two.positions.B.x && two.positions.C.x > two.positions.B.x);
const many = ['B', ...Array.from({length:30}, (_,i) => `N${i}`)];
const layout = localGraphLayout(many, 'B');
assert.strictEqual(Object.keys(layout.positions).length, many.length);
assert(layout.width > 600 && layout.height > 600);
for (const p of Object.values(layout.positions)) {
  assert(p.x >= 0 && p.x <= layout.width && p.y >= 0 && p.y <= layout.height);
}
"""
    completed = subprocess.run(
        [node, "-e", match.group(1) + "\n" + assertions],
        cwd=tmp_path,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr


def test_local_graph_ui_is_read_only_responsive_and_keyboard_navigable(tmp_path):
    html = (MODULE_PATH.parent / "mobile_graph_annotator.html").read_text(encoding="utf-8")
    for required in (
        "当前页局部图（1-hop）",
        "localGraphSummary",
        "localGraphRelations",
        "局部图关系明细",
        "relation-detail",
        "localGraphEmpty",
        "graphRelations",
        "oneHopSubgraph",
        "localGraphLayout",
        "clipLocalGraphPoint",
        "renderLocalGraph",
        "jumpLocalState",
        "marker-end",
        "stroke-dasharray",
        "same-page（无向）",
        "role:'button'",
        "tabindex:0",
        "ev.key==='Enter'||ev.key===' '",
        "ui.canvas='viewport'",
        "/api/image/${id}/viewport",
        "panel.setAttribute('viewBox'",
        "Math.max(260,neighbors.length*48)",
        "neighbors.length===2?(i===0?Math.PI:0)",
        "canonicalIds=[r.source,r.target].sort()",
        "—${r.type}→",
        "←same-page→",
    ):
        assert required in html
    assert html.index("for(const relations of groups.values())") < html.index("for(const id of sub.nodes)")
    assert not re.search(r"<(?:script|link)[^>]+(?:src|href)=[\"']https?://", html, re.IGNORECASE)
    assert "if(full||!hasState||devicePending)" not in html
    assert "$('vmControl').disabled=!ui.controlAvailable||!hasState||full||ui.busy" in html
    assert "$('vmBack').disabled=!ui.backAvailable||!hasState||full||ui.busy" in html
    assert "async function stageControlAction(path,data){if(ui.busy)return" in html
    assert "继续操作会覆盖，只保留最后一次" in html
    script = re.search(r"<script>\s*(.*?)\s*</script>", html, re.DOTALL)
    assert script
    script_path = tmp_path / "mobile_graph_annotator_ui.js"
    script_path.write_text(script.group(1), encoding="utf-8")
    completed = subprocess.run(
        [shutil.which("node") or "node", "--check", str(script_path)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
