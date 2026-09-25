"""Offline VLM transport-robustness test (no network, no emulator, no a11y).

Validates the fix for the ~10-minute hang: a SINGLE DashScope/qwen
chat.completions request stalled with no timeout (the openai client's built-in
default read timeout is 600s), freezing the whole visual traversal. The fix
(gui_rewalk/env/gui_gen_agent.py):

  * constructs the model client with a SHORT per-request timeout (~75s) instead
    of the 600s default, and disables the client's own internal retries;
  * pins that timeout again per-call via ``with_options(timeout=...)``;
  * runs a bounded retry loop in ``predict_mm`` with a SHORT backoff and, on
    total failure, returns the safe default ``ERROR_CALLING_LLM`` (which the
    visual_agents callers already turn into their own safe fallbacks) WITHOUT
    raising — so a stalled request fails fast and retries instead of hanging.

We never touch the network: we build a real GUIGenAgent, then swap its
``model_client`` for a fake whose ``chat.completions.create`` raises a timeout
(or sleeps), and we monkeypatch ``time.sleep`` so the retry backoff is instant
while still proving the retry COUNT and the fast-fail / safe-default behaviour.
"""
import os
import sys
import time
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Make construction deterministic / network-free-friendly.
os.environ.setdefault("DASHSCOPE_API_KEY", "sk-test-offline")

import httpx

from gui_rewalk.env import gui_gen_agent as gga
from gui_rewalk.env.gui_gen_agent import GUIGenAgent, ERROR_CALLING_LLM


# ── fake openai-style client ────────────────────────────────────────────────
class _FakeCompletions:
    def __init__(self, parent):
        self._parent = parent

    def create(self, **kwargs):
        self._parent.calls += 1
        self._parent.last_kwargs = kwargs
        if self._parent.mode == "timeout":
            # Simulate what the openai client raises when the per-request timeout
            # trips — APITimeoutError wraps a httpx timeout. Raise the underlying
            # httpx timeout (caught by predict_mm's broad except) to prove we do
            # NOT swallow it silently and DO retry.
            raise httpx.ReadTimeout("simulated read timeout")
        if self._parent.mode == "sleep":
            # A genuinely slow call; the real client would abort at the timeout,
            # here we just sleep briefly to prove wall-clock stays bounded.
            time.sleep(self._parent.sleep_s)
            raise httpx.ReadTimeout("simulated slow then timeout")
        if self._parent.mode == "success":
            return SimpleNamespace(
                usage=SimpleNamespace(
                    prompt_tokens=10,
                    completion_tokens=2,
                    prompt_tokens_details=SimpleNamespace(
                        cached_tokens=7,
                        cache_creation_input_tokens=3,
                    ),
                ),
                choices=[SimpleNamespace(
                    message=SimpleNamespace(content="{}"))],
            )
        raise AssertionError("unexpected mode")


class _FakeChat:
    def __init__(self, parent):
        self.completions = _FakeCompletions(parent)


class FakeClient:
    """Stand-in for openai.OpenAI: records call count, raises a timeout."""

    def __init__(self, mode="timeout", sleep_s=0.05):
        self.mode = mode
        self.sleep_s = sleep_s
        self.calls = 0
        self.last_kwargs = None
        self.with_options_calls = 0
        self.last_options = {}
        self.chat = _FakeChat(self)

    def with_options(self, **kwargs):
        # openai's real with_options returns a shallow copy with overridden
        # options; we just record that the call site pinned a timeout and reuse
        # ourselves so the call counter is shared.
        self.with_options_calls += 1
        self.last_options = kwargs
        assert "timeout" in kwargs, "call site must pin a per-request timeout"
        return self


def _make_agent():
    """Build a real GUIGenAgent (screenshot/gen_data is a valid combo)."""
    return GUIGenAgent(
        platform="ubuntu",
        model="qwen-vl-max",
        model_version="qwen-vl-max",
        observation_type="screenshot",
        action_space="gen_data",
        max_retry=3,
    )


def test_real_client_has_bounded_timeout():
    """Constructor must give the openai client a SHORT timeout, not 600s."""
    agent = _make_agent()
    client = agent.model_client
    # openai stores the per-request timeout on the client; it must be our short
    # cap, not the 600s default that caused the hang.
    to = getattr(client, "timeout", None)
    assert to is not None, "openai client has no timeout set"
    if isinstance(to, httpx.Timeout):
        read = to.read
    else:  # a plain float
        read = float(to)
    assert read is not None and read <= 120, (
        f"per-request read timeout too high ({read}s) — would still hang")
    assert read == gga._VLM_REQUEST_TIMEOUT, (
        f"timeout {read}s != configured {gga._VLM_REQUEST_TIMEOUT}s")
    print(f"[1] client read-timeout = {read}s (<=120, == configured)  OK")


def test_constructor_strips_transport_whitespace_from_api_key():
    with mock.patch.dict(
        os.environ, {"DASHSCOPE_API_KEY": "\ufeff  sk-test-secret\r\n"}
    ), mock.patch.object(gga.openai, "OpenAI") as client_factory:
        _make_agent()

    assert client_factory.call_args.kwargs["api_key"] == "sk-test-secret"


