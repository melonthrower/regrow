"""Exercise modular input through the real desktop controller without a VM."""

import pytest

from gui_rewalk.env.osworld_reload import PythonController
from gui_rewalk.src.core.explore.contracts import ActionRequest
from gui_rewalk.src.core.explore.runtime import ExplorationRuntime
from gui_rewalk.src.core.explore.status import pending_action_record

from .explore_fixtures import _Agent, _Env, _png, _seed_ledger


@pytest.mark.parametrize("value", ["replacement", "", "old-value"])
def test_desktop_input_replaces_nonempty_field_through_controller(tmp_path, value):
    class TextField:
        def __init__(self):
            self.value = "old-value"
            self.selected = False
            self.clicks = 0
            self.selections = 0

        def click(self, **_kwargs):
            self.clicks += 1
            self.selected = False

        def hotkey(self, *keys):
            assert keys == ("ctrl", "a")
            self.selections += 1
            self.selected = True

        def typewrite(self, text):
            self.value = text if self.selected else self.value + text
            self.selected = False

        def press(self, key):
            assert key == "backspace"
            self.value = "" if self.selected else self.value[:-1]
            self.selected = False

    field = TextField()
    controller = PythonController.__new__(PythonController)
    controller.execute_python_command = lambda command: exec(command, {"pyautogui": field})

    class ControllerEnv(_Env):
        def step(self, action, pause=0):
            controller.execute_gui_action(action)
            return super().step(action, pause=pause)

    env = ControllerEnv(_png("white"), _png("black"))
    runtime = ExplorationRuntime(env=env, app_name="fixture", platform="desktop",
                                 output_root=str(tmp_path), agent=_Agent([]), max_actions=1)
    runtime.ledger = _seed_ledger()
    operation = runtime.ledger.operations["o1"]
    operation.action = "input_text"
    runtime.ledger.canonical_operations[operation.canonical_operation_id].action = "input_text"
    task = runtime.ledger.operation_task(operation.operation_id)
    action = ActionRequest(kind="input_text", purpose="execute", target="Text field",
                           owner_ref=operation.element_id, operation_ref=operation.operation_id,
                           point_1000=[500, 500], text=value, direction="", amount=650)

    result = runtime._execute(task=task, action=action, screenshot=env._get_obs()["screenshot"])

    assert field.value == value
    assert field.clicks == 1
    assert field.selections == 1
    assert runtime.actions_used == 1
    assert len(runtime.ledger.attempts) == 1
    assert task.attempt_count == operation.attempt_count == 1
    assert result["screenshot"] == _png("black")
    assert pending_action_record(runtime.ledger, "a1")["text"] == value


def test_desktop_input_stops_when_selection_delivery_fails(tmp_path):
    class FailingEnv(_Env):
        def step(self, action, pause=0):
            result = super().step(action, pause=pause)
            if action["action_type"] == "HOTKEY":
                return {**result, "action_error": "selection delivery failed"}
            return result

    env = FailingEnv(_png("white"), _png("black"))
    runtime = ExplorationRuntime(
        env=env, app_name="fixture", platform="desktop",
        output_root=str(tmp_path), agent=_Agent([]), max_actions=1,
    )
    runtime.ledger = _seed_ledger()
    action = ActionRequest(
        kind="input_text", purpose="execute", target="Text field",
        owner_ref="el1", operation_ref="o1", point_1000=[500, 500],
        text="replacement", direction="", amount=650,
    )

    runtime._execute(
        task=runtime.ledger.operation_task("o1"), action=action,
        screenshot=env._get_obs()["screenshot"],
    )

    assert [a["action_type"] for a in env.actions] == ["CLICK", "HOTKEY"]
    assert runtime.pending_action_error == "selection delivery failed"
    assert runtime.actions_used == 1
    assert runtime.pending_attempt_id == "a1"
