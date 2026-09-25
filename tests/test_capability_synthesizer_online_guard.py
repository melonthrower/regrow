"""Offline guard: VLM enrichment cannot overwrite online verified evidence."""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gui_rewalk.src.core.scenario.capability_synthesizer import (  # noqa: E402
    CapabilitySynthesizer,
)


class _Agent:
    def predict_mm(self, _prompt, _images):
        return json.dumps({
            "page_name": "Alarm",
            "page_breakdown": "Alarm home",
            "capabilities": [{
                "name": "Create alarm",
                "region": "toolbar",
                "elements": ["1"],
                "param": {"type": "none", "current": "", "values": []},
                "requires": [],
                "effects": [],
                "success_predicate": "Editor is visible",
                "observables": [],
                "availability_status": "discovered",
                "execution_recipe": [{
                    "action_type": "CLICK",
                    "selector": {"element_label": "Add alarm"},
                }],
            }],
        }), None


def main() -> int:
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        state = root / "state"
        state.mkdir(parents=True)
        Image.new("RGB", (64, 64), "white").save(state / "screenshot.png")
        (state / "elements.json").write_text(json.dumps([{
            "id": 1, "name": "Add alarm", "el_type": "button",
            "category": "navigation", "region": "toolbar",
        }]), encoding="utf-8")
        (state / "state_meta.json").write_text(json.dumps({
            "state_id": "state", "page_name": "Alarm",
        }), encoding="utf-8")
        canonical = {
            "schema_version": "capability.discovery.v1",
            "node_id": "state", "app_id": "clock", "page_name": "Alarm",
            "page_id": "page_alarm", "variant_id": "has_alarm",
            "capabilities": [{
                "capability_id": "create_alarm", "name": "Create alarm",
                "status": "verified", "availability_status": "verified",
                "action_edge_ids": ["ae_verified"],
                "source_elements": [{"element_id": "1"}],
            }],
        }
        canonical_path = state / "page_capabilities.json"
        canonical_bytes = json.dumps(
            canonical, ensure_ascii=False, indent=2).encode("utf-8")
        canonical_path.write_bytes(canonical_bytes)

        result = CapabilitySynthesizer(
            str(root), agent=_Agent(), app_id="clock").synthesize_node(
                "state", force=True)

        assert result is not None and result.capabilities
        assert canonical_path.read_bytes() == canonical_bytes
        enrichment = state / "page_capabilities_enrichment.json"
        assert enrichment.is_file()
        enriched = json.loads(enrichment.read_text(encoding="utf-8"))
        assert enriched["capabilities"][0]["availability_status"] == "discovered"
        assert canonical["capabilities"][0]["status"] == "verified"

    print("PASS offline enrichment preserves canonical online verified evidence")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
