"""Artifact writer — StateGraph-compatible output for the visual traversal.

Mirrors the directory layout produced by the a11y traversal so the existing
``trajectory_composer`` can read it unchanged:

  <output_root>/
  ├── graph.json                 # StateGraph.save() (nx node_link_data)
  ├── screenshots/<state_id>.png
  └── node_artifacts/
      ├── node_index.json
      └── <state_id>/
          ├── screenshot.png
          ├── som_labeled.png    # numbered Set-of-Mark image (visual-only extra)
          ├── elements.json      # detected+named visual elements
          └── state_meta.json    # state_id, state_type, pHash fingerprint, ...

There is no ``a11y.xml`` (this is the whole point of route B); downstream code
treats it as optional.
"""

from __future__ import annotations

import copy
import io
import json
import logging
import os
import tempfile
from typing import Any, Dict, List, Optional

import numpy as np
from PIL import Image, ImageDraw

logger = logging.getLogger(__name__)


class ArtifactWriter:
    def __init__(self, output_root: str):
        self.root = output_root
        self.screenshots_dir = os.path.join(output_root, "screenshots")
        self.nodes_dir = os.path.join(output_root, "node_artifacts")
        self.action_attempts_dir = os.path.join(output_root, "action_attempts")
        self.entry_discovery_dir = os.path.join(
            output_root, "entry_discovery_frames")
        self.target_grounding_dir = os.path.join(output_root, "target_grounding_attempts")
        self.block_identity_dir = os.path.join(output_root, "block_identity_attempts")
        os.makedirs(self.screenshots_dir, exist_ok=True)
        os.makedirs(self.nodes_dir, exist_ok=True)
        self._target_grounding_sequence = 0
        self._block_identity_sequence = 0
        self._entry_discovery_sequence = 0
        existing_attempts = (
            os.listdir(self.target_grounding_dir)
            if os.path.isdir(self.target_grounding_dir) else [])
        for name in existing_attempts:
            prefix = str(name).split("_", 1)[0]
            if prefix.isdigit():
                self._target_grounding_sequence = max(
                    self._target_grounding_sequence, int(prefix))
        for name in (os.listdir(self.block_identity_dir)
                     if os.path.isdir(self.block_identity_dir) else []):
            prefix = str(name).split("_", 1)[0]
            if prefix.isdigit():
                self._block_identity_sequence = max(
                    self._block_identity_sequence, int(prefix))
        for name in (os.listdir(self.entry_discovery_dir)
                     if os.path.isdir(self.entry_discovery_dir) else []):
            if str(name).isdigit():
                self._entry_discovery_sequence = max(
                    self._entry_discovery_sequence, int(name))
        self._index: Dict[str, Dict[str, Any]] = {}
        index_path = os.path.join(self.nodes_dir, "node_index.json")
        if os.path.isfile(index_path):
            try:
                with open(index_path, "r", encoding="utf-8") as stream:
                    stored = json.load(stream)
                rows = stored.values() if isinstance(stored, dict) else stored
                self._index = {
                    str(row.get("state_id")): dict(row)
                    for row in (rows or [])
                    if isinstance(row, dict) and row.get("state_id")
                }
            except Exception as exc:
                logger.warning("node artifact index could not be loaded: %s", exc)

    @staticmethod
    def _write_json_atomic(path: str, payload: Any) -> None:
        directory = os.path.dirname(path) or "."
        os.makedirs(directory, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(
            prefix=".artifact-", suffix=".json.tmp", dir=directory)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
                json.dump(payload, stream, ensure_ascii=False, indent=2)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    # ── screenshots ──────────────────────────────────────────────────────
    def save_screenshot(
            self, state_id: str, screenshot_bytes: bytes, *,
            replace: bool = False) -> str:
        path = os.path.join(self.screenshots_dir, f"{state_id}.png")
        if replace or not os.path.exists(path):
            with open(path, "wb") as f:
                f.write(screenshot_bytes)
        return path

    def save_entry_discovery_frame(self, screenshot_bytes: bytes) -> str:
        """Persist one immutable full frame used to accept an Entry batch."""
        self._entry_discovery_sequence += 1
        frame_dir = os.path.join(
            self.entry_discovery_dir,
            f"{self._entry_discovery_sequence:06d}",
        )
        os.makedirs(frame_dir, exist_ok=False)
        path = os.path.join(frame_dir, "screenshot.png")
        with open(path, "wb") as stream:
            stream.write(screenshot_bytes)
        return path

    def save_target_grounding_attempt(
        self, *, screenshot_bytes: bytes, stored_target: Any,
        target_attempt: int, diagnostic: Dict[str, Any],
        reviewer: Dict[str, Any], grounded_target: Optional[Any],
        outcome: str,
    ) -> str:
        """Persist one auditable semantic target-grounding attempt."""
        self._target_grounding_sequence += 1
        sequence = self._target_grounding_sequence
        os.makedirs(self.target_grounding_dir, exist_ok=True)
        raw_name = str(getattr(stored_target, "name", "") or "target")
        safe_name = "".join(
            char.lower() if char.isalnum() else "_" for char in raw_name)
        safe_name = "_".join(part for part in safe_name.split("_") if part)[:48]
        attempt_dir = os.path.join(
            self.target_grounding_dir,
            f"{sequence:06d}_{safe_name or 'target'}")
        os.makedirs(attempt_dir, exist_ok=False)
        with open(os.path.join(attempt_dir, "input.png"), "wb") as stream:
            stream.write(screenshot_bytes)

        geometry: Optional[Dict[str, Any]] = None
        overlay_name: Optional[str] = None
        if grounded_target is not None:
            bbox = [int(value) for value in grounded_target.bbox_xywh]
            point = [int(value) for value in grounded_target.center]
            geometry = {"bbox_px_xywh": bbox, "click_point_px": point}
            image = Image.open(io.BytesIO(screenshot_bytes)).convert("RGB")
            x, y, width, height = bbox
            cx, cy = point
            draw = ImageDraw.Draw(image)
            draw.rectangle([x, y, x + width, y + height], outline="red", width=4)
            radius = 8
            draw.line([cx - radius, cy, cx + radius, cy], fill="black", width=3)
            draw.line([cx, cy - radius, cx, cy + radius], fill="black", width=3)
            overlay_name = "overlay.png"
            image.save(os.path.join(attempt_dir, overlay_name))

        target_context = {
            key: copy.deepcopy(getattr(stored_target, key, None))
            for key in (
                "id", "uid", "name", "el_type", "category", "group",
                "region", "region_id", "interactive", "selected", "enabled",
                "stateful", "state_key", "state_value", "surface_kind",
                "geometry_status", "source",
            )
        }
        self._write_json_atomic(os.path.join(attempt_dir, "result.json"), {
            "schema_version": "semantic_target_grounding_attempt.v1",
            "sequence": sequence,
            "target_attempt": int(target_attempt),
            "outcome": str(outcome or "unknown"),
            "target": target_context,
            "diagnostic": copy.deepcopy(diagnostic or {}),
            "reviewer": copy.deepcopy(reviewer or {}),
            "grounded_geometry": geometry,
            "artifacts": {"input": "input.png", "overlay": overlay_name},
        })
        return attempt_dir

    @staticmethod
    def _readable_slug(value: Any, fallback: str) -> str:
        parts = []
        separator = False
        for char in str(value or "").strip().casefold():
            if char.isalnum():
                parts.append(char)
                separator = False
            elif not separator and parts:
                parts.append("_")
                separator = True
        slug = "".join(parts).strip("_")
        return (slug or fallback)[:80]

    def save_action_attempt_screenshot(
        self, *, source_state_id: str, page_description: str,
        region_id: str, region_description: str,
        element_id: str, element_description: str,
        attempt_id: str, phase: str, screenshot_bytes: bytes,
    ) -> Optional[str]:
        """Persist one semantic action frame under a readable attempt path."""
        phase = str(phase or "").strip().casefold()
        if phase not in {"before", "after"} or not screenshot_bytes:
            return None
        state_token = self._readable_slug(source_state_id, "unknown")[:8]
        region_token = self._readable_slug(region_id, "none")
        element_token = self._readable_slug(element_id, "native")
        attempt_token = self._readable_slug(attempt_id, "attempt")
        directory = os.path.join(
            self.action_attempts_dir,
            f"{self._readable_slug(page_description, 'page')}__state_{state_token}",
            f"{self._readable_slug(region_description, 'whole_surface')}"
            f"__region_{region_token}",
            f"{self._readable_slug(element_description, 'native_action')}"
            f"__element_{element_token}",
            attempt_token,
        )
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{phase}.png")
        with open(path, "wb") as stream:
            stream.write(screenshot_bytes)
        return os.path.relpath(path, self.root).replace(os.sep, "/")

    def save_block_identity_attempt(
        self, *, audit: Dict[str, Any], current_atlas: Optional[bytes],
        current_crops: Dict[str, bytes],
    ) -> str:
        """Persist optional transient-crop evidence for one online alignment."""
        self._block_identity_sequence += 1
        os.makedirs(self.block_identity_dir, exist_ok=True)
        attempt_dir = os.path.join(
            self.block_identity_dir, f"{self._block_identity_sequence:06d}")
        os.makedirs(attempt_dir, exist_ok=False)
        artifacts = {"current_atlas": None, "crops": {}}
        if current_atlas:
            with open(os.path.join(attempt_dir, "current_atlas.png"), "wb") as stream:
                stream.write(current_atlas)
            artifacts["current_atlas"] = "current_atlas.png"
        crop_dir = os.path.join(attempt_dir, "current_crops")
        for local_id, payload in (current_crops or {}).items():
            safe = "".join(char for char in str(local_id) if char.isalnum() or char in "_-")
            if not safe or not payload:
                continue
            os.makedirs(crop_dir, exist_ok=True)
            name = f"{safe}.png"
            with open(os.path.join(crop_dir, name), "wb") as stream:
                stream.write(payload)
            artifacts["crops"][str(local_id)] = f"current_crops/{name}"
        payload = copy.deepcopy(audit or {})
        payload["artifacts"] = artifacts
        self._write_json_atomic(os.path.join(attempt_dir, "result.json"), payload)
        return attempt_dir

    def save_fullpage(self, state_id: str, image_bytes: bytes) -> str:
        """Save a FULL-PAGE composite (STITCH_NODE_IMAGE) to a SEPARATE file and
        return its path. Kept distinct from ``save_screenshot``'s
        ``<state_id>.png`` so the registry's SSIM identity file (the top viewport
        frame) is never overwritten by the tall composite — only the graph / node
        artifact image is upgraded to the full page."""
        path = os.path.join(self.screenshots_dir, f"{state_id}__fullpage.png")
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path

    def save_region_composite(self, state_id: str, role: str, image_bytes: bytes) -> str:
        """[REGION-SCROLL CHANGE 14] Save a scrollable REGION's stitched full composite
        (e.g. the whole nav sidebar) as a per-node artifact, so downstream capability
        synthesis / instruction construction can see the full region, not just the top
        viewport. One file per region role under the node dir."""
        node_dir = os.path.join(self.nodes_dir, state_id)
        os.makedirs(node_dir, exist_ok=True)
        safe = "".join(c if (c.isalnum() or c == "_") else "_" for c in (role or "region").lower())
        path = os.path.join(node_dir, f"region_{safe}.png")
        with open(path, "wb") as f:
            f.write(image_bytes)
        return path

    @staticmethod
    def _safe_region_id(region_id: str) -> str:
        return "".join(
            char if (char.isalnum() or char == "_") else "_"
            for char in str(region_id or "")
        )

    def save_region_image(
        self, state_id: str, region_id: str, image_bytes: bytes
    ) -> Optional[str]:
        """Save one Region crop by stable id without any full-page fallback."""
        safe = self._safe_region_id(region_id)
        if not safe or not image_bytes:
            return None
        node_dir = os.path.join(self.nodes_dir, state_id)
        os.makedirs(node_dir, exist_ok=True)
        path = os.path.join(node_dir, f"region_{safe}.png")
        with open(path, "wb") as stream:
            stream.write(image_bytes)
        return path

    def load_region_image(self, state_id: str, region_id: str) -> Optional[bytes]:
        """Load the persisted long/cropped Region image for live map grounding."""
        safe = self._safe_region_id(region_id)
        if not safe:
            return None
        path = os.path.join(self.nodes_dir, state_id, f"region_{safe}.png")
        try:
            with open(path, "rb") as stream:
                return stream.read()
        except OSError:
            return None

    # ── per-node artifacts ───────────────────────────────────────────────
    def save_node(
        self,
        state_id: str,
        screenshot_bytes: bytes,
        elements: List[Dict[str, Any]],
        visual_fingerprint: Dict[str, Any],
        som_image: Optional[np.ndarray] = None,
        action_path_from_root: Optional[List[Dict[str, Any]]] = None,
        state_type: str = "visual",
        node_local_functions: Optional[List[Dict[str, Any]]] = None,
        page_name: str = "",
        app_id: str = "",
        page_id: str = "",
        variant_id: str = "",
        page_identity_version: str = "",
        variant_signature: Optional[Any] = None,
        observed_facts: Optional[Dict[str, Any]] = None,
        visible_capabilities: Optional[List[str]] = None,
        capability_records: Optional[List[Dict[str, Any]]] = None,
        semantic_blocks: Optional[List[Dict[str, Any]]] = None,
        region_partition_mapping: Optional[Dict[str, Any]] = None,
        region_transition: Optional[Dict[str, Any]] = None,
        perception_mode: str = "",
        geometry_mode: str = "",
    ) -> str:
        node_dir = os.path.join(self.nodes_dir, state_id)
        os.makedirs(node_dir, exist_ok=True)

        with open(os.path.join(node_dir, "screenshot.png"), "wb") as f:
            f.write(screenshot_bytes)

        if som_image is not None:
            try:
                Image.fromarray(som_image).save(os.path.join(node_dir, "som_labeled.png"))
            except Exception as e:
                logger.debug("som image save failed: %s", e)

        self._write_json_atomic(
            os.path.join(node_dir, "elements.json"), elements)
        if semantic_blocks is not None:
            self._write_json_atomic(
                os.path.join(node_dir, "semantic_blocks.json"), semantic_blocks)

        meta = {
            "state_id": state_id,
            "state_type": state_type,
            "elements_count": len(elements),
            "visual_fingerprint": visual_fingerprint,
            "action_path_from_root": action_path_from_root or [],
            "node_local_functions": node_local_functions or [],
            "page_name": page_name or "",
            "page_id": page_id or "",
            "variant_id": variant_id or state_id,
            "page_identity_version": str(page_identity_version or ""),
            "variant_signature": copy.deepcopy(variant_signature),
            "observed_facts": dict(observed_facts or {}),
            "visible_capabilities": list(visible_capabilities or []),
            "region_partition_mapping": copy.deepcopy(
                region_partition_mapping or {}),
            "region_transition": copy.deepcopy(region_transition or {}),
            "perception_mode": str(perception_mode or "legacy_grounded"),
            "geometry_mode": str(geometry_mode or "stored_bbox"),
        }
        self._write_json_atomic(
            os.path.join(node_dir, "state_meta.json"), meta)

        if capability_records is not None:
            self.save_capabilities(
                state_id,
                app_id=app_id,
                page_name=page_name,
                page_id=page_id,
                variant_id=variant_id or state_id,
                capabilities=capability_records,
            )

        self._index[state_id] = {
            "state_id": state_id,
            "state_type": state_type,
            "elements_count": len(elements),
            "page_name": page_name or "",
            "page_id": page_id or "",
            "variant_id": variant_id or state_id,
        }
        self._flush_index()
        return node_dir

    def update_node_observation(
        self,
        state_id: str,
        *,
        elements: List[Dict[str, Any]],
        page_name: str,
        page_id: str,
        variant_id: str,
        variant_signature: Optional[Any],
        observed_facts: Dict[str, Any],
        visible_capabilities: List[str],
        node_local_functions: Optional[List[Dict[str, Any]]] = None,
        page_identity_version: str = "",
        semantic_blocks: Optional[List[Dict[str, Any]]] = None,
        perception_mode: str = "",
        geometry_mode: str = "",
    ) -> None:
        """Atomically refresh mutable sidecars after a revisit/top-up.

        The canonical screenshot remains the original observation used for visual
        identity.  Elements, Page/Variant metadata and the index must nevertheless
        track graph truth so offline enrichment cannot silently lose controls first
        discovered on a later visit.
        """
        node_dir = os.path.join(self.nodes_dir, state_id)
        os.makedirs(node_dir, exist_ok=True)
        meta_path = os.path.join(node_dir, "state_meta.json")
        meta: Dict[str, Any] = {}
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as stream:
                    loaded = json.load(stream)
                if isinstance(loaded, dict):
                    meta = loaded
            except Exception as exc:
                logger.warning("state_meta refresh starts from empty for %s: %s",
                               state_id, exc)
        functions = list(meta.get("node_local_functions") or [])
        for function in node_local_functions or []:
            if function not in functions:
                functions.append(copy.deepcopy(function))
        meta.pop("page_anchor_tokens", None)
        meta.update({
            "state_id": state_id,
            "state_type": str(meta.get("state_type") or "visual"),
            "elements_count": len(elements),
            "node_local_functions": functions,
            "page_name": str(page_name or ""),
            "page_id": str(page_id or ""),
            "variant_id": str(variant_id or state_id),
            "page_identity_version": str(
                page_identity_version
                or meta.get("page_identity_version")
                or "semantic_page_variant_v1"),
            "variant_signature": copy.deepcopy(variant_signature),
            "observed_facts": copy.deepcopy(observed_facts or {}),
            "visible_capabilities": list(visible_capabilities or []),
            "perception_mode": str(perception_mode or meta.get("perception_mode") or "legacy_grounded"),
            "geometry_mode": str(geometry_mode or meta.get("geometry_mode") or "stored_bbox"),
        })
        self._write_json_atomic(
            os.path.join(node_dir, "elements.json"), elements)
        if semantic_blocks is not None:
            self._write_json_atomic(
                os.path.join(node_dir, "semantic_blocks.json"), semantic_blocks)
        self._write_json_atomic(meta_path, meta)
        current = dict(self._index.get(state_id) or {})
        current.update({
            "state_id": state_id,
            "state_type": str(meta.get("state_type") or "visual"),
            "elements_count": len(elements),
            "page_name": str(page_name or ""),
            "page_id": str(page_id or ""),
            "variant_id": str(variant_id or state_id),
        })
        self._index[state_id] = current
        self._flush_index()

    def save_capabilities(
        self,
        state_id: str,
        *,
        app_id: str,
        page_name: str,
        page_id: str,
        variant_id: str,
        capabilities: List[Dict[str, Any]],
    ) -> str:
        """Persist the online discovered/verified capability snapshot."""
        node_dir = os.path.join(self.nodes_dir, state_id)
        os.makedirs(node_dir, exist_ok=True)
        path = os.path.join(node_dir, "page_capabilities.json")
        payload = {
            "schema_version": "capability.discovery.v1",
            "node_id": state_id,
            "app_id": str(app_id or ""),
            "page_name": str(page_name or ""),
            "page_id": str(page_id or ""),
            "variant_id": str(variant_id or state_id),
            "capabilities": copy.deepcopy(capabilities or []),
        }
        self._write_json_atomic(path, payload)
        return path

    def discard_node_index(self, state_id: str) -> None:
        """Remove a provisional node from the authoritative artifact index.

        Diagnostic files already written for the rejected observation are kept;
        they are not graph inputs and can help post-run debugging.  Consumers of
        ``node_index.json`` see only live graph nodes.
        """
        if self._index.pop(str(state_id or ""), None) is not None:
            self._flush_index()

    def _flush_index(self) -> None:
        self._write_json_atomic(
            os.path.join(self.nodes_dir, "node_index.json"),
            list(self._index.values()),
        )
