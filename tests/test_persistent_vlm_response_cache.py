import json

import numpy as np

from gui_rewalk.src.core.visual_traversal.visual_cache import VLMCallLedger


class _FakeAgent:
    def __init__(self, model_version="model-v1"):
        self.model = "Fake"
        self.model_version = model_version
        self.max_tokens = 100
        self.top_p = 0.9
        self.temperature = 0.2
        self.enable_thinking = False
        self.max_retry = 3
        self.calls = 0

    def predict_mm(self, prompt, images):
        self.calls += 1
        return f"reply:{prompt}:{int(images[0][0, 0, 0])}", 11, 4, 1


def test_exact_reply_is_reused_across_ledgers(tmp_path):
    cache = tmp_path / "responses"
    image = np.zeros((3, 4, 3), dtype=np.uint8)
    first_agent = _FakeAgent()
    first = VLMCallLedger(response_cache_dir=str(cache))

    live = first.predict("semantic_inventory", first_agent, "prompt A", [image])
    assert first_agent.calls == 1
    assert live == ("reply:prompt A:0", 11, 4, 1)

    second_agent = _FakeAgent()
    replay = VLMCallLedger(response_cache_dir=str(cache))
    cached = replay.predict(
        "semantic_inventory", second_agent, "prompt A", [image.copy()])
    assert second_agent.calls == 0
    assert cached == ("reply:prompt A:0", 0, 0, 0)
    snapshot = replay.snapshot()
    assert snapshot["logical_calls"] == 1
    assert snapshot["transport_attempts"] == 0
    assert snapshot["persistent_cache_hits"] == 1
    assert snapshot["roles"]["semantic_inventory"]["persistent_cache_hits"] == 1

    files = list(cache.rglob("*.json"))
    assert len(files) == 1
    payload = json.loads(files[0].read_text(encoding="utf-8"))
    assert payload["response"] == "reply:prompt A:0"
    assert "prompt" not in payload
    assert "image" not in payload


def test_prompt_image_model_and_settings_changes_invalidate(tmp_path):
    cache = tmp_path / "responses"
    image = np.zeros((2, 2, 3), dtype=np.uint8)
    seed_agent = _FakeAgent()
    VLMCallLedger(response_cache_dir=str(cache)).predict(
        "page_identity", seed_agent, "same prompt", [image])
    assert seed_agent.calls == 1

    changed_prompt = _FakeAgent()
    VLMCallLedger(response_cache_dir=str(cache)).predict(
        "page_identity", changed_prompt, "same prompt!", [image])
    assert changed_prompt.calls == 1

    changed_image = _FakeAgent()
    other_image = image.copy()
    other_image[0, 0, 0] = 1
    VLMCallLedger(response_cache_dir=str(cache)).predict(
        "page_identity", changed_image, "same prompt", [other_image])
    assert changed_image.calls == 1

    changed_model = _FakeAgent(model_version="model-v2")
    VLMCallLedger(response_cache_dir=str(cache)).predict(
        "page_identity", changed_model, "same prompt", [image])
    assert changed_model.calls == 1

    changed_settings = _FakeAgent()
    changed_settings.enable_thinking = True
    VLMCallLedger(response_cache_dir=str(cache)).predict(
        "page_identity", changed_settings, "same prompt", [image])
    assert changed_settings.calls == 1


def test_disabled_cache_always_calls_model():
    image = np.zeros((1, 1, 3), dtype=np.uint8)
    agent = _FakeAgent()
    ledger = VLMCallLedger()
    ledger.predict("probe", agent, "prompt", [image])
    ledger.predict("probe", agent, "prompt", [image])
    assert agent.calls == 2
    assert ledger.snapshot()["persistent_cache_hits"] == 0


def test_force_refresh_bypasses_existing_persistent_reply(tmp_path):
    cache = tmp_path / "responses"
    image = np.zeros((1, 1, 3), dtype=np.uint8)
    seed = _FakeAgent()
    VLMCallLedger(response_cache_dir=str(cache)).predict(
        "semantic_inventory", seed, "prompt", [image])

    refresh = _FakeAgent()
    result = VLMCallLedger(response_cache_dir=str(cache)).predict(
        "semantic_inventory", refresh, "prompt", [image],
        use_response_cache=False)
    assert refresh.calls == 1
    assert result[1:] == (11, 4, 1)
