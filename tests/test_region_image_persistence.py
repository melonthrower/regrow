from __future__ import annotations

import io

from PIL import Image

from gui_rewalk.src.core.visual_traversal.artifacts import ArtifactWriter
from gui_rewalk.src.core.visual_traversal.grounding.region.registry import (
    RegionRegistry,
)
from gui_rewalk.src.core.visual_traversal.state.block_identity import (
    resolve_semantic_blocks,
)
from gui_rewalk.src.core.visual_traversal.visual_perception import VisualElement


def _png(color: str = "white", size=(100, 100)) -> bytes:
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, "PNG")
    return stream.getvalue()


def test_save_region_image_uses_stable_ids_without_role_collisions(tmp_path):
    writer = ArtifactWriter(str(tmp_path))

    paths = [
        writer.save_region_image("state", "r1", _png("red")),
        writer.save_region_image("state", "r2", _png("green")),
        writer.save_region_image("state", "r3", _png("blue")),
    ]

    assert all(paths)
    assert {path.name for path in (tmp_path / "node_artifacts" / "state").iterdir()} == {
        "region_r1.png", "region_r2.png", "region_r3.png",
    }
    assert len({(tmp_path / "node_artifacts" / "state" / name).read_bytes()
                for name in ("region_r1.png", "region_r2.png")}) == 2
    assert writer.save_region_image("state", "", _png()) is None
    assert writer.save_region_image("state", "r4", b"") is None
    assert writer.load_region_image("state", "r2") == _png("green")
    assert writer.load_region_image("state", "missing") is None


class _Perception:
    last_surface_kind = "page"

    def __init__(self):
        self.calls = 0
        self.last_block_localization = {}


class _Judge:
    last_raw_response = ""

    def align(self, *_args, **_kwargs):
        raise AssertionError("an empty registry must not invoke alignment")


class _IdentityWriter:
    def __init__(self):
        self.rows = []

    def save_block_identity_attempt(self, **kwargs):
        self.rows.append(kwargs)


def _semantic_inputs():
    blocks = []
    elements = []
    for index in range(3):
        local_id = f"b{index}"
        blocks.append({
            "local_id": local_id,
            "role": "content",
            "note": f"block {index}",
            "bbox_1000": [
                0 if index != 1 else 500,
                0 if index == 0 else 500,
                500 if index != 1 else 1000,
                500 if index == 0 else 1000,
            ],
            "element_ids": [index],
            "element_names": [f"Action {index}"],
        })
        elements.append(VisualElement(
            id=index,
            name=f"Action {index}",
            bbox_xywh=[0, 0, 0, 0],
            center=[0, 0],
            el_type="button",
            category="shallow",
            region="content",
            region_id=local_id,
            geometry_status="semantic_only",
        ))
    return blocks, elements


def test_resolve_returns_crops_by_stable_region_id():
    blocks, elements = _semantic_inputs()
    perception = _Perception()
    writer = _IdentityWriter()

    audit, region_crops = resolve_semantic_blocks(
        screenshot=_png(),
        blocks=blocks,
        elements=elements,
        perception=perception,
        judge=_Judge(),
        region_registry=RegionRegistry(),
        writer=writer,
        state_data={},
    )

    assert perception.calls == 0
    assert set(region_crops) == {
        blocks[0]["region_id"], blocks[1]["region_id"],
        blocks[2]["region_id"],
    }
    assert all(Image.open(io.BytesIO(payload)).size == (50, 50)
               for payload in region_crops.values())
    assert len(writer.rows) == 1
    json.dumps(audit)
