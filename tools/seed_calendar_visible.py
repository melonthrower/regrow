"""Add CURRENT-month (June/July 2026) calendar events to Simple Calendar Pro so
they're visible in the default view (android_world's add_random_events puts them
in Oct 2023, which the current-month view never shows).

Usage:  python tools/seed_calendar_visible.py <console_port> <grpc_port>
"""
import datetime
import os
import sys

console = int(sys.argv[1]) if len(sys.argv) > 1 else 5590
grpc = int(sys.argv[2]) if len(sys.argv) > 2 else 8590
adb_path = os.path.expanduser("~/android-sdk/platform-tools/adb")

from android_env import loader
from android_env.components import config_classes
from android_world.env import android_world_controller
from android_world.env import interface

config = config_classes.AndroidEnvConfig(
    task=config_classes.FilesystemTaskConfig(
        path=android_world_controller._write_default_task_proto()),
    simulator=config_classes.EmulatorConfig(
        emulator_launcher=config_classes.EmulatorLauncherConfig(
            emulator_console_port=console, adb_port=console + 1, grpc_port=grpc),
        adb_controller=config_classes.AdbControllerConfig(adb_path=adb_path)),
)
aw = android_world_controller.AndroidWorldController(
    loader.load(config), install_a11y_forwarding_app=False)
env = interface.AsyncAndroidEnv(aw)
print("env attached.")

from android_world.task_evals.utils import sqlite_schema_utils as ss
from android_world.task_evals.single.calendar import calendar_utils


def ts(mo, d, h, mi=0):
    return int(datetime.datetime(2026, mo, d, h, mi,
                                 tzinfo=datetime.timezone.utc).timestamp())


# clear the Oct-2023 random noise (and any prior run) so the calendar is a clean,
# findable set on TODAY (2026-06-29) + the coming week.
calendar_utils.clear_calendar_db(env)
print("cleared existing calendar events")

events = [
    ss.CalendarEvent(start_ts=ts(6, 29, 12, 30), end_ts=ts(6, 29, 13, 30),
                     title="Lunch with Sarah", location="Cafe Nero"),
    ss.CalendarEvent(start_ts=ts(6, 29, 16, 0), end_ts=ts(6, 29, 16, 30),
                     title="Call with the bank"),
    ss.CalendarEvent(start_ts=ts(6, 30, 10), end_ts=ts(6, 30, 11),
                     title="Team standup", location="Room 2A"),
    ss.CalendarEvent(start_ts=ts(6, 30, 18), end_ts=ts(6, 30, 19),
                     title="Gym session"),
    ss.CalendarEvent(start_ts=ts(7, 1, 14), end_ts=ts(7, 1, 15),
                     title="Dentist appointment"),
    ss.CalendarEvent(start_ts=ts(7, 2, 20), end_ts=ts(7, 2, 22),
                     title="Movie night with friends"),
    ss.CalendarEvent(start_ts=ts(7, 3, 17), end_ts=ts(7, 3, 18),
                     title="Project deadline"),
    ss.CalendarEvent(start_ts=ts(7, 4, 11), end_ts=ts(7, 4, 12),
                     title="Coffee with Mark"),
    ss.CalendarEvent(start_ts=ts(7, 5, 19), end_ts=ts(7, 5, 21),
                     title="Family dinner"),
    ss.CalendarEvent(start_ts=ts(7, 6, 15), end_ts=ts(7, 6, 16),
                     title="Quarterly review", location="Conference Room"),
]
calendar_utils.add_events(events, env)
print(f"added {len(events)} events across today (6/29) -> next week (7/6)")
