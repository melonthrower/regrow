#!/usr/bin/env python3
"""Loopback-only, box-and-point mobile state graph annotation server."""

from __future__ import annotations

import argparse
import copy
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import io
import ipaddress
import json
import math
import os
from pathlib import Path
import sys
import threading
import time
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import parse_qs, urlsplit
import webbrowser


TOOLS_DIR = Path(__file__).resolve().parent
REPO_ROOT = TOOLS_DIR.parent
_TRUSTED_IMPORT_ROOTS = [str(TOOLS_DIR), str(REPO_ROOT)]
for _trusted_root in _TRUSTED_IMPORT_ROOTS:
    while _trusted_root in sys.path:
        sys.path.remove(_trusted_root)
sys.path[:0] = _TRUSTED_IMPORT_ROOTS

from capture_mobile_screens import (  # noqa: E402
    AdbClient,
    CaptureApp,
    CaptureError,
    SCHEMA_ID as CAPTURE_SCHEMA,
    SessionStore,
    png_dimensions,
)


GRAPH_SCHEMA = "gui_rewalk.manual_grounding_graph.v1"
MAX_JSON_BODY = 1_000_000
MAX_PNG_BODY = 30_000_000
FORBIDDEN_GRAPH_KEYS = {"name", "label"}


class GraphError(RuntimeError):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _atomic_json(path: Path, data: Mapping[str, Any]) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    os.replace(temporary, path)


def _atomic_bytes(path: Path, data: bytes) -> None:
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def _assert_no_semantic_text_keys(value: Any) -> None:
    if isinstance(value, dict):
        forbidden = FORBIDDEN_GRAPH_KEYS.intersection(value)
        if forbidden:
            raise GraphError(f"Graph must not contain semantic text fields: {sorted(forbidden)}")
        for child in value.values():
            _assert_no_semantic_text_keys(child)
    elif isinstance(value, list):
        for child in value:
            _assert_no_semantic_text_keys(child)


def _numbers(values: Any, count: int, field: str) -> list[float]:
    if not isinstance(values, list) or len(values) != count:
        raise GraphError(f"{field} must contain {count} numbers")
    try:
        converted = [float(value) for value in values]
    except (TypeError, ValueError) as exc:
        raise GraphError(f"{field} must contain only numbers") from exc
    if any(value != value or value in (float("inf"), float("-inf")) for value in converted):
        raise GraphError(f"{field} must contain finite numbers")
    return converted


def normalize_bbox(bbox: Any, width: int, height: int) -> tuple[list[int], list[int]]:
    x1, y1, x2, y2 = _numbers(bbox, 4, "bbox_xyxy")
    x1, x2 = sorted((max(0.0, min(float(width), x1)), max(0.0, min(float(width), x2))))
    y1, y2 = sorted((max(0.0, min(float(height), y1)), max(0.0, min(float(height), y2))))
    pixels = [round(x1), round(y1), round(x2), round(y2)]
    if pixels[2] <= pixels[0] or pixels[3] <= pixels[1]:
        raise GraphError("bbox_xyxy must have a positive area inside the canvas")
    norm = [
        round(pixels[0] * 1000 / width),
        round(pixels[1] * 1000 / height),
        round(pixels[2] * 1000 / width),
        round(pixels[3] * 1000 / height),
    ]
    return pixels, [max(0, min(1000, value)) for value in norm]


def bbox_from_norm(norm: Any, width: int, height: int) -> tuple[list[int], list[int]]:
    values = _numbers(norm, 4, "bbox_norm")
    return normalize_bbox(
        [values[0] * width / 1000, values[1] * height / 1000,
         values[2] * width / 1000, values[3] * height / 1000],
        width,
        height,
    )


def normalize_point(point: Any, width: int, height: int) -> tuple[list[int], list[int]]:
    x, y = _numbers(point, 2, "point_pixel")
    pixels = [round(max(0.0, min(float(width - 1), x))), round(max(0.0, min(float(height - 1), y)))]
    norm = [round(pixels[0] * 1000 / width), round(pixels[1] * 1000 / height)]
    return pixels, [max(0, min(1000, value)) for value in norm]


def normalize_action_point(point: Any, width: int, height: int) -> tuple[list[int], list[int]]:
    """Clamp a real device action to valid pixel indices, then normalize it."""

    x, y = _numbers(point, 2, "action_pixel")
    pixels = [
        max(0, min(width - 1, round(x))),
        max(0, min(height - 1, round(y))),
    ]
    norm = [round(pixels[0] * 1000 / width), round(pixels[1] * 1000 / height)]
    return pixels, [max(0, min(1000, value)) for value in norm]


