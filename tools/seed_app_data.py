"""Seed in-app user data using android_world's OWN data-generation utilities,
against an ALREADY-RUNNING (writable) emulator.

Reuses the exact env-attach block our AndroidGUIGenEnv uses (android_env loader →
AndroidWorldController → AsyncAndroidEnv — it ATTACHES to the running emulator,
does not launch a new one), then calls android_world's user_data_generation so
the data lands exactly where each app reads it (Simple Gallery ← DCIM, Markor ←
Documents/Markor, Retro Music ← Music). This is the file/media tier, which is
robust (pure adb push under the hood); provider/DB apps (contacts/sms/calendar/
tasks/expense) are a separate, finickier tier and are NOT done here.

Usage:  python tools/seed_app_data.py <console_port> <grpc_port>
Run on the server with the guiwalk-android python (protos compiled there).
"""
import os
import sys

console = int(sys.argv[1]) if len(sys.argv) > 1 else 5590
grpc = int(sys.argv[2]) if len(sys.argv) > 2 else 8590
adb_path = os.path.expanduser("~/android-sdk/platform-tools/adb")

from android_env import loader
from android_env.components import config_classes
from android_world.env import android_world_controller
from android_world.env import interface

print(f"attaching android_world env to emulator console={console} grpc={grpc} ...")
config = config_classes.AndroidEnvConfig(
    task=config_classes.FilesystemTaskConfig(
        path=android_world_controller._write_default_task_proto()),
    simulator=config_classes.EmulatorConfig(
        emulator_launcher=config_classes.EmulatorLauncherConfig(
            emulator_console_port=console, adb_port=console + 1, grpc_port=grpc),
        adb_controller=config_classes.AdbControllerConfig(adb_path=adb_path)),
)
env_instance = loader.load(config)
aw = android_world_controller.AndroidWorldController(
    env_instance, install_a11y_forwarding_app=False)
env = interface.AsyncAndroidEnv(aw)
print("env attached.")

from android_world.task_evals.utils import user_data_generation as udg
from android_world.env import device_constants as dc
from android_world.utils import file_utils as fu

ok, fail = [], []


def safe(label, fn):
    try:
        fn()
        ok.append(label)
        print("  OK   " + label)
    except Exception as e:  # noqa: BLE001
        fail.append(label)
        print("  FAIL " + label + " :: " + repr(e)[:140])


# ── Simple Gallery (reads DCIM) — labelled jpgs ──────────────────────────────
GALLERY = [("Beach holiday with friends", "beach_holiday.jpg"),
           ("Birthday celebration", "birthday_party.jpg"),
           ("Mountain hiking trip", "mountain_hike.jpg"),
           ("City skyline at night", "city_night.jpg")]
for txt, name in GALLERY:
    safe("gallery:" + name, lambda t=txt, n=name: udg.write_to_gallery(t, n, env))

# ── Markor (reads Documents/Markor) — markdown notes ─────────────────────────
NOTES = [("# Shopping List\n\n- Milk\n- Eggs\n- Bread\n- Coffee", "shopping_list.md"),
         ("# Meeting Notes\n\nQ3 roadmap, hiring, budget review.", "meeting_notes.md"),
         ("# Project Ideas\n\n1. Habit tracker\n2. Recipe app\n3. Expense splitter", "ideas.md"),
         ("# Travel Plan\n\nFlights Fri, hotel booked, pack light.", "travel_plan.md")]
for data, name in NOTES:
    safe("markor:" + name, lambda d=data, n=name: udg.write_to_markor(d, n, env))

# ── Retro Music (reads Music) — tiny tagged mp3s (pydub; skipped if unavailable)
TRACKS = [("The Quartet", "Morning Light"), ("Echo Valley", "Open Road"),
          ("Blue Harbor", "Slow Tide"), ("Night Owls", "City Lights")]
for artist, title in TRACKS:
    remote = fu.convert_to_posix_path(dc.MUSIC_DATA, f"{title}.mp3")
    safe("music:" + title,
         lambda a=artist, t=title, r=remote: udg.write_mp3_file_to_device(
             r, env, artist=a, title=t, duration_milliseconds=2000))

print(f"\nDONE  seeded={len(ok)}  failed={len(fail)}")
if fail:
    print("failed: " + ", ".join(fail))
