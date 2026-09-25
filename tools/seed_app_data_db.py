"""DB-tier seeding (Simple Calendar Pro events, Tasks) via android_world's SQLite
round-trip helpers. Run AFTER the app has been launched once (so its DB exists).

Usage:  python tools/seed_app_data_db.py <console_port> <grpc_port>
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

ok, fail = [], []


def safe(label, fn):
    try:
        fn()
        ok.append(label)
        print("  OK   " + label)
    except Exception as e:  # noqa: BLE001
        fail.append(label)
        print("  FAIL " + label + " :: " + repr(e)[:160])


# ── Simple Calendar Pro — random events (built-in generator) ─────────────────
import uuid

SEED_CALENDAR = os.environ.get("SEED_CALENDAR") == "1"  # off by default (already seeded)


def seed_calendar():
    from android_world.task_evals.single.calendar import calendar_utils
    calendar_utils.add_random_events(env, n=15)


if SEED_CALENDAR:
    safe("calendar:15 events", seed_calendar)

# ── Tasks (org.tasks) — a handful of realistic to-dos ────────────────────────
def seed_tasks():
    from android_world.task_evals.information_retrieval import task_app_utils
    from android_world.task_evals.utils import sqlite_schema_utils as ss
    titles = ["Buy groceries", "Call the dentist", "Finish quarterly report",
              "Water the plants", "Pay the rent", "Book flights for the trip",
              "Reply to Alex's email", "Renew gym membership"]
    rows = [ss.Task(title=t, remoteId=str(uuid.uuid4().int)) for t in titles]
    task_app_utils.add_tasks(rows, env)


safe("tasks:8 todos", seed_tasks)

print(f"\nDONE  seeded={len(ok)}  failed={len(fail)}")
if fail:
    print("failed: " + ", ".join(fail))