class GraphStore:
    def __init__(self, session_dir: Path, clock: Callable[[], str] = utc_now):
        self.session_dir = Path(session_dir).resolve()
        self.manifest_path = self.session_dir / "manifest.json"
        self.annotations_dir = self.session_dir / "annotations"
        self.graph_path = self.annotations_dir / "graph.json"
        self.fullpage_dir = self.annotations_dir / "fullpage"
        self.scroll_root = self.annotations_dir / "scroll_frames"
        self.clock = clock
        self._history: list[dict[str, Any]] = []
        if not self.session_dir.is_dir():
            raise GraphError(f"Capture session directory does not exist: {self.session_dir}")
        self.annotations_dir.mkdir(exist_ok=True)
        self.fullpage_dir.mkdir(exist_ok=True)
        self.scroll_root.mkdir(exist_ok=True)
        self.capture_manifest = self._read_capture_manifest()
        self.graph = self._load_graph()
        self.sync_capture_manifest(persist=True)

    def _read_capture_manifest(self) -> dict[str, Any]:
        try:
            manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except FileNotFoundError as exc:
            raise GraphError("Capture manifest.json was not found") from exc
        except (OSError, json.JSONDecodeError) as exc:
            raise GraphError(f"Capture manifest is invalid: {exc}") from exc
        if manifest.get("schema") != CAPTURE_SCHEMA:
            raise GraphError(f"Unsupported capture manifest schema: {manifest.get('schema')!r}")
        if not isinstance(manifest.get("frames"), list):
            raise GraphError("Capture manifest frames must be a list")
        return manifest

    def _load_graph(self) -> dict[str, Any]:
        if self.graph_path.exists():
            try:
                graph = json.loads(self.graph_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                raise GraphError(f"Annotation graph is invalid: {exc}") from exc
            if graph.get("schema") != GRAPH_SCHEMA:
                raise GraphError(f"Unsupported annotation graph schema: {graph.get('schema')!r}")
            graph.setdefault("scroll_edges", [])
            graph.setdefault("back_edges", [])
            graph.setdefault("same_page_links", [])
            graph.setdefault("pending_device_action", None)
            graph.setdefault("capture_floor_index", 0)
            try:
                graph["capture_floor_index"] = int(graph["capture_floor_index"])
            except (TypeError, ValueError) as exc:
                raise GraphError("Annotation graph capture_floor_index must be an integer") from exc
            if graph["capture_floor_index"] < 0:
                raise GraphError("Annotation graph capture_floor_index cannot be negative")
            _assert_no_semantic_text_keys(graph)
            return graph
        now = self.clock()
        return {
            "schema": GRAPH_SCHEMA,
            "session": {
                "id": self.capture_manifest.get("session", {}).get("id", self.session_dir.name),
                "capture_schema": CAPTURE_SCHEMA,
                "capture_manifest": "manifest.json",
            },
            "created_utc": now,
            "updated_utc": now,
            "capture_floor_index": 0,
            "states": [],
            "click_edges": [],
            "scroll_edges": [],
            "back_edges": [],
            "same_page_links": [],
            "shared_regions": [],
            "pending_click": None,
            "pending_device_action": None,
            "scroll_sequences": {},
        }

    def _safe_relative(self, relative: str, expected_parent: str | None = None) -> Path:
        if not isinstance(relative, str) or not relative:
            raise GraphError("Manifest contains an invalid relative path")
        candidate = (self.session_dir / relative).resolve()
        try:
            candidate.relative_to(self.session_dir)
        except ValueError as exc:
            raise GraphError(f"Manifest path escapes the session: {relative!r}") from exc
        if expected_parent and (not Path(relative).parts or Path(relative).parts[0] != expected_parent):
            raise GraphError(f"Manifest path is outside {expected_parent}/: {relative!r}")
        return candidate

    def _save(self) -> None:
        _assert_no_semantic_text_keys(self.graph)
        self.graph["updated_utc"] = self.clock()
        _atomic_json(self.graph_path, self.graph)

    def _remember(self) -> None:
        self._history.append(copy.deepcopy(self.graph))
        if len(self._history) > 100:
            del self._history[0]

    def undo(self) -> bool:
        if not self._history:
            return False
        before = copy.deepcopy(self.graph)
        history_before = copy.deepcopy(self._history)
        self.graph = self._history.pop()
        try:
            self._save()
        except BaseException:
            self.graph = before
            self._history = history_before
            raise
        return True

    def clear_graph(self) -> dict[str, int]:
        """Hide every captured state from the active graph without deleting artifacts."""

        summary = {
            "states": len(self.graph["states"]),
            "annotations": sum(len(state.get("annotations", [])) for state in self.graph["states"]),
            "fullpages": sum(1 for state in self.graph["states"] if state.get("fullpage") is not None),
            "click_edges": len(self.graph["click_edges"]),
            "scroll_edges": len(self.graph["scroll_edges"]),
            "back_edges": len(self.graph["back_edges"]),
            "same_page_links": len(self.graph["same_page_links"]),
            "shared_regions": len(self.graph["shared_regions"]),
            "pending_clicks": int(self.graph.get("pending_click") is not None),
            "pending_device_actions": int(self.graph.get("pending_device_action") is not None),
            "scroll_sequences": len(self.graph["scroll_sequences"]),
        }
        before = copy.deepcopy(self.graph)
        history_before = copy.deepcopy(self._history)
        self._remember()
        try:
            capture_manifest = self._read_capture_manifest()
            manifest_indices: list[int] = []
            for frame in capture_manifest["frames"]:
                try:
                    manifest_indices.append(int(frame.get("index")))
                except (TypeError, ValueError) as exc:
                    raise GraphError("Capture frame index must be an integer") from exc
            state_indices = [int(state["frame_index"]) for state in self.graph["states"]]
            self.graph["capture_floor_index"] = max(
                [int(self.graph.get("capture_floor_index", 0)), *manifest_indices, *state_indices]
            )
            self.graph["states"] = []
            self.graph["click_edges"] = []
            self.graph["scroll_edges"] = []
            self.graph["back_edges"] = []
            self.graph["same_page_links"] = []
            self.graph["shared_regions"] = []
            self.graph["pending_click"] = None
            self.graph["pending_device_action"] = None
            self.graph["scroll_sequences"] = {}
            self._save()
        except BaseException:
            self.graph = before
            self._history = history_before
            raise
        return summary

    def _next_id(self, prefix: str, values: Sequence[Mapping[str, Any]]) -> str:
        greatest = 0
        for value in values:
            identifier = str(value.get("id", ""))
            if identifier.startswith(prefix) and identifier[len(prefix):].isdigit():
                greatest = max(greatest, int(identifier[len(prefix):]))
        return f"{prefix}{greatest + 1:06d}"

    def _state(self, state_id: str) -> dict[str, Any]:
        for state in self.graph["states"]:
            if state.get("id") == state_id:
                return state
        raise GraphError(f"Unknown state id: {state_id}", 404)

    def canvas(self, state_id: str, canvas_kind: str) -> dict[str, Any]:
        if canvas_kind not in {"viewport", "fullpage"}:
            raise GraphError("canvas must be viewport or fullpage")
        canvas = self._state(state_id).get(canvas_kind)
        if not isinstance(canvas, dict):
            raise GraphError(f"State {state_id} has no {canvas_kind} canvas", 409)
        return canvas

    def sync_capture_manifest(self, persist: bool = True) -> list[str]:
        self.capture_manifest = self._read_capture_manifest()
        existing = {state.get("frame_index"): state for state in self.graph["states"]}
        capture_floor_index = int(self.graph.get("capture_floor_index", 0))
        states: list[dict[str, Any]] = []
        seen_indices: set[int] = set()
        for frame in self.capture_manifest["frames"]:
            try:
                index = int(frame.get("index"))
            except (TypeError, ValueError) as exc:
                raise GraphError("Capture frame index must be an integer") from exc
            if index <= 0 or index in seen_indices:
                raise GraphError(f"Capture frame index is invalid or duplicated: {index}")
            seen_indices.add(index)
            if index <= capture_floor_index:
                continue
            image_relative = frame.get("image")
            image_path = self._safe_relative(image_relative, "images")
            try:
                image_bytes = image_path.read_bytes()
            except OSError as exc:
                raise GraphError(f"Capture image is unavailable: {image_relative}") from exc
            width, height = png_dimensions(image_bytes)
            state_id = f"s{index:06d}"
            state = existing.get(index)
            if state is None:
                state = {
                    "id": state_id,
                    "frame_index": index,
                    "viewport": {
                        "source_image": image_relative,
                        "width": width,
                        "height": height,
                        "sha256": hashlib.sha256(image_bytes).hexdigest(),
                    },
                    "fullpage": None,
                    "annotations": [],
                }
            else:
                state["id"] = state_id
                state["viewport"] = {
                    "source_image": image_relative,
                    "width": width,
                    "height": height,
                    "sha256": hashlib.sha256(image_bytes).hexdigest(),
                }
            states.append(state)
        states.sort(key=lambda state: state["frame_index"])
        valid_ids = {state["id"] for state in states}
        self.graph["states"] = states
        self.graph["click_edges"] = [
            edge for edge in self.graph["click_edges"]
            if edge.get("source") in valid_ids and edge.get("target") in valid_ids
        ]
        self.graph["scroll_edges"] = [
            edge for edge in self.graph["scroll_edges"]
            if edge.get("source") in valid_ids and edge.get("target") in valid_ids
        ]
        self.graph["back_edges"] = [
            edge for edge in self.graph["back_edges"]
            if edge.get("source") in valid_ids and edge.get("target") in valid_ids
        ]
        state_order = {state["id"]: (int(state["frame_index"]), state["id"]) for state in states}
        valid_same_page_links: list[dict[str, Any]] = []
        seen_same_page_pairs: set[tuple[str, str]] = set()
        for link in self.graph["same_page_links"]:
            members = link.get("states")
            if not isinstance(members, list) or len(members) != 2:
                continue
            if members[0] == members[1] or any(member not in valid_ids for member in members):
                continue
            canonical = tuple(sorted(members, key=state_order.__getitem__))
            if canonical in seen_same_page_pairs:
                continue
            seen_same_page_pairs.add(canonical)
            link["states"] = list(canonical)
            valid_same_page_links.append(link)
        self.graph["same_page_links"] = valid_same_page_links
        pending = self.graph.get("pending_click")
        if pending and pending.get("source") not in valid_ids:
            self.graph["pending_click"] = None
        pending_device_action = self.graph.get("pending_device_action")
        if pending_device_action and pending_device_action.get("source") not in valid_ids:
            self.graph["pending_device_action"] = None
        self._repair_shared_members()
        if persist:
            self._save()
        return [state["id"] for state in states]

    def _annotation(self, state_id: str, annotation_id: str) -> tuple[dict[str, Any], dict[str, Any]]:
        state = self._state(state_id)
        for annotation in state["annotations"]:
            if annotation.get("id") == annotation_id:
                return state, annotation
        raise GraphError(f"Unknown annotation id: {annotation_id}", 404)

    def add_annotation(self, state_id: str, kind: str, canvas_kind: str, bbox: Any) -> dict[str, Any]:
        if kind not in {"button", "region"}:
            raise GraphError("annotation kind must be button or region")
        if canvas_kind == "fullpage" and kind != "region":
            raise GraphError("Fullpage canvas accepts region boxes only", 409)
        if canvas_kind not in {"viewport", "fullpage"}:
            raise GraphError("canvas must be viewport or fullpage")
        canvas = self.canvas(state_id, canvas_kind)
        pixels, norm = normalize_bbox(bbox, int(canvas["width"]), int(canvas["height"]))
        state = self._state(state_id)
        all_annotations = [item for s in self.graph["states"] for item in s["annotations"]]
        annotation = {
            "id": self._next_id("a", all_annotations),
            "kind": kind,
            "canvas": canvas_kind,
            "bbox_xyxy": pixels,
            "bbox_norm": norm,
        }
        self._remember()
        state["annotations"].append(annotation)
        self._save()
        return annotation

    def delete_annotation(self, state_id: str, annotation_id: str) -> dict[str, Any]:
        state, annotation = self._annotation(state_id, annotation_id)
        self._remember()
        state["annotations"].remove(annotation)
        shared_id = annotation.get("shared_region_id")
        if shared_id:
            shared = self._shared(shared_id)
            shared["members"] = [
                member for member in shared["members"]
                if not (member.get("state_id") == state_id and member.get("annotation_id") == annotation_id)
            ]
            if not shared["members"]:
                self.graph["shared_regions"].remove(shared)
        self._save()
        return annotation

    def set_pending_click(self, state_id: str, point: Any) -> dict[str, Any]:
        canvas = self.canvas(state_id, "viewport")
        pixels, norm = normalize_point(point, int(canvas["width"]), int(canvas["height"]))
        pending = {"source": state_id, "point_pixel": pixels, "point_norm": norm}
        self._remember()
        self.graph["pending_click"] = pending
        self._save()
        return pending

    def complete_pending(self, target_state_id: str, persist: bool = True) -> dict[str, Any]:
        self._state(target_state_id)
        pending = self.graph.get("pending_click")
        if not isinstance(pending, dict):
            raise GraphError("There is no pending click", 409)
        edge = {
            "id": self._next_id("e", self.graph["click_edges"]),
            "source": pending["source"],
            "target": target_state_id,
            "point_pixel": list(pending["point_pixel"]),
            "point_norm": list(pending["point_norm"]),
        }
        self._remember()
        self.graph["click_edges"].append(edge)
        self.graph["pending_click"] = None
        if persist:
            self._save()
        return edge

    def add_click_edge(
        self,
        source_state_id: str,
        target_state_id: str,
        point_pixel: list[int],
        point_norm: list[int],
        persist: bool = True,
        remember: bool = True,
    ) -> dict[str, Any]:
        self._state(source_state_id)
        self._state(target_state_id)
        edge = {
            "id": self._next_id("e", self.graph["click_edges"]),
            "source": source_state_id,
            "target": target_state_id,
            "point_pixel": list(point_pixel),
            "point_norm": list(point_norm),
        }
        if remember:
            self._remember()
        self.graph["click_edges"].append(edge)
        if persist:
            self._save()
        return edge

    def add_scroll_edge(
        self,
        source_state_id: str,
        target_state_id: str,
        direction: str,
        anchor_pixel: list[int],
        anchor_norm: list[int],
        swipe_start_pixel: list[int],
        swipe_end_pixel: list[int],
        persist: bool = True,
        remember: bool = True,
    ) -> dict[str, Any]:
        self._state(source_state_id)
        self._state(target_state_id)
        if direction not in {"down", "up"}:
            raise GraphError("Scroll direction must be down or up")
        edge = {
            "id": self._next_id("se", self.graph["scroll_edges"]),
            "source": source_state_id,
            "target": target_state_id,
            "direction": direction,
            "anchor_pixel": list(anchor_pixel),
            "anchor_norm": list(anchor_norm),
            "swipe_start_pixel": list(swipe_start_pixel),
            "swipe_end_pixel": list(swipe_end_pixel),
        }
        if remember:
            self._remember()
        self.graph["scroll_edges"].append(edge)
        if persist:
            self._save()
        return edge

    def add_back_edge(
        self, source_state_id: str, target_state_id: str, persist: bool = True,
        remember: bool = True,
    ) -> dict[str, Any]:
        self._state(source_state_id)
        self._state(target_state_id)
        edge = {
            "id": self._next_id("be", self.graph["back_edges"]),
            "source": source_state_id,
            "target": target_state_id,
        }
        if remember:
            self._remember()
        self.graph["back_edges"].append(edge)
        if persist:
            self._save()
        return edge

    def stage_device_action(self, action: Mapping[str, Any]) -> dict[str, Any]:
        pending = copy.deepcopy(dict(action))
        self._state(str(pending.get("source", "")))
        before = copy.deepcopy(self.graph)
        history_before = copy.deepcopy(self._history)
        self._remember()
        try:
            self.graph["pending_device_action"] = pending
            self._save()
        except BaseException:
            self.graph = before
            self._history = history_before
            raise
        return pending

    def cancel_device_action(self) -> dict[str, Any] | None:
        pending = self.graph.get("pending_device_action")
        if pending is None:
            return None
        canceled = copy.deepcopy(pending)
        before = copy.deepcopy(self.graph)
        history_before = copy.deepcopy(self._history)
        self._remember()
        try:
            self.graph["pending_device_action"] = None
            self._save()
        except BaseException:
            self.graph = before
            self._history = history_before
            raise
        return canceled

    def link_same_page(self, state_id: str, peer_state_id: str) -> dict[str, Any]:
        state = self._state(state_id)
        peer = self._state(peer_state_id)
        if state_id == peer_state_id:
            raise GraphError("Same-page states must be different", 409)
        pair = [state, peer]
        pair.sort(key=lambda item: (int(item["frame_index"]), str(item["id"])))
        canonical = [pair[0]["id"], pair[1]["id"]]
        for link in self.graph["same_page_links"]:
            if link.get("states") == canonical:
                return link
        link = {
            "id": self._next_id("sp", self.graph["same_page_links"]),
            "states": canonical,
        }
        self._remember()
        self.graph["same_page_links"].append(link)
        self._save()
        return link

    def _shared(self, shared_id: str) -> dict[str, Any]:
        for shared in self.graph["shared_regions"]:
            if shared.get("id") == shared_id:
                return shared
        raise GraphError(f"Unknown shared region id: {shared_id}", 404)

    def create_shared_region(self, state_id: str, annotation_id: str) -> dict[str, Any]:
        _state, annotation = self._annotation(state_id, annotation_id)
        if annotation["kind"] != "region":
            raise GraphError("Only region boxes can become shared regions", 409)
        if annotation.get("shared_region_id"):
            return self._shared(annotation["shared_region_id"])
        shared = {
            "id": self._next_id("sr", self.graph["shared_regions"]),
            "canvas": annotation["canvas"],
            "bbox_norm": list(annotation["bbox_norm"]),
            "members": [{"state_id": state_id, "annotation_id": annotation_id}],
        }
        self._remember()
        annotation["shared_region_id"] = shared["id"]
        self.graph["shared_regions"].append(shared)
        self._save()
        return shared

    def reuse_shared_region(self, state_id: str, shared_id: str) -> dict[str, Any]:
        shared = self._shared(shared_id)
        for member in shared["members"]:
            if member.get("state_id") == state_id:
                _state, annotation = self._annotation(state_id, member["annotation_id"])
                return annotation
        canvas_kind = shared["canvas"]
        canvas = self.canvas(state_id, canvas_kind)
        pixels, _round_trip_norm = bbox_from_norm(
            shared["bbox_norm"], int(canvas["width"]), int(canvas["height"])
        )
        norm = list(shared["bbox_norm"])
        state = self._state(state_id)
        all_annotations = [item for s in self.graph["states"] for item in s["annotations"]]
        annotation = {
            "id": self._next_id("a", all_annotations),
            "kind": "region",
            "canvas": canvas_kind,
            "bbox_xyxy": pixels,
            "bbox_norm": norm,
            "shared_region_id": shared_id,
        }
        self._remember()
        state["annotations"].append(annotation)
        shared["members"].append({"state_id": state_id, "annotation_id": annotation["id"]})
        self._save()
        return annotation

    def _repair_shared_members(self) -> None:
        actual: dict[str, list[dict[str, str]]] = {}
        valid_annotations: dict[str, dict[str, Any]] = {}
        for state in self.graph["states"]:
            for annotation in state.get("annotations", []):
                valid_annotations[annotation.get("id", "")] = annotation
                shared_id = annotation.get("shared_region_id")
                if shared_id:
                    actual.setdefault(shared_id, []).append(
                        {"state_id": state["id"], "annotation_id": annotation["id"]}
                    )
        retained = []
        for shared in self.graph["shared_regions"]:
            members = actual.get(shared.get("id"), [])
            if members:
                shared["members"] = members
                retained.append(shared)
        self.graph["shared_regions"] = retained

    def set_fullpage(self, state_id: str, png: bytes, metadata: Mapping[str, Any]) -> dict[str, Any]:
        width, height = png_dimensions(png)
        state = self._state(state_id)
        path = self.fullpage_dir / f"{state_id}.png"
        relative = path.relative_to(self.session_dir).as_posix()
        new_canvas = {
            "source_image": relative,
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(png).hexdigest(),
            "generation": dict(metadata),
        }
        old_canvas = state.get("fullpage")
        old_bytes = path.read_bytes() if path.exists() else None
        before = copy.deepcopy(self.graph)
        history_length = len(self._history)
        try:
            _atomic_bytes(path, png)
            state["fullpage"] = new_canvas
            for annotation in state["annotations"]:
                if annotation.get("canvas") == "fullpage":
                    pixels, _round_trip_norm = bbox_from_norm(annotation["bbox_norm"], width, height)
                    annotation["bbox_xyxy"] = pixels
            self._history.append(before)
            self._save()
        except BaseException:
            self.graph = before
            del self._history[history_length:]
            if old_bytes is None:
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
            else:
                _atomic_bytes(path, old_bytes)
            raise
        return new_canvas

    def commit_auto_fullpage(
        self,
        state_id: str,
        frames: list[bytes],
        fullpage_png: bytes,
        sequence_metadata: Mapping[str, Any],
        generation_metadata: Mapping[str, Any],
    ) -> dict[str, Any]:
        """Commit one auto-scroll sequence/fullpage as a single undoable graph change."""

        if not frames:
            raise GraphError("Automatic scroll produced no frames", 422)
        state = self._state(state_id)
        viewport = state["viewport"]
        viewport_size = (int(viewport["width"]), int(viewport["height"]))
        for frame in frames:
            if png_dimensions(frame) != viewport_size:
                raise GraphError("Automatic scroll frame dimensions changed", 422)
        width, height = png_dimensions(fullpage_png)

        state_scroll_dir = self.scroll_root / state_id
        state_scroll_dir.mkdir(exist_ok=True)
        run_number = 1
        while (state_scroll_dir / f"auto_{run_number:06d}").exists():
            run_number += 1
        run_dir = state_scroll_dir / f"auto_{run_number:06d}"
        run_dir.mkdir()
        frame_paths: list[str] = []
        for index, frame in enumerate(frames, start=1):
            path = run_dir / f"{index:06d}.png"
            _atomic_bytes(path, frame)
            frame_paths.append(path.relative_to(self.session_dir).as_posix())

        fullpage_path = self.fullpage_dir / f"{state_id}_auto_{run_number:06d}.png"
        fullpage_relative = fullpage_path.relative_to(self.session_dir).as_posix()
        graph_before = copy.deepcopy(self.graph)
        history_before = copy.deepcopy(self._history)
        generation = dict(generation_metadata)
        generation["source_frames"] = frame_paths
        canvas = {
            "source_image": fullpage_relative,
            "width": width,
            "height": height,
            "sha256": hashlib.sha256(fullpage_png).hexdigest(),
            "generation": generation,
        }
        sequence = {
            "active": False,
            "frames": frame_paths,
            **dict(sequence_metadata),
        }
        self._remember()
        try:
            _atomic_bytes(fullpage_path, fullpage_png)
            state["fullpage"] = canvas
            for annotation in state["annotations"]:
                if annotation.get("canvas") == "fullpage":
                    pixels, _round_trip_norm = bbox_from_norm(annotation["bbox_norm"], width, height)
                    annotation["bbox_xyxy"] = pixels
            self.graph["scroll_sequences"][state_id] = sequence
            self._save()
        except BaseException:
            self.graph = graph_before
            self._history = history_before
            try:
                fullpage_path.unlink()
            except FileNotFoundError:
                pass
            raise
        return canvas

    def state_image(self, state_id: str, canvas_kind: str) -> bytes:
        canvas = self.canvas(state_id, canvas_kind)
        expected = "images" if canvas_kind == "viewport" else "annotations"
        path = self._safe_relative(canvas["source_image"], expected)
        try:
            return path.read_bytes()
        except OSError as exc:
            raise GraphError("Canvas image is unavailable", 404) from exc

    def sequence(self, state_id: str) -> dict[str, Any]:
        self._state(state_id)
        sequences = self.graph["scroll_sequences"]
        sequence = sequences.get(state_id)
        if not isinstance(sequence, dict):
            raise GraphError("No scroll sequence has been started for this state", 409)
        return sequence

    def start_sequence(self, state_id: str) -> dict[str, Any]:
        first = self.state_image(state_id, "viewport")
        directory = self.scroll_root / state_id
        directory.mkdir(exist_ok=True)
        first_path = directory / "000001.png"
        _atomic_bytes(first_path, first)
        sequence = {
            "active": True,
            "frames": [first_path.relative_to(self.session_dir).as_posix()],
            "started_utc": self.clock(),
        }
        self._remember()
        self.graph["scroll_sequences"][state_id] = sequence
        self._save()
        return sequence

    def append_sequence_frame(self, state_id: str, png: bytes) -> dict[str, Any]:
        png_dimensions(png)
        sequence = self.sequence(state_id)
        directory = self.scroll_root / state_id
        path = directory / f"{len(sequence['frames']) + 1:06d}.png"
        _atomic_bytes(path, png)
        self._remember()
        sequence["frames"].append(path.relative_to(self.session_dir).as_posix())
        self._save()
        return sequence

    def sequence_bytes(self, state_id: str) -> tuple[list[str], list[bytes]]:
        sequence = self.sequence(state_id)
        paths = list(sequence["frames"])
        return paths, [self._safe_relative(path, "annotations").read_bytes() for path in paths]


def canonical_stitch(frames: list[bytes]) -> tuple[bytes, dict[str, Any]]:
    from gui_rewalk.src.core.visual_traversal.grounding.stitch import encode_png, stitch_frames

    result = stitch_frames(frames)
    if result is None:
        raise GraphError("The canonical stitcher could not decode any scroll frames", 422)
    png = encode_png(result.image)
    metadata = {
        "sticky_top_h": int(result.sticky_top_h),
        "sticky_bottom_h": int(result.sticky_bot_h),
        "frame_top_in_composite": [int(value) for value in result.frame_top_in_composite],
    }
    return png, metadata


def auto_scroll_contract() -> dict[str, Any]:
    """Lazily load canonical scroll constants and pHash dependencies."""

    try:
        from gui_rewalk.src.core.visual_traversal.grounding.scroll import (
            SCROLL_PATIENCE,
            STITCH_MAX_SCROLL_STEPS,
            STITCH_SCROLL_FRAC,
            VIEW_STABLE_DISTANCE,
        )
        import imagehash
        from PIL import Image
    except Exception as exc:
        raise GraphError(f"Automatic long-page dependencies are unavailable: {exc}", 503) from exc

    def frame_phash(data: bytes) -> Any:
        try:
            return imagehash.phash(Image.open(io.BytesIO(data)).convert("RGB"))
        except Exception as exc:
            raise GraphError(f"Automatic scroll screenshot cannot be decoded for pHash: {exc}", 422) from exc

    return {
        "scroll_frac": float(STITCH_SCROLL_FRAC),
        "max_steps": int(STITCH_MAX_SCROLL_STEPS),
        "patience": int(SCROLL_PATIENCE),
        "stable_distance": int(VIEW_STABLE_DISTANCE),
        "phash": frame_phash,
    }


class AnnotatorService:
    def __init__(
        self,
        store: GraphStore,
        capture_frame: Callable[[], Any] | None = None,
        screenshot: Callable[[], bytes] | None = None,
        stitcher: Callable[[list[bytes]], tuple[bytes, dict[str, Any]]] = canonical_stitch,
        tap: Callable[[int, int], Any] | None = None,
        swipe: Callable[[int, int, int, int, int], Any] | None = None,
        back: Callable[[], Any] | None = None,
        action_settle_seconds: float = 0.5,
        sleeper: Callable[[float], None] = time.sleep,
        foreground: Callable[[], Any] | None = None,
        auto_contract_loader: Callable[[], dict[str, Any]] = auto_scroll_contract,
    ):
        self.store = store
        self.capture_frame = capture_frame
        self.screenshot = screenshot
        self.stitcher = stitcher
        self.tap = tap
        self.swipe = swipe
        self.back = back
        self.action_settle_seconds = action_settle_seconds
        self.sleeper = sleeper
        self.foreground = foreground
        self.auto_contract_loader = auto_contract_loader
        self._action_lock = threading.Lock()

    @property
    def live_enabled(self) -> bool:
        return self.capture_frame is not None and self.screenshot is not None

    @property
    def control_enabled(self) -> bool:
        return self.capture_frame is not None and self.tap is not None and self.swipe is not None

    @property
    def back_enabled(self) -> bool:
        return self.capture_frame is not None and self.back is not None

    @property
    def action_busy(self) -> bool:
        return self._action_lock.locked()

    def _capture_new_state(self) -> str:
        if self.capture_frame is None:
            raise GraphError("Server has no live capture callback", 409)
        before = {state["id"] for state in self.store.graph["states"]}
        try:
            self.capture_frame()
            ids = self.store.sync_capture_manifest(persist=False)
        except Exception as exc:
            raise GraphError(f"Follow-up screenshot failed: {exc}", 502) from exc
        created = [state_id for state_id in ids if state_id not in before]
        if not created:
            raise GraphError("Live capture did not append a new capture frame", 500)
        return created[-1]

    def live_capture(self) -> dict[str, Any]:
        if self.capture_frame is None:
            raise GraphError("Server was not started with --live-capture", 409)
        if self.store.graph.get("pending_device_action") is not None:
            raise GraphError("Generate or cancel the pending device action first", 409)
        target = self._capture_new_state()
        edge = None
        if self.store.graph.get("pending_click"):
            edge = self.store.complete_pending(target, persist=False)
        self.store._save()
        return {"state_id": target, "edge": edge}

    def live_refresh(self) -> dict[str, Any]:
        """Sync the current device view without completing pending actions or adding edges."""

        if not self.live_enabled:
            raise GraphError("Server was not started with --live-capture", 409)
        if self.store.graph.get("pending_device_action") is not None:
            raise GraphError("Generate or cancel the pending device action first", 409)
        self._acquire_mutation_lock()
        try:
            states = self.store.graph["states"]
            if states:
                latest = states[-1]
                try:
                    assert self.screenshot is not None
                    current = self.screenshot()
                except Exception as exc:
                    raise GraphError(f"Live screenshot failed: {exc}", 502) from exc
                width, height = png_dimensions(current)
                viewport = latest["viewport"]
                if width == int(viewport["width"]) and height == int(viewport["height"]):
                    contract = self.auto_contract_loader()
                    frame_phash = contract["phash"]
                    stable_distance = int(contract["stable_distance"])
                    latest_bytes = self.store.state_image(latest["id"], "viewport")
                    if (frame_phash(current) - frame_phash(latest_bytes)) <= stable_distance:
                        return {"state_id": latest["id"], "captured": False}
            target = self._capture_new_state()
            self.store._save()
            return {"state_id": target, "captured": True}
        finally:
            self._action_lock.release()

    def generate_state(self) -> dict[str, Any]:
        if self.capture_frame is None:
            raise GraphError("Server was not started with --live-capture", 409)
        self._acquire_mutation_lock()
        before = copy.deepcopy(self.store.graph)
        history_before = copy.deepcopy(self.store._history)
        self.store._remember()
        try:
            target = self._capture_new_state()
            pending = self.store.graph.get("pending_device_action")
            edge = None
            if pending is not None:
                kind = pending.get("kind")
                source = pending.get("source", "")
                if kind == "click":
                    edge = self.store.add_click_edge(
                        source, target, pending["point_pixel"], pending["point_norm"],
                        persist=False, remember=False,
                    )
                elif kind == "scroll":
                    edge = self.store.add_scroll_edge(
                        source, target, pending["direction"], pending["anchor_pixel"],
                        pending["anchor_norm"], pending["swipe_start_pixel"],
                        pending["swipe_end_pixel"], persist=False, remember=False,
                    )
                elif kind == "back":
                    edge = self.store.add_back_edge(
                        source, target, persist=False, remember=False
                    )
                else:
                    raise GraphError("Pending device action kind is invalid", 409)
                self.store.graph["pending_device_action"] = None
            self.store._save()
            return {"state_id": target, "edge": edge}
        except BaseException:
            self.store.graph = before
            self.store._history = history_before
            raise
        finally:
            self._action_lock.release()

    def cancel_device_action(self) -> dict[str, Any] | None:
        self._acquire_mutation_lock()
        try:
            return self.store.cancel_device_action()
        finally:
            self._action_lock.release()

    def _acquire_action(self) -> None:
        if not self.control_enabled:
            raise GraphError("Server was not started with --live-control", 409)
        self._acquire_mutation_lock()

    def _acquire_mutation_lock(self) -> None:
        if not self._action_lock.acquire(blocking=False):
            raise GraphError("Another VM action is still in progress", 409)

    def clear_graph(self) -> dict[str, int]:
        self._acquire_mutation_lock()
        try:
            return self.store.clear_graph()
        finally:
            self._action_lock.release()

    def control_tap(self, state_id: str, point: Any, canvas_kind: str = "viewport") -> dict[str, Any]:
        if canvas_kind != "viewport":
            raise GraphError("Real VM actions are forbidden on the fullpage canvas", 409)
        canvas = self.store.canvas(state_id, "viewport")
        pixels, norm = normalize_action_point(point, int(canvas["width"]), int(canvas["height"]))
        self._acquire_action()
        try:
            try:
                assert self.tap is not None
                self.tap(pixels[0], pixels[1])
            except Exception as exc:
                raise GraphError(f"ADB tap failed: {exc}", 502) from exc
            self.sleeper(self.action_settle_seconds)
            pending = self.store.stage_device_action({
                "kind": "click", "source": state_id,
                "point_pixel": pixels, "point_norm": norm,
            })
            return {"pending_device_action": pending}
        finally:
            self._action_lock.release()

    def control_back(self, state_id: str, canvas_kind: str = "viewport") -> dict[str, Any]:
        if canvas_kind != "viewport":
            raise GraphError("Real VM actions are forbidden on the fullpage canvas", 409)
        self.store.canvas(state_id, "viewport")
        if not self.back_enabled:
            raise GraphError("Server was not started with --live-control Back support", 409)
        self._acquire_mutation_lock()
        try:
            try:
                assert self.back is not None
                self.back()
            except Exception as exc:
                raise GraphError(f"ADB Back failed: {exc}", 502) from exc
            self.sleeper(self.action_settle_seconds)
            pending = self.store.stage_device_action({"kind": "back", "source": state_id})
            return {"pending_device_action": pending}
        finally:
            self._action_lock.release()

    def _scroll_gesture(
        self, state_id: str, anchor: Any, delta_y: Any
    ) -> tuple[str, list[int], list[int], list[int], list[int]]:
        canvas = self.store.canvas(state_id, "viewport")
        width, height = int(canvas["width"]), int(canvas["height"])
        anchor_pixel, anchor_norm = normalize_action_point(anchor, width, height)
        try:
            delta = float(delta_y)
        except (TypeError, ValueError) as exc:
            raise GraphError("delta_y must be a non-zero finite number") from exc
        if not math.isfinite(delta) or delta == 0:
            raise GraphError("delta_y must be a non-zero finite number")
        travel = max(40, round(height * 0.45))
        x, y = anchor_pixel
        if delta > 0:
            direction = "down"
            start = [x, min(height - 1, y + travel)]
            end = [x, max(0, y - travel)]
        else:
            direction = "up"
            start = [x, max(0, y - travel)]
            end = [x, min(height - 1, y + travel)]
        if start == end:
            raise GraphError("Scroll anchor cannot produce a valid swipe")
        return direction, anchor_pixel, anchor_norm, start, end

    def control_scroll(
        self, state_id: str, anchor: Any, delta_y: Any, canvas_kind: str = "viewport"
    ) -> dict[str, Any]:
        if canvas_kind != "viewport":
            raise GraphError("Real VM actions are forbidden on the fullpage canvas", 409)
        direction, anchor_pixel, anchor_norm, start, end = self._scroll_gesture(
            state_id, anchor, delta_y
        )
        self._acquire_action()
        try:
            try:
                assert self.swipe is not None
                self.swipe(start[0], start[1], end[0], end[1], 300)
            except Exception as exc:
                raise GraphError(f"ADB swipe failed: {exc}", 502) from exc
            self.sleeper(self.action_settle_seconds)
            pending = self.store.stage_device_action({
                "kind": "scroll", "source": state_id, "direction": direction,
                "anchor_pixel": anchor_pixel, "anchor_norm": anchor_norm,
                "swipe_start_pixel": start, "swipe_end_pixel": end,
            })
            return {"pending_device_action": pending}
        finally:
            self._action_lock.release()

    def upload_fullpage(self, state_id: str, png: bytes) -> dict[str, Any]:
        if len(png) > MAX_PNG_BODY:
            raise GraphError("PNG upload exceeds the size limit", 413)
        return self.store.set_fullpage(state_id, png, {"method": "upload"})

    def start_scroll(self, state_id: str) -> dict[str, Any]:
        if not self.live_enabled:
            raise GraphError("Scroll capture requires --live-capture", 409)
        if self.store.graph.get("pending_device_action") is not None:
            raise GraphError("Generate or cancel the pending device action first", 409)
        return self.store.start_sequence(state_id)

    def append_scroll(self, state_id: str) -> dict[str, Any]:
        if self.screenshot is None:
            raise GraphError("Scroll capture requires --live-capture", 409)
        if self.store.graph.get("pending_device_action") is not None:
            raise GraphError("Generate or cancel the pending device action first", 409)
        return self.store.append_sequence_frame(state_id, self.screenshot())

    def generate_fullpage(self, state_id: str) -> dict[str, Any]:
        source_paths, frames = self.store.sequence_bytes(state_id)
        try:
            png, metadata = self.stitcher(frames)
            width, height = png_dimensions(png)
        except GraphError:
            raise
        except Exception as exc:
            raise GraphError(f"Long-page stitching failed; source frames were retained: {exc}", 422) from exc
        generation = {
            "method": "canonical_stitch",
            "source_frames": source_paths,
            "width": width,
            "height": height,
            **metadata,
        }
        canvas = self.store.set_fullpage(state_id, png, generation)
        sequence = self.store.sequence(state_id)
        sequence["active"] = False
        self.store._save()
        return canvas

    def _foreground_package(self) -> str:
        if self.foreground is None:
            return ""
        try:
            value = self.foreground()
        except Exception as exc:
            raise GraphError(f"Foreground package probe failed: {exc}", 502) from exc
        if isinstance(value, Mapping):
            return str(value.get("package", "") or "")
        return str(value or "")

    def auto_scroll_fullpage(self, state_id: str) -> dict[str, Any]:
        if not self.control_enabled or self.screenshot is None or self.swipe is None:
            raise GraphError("Automatic scroll requires --live-control", 409)
        self._acquire_mutation_lock()
        try:
            return self._auto_scroll_fullpage_locked(state_id)
        finally:
            self._action_lock.release()

    def _auto_scroll_fullpage_locked(self, state_id: str) -> dict[str, Any]:
        if self.store.graph.get("pending_device_action") is not None:
            raise GraphError("Generate or cancel the pending device action first", 409)
        contract = self.auto_contract_loader()
        scroll_frac = float(contract["scroll_frac"])
        max_steps = int(contract["max_steps"])
        patience = int(contract["patience"])
        stable_distance = int(contract["stable_distance"])
        frame_phash = contract["phash"]
        canvas = self.store.canvas(state_id, "viewport")
        width, height = int(canvas["width"]), int(canvas["height"])

        try:
            first = self.screenshot()
            if png_dimensions(first) != (width, height):
                raise GraphError("Live screenshot dimensions do not match the state viewport", 409)
            source_hash = frame_phash(self.store.state_image(state_id, "viewport"))
            top_hash = frame_phash(first)
            source_match_distance = int(source_hash - top_hash)
            if source_match_distance > stable_distance:
                raise GraphError(
                    "Live VM does not match the selected viewport state; "
                    "return the VM to the selected short screenshot before automatic scrolling",
                    409,
                )
            initial_package = self._foreground_package()
        except GraphError:
            raise
        except Exception as exc:
            raise GraphError(f"Initial automatic-scroll screenshot failed: {exc}", 502) from exc

        frames = [first]
        previous_hash = top_hash
        steps = 0
        stale = 0
        termination = "hard_cap"
        bottom_reached = False
        top_restored = True
        restore_attempts = 0
        restore_error = ""
        primary_error: Exception | None = None
        safe = max(1, height // 12)
        high = max(safe, height - 1 - safe)
        cx, cy = width // 2, height // 2
        half_span = max(1, round(height * scroll_frac / 2))
        down_start = [max(0, min(width - 1, cx)), max(safe, min(high, cy + half_span))]
        down_end = [down_start[0], max(safe, min(high, cy - half_span))]

        try:
            while steps < max_steps and stale < patience:
                self.swipe(down_start[0], down_start[1], down_end[0], down_end[1], 750)
                steps += 1
                self.sleeper(self.action_settle_seconds)
                current = self.screenshot()
                if png_dimensions(current) != (width, height):
                    raise GraphError("Automatic-scroll screenshot dimensions changed", 422)
                current_package = self._foreground_package()
                if initial_package and current_package and current_package != initial_package:
                    termination = "off_app"
                    break
                current_hash = frame_phash(current)
                if (current_hash - previous_hash) <= stable_distance:
                    stale += 1
                else:
                    frames.append(current)
                    previous_hash = current_hash
                    stale = 0
            if stale >= patience:
                termination = "stable"
                bottom_reached = True
            elif steps >= max_steps:
                termination = "hard_cap"
        except Exception as exc:
            primary_error = exc

        if steps > 0:
            top_restored = False
            restore_start = [max(0, min(width - 1, cx)), safe]
            restore_end = [restore_start[0], high]
            try:
                for _attempt in range(steps + 3):
                    self.swipe(
                        restore_start[0], restore_start[1],
                        restore_end[0], restore_end[1], 400,
                    )
                    restore_attempts += 1
                    self.sleeper(self.action_settle_seconds)
                    restored = self.screenshot()
                    if png_dimensions(restored) != (width, height):
                        raise GraphError("Restore screenshot dimensions changed", 422)
                    if (frame_phash(restored) - top_hash) <= stable_distance:
                        top_restored = True
                        break
            except Exception as exc:
                restore_error = str(exc)

        if primary_error is not None:
            detail = f"; restore failed: {restore_error}" if restore_error else ""
            raise GraphError(
                f"Automatic scroll failed after {steps} down swipe(s): {primary_error}{detail}", 502
            ) from primary_error

        metadata = {
            "method": "auto_scroll",
            "steps": steps,
            "frame_count": len(frames),
            "termination": termination,
            "bottom_reached": bottom_reached,
            "top_restored": top_restored,
            "restore_attempts": restore_attempts,
            "max_steps": max_steps,
            "patience": patience,
            "stable_distance": stable_distance,
            "scroll_frac": scroll_frac,
            "source_match_distance": source_match_distance,
        }
        if restore_error:
            metadata["restore_error"] = restore_error
        try:
            fullpage_png, stitch_metadata = self.stitcher(frames)
            generation = {**metadata, **stitch_metadata}
            fullpage = self.store.commit_auto_fullpage(
                state_id, frames, fullpage_png, metadata, generation
            )
        except GraphError:
            raise
        except Exception as exc:
            raise GraphError(f"Automatic long-page stitching failed: {exc}", 422) from exc
        return {
            "state_id": state_id,
            "frame_count": len(frames),
            "steps": steps,
            "termination": termination,
            "top_restored": top_restored,
            "source_match_distance": source_match_distance,
            "fullpage": fullpage,
        }


def _loopback_host(host: str) -> str:
    if host == "localhost":
        return "127.0.0.1"
    try:
        address = ipaddress.ip_address(host)
    except ValueError as exc:
        raise GraphError("--host must be a loopback IP address or localhost") from exc
    if not address.is_loopback:
        raise GraphError("Refusing to bind the annotation server outside loopback")
    if address.version != 4:
        raise GraphError("This server supports IPv4 loopback addresses only")
    return str(address)


def make_handler(service: AnnotatorService, ui_path: Path | None = None):
    ui_file = ui_path or TOOLS_DIR / "mobile_graph_annotator.html"

    class Handler(BaseHTTPRequestHandler):
        server_version = "MobileGraphAnnotator/1"

        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def _json(self, status: int, value: Any) -> None:
            body = json.dumps(value, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def _error(self, error: Exception) -> None:
            if isinstance(error, GraphError):
                self._json(error.status, {"error": str(error)})
            else:
                self._json(500, {"error": f"Internal server error: {error}"})

        def _json_body(self) -> dict[str, Any]:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise GraphError("Invalid Content-Length") from exc
            if length <= 0:
                return {}
            if length > MAX_JSON_BODY:
                self.close_connection = True
                raise GraphError("JSON request exceeds the size limit", 413)
            try:
                value = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise GraphError("Request body is not valid JSON") from exc
            if not isinstance(value, dict):
                raise GraphError("JSON request body must be an object")
            return value

        def _png_body(self) -> bytes:
            try:
                length = int(self.headers.get("Content-Length", "0"))
            except ValueError as exc:
                raise GraphError("Invalid Content-Length") from exc
            if length <= 0:
                raise GraphError("PNG request body is empty")
            if length > MAX_PNG_BODY:
                self.close_connection = True
                raise GraphError("PNG request exceeds the size limit", 413)
            return self.rfile.read(length)

        def do_GET(self) -> None:
            try:
                path = urlsplit(self.path).path
                if path == "/":
                    body = ui_file.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(body)))
                    self.end_headers()
                    self.wfile.write(body)
                    return
                if path == "/api/graph":
                    self._json(200, {
                        "graph": service.store.graph,
                        "live_enabled": service.live_enabled,
                        "control_enabled": service.control_enabled,
                        "back_enabled": service.back_enabled,
                    })
                    return
                parts = path.strip("/").split("/")
                if len(parts) == 4 and parts[:2] == ["api", "image"]:
                    body = service.store.state_image(parts[2], parts[3])
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return
                raise GraphError("Route not found", 404)
            except Exception as exc:
                self._error(exc)

        def do_POST(self) -> None:
            try:
                if service.action_busy:
                    self.close_connection = True
                    raise GraphError("Another VM action is still in progress", 409)
                split = urlsplit(self.path)
                path = split.path
                if path == "/api/fullpage/upload":
                    state_id = parse_qs(split.query).get("state", [""])[0]
                    result = service.upload_fullpage(state_id, self._png_body())
                else:
                    body = self._json_body()
                    if path == "/api/annotations":
                        result = service.store.add_annotation(
                            body.get("state_id", ""), body.get("kind", ""),
                            body.get("canvas", ""), body.get("bbox_xyxy"),
                        )
                    elif path == "/api/annotations/delete":
                        result = service.store.delete_annotation(body.get("state_id", ""), body.get("annotation_id", ""))
                    elif path == "/api/pending":
                        result = service.store.set_pending_click(body.get("state_id", ""), body.get("point_pixel"))
                    elif path == "/api/target-existing":
                        result = service.store.complete_pending(body.get("state_id", ""))
                    elif path == "/api/live-capture":
                        result = service.live_capture()
                    elif path == "/api/live-refresh":
                        result = service.live_refresh()
                    elif path == "/api/state/generate":
                        result = service.generate_state()
                    elif path == "/api/device-action/cancel":
                        result = service.cancel_device_action()
                    elif path == "/api/control/tap":
                        result = service.control_tap(
                            body.get("state_id", ""), body.get("point_pixel"), body.get("canvas", "viewport")
                        )
                    elif path == "/api/control/scroll":
                        result = service.control_scroll(
                            body.get("state_id", ""), body.get("anchor_pixel"),
                            body.get("delta_y"), body.get("canvas", "viewport"),
                        )
                    elif path == "/api/control/back":
                        result = service.control_back(
                            body.get("state_id", ""), body.get("canvas", "viewport")
                        )
                    elif path == "/api/same-page/link":
                        result = service.store.link_same_page(
                            body.get("state_id", ""), body.get("peer_state_id", "")
                        )
                    elif path == "/api/shared/create":
                        result = service.store.create_shared_region(body.get("state_id", ""), body.get("annotation_id", ""))
                    elif path == "/api/shared/reuse":
                        result = service.store.reuse_shared_region(body.get("state_id", ""), body.get("shared_region_id", ""))
                    elif path == "/api/scroll/start":
                        result = service.start_scroll(body.get("state_id", ""))
                    elif path == "/api/scroll/append":
                        result = service.append_scroll(body.get("state_id", ""))
                    elif path == "/api/scroll/stitch":
                        result = service.generate_fullpage(body.get("state_id", ""))
                    elif path == "/api/scroll/auto":
                        result = service.auto_scroll_fullpage(body.get("state_id", ""))
                    elif path == "/api/undo":
                        result = {"undone": service.store.undo()}
                    elif path == "/api/clear":
                        result = service.clear_graph()
                    else:
                        raise GraphError("Route not found", 404)
                self._json(200, {"result": result, "graph": service.store.graph})
            except Exception as exc:
                self._error(exc)

    return Handler


def make_server(service: AnnotatorService, host: str, port: int, ui_path: Path | None = None) -> ThreadingHTTPServer:
    safe_host = _loopback_host(host)
    if not 0 <= port <= 65535:
        raise GraphError("--port must be between 0 and 65535")
    return ThreadingHTTPServer((safe_host, port), make_handler(service, ui_path))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a local box-only mobile grounding state graph annotation UI.")
    parser.add_argument("session_dir", type=Path, help="capture session directory containing manifest.json")
    parser.add_argument("--live-capture", action="store_true", help="enable read-only ADB screenshot capture")
    parser.add_argument(
        "--live-control", action="store_true",
        help="enable explicit ADB tap/swipe control (also enables live capture; requires --serial)",
    )
    parser.add_argument(
        "--action-settle-seconds", type=float, default=0.5,
        help="wait after a real VM action before capture, from 0 to 10 seconds (default: 0.5)",
    )
    parser.add_argument("--adb", default="adb", help="ADB executable")
    parser.add_argument("--serial", help="ADB serial used for live capture")
    parser.add_argument("--host", default="127.0.0.1", help="loopback bind address (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-open", action="store_true", help="do not open the local UI in a browser")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if not math.isfinite(args.action_settle_seconds) or not 0 <= args.action_settle_seconds <= 10:
            raise GraphError("--action-settle-seconds must be a finite value from 0 to 10")
        if args.live_control and not args.serial:
            raise GraphError("--live-control requires an explicit --serial")
        store = GraphStore(args.session_dir)
        capture_frame = None
        screenshot = None
        adb = None
        if args.live_capture or args.live_control:
            adb = AdbClient(args.adb)
            adb.discover(args.serial)
            capture_store = SessionStore(
                store.session_dir.parent,
                store.session_dir.name,
                adb.device_metadata(),
                adb_executable=args.adb,
            )
            capture_app = CaptureApp(adb, capture_store, settle_seconds=0 if args.live_control else 0.3)
            capture_frame = lambda: capture_app.capture("")
            screenshot = adb.capture_png
        service = AnnotatorService(
            store,
            capture_frame=capture_frame,
            screenshot=screenshot,
            tap=adb.tap if args.live_control and adb is not None else None,
            swipe=adb.swipe if args.live_control and adb is not None else None,
            back=adb.back if args.live_control and adb is not None else None,
            action_settle_seconds=args.action_settle_seconds,
            foreground=adb.foreground if args.live_control and adb is not None else None,
        )
        server = make_server(service, args.host, args.port)
        url = f"http://{server.server_address[0]}:{server.server_address[1]}/"
        print(f"Mobile graph annotator: {url}")
        print(f"Graph: {store.graph_path}")
        if not args.no_open:
            threading.Timer(0.2, lambda: webbrowser.open(url)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping safely.")
        finally:
            server.server_close()
        return 0
    except (GraphError, CaptureError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
