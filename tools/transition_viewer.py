#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import ttk, messagebox

from PIL import Image, ImageDraw, ImageFont, ImageTk

_TOK = re.compile(r"[0-9a-z一-鿿]+")


def _norm(s: Optional[str]) -> str:
    return " ".join(_TOK.findall((s or "").lower()))


# ── region role → outline colour (region boxes) ──────────────────────────────
REGION_COLORS: Dict[str, Tuple[int, int, int]] = {
    "nav_sidebar": (70, 130, 255),      # blue   — main navigation sidebar
    "content": (40, 180, 80),           # green  — page content pane
    "titlebar": (150, 150, 150),        # grey   — window title bar
    "tab_bar": (180, 80, 220),          # purple — tab strip
    "form_body": (240, 150, 40),        # orange — form / dialog body
    "dialog_titlebar": (220, 60, 60),   # red    — modal title bar
    "action_bar": (200, 120, 40),       # amber  — bottom action bar
    "toolbar": (200, 180, 40),          # yellow — toolbar
    "menubar": (0, 190, 190),           # teal   — menu bar
    "statusbar": (120, 120, 120),       # grey   — status bar
}


@dataclass
class Transition:
    src: str
    dst: str
    element_id: str
    element_label: str
    action: Any
    action_index: int


@dataclass
class GroundingEvidence:
    label: str
    bbox: Tuple[int, int, int, int]
    click_point: Optional[Tuple[int, int]]
    state_id: str
    sequence: int


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _elem_bbox(e: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
    """Screen-space (x1, y1, x2, y2) of an element, tolerant of both formats:
    visual traversal ``bbox_xywh`` [x, y, w, h], or the a11y ``screen_x/width``."""
    b = e.get("bbox_xywh") or e.get("bbox")
    if isinstance(b, (list, tuple)) and len(b) >= 4:
        try:
            x, y, w, h = (int(round(float(v))) for v in b[:4])
        except (TypeError, ValueError):
            x = y = w = h = 0
        if w > 0 and h > 0:
            return (x, y, x + w, y + h)
    x, y = int(e.get("screen_x", 0) or 0), int(e.get("screen_y", 0) or 0)
    w, h = int(e.get("width", 0) or 0), int(e.get("height", 0) or 0)
    if w > 0 and h > 0:
        return (x, y, x + w, y + h)
    return None


def _xywh_bbox(value: Any) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x, y, w, h = (int(round(float(v))) for v in value[:4])
    except (TypeError, ValueError):
        return None
    if w <= 0 or h <= 0:
        return None
    return x, y, x + w, y + h


def _xyxy_bbox(value: Any) -> Optional[Tuple[int, int, int, int]]:
    if not isinstance(value, (list, tuple)) or len(value) < 4:
        return None
    try:
        x1, y1, x2, y2 = (int(round(float(v))) for v in value[:4])
    except (TypeError, ValueError):
        return None
    if x2 <= x1 or y2 <= y1:
        return None
    return x1, y1, x2, y2


def _pixel_digest(path: Path) -> str:
    with Image.open(path) as image:
        rgb = image.convert("RGB")
        return hashlib.sha256(rgb.tobytes()).hexdigest()


def _load_node_index(path: Path) -> Dict[str, Any]:
    """Return a {state_id: meta} dict. Visual traversal writes a LIST of
    {state_id, state_type, elements_count}; the a11y pipeline writes a dict."""
    raw = _load_json(path)
    if isinstance(raw, dict):
        return raw
    out: Dict[str, Any] = {}
    for item in raw if isinstance(raw, list) else []:
        sid = str(item.get("state_id", "") or item.get("id", ""))
        if sid:
            out[sid] = item
    return out


def _load_transitions(path: Path) -> List[Transition]:
    rows: List[Transition] = []
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            rows.append(
                Transition(
                    src=str(obj.get("src", "")),
                    dst=str(obj.get("dst", "")),
                    element_id=str(obj.get("element_id", "")),
                    element_label=str(obj.get("element_label", "")),
                    action=obj.get("action", {}),
                    action_index=int(obj.get("action_index", 0)),
                )
            )
    return rows


def _load_transitions_from_graph(path: Path) -> List[Transition]:
    """Build transitions from the canonical visual-traversal action ledger.

    ``edges`` is a compact NetworkX view and may collapse multiple controls that
    connect the same source/target pair.  ``action_edges`` preserves those
    parallel controls, so the viewer must prefer it whenever it is available.
    """
    g = _load_json(path)
    action_edges = g.get("action_edges")
    if isinstance(action_edges, list):
        edges = [
            edge for edge in action_edges
            if edge.get("routing_verified") is True
            and edge.get("source")
            and edge.get("target")
        ]
    else:
        edges = g.get("edges", g.get("links", []))
    rows: List[Transition] = []
    for i, e in enumerate(edges):
        attempts = e.get("attempts", []) if isinstance(e, dict) else []
        verified_attempt = next(
            (
                attempt for attempt in reversed(attempts)
                if attempt.get("committed") is True
                and attempt.get("landing_verified") is True
            ),
            attempts[-1] if attempts else {},
        )
        action = e.get("action") or verified_attempt.get("action", {})
        selector = action.get("selector", {}) if isinstance(action, dict) else {}
        rows.append(
            Transition(
                src=str(e.get("source", e.get("src", ""))),
                dst=str(e.get("target", e.get("dst", ""))),
                element_id=str(e.get("element_id", verified_attempt.get("element_id", ""))),
                element_label=str(
                    e.get("element_label")
                    or verified_attempt.get("element_label")
                    or selector.get("element_label", "")
                ),
                action=action,
                action_index=int(
                    verified_attempt.get(
                        "action_index", e.get("action_index", e.get("timestamp", i))
                    ) or i
                ),
            )
        )
    return rows


def _contains_type_action(action: Any) -> bool:
    if isinstance(action, dict):
        return str(action.get("action_type", "")).upper() == "TYPE"
    if isinstance(action, list):
        for item in action:
            if isinstance(item, dict) and str(item.get("action_type", "")).upper() == "TYPE":
                return True
    return False


def _find_click_point(action: Any) -> Optional[Tuple[int, int]]:
    def _extract(a: Dict[str, Any]) -> Optional[Tuple[int, int]]:
        params = a.get("parameters", {}) if isinstance(a, dict) else {}
        if not isinstance(params, dict):
            return None
        x = params.get("x")
        y = params.get("y")
        if isinstance(x, (int, float)) and isinstance(y, (int, float)):
            return int(x), int(y)
        return None

    if isinstance(action, dict):
        if str(action.get("action_type", "")).upper() == "CLICK":
            return _extract(action)
        return None

    if isinstance(action, list):
        for item in action:
            if not isinstance(item, dict):
                continue
            if str(item.get("action_type", "")).upper() == "CLICK":
                point = _extract(item)
                if point:
                    return point
    return None


def _resolve_screenshot_path(nodes_dir: Path, state_id: str) -> Optional[Path]:
    state_dir = nodes_dir / state_id
    local_img = state_dir / "screenshot.png"
    if local_img.exists():
        return local_img

    meta_path = state_dir / "state_meta.json"
    if meta_path.exists():
        try:
            meta = _load_json(meta_path)
            raw = str(meta.get("screenshot_path", "")).replace("\\", "/")
            if raw:
                p = Path(raw)
                if p.exists():
                    return p
                joined = nodes_dir.parent / p.name
                if joined.exists():
                    return joined
        except Exception:
            return None
    return None


class TransitionViewerApp:
    def __init__(self, root: tk.Tk, nodes_dir: Path, transitions_path: Optional[Path],
                 start_state: Optional[str]):
        self.root = root
        self.root.title("GUI-ReWalk Transition Viewer")
        self.nodes_dir = nodes_dir
        self.transitions_path = transitions_path

        self.node_index_path = nodes_dir / "node_index.json"
        if not self.node_index_path.exists():
            raise FileNotFoundError(f"Missing node index: {self.node_index_path}")

        self.node_index: Dict[str, Any] = _load_node_index(self.node_index_path)
        self.elements_cache: Dict[str, List[Dict[str, Any]]] = {}
        self.current_rows: List[Dict[str, Any]] = []
        self.grounding_by_label = self._load_grounding_evidence()

        # Transitions: prefer an explicit transitions.ndjson; else fall back to the
        # networkx graph.json that visual traversal writes (no ndjson there).
        if transitions_path and transitions_path.exists():
            self.transitions = sorted(_load_transitions(transitions_path),
                                      key=lambda x: x.action_index)
        else:
            gp = self._find_graph_path()
            self.transitions = (sorted(_load_transitions_from_graph(gp),
                                       key=lambda x: x.action_index)
                                if gp else [])

        self.outgoing: Dict[str, List[Transition]] = {}
        for t in self.transitions:
            self.outgoing.setdefault(t.src, []).append(t)

        ordered_ids = list(self.node_index.keys())
        self.current_state = (start_state if start_state in self.node_index
                              else (ordered_ids[0] if ordered_ids else ""))
        self.history: List[str] = []

        # overlay toggles
        self.show_regions = tk.BooleanVar(value=True)
        self.show_buttons = tk.BooleanVar(value=True)
        self.show_trans = tk.BooleanVar(value=True)

        self._font = self._load_font(15)
        self._image_ref = None
        self._build_ui()
        self._refresh()

    @staticmethod
    def _load_font(size: int) -> ImageFont.FreeTypeFont:
        for p in ("C:/Windows/Fonts/msyh.ttc", "C:/Windows/Fonts/arial.ttf"):
            try:
                return ImageFont.truetype(p, size)
            except Exception:
                continue
        return ImageFont.load_default()

    def _find_graph_path(self) -> Optional[Path]:
        for cand in (self.nodes_dir / "graph.json", self.nodes_dir.parent / "graph.json"):
            if cand.exists():
                return cand
        return None

    def _build_ui(self) -> None:
        self.root.geometry("1500x900")

        main = ttk.Frame(self.root)
        main.pack(fill=tk.BOTH, expand=True)

        left = ttk.Frame(main)
        left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        right = ttk.Frame(main, width=480)
        right.pack(side=tk.RIGHT, fill=tk.Y)

        top_bar = ttk.Frame(left)
        top_bar.pack(fill=tk.X, padx=10, pady=8)

        self.state_var = tk.StringVar()
        self.meta_var = tk.StringVar()

        ttk.Label(top_bar, textvariable=self.state_var, font=("Segoe UI", 12, "bold")).pack(anchor=tk.W)
        ttk.Label(top_bar, textvariable=self.meta_var).pack(anchor=tk.W, pady=(4, 0))

        # overlay toggles
        toggles = ttk.Frame(left)
        toggles.pack(fill=tk.X, padx=10)
        ttk.Checkbutton(toggles, text="区块框", variable=self.show_regions,
                        command=self._refresh).pack(side=tk.LEFT)
        ttk.Checkbutton(toggles, text="可交互按钮框", variable=self.show_buttons,
                        command=self._refresh).pack(side=tk.LEFT, padx=(10, 0))
        ttk.Checkbutton(toggles, text="点击/输入标注", variable=self.show_trans,
                        command=self._refresh).pack(side=tk.LEFT, padx=(10, 0))

        self.image_label = ttk.Label(left)
        self.image_label.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

        right_top = ttk.Frame(right)
        right_top.pack(fill=tk.X, padx=10, pady=10)

        ttk.Button(right_top, text="跳转到所选操作", command=self._jump_selected).pack(side=tk.LEFT)
        ttk.Button(right_top, text="回退", command=self._go_back).pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(right_top, text="刷新", command=self._refresh).pack(side=tk.LEFT, padx=(8, 0))

        self.listbox = tk.Listbox(right, font=("Consolas", 10), width=72)
        self.listbox.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 10))
        self.listbox.bind("<Double-Button-1>", lambda _e: self._jump_selected())
        self.listbox.bind("<Return>", lambda _e: self._jump_selected())

        tip = (
            "区块框(粗): 按 region 上色, 左上标 role\n"
            "按钮框(细): 绿=本页已验证 / 蓝=策略覆盖 / 橙=待补点 / 浅灰=禁用、选中或非导航\n"
            "点击=红点  输入=蓝框\n"
            "右侧列表: 双击[已验证]跳转; [策略覆盖]无需重复点; [待补点]才是真缺口"
        )
        ttk.Label(right, text=tip, justify=tk.LEFT, foreground="#444").pack(fill=tk.X, padx=10, pady=(0, 10))

    def _load_elements(self, state_id: str) -> List[Dict[str, Any]]:
        if state_id in self.elements_cache:
            return self.elements_cache[state_id]

        path = self.nodes_dir / state_id / "elements.json"
        if path.exists():
            try:
                data = _load_json(path)
                if isinstance(data, list):
                    self.elements_cache[state_id] = data
                    return data
            except Exception:
                pass

        self.elements_cache[state_id] = []
        return []

    def _load_grounding_evidence(self) -> Dict[str, List[GroundingEvidence]]:
        state_by_digest: Dict[str, List[str]] = defaultdict(list)
        for state_id in self.node_index:
            screenshot = _resolve_screenshot_path(self.nodes_dir, state_id)
            if not screenshot:
                continue
            try:
                state_by_digest[_pixel_digest(screenshot)].append(state_id)
            except Exception:
                continue

        result: Dict[str, List[GroundingEvidence]] = defaultdict(list)
        attempts_dir = self.nodes_dir.parent / "target_grounding_attempts"
        if not attempts_dir.exists():
            return {}
        for result_path in sorted(attempts_dir.glob("*/result.json")):
            try:
                raw = _load_json(result_path)
            except Exception:
                continue
            if raw.get("outcome") != "accepted":
                continue
            label = str(raw.get("target", {}).get("name", "")).strip()
            bbox = _xywh_bbox(raw.get("grounded_geometry", {}).get("bbox_px_xywh"))
            if not label or not bbox:
                continue
            point_raw = raw.get("grounded_geometry", {}).get("click_point_px")
            point = None
            if isinstance(point_raw, (list, tuple)) and len(point_raw) >= 2:
                try:
                    point = int(round(float(point_raw[0]))), int(round(float(point_raw[1])))
                except (TypeError, ValueError):
                    point = None

            state_id = ""
            input_path = result_path.parent / "input.png"
            if input_path.exists():
                try:
                    matches = state_by_digest.get(_pixel_digest(input_path), [])
                    if len(matches) == 1:
                        state_id = matches[0]
                except Exception:
                    pass
            result[_norm(label)].append(
                GroundingEvidence(
                    label=label,
                    bbox=bbox,
                    click_point=point,
                    state_id=state_id,
                    sequence=int(raw.get("sequence", 0) or 0),
                )
            )
        return dict(result)

    def _grounding_for(
        self,
        state_id: str,
        label: str,
        center: Any = None,
    ) -> Optional[GroundingEvidence]:
        candidates = list(getattr(self, "grounding_by_label", {}).get(_norm(label), []))
        exact = [item for item in candidates if item.state_id == state_id]
        if exact:
            return min(exact, key=lambda item: item.sequence)
        if not isinstance(center, (list, tuple)) or len(center) < 2:
            return None
        try:
            cx, cy = float(center[0]), float(center[1])
        except (TypeError, ValueError):
            return None
        located = [item for item in candidates if item.click_point is not None]
        if not located:
            return None
        best = min(
            located,
            key=lambda item: (item.click_point[0] - cx) ** 2 + (item.click_point[1] - cy) ** 2,
        )
        return best

    def _element_bbox(self, state_id: str, element: Dict[str, Any]) -> Optional[Tuple[int, int, int, int]]:
        bbox = _elem_bbox(element)
        if bbox:
            return bbox
        grounding = self._grounding_for(state_id, str(element.get("name", "")), element.get("center"))
        return grounding.bbox if grounding else None

    def _region_boxes(
        self,
        state_id: str,
        elements: List[Dict[str, Any]],
    ) -> Dict[str, Tuple[int, int, int, int]]:
        """One bounding box per region role from persisted Region geometry."""
        boxes: Dict[str, Tuple[int, int, int, int]] = {}
        for e in elements:
            role = (e.get("region") or "").strip()
            if not role:
                continue
            bb = _xyxy_bbox(e.get("region_bbox")) or self._element_bbox(state_id, e)
            if not bb:
                continue
            if role in boxes:
                x1, y1, x2, y2 = boxes[role]
                boxes[role] = (min(x1, bb[0]), min(y1, bb[1]), max(x2, bb[2]), max(y2, bb[3]))
            else:
                boxes[role] = bb
        return boxes

    def _button_boxes(
        self,
        state_id: str,
        elements: List[Dict[str, Any]],
    ) -> List[Tuple[Tuple[int, int, int, int], str]]:
        """Box + name for every INTERACTIVE element (non-interactive text is not boxed)."""
        out = []
        for e in elements:
            if not e.get("interactive"):
                continue
            bb = self._element_bbox(state_id, e)
            if bb:
                out.append((bb, (e.get("name") or "").strip()))
        return out

    def _element_rows(self, state_id: str) -> List[Dict[str, Any]]:
        """Classify interactive elements using source-local traversal evidence.

        A same-named control on another State is recognition evidence only; it
        never creates a jump from this State.  ``visited`` without a local edge
        represents policy coverage such as ``group_once``. Disabled, selected,
        display-only, shallow, and dangerous controls are legitimate skips.
        """
        elements = self._load_elements(state_id)
        direct: Dict[str, List[Transition]] = defaultdict(list)
        for transition in self.outgoing.get(state_id, []):
            direct[_norm(transition.element_label)].append(transition)
        seen = set()
        rows: List[Dict[str, Any]] = []
        for e in elements:
            if not e.get("interactive"):
                continue
            name = (e.get("name") or "").strip()
            k = _norm(name)
            if not k or k in seen:
                continue
            seen.add(k)
            bb = self._element_bbox(state_id, e)
            cat = (e.get("category") or "").strip().lower()
            if k in direct:
                actions = direct[k]
                kind, dst = "direct", actions[-1].dst
                reason = f"{len(actions)} source-local verified action(s)"
                edge_count = len(actions)
            elif e.get("enabled") is False or e.get("abnormal_reason") or e.get("blocked_reason"):
                kind, dst, reason = "skip", None, str(
                    e.get("blocked_reason") or e.get("abnormal_reason") or "disabled"
                )
                edge_count = 0
            elif e.get("selected") is True:
                kind, dst, reason = "skip", None, "current selection"
                edge_count = 0
            elif e.get("visited") is True:
                kind, dst, reason = "covered", None, "covered by traversal policy"
                edge_count = 0
            elif cat != "navigation":
                kind, dst, reason = "skip", None, cat or "non-navigation"
                edge_count = 0
            else:
                kind, dst, reason = "unexplored", None, "eligible navigation without coverage"
                edge_count = 0
            rows.append({
                "name": name,
                "dst": dst,
                "kind": kind,
                "bbox": bb,
                "cat": cat,
                "reason": reason,
                "edge_count": edge_count,
            })

        for key, actions in direct.items():
            if not key or key in seen:
                continue
            label = actions[-1].element_label
            grounding = self._grounding_for(state_id, label)
            rows.append({
                "name": label,
                "dst": actions[-1].dst,
                "kind": "direct",
                "bbox": grounding.bbox if grounding else None,
                "cat": "",
                "reason": f"{len(actions)} verified action(s) without a durable element",
                "edge_count": len(actions),
            })
        return rows

    def _build_annotations(self, state_id: str, transitions: List[Transition]) -> List[Dict[str, Any]]:
        elements = self._load_elements(state_id)
        elem_by_id = {str(e.get("id", "")): e for e in elements}

        annotations: List[Dict[str, Any]] = []
        for idx, t in enumerate(transitions, start=1):
            if _contains_type_action(t.action):
                elem = elem_by_id.get(t.element_id, {})
                bb = self._element_bbox(state_id, elem)
                if bb:
                    annotations.append({"kind": "type", "idx": idx, "bbox": bb, "label": t.element_label})
                    continue

            elem = elem_by_id.get(t.element_id, {})
            grounding = self._grounding_for(
                state_id,
                t.element_label,
                elem.get("center") if elem else None,
            )
            point = _find_click_point(t.action) or (grounding.click_point if grounding else None)
            if point:
                annotations.append({
                    "kind": "click",
                    "idx": idx,
                    "point": point,
                    "bbox": grounding.bbox if grounding else None,
                    "label": t.element_label,
                })

        return annotations

    def _render_state_image(self, state_id: str, transitions: List[Transition]) -> Optional[Image.Image]:
        img_path = _resolve_screenshot_path(self.nodes_dir, state_id)
        if not img_path or not img_path.exists():
            return None

        img = Image.open(img_path).convert("RGB")
        draw = ImageDraw.Draw(img)
        elements = self._load_elements(state_id)

        # 1) region boxes (bottom layer): union box per role, coloured, role label
        if self.show_regions.get():
            for role, (x1, y1, x2, y2) in self._region_boxes(state_id, elements).items():
                col = REGION_COLORS.get(role, (120, 120, 120))
                draw.rectangle((x1, y1, x2, y2), outline=col, width=4)
                tag = role
                tw = draw.textlength(tag, font=self._font) if hasattr(draw, "textlength") else 8 * len(tag)
                draw.rectangle((x1, y1, x1 + tw + 6, y1 + 20), fill=col)
                draw.text((x1 + 3, y1 + 2), tag, fill=(255, 255, 255), font=self._font)

        # 2) interactive buttons, coloured by source-local traversal status:
        #    green = verified action edge, blue = policy-covered without a local
        #    edge, orange = eligible navigation gap, grey = legitimate skip. Name drawn
        #    INSIDE the box on a filled bar so labels never stack/overlap.
        KIND_COL = {"direct": (0, 190, 90), "covered": (70, 130, 255),
                    "unexplored": (245, 150, 30), "skip": (180, 180, 180)}
        if self.show_buttons.get():
            for row in self._element_rows(state_id):
                bb = row["bbox"]
                if not bb:
                    continue
                x1, y1, x2, y2 = bb
                col = KIND_COL.get(row["kind"], (0, 190, 90))
                draw.rectangle((x1, y1, x2, y2), outline=col, width=2)
                name = row["name"]
                if name and (y2 - y1) >= 14 and (x2 - x1) >= 24:
                    tag = name[:26]
                    tw = int(draw.textlength(tag, font=self._font)) if hasattr(draw, "textlength") else 8 * len(tag)
                    bar_w = min(tw + 6, x2 - x1)
                    draw.rectangle((x1, y1, x1 + bar_w, min(y1 + 18, y2)), fill=col)
                    draw.text((x1 + 3, y1 + 1), tag, fill=(255, 255, 255), font=self._font)

        # 3) click/type transition annotations (top layer)
        if self.show_trans.get():
            for ann in self._build_annotations(state_id, transitions):
                idx = ann["idx"]
                if ann["kind"] == "click":
                    x, y = ann["point"]
                    if ann.get("bbox"):
                        draw.rectangle(ann["bbox"], outline=(255, 40, 40), width=3)
                    r = 8
                    draw.ellipse((x - r, y - r, x + r, y + r), outline=(255, 40, 40), width=3)
                    draw.text((x + 11, y - 13), str(idx), fill=(255, 40, 40), font=self._font)
                else:
                    x1, y1, x2, y2 = ann["bbox"]
                    draw.rectangle((x1, y1, x2, y2), outline=(70, 130, 255), width=3)
                    draw.text((x1 + 3, max(0, y1 - 14)), f"{idx}", fill=(70, 130, 255), font=self._font)

        return img

    def _fit_for_panel(self, img: Image.Image) -> Image.Image:
        panel_w = max(self.image_label.winfo_width(), 900)
        panel_h = max(self.image_label.winfo_height(), 700)

        work_w = panel_w - 20
        work_h = panel_h - 20

        ratio = min(work_w / img.width, work_h / img.height)
        ratio = max(ratio, 0.1)

        new_w = int(img.width * ratio)
        new_h = int(img.height * ratio)
        return img.resize((new_w, new_h), Image.Resampling.LANCZOS)

    def _refresh(self) -> None:
        if not self.current_state:
            messagebox.showerror("错误", "没有可用节点")
            return

        outgoing = self.outgoing.get(self.current_state, [])
        outgoing = sorted(outgoing, key=lambda x: x.action_index)

        meta = self.node_index.get(self.current_state, {})
        alias = meta.get("node_alias", "") or meta.get("state_type", "")
        elements = self._load_elements(self.current_state)
        n_inter = sum(1 for e in elements if e.get("interactive"))
        n_region = len(self._region_boxes(self.current_state, elements))

        rows = self._element_rows(self.current_state)
        rows.sort(key=lambda r: {"direct": 0, "covered": 1, "unexplored": 2, "skip": 3}.get(r["kind"], 4))
        self.current_rows = rows
        n_d = sum(1 for r in rows if r["kind"] == "direct")
        n_c = sum(1 for r in rows if r["kind"] == "covered")
        n_u = sum(1 for r in rows if r["kind"] == "unexplored")
        n_s = sum(1 for r in rows if r["kind"] == "skip")

        self.state_var.set(f"当前节点: {self.current_state[:10]} ({alias})")
        self.meta_var.set(
            f"元素 {len(elements)} (可交互 {n_inter}) | 区块 {n_region} | "
            f"控件: 已验证 {n_d} / 策略覆盖 {n_c} / 待补 {n_u} / 跳过 {n_s} | 历史 {len(self.history)}")

        self.listbox.delete(0, tk.END)
        if not rows:
            self.listbox.insert(tk.END, "(该节点无可交互元素)")
        else:
            TAG = {"direct": "[已验证]", "covered": "[策略覆盖]",
                   "unexplored": "[待补点]", "skip": "[跳过  ]"}
            for r in rows:
                dst = r["dst"][:8] if r["dst"] else "--------"
                suffix = f" -> {dst}" if r["dst"] else f" | {r['reason']}"
                if r.get("edge_count", 0) > 1:
                    suffix += f" | {r['edge_count']} 条同名边"
                self.listbox.insert(tk.END, f"{TAG.get(r['kind'], '')}  {r['name'][:26]:28}{suffix}")
            self.listbox.selection_set(0)

        rendered = self._render_state_image(self.current_state, outgoing)
        if rendered is None:
            self.image_label.configure(text=f"截图不存在: {self.current_state}")
            self.image_label.image = None
            self._image_ref = None
            return

        fitted = self._fit_for_panel(rendered)
        tk_img = ImageTk.PhotoImage(fitted)
        self.image_label.configure(image=tk_img, text="")
        self.image_label.image = tk_img
        self._image_ref = tk_img

    def _jump_selected(self) -> None:
        rows = self.current_rows
        sel = self.listbox.curselection()
        if not sel or sel[0] >= len(rows):
            return
        row = rows[sel[0]]
        target = row.get("dst")
        if not target:
            messagebox.showinfo(
                "提示",
                f"'{row['name']}' 无可跳转的本页验证边：{row.get('reason', '尚无目标节点')}",
            )
            return
        if target not in self.node_index:
            messagebox.showwarning("提示", f"目标节点不在 node_index: {target}")
            return
        self.history.append(self.current_state)
        self.current_state = target
        self._refresh()

    def _go_back(self) -> None:
        if not self.history:
            return
        self.current_state = self.history.pop()
        self._refresh()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Interactive transition viewer for GUI-ReWalk graph results")
    parser.add_argument(
        "--nodes-dir",
        default=r"result_g2_verify17\20260704\setting\node_artifacts",
        help="Path to nodes directory containing node_index.json + <state>/ folders "
             "(visual traversal: <result>/<date>/<app>/node_artifacts)",
    )
    parser.add_argument(
        "--transitions",
        default="",
        help="Path to transitions.ndjson (optional; falls back to graph.json next to nodes-dir)",
    )
    parser.add_argument(
        "--start-state",
        default="",
        help="Optional state id to start from",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    nodes_dir = Path(args.nodes_dir)
    transitions_path = Path(args.transitions) if args.transitions else None

    if not nodes_dir.exists():
        raise FileNotFoundError(f"nodes-dir not found: {nodes_dir}")

    root = tk.Tk()
    app = TransitionViewerApp(
        root=root,
        nodes_dir=nodes_dir,
        transitions_path=transitions_path,
        start_state=args.start_state or None,
    )

    def _on_resize(_event):
        app._refresh()

    root.bind("<Configure>", _on_resize)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