def test_predict_mm_times_out_fast_retries_and_returns_safe_default():
    agent = _make_agent()
    fake = FakeClient(mode="timeout")
    agent.model_client = fake

    # Make backoff instant but still observable, so the test runs fast while
    # proving the loop slept BETWEEN attempts (short backoff, not 20s/40s).
    slept = []
    orig_sleep = time.sleep
    gga.time.sleep = lambda s: slept.append(s)  # noqa: E731
    try:
        t0 = time.monotonic()
        resp, ptok, ctok, counter = agent.predict_mm(
            "is this the same page?", [__import__("numpy").zeros((4, 4, 3), "uint8")])
        elapsed = time.monotonic() - t0
    finally:
        gga.time.sleep = orig_sleep

    # (a) returns the SAFE DEFAULT without raising
    assert resp == ERROR_CALLING_LLM, f"expected safe default, got {resp!r}"
    # (b) RETRIED up to max_retry (one create() per attempt)
    assert fake.calls == agent.max_retry, (
        f"expected {agent.max_retry} attempts, got {fake.calls}")
    # the call site pinned a per-request timeout each attempt
    assert fake.with_options_calls == agent.max_retry, (
        "with_options(timeout=) not applied on every attempt")
    # (c) FAST: with sleep stubbed out, the wrapper itself adds no long waits
    assert elapsed < 5, f"wrapper too slow ({elapsed:.2f}s) even with no real sleep"
    # backoff was SHORT and bounded (3s then 6s), retried max_retry-1 times
    assert slept == [3, 6], f"expected short backoff [3, 6], got {slept}"
    print(f"[2] timeout->retry x{fake.calls} -> safe default '{resp}' in "
          f"{elapsed:.3f}s, backoff {slept}  OK")


def test_slow_call_wall_clock_bounded():
    """A slow call path: wall-clock stays small (the real timeout would abort)."""
    agent = _make_agent()
    fake = FakeClient(mode="sleep", sleep_s=0.05)
    agent.model_client = fake
    gga.time.sleep = lambda s: None  # skip backoff
    try:
        t0 = time.monotonic()
        resp, *_ = agent.predict_mm(
            "x", [__import__("numpy").zeros((4, 4, 3), "uint8")])
        elapsed = time.monotonic() - t0
    finally:
        gga.time.sleep = time.sleep
    assert resp == ERROR_CALLING_LLM
    # 3 attempts * 0.05s sleep ~= 0.15s; nowhere near 10 minutes.
    assert elapsed < 5, f"slow path not bounded ({elapsed:.2f}s)"
    print(f"[3] slow-call path bounded: {elapsed:.3f}s for {fake.calls} attempts  OK")


def test_role_owned_attempt_budget_prevents_nested_retries():
    """Grounding's outer retry must be able to request one transport attempt."""
    agent = _make_agent()
    fake = FakeClient(mode="timeout")
    agent.model_client = fake
    resp, _ptok, _ctok, counter = agent.predict_mm_with_policy(
        "ground this frame", [__import__("numpy").zeros((4, 4, 3), "uint8")],
        max_attempts=1,
        timeout_seconds=150,
    )
    assert resp == ERROR_CALLING_LLM
    assert fake.calls == 1
    assert fake.with_options_calls == 1
    assert counter == 2
    assert fake.last_options["timeout"].read == 150
    print("[4] grounding policy -> 1 transport attempt with 150s timeout  OK")


def test_system_prompt_precedes_multimodal_user_message():
    agent = _make_agent()
    captured = {}

    def fake_get_api_info(messages, model, timeout_seconds=None):
        captured["messages"] = messages
        captured["model"] = model
        captured["timeout_seconds"] = timeout_seconds
        return "{}", 10, 2

    agent.get_api_info = fake_get_api_info
    response, *_ = agent.predict_mm_with_policy(
        "dynamic turn",
        [__import__("numpy").zeros((4, 4, 3), "uint8")],
        max_attempts=1,
        system_prompt="stable contract",
    )

    assert response == "{}"
    assert captured["messages"][0] == {
        "role": "system", "content": "stable contract",
    }
    user = captured["messages"][1]
    assert user["role"] == "user"
    assert user["content"][0] == {"type": "text", "text": "dynamic turn"}
    assert user["content"][1]["type"] == "image_url"


def test_prompt_cache_usage_is_exposed_for_debugging():
    agent = _make_agent()
    agent.model_client = FakeClient(mode="success")

    response, prompt_tokens, completion_tokens, _ = agent.predict_mm_with_policy(
        "dynamic turn",
        [__import__("numpy").zeros((4, 4, 3), "uint8")],
        max_attempts=1,
        system_prompt="stable contract",
    )

    assert response == "{}"
    assert prompt_tokens == 10
    assert completion_tokens == 2
    assert agent.last_prompt_tokens_details == {
        "cached_tokens": 7,
        "cache_creation_input_tokens": 3,
    }


def main():
    test_real_client_has_bounded_timeout()
    test_predict_mm_times_out_fast_retries_and_returns_safe_default()
    test_slow_call_wall_clock_bounded()
    test_role_owned_attempt_budget_prevents_nested_retries()
    print("ALL PASS — a stalled VLM request now fails fast, retries with short "
          "backoff, and returns the safe default without hanging ~10 min.")


if __name__ == "__main__":
    main()
