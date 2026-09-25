from pathlib import Path
from types import SimpleNamespace

import numpy as np

from gui_rewalk.env.codex_gui_gen_agent import CodexGUIGenAgent


def test_codex_gui_agent_passes_prompt_and_images_to_read_only_exec(tmp_path):
    captured = {}

    def fake_runner(command, **kwargs):
        captured["command"] = list(command)
        captured["input"] = kwargs["input"]
        image_paths = [
            Path(command[index + 1])
            for index, value in enumerate(command[:-1])
            if value == "-i"
        ]
        captured["images_exist"] = [path.is_file() for path in image_paths]
        output_path = Path(command[command.index("-o") + 1])
        output_path.write_text(
            '{"complete":true,"reason":"visible result"}',
            encoding="utf-8",
        )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    agent = CodexGUIGenAgent(
        model_version="gpt-5.6-luna",
        output_root=str(tmp_path),
        runner=fake_runner,
        command=["codex"],
    )
    raw, prompt_tokens, completion_tokens, attempts = agent.predict_mm(
        "Return final verification JSON.",
        [np.zeros((16, 24, 3), dtype=np.uint8)],
    )

    assert raw == '{"complete":true,"reason":"visible result"}'
    assert (prompt_tokens, completion_tokens, attempts) == (None, None, 1)
    assert captured["input"] == "Return final verification JSON."
    assert captured["images_exist"] == [True]
    assert captured["command"][:7] == [
        "codex", "exec", "-m", "gpt-5.6-luna",
        "--sandbox", "read-only", "--skip-git-repo-check",
    ]
    assert "-i" in captured["command"]
    assert captured["command"][-1] == "-"


def test_codex_gui_agent_surfaces_cli_failure(tmp_path):
    def failed_runner(_command, **_kwargs):
        return SimpleNamespace(
            returncode=7, stdout="", stderr="authentication required")

    agent = CodexGUIGenAgent(
        model_version="gpt-5.6-luna",
        output_root=str(tmp_path),
        runner=failed_runner,
        command=["codex"],
    )

    try:
        agent.predict_mm("test", [])
    except RuntimeError as exc:
        assert "authentication required" in str(exc)
    else:
        raise AssertionError("Codex CLI failure must fail closed")
