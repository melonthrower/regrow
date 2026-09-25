import subprocess

from gui_rewalk.src.config.config import get_android_package
from tools.mobileworld_external_env import (
    MOBILEWORLD_APP_PACKAGES,
    ExternalADBController,
    ExternalADBEnv,
)


class _Runner:
    def __init__(self):
        self.calls = []

    def __call__(self, argv, **kwargs):
        self.calls.append((list(argv), dict(kwargs)))
        if "exec-out" in argv:
            return subprocess.CompletedProcess(argv, 0, stdout=b"PNG", stderr=b"")
        command = " ".join(argv)
        if "dumpsys activity activities" in command:
            return subprocess.CompletedProcess(
                argv, 0,
                stdout="mResumedActivity: ActivityRecord{1 u0 com.testmall.app/.Main}",
                stderr="",
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def test_mobileworld_mapping_contains_only_the_fifteen_gui_apps():
    assert list(MOBILEWORLD_APP_PACKAGES) == [
        "calendar", "camera", "chrome", "clock", "contacts", "docreader",
        "files", "gallery", "mail", "maps", "mastodon", "mattermost",
        "messages", "settings", "taodian",
    ]
    assert all(not name.startswith("mcp-") for name in MOBILEWORLD_APP_PACKAGES)


def test_android_chrome_has_a_launchable_mobile_package():
    assert get_android_package("android_chrome") == "com.android.chrome"


def test_external_controller_scroll_uses_content_direction_from_visible_point():
    runner = _Runner()
    controller = ExternalADBController(
        adb_path="adb", serial="127.0.0.1:5709",
        screen_size=(1080, 2400), runner=runner)

    controller.execute_gui_action({
        "action_type": "scroll", "direction": "down", "x": 540, "y": 1800,
    })

    argv = runner.calls[-1][0]
    assert argv == [
        "adb", "-s", "127.0.0.1:5709", "shell", "input", "swipe",
        "540", "1800", "540", "960", "400",
    ]


def test_external_controller_reads_foreground_package():
    controller = ExternalADBController(
        adb_path="adb", serial="127.0.0.1:5709",
        screen_size=(1080, 2400), runner=_Runner())

    assert controller.foreground_package() == "com.testmall.app"


def test_external_env_returns_fresh_screenshot_after_action():
    runner = _Runner()
    controller = ExternalADBController(
        adb_path="adb", serial="127.0.0.1:5709",
        screen_size=(1080, 2400), runner=runner)
    env = ExternalADBEnv(controller)

    observation = env.step({"action_type": "click", "x": 120, "y": 240}, pause=0)

    assert observation == {"screenshot": b"PNG"}
    assert ["shell", "input", "tap", "120", "240"] == runner.calls[-2][0][-5:]
