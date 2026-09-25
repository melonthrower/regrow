"""Offline order contract for data-preserving traversal recovery."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from gui_rewalk.src.core import app_lifecycle


def main() -> int:
    events = []
    originals = {
        name: getattr(app_lifecycle, name)
        for name in (
            "_get_process_name", "_kill_app", "launch_app", "wait_for_app",
            "_maximize_app_window",
        )
    }
    original_sleep = app_lifecycle.time.sleep
    try:
        app_lifecycle._get_process_name = lambda app: f"proc:{app}"
        app_lifecycle._kill_app = lambda _env, process: events.append(("kill", process))
        app_lifecycle.launch_app = lambda _env, app, appear_check=None: events.append(
            ("launch", app, appear_check))
        app_lifecycle.wait_for_app = lambda _env, app, appear_check=None: (
            events.append(("wait", app, appear_check)) or True)
        app_lifecycle._maximize_app_window = lambda _env, app: events.append(
            ("maximize", app))
        app_lifecycle.time.sleep = lambda seconds: events.append(("sleep", seconds))

        marker = object()
        ready = app_lifecycle.restart_app_preserving_data(
            object(), "clock", appear_check=marker)
    finally:
        for name, value in originals.items():
            setattr(app_lifecycle, name, value)
        app_lifecycle.time.sleep = original_sleep

    assert ready is True
    assert [event[0] for event in events] == [
        "kill", "sleep", "launch", "wait", "maximize"
    ]
    assert events[0][1] == "proc:clock"
    assert events[2][2] is marker and events[3][2] is marker
    print("PASS data-preserving app restart keeps prerequisite resources")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
