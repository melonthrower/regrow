import copy
import json
from pathlib import Path

import pytest

from tools.export_sft_dataset import main


def episode():
    return {
        "meta": {"schema_version": "m13.visual_collection.v1", "instruction": "Measure a lap",
                 "scenario_success": True, "final_verification": {"complete": True}, "errors": []},
        "steps": [{"kind": "region_goal", "committed": True,
                   "frames": {"before": "before.png", "after": "after.png"},
                   "action_spec": {"kind": "click", "target": "Open the timing page"},
                   "grounding": {"primitive_actions": [
                       {"action_type": "CLICK", "parameters": {"x": 739, "y": 49}}]},
                   "verification": {"outcome": "success", "reason": "AFTER_ONLY_RESULT"}}],
    }


def export(tmp_path, monkeypatch, data):
    source = tmp_path / "episode"
    (source / "screenshots").mkdir(parents=True)
    from PIL import Image
    for name in ("before.png", "after.png"):
        Image.new("RGB", (800, 600)).save(source / "screenshots" / name)
    raw = json.dumps(data).encode()
    (source / "trajectory.json").write_bytes(raw)
    out = tmp_path / "sft"
    monkeypatch.setattr("sys.argv", ["export_sft_dataset", "--collections", str(source),
                                     "--out", str(out), "--val_ratio", "0"])
    main()
    assert (source / "trajectory.json").read_bytes() == raw
    return [json.loads(line) for line in (out / "train.jsonl").read_text().splitlines()]


def test_export_verified_visual_navigation_preserves_actual_action(tmp_path, monkeypatch):
    samples = export(tmp_path, monkeypatch, episode())
    assert len(samples) == 1
    sample = samples[0]
    assert Path(sample["images"][0]).name == "before.png"
    answer = sample["messages"][-1]["content"]
    assert json.loads(answer.split("Action: ", 1)[1]) == {
        "action_type": "CLICK", "parameters": {"x": 739, "y": 49}}
    assert "Open the timing page" in answer
    assert "AFTER_ONLY_RESULT" not in json.dumps(sample)


@pytest.mark.parametrize("fault", ["receipt", "commit", "final", "compound"])
def test_export_does_not_launder_unverified_or_unframed_steps(tmp_path, monkeypatch, fault):
    data = episode()
    step = data["steps"][0]
    if fault == "receipt":
        step["verification"]["outcome"] = "none"
    elif fault == "commit":
        step["committed"] = False
    elif fault == "final":
        data["meta"]["final_verification"]["complete"] = False
    else:
        step["grounding"]["primitive_actions"].append(
            copy.deepcopy(step["grounding"]["primitive_actions"][0]))
    assert export(tmp_path, monkeypatch, data) == []


def test_legacy_export_still_uses_legacy_frame_and_annotation(tmp_path, monkeypatch):
    data = {"meta": {"instruction": "Use the form"}, "steps": [{
        "frame": "before.png", "action": "CLICK", "thinking": "Open the form",
        "action_json": '{"action_type":"CLICK","parameters":{"x":10,"y":20}}',
        "annotation": {"step_type": "progress", "had_effect": True}}]}
    assert len(export(tmp_path, monkeypatch, data)) == 1


@pytest.mark.parametrize("primitive", [{"action_type": "click", "x": 248, "y": 393},
                                      {"action_type": "navigate_back"}])
def test_android_primitive_keeps_its_flat_executable_format(tmp_path, monkeypatch, primitive):
    data = episode()
    data["steps"][0]["grounding"]["primitive_actions"] = [primitive]
    samples = export(tmp_path, monkeypatch, data)
    assert len(samples) == 1
    assert json.loads(samples[0]["messages"][-1]["content"].split("Action: ", 1)[1]) == primitive
    assert "navigate_back" in samples[0]["messages"][0]["content"]


@pytest.mark.parametrize("mobile", [True, False])
def test_visual_history_retains_the_target_of_completed_clicks(tmp_path, monkeypatch, mobile):
    data = episode()
    if mobile:
        data["steps"][0]["grounding"]["primitive_actions"] = [{"action_type": "click", "x": 10, "y": 20}]
    data["steps"].append(copy.deepcopy(data["steps"][0]))
    data["steps"][1]["action_spec"]["target"] = "Finish the date selection"
    samples = export(tmp_path, monkeypatch, data)
    followup = next(x for x in samples if "这是第一步" not in x["messages"][1]["content"])
    assert "Open the timing page" in followup["messages"][1]["content"]
    assert "AFTER_ONLY_RESULT" not in followup["messages"][1]["content"]
