"""Focused contracts for exact, on-demand v2 mobile seed plans."""

from __future__ import annotations

import hashlib
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace
import sqlite3
from contextlib import contextmanager

from tools.guitraverse_seed.v2_runtime import (
    _apply_clipper,
    _apply_pro_expense,
    _copy_audio_asset_with_metadata,
    _write_joplin_rows,
    _write_sms_rows,
    _write_osmand_rows,
    _write_audio_recorder_index,
    _write_broccoli_rows,
    apply_seed_plan,
    build_collection_seed_plan,
    build_traversal_seed_plan,
)


MANIFEST = (
    Path(__file__).resolve().parents[1]
    / "data"
    / "dev_seed"
    / "guitraverse_explore_seed_v2.yaml"
)


def test_traversal_plan_selects_only_the_target_app_dataset() -> None:
    """A Broccoli run receives only its declared app dataset."""
    plan = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="broccoli",
    )

    assert plan["base_snapshot"] == "guitraverse_mobile_clean_base_v1"
    assert plan["apps"] == ["broccoli"]
    assert {item["dataset_id"] for item in plan["objects"]} == {"broccoli"}
    assert all(item["seed_id"].startswith("broccoli_") for item in plan["objects"])
    assert plan["objects"][0]["content"] == {
        "title": "Quick salad",
        "description": "A lunch recipe with 3 ingredients.",
        "servings": "2 servings",
        "ingredients": "3 ingredients",
        "directions": "Prepare the lunch recipe and serve.",
        "favorite": 1,
    }
    assert plan["manifest_digest"]
    assert len(plan["digest"]) == 64


def test_seed_plan_freezes_dynamic_timestamps_and_ids_before_apply() -> None:
    first = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="simple_calendar_pro",
        now_ms=1_700_000_000_000,
    )
    second = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="simple_calendar_pro",
        now_ms=1_700_000_000_000,
    )
    task_plan = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="tasks",
        now_ms=1_700_000_000_000,
    )
    expense_plan = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="pro_expense",
        now_ms=1_700_000_000_000,
    )
    sms_plan = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="simple_sms_messenger",
        now_ms=1_700_000_000_000,
    )

    assert first["digest"] == second["digest"]
    assert first["resolved_at_ms"] == 1_700_000_000_000
    assert first["objects"][0]["content"]["start_ts"] == 1_699_358_400
    assert task_plan["objects"][0]["content"] == {
        "list": "routes",
        "remote_id": "588926b1f8c81a27bef78ff06a428f13",
        "created_ms": 1_699_996_400_000,
        "modified_ms": 1_700_000_000_000,
        "completed_ms": 1_699_999_940_000,
        "due_ms": 0,
    }
    assert sms_plan["objects"][0]["content"]["received_ms"] == 1_699_999_999_000
    assert [item["content"] for item in expense_plan["objects"][:3]] == [
        {"category": "transit", "amount_cents": 325, "created_ms": 1_699_913_600_000, "modified_ms": 1_699_913_600_000},
        {"category": "food", "amount_cents": 875, "created_ms": 1_699_999_880_000, "modified_ms": 1_699_999_880_000},
        {"category": "supplies", "amount_cents": 1200, "created_ms": 1_700_259_200_000, "modified_ms": 1_700_259_200_000},
    ]


def test_markor_plan_uses_manifest_natural_file_paths() -> None:
    plan = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="markor",
        now_ms=1_700_000_000_000,
    )

    paths = [item["content"]["path"] for item in plan["objects"]]
    assert paths[0] == "Documents/Markor/inbox/field_notes.md"
    assert all("markor_" not in path for path in paths)
def test_collection_plan_unions_exact_ref_objects_and_scenario_delta() -> None:
    """The instruction fixes the seed set; the model has no expansion channel."""
    plan = build_collection_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        capability_refs=[
            {
                "app_id": "simple_sms",
                "seed_objects": ["simple_sms_ref_01"],
            },
            {
                "app_id": "simple_gallery",
                "seed_objects": ["simple_gallery_ref_01"],
            },
        ],
        scenario_delta={
            "schema": "guitraverse.scenario_delta.v1",
            "task_id": "dining-copy",
            "base_snapshot": "guitraverse_mobile_clean_base_v1",
            "mutations": [{
                "kind": "text_file",
                "path": "Documents/GUITRAVERSE/dinner.txt",
                "content": "Friday 19:00",
            }],
            "assertions": [],
            "digest": "d" * 64,
        },
    )

    assert plan["apps"] == ["simple_gallery", "simple_sms"]
    assert [item["seed_id"] for item in plan["objects"]] == [
        "shared_files_03", "sms_01",
    ]
    assert plan["scenario_delta_digest"] == "d" * 64
    assert plan["scenario_delta"]["mutations"][0]["content"] == "Friday 19:00"


def test_collection_plan_allows_an_authoritative_capability_without_seed_data() -> None:
    plan = build_collection_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        capability_refs=[{"app_id": "broccoli"}],
    )

    assert plan["apps"] == ["broccoli"]
    assert plan["objects"] == []


def test_minimal_no_data_app_is_explicitly_verified_as_a_noop() -> None:
    plan = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="miniwob",
    )

    assert plan["datasets"] == ["miniwob"]

    class _Device:
        def run(self, *args, **_kwargs) -> str:
            assert args == (
                "shell", "pm", "path", "com.google.androidenv.miniwob")
            return "package:/data/app/miniwob.apk"

    report = apply_seed_plan(
        plan,
        _Device(),
        expected_snapshot="guitraverse_mobile_clean_base_v1",
    )

    assert report["dataset_checks"] == [{
        "dataset_id": "miniwob", "ok": True,
    }]


def test_clipper_adapter_passes_the_full_androidworld_environment(monkeypatch) -> None:
    received: list[object] = []
    android_world = ModuleType("android_world")
    env_module = ModuleType("android_world.env")
    adb_utils = ModuleType("android_world.env.adb_utils")
    stored = {"text": ""}

    def set_clipboard_contents(text, env):
        received.append(env)
        stored["text"] = text

    def get_clipboard_contents(env):
        received.append(env)
        return stored["text"]

    adb_utils.set_clipboard_contents = set_clipboard_contents
    adb_utils.get_clipboard_contents = get_clipboard_contents
    env_module.adb_utils = adb_utils
    android_world.env = env_module
    monkeypatch.setitem(sys.modules, "android_world", android_world)
    monkeypatch.setitem(sys.modules, "android_world.env", env_module)
    monkeypatch.setitem(sys.modules, "android_world.env.adb_utils", adb_utils)
    aw_env = SimpleNamespace(controller=object())
    android_env = object()

    result = _apply_clipper(
        [{"seed_id": "clipper_01", "data": {"text": "Field note"}}],
        object(),
        SimpleNamespace(_aw_env=aw_env, _android_env=android_env),
    )

    assert result == [True]
    assert received == [android_env, android_env]


def test_pro_expense_adapter_writes_the_planned_modified_timestamp(monkeypatch) -> None:
    android_world = ModuleType("android_world")
    task_evals = ModuleType("android_world.task_evals")
    utils = ModuleType("android_world.task_evals.utils")
    sqlite_schema_utils = ModuleType(
        "android_world.task_evals.utils.sqlite_schema_utils")
    sqlite_utils = ModuleType("android_world.task_evals.utils.sqlite_utils")
    captured: list[object] = []

    class Expense:
        def __init__(self, **kwargs) -> None:
            self.__dict__.update(kwargs)

    def insert_rows(rows, *_args) -> None:
        captured.extend(rows)

    sqlite_schema_utils.Expense = Expense
    sqlite_utils.delete_all_rows_from_table = lambda *_args: None
    sqlite_utils.insert_rows_to_remote_db = insert_rows
    sqlite_utils.get_rows_from_remote_device = lambda *_args: captured
    utils.sqlite_schema_utils = sqlite_schema_utils
    utils.sqlite_utils = sqlite_utils
    task_evals.utils = utils
    android_world.task_evals = task_evals
    monkeypatch.setitem(sys.modules, "android_world", android_world)
    monkeypatch.setitem(sys.modules, "android_world.task_evals", task_evals)
    monkeypatch.setitem(sys.modules, "android_world.task_evals.utils", utils)
    monkeypatch.setitem(
        sys.modules,
        "android_world.task_evals.utils.sqlite_schema_utils",
        sqlite_schema_utils,
    )
    monkeypatch.setitem(
        sys.modules,
        "android_world.task_evals.utils.sqlite_utils",
        sqlite_utils,
    )
    monkeypatch.setattr(
        "tools.guitraverse_seed.v2_runtime._ensure_database_template",
        lambda *_args: None,
    )

    result = _apply_pro_expense(
        [{
            "display_name": "Today food",
            "content": {
                "amount_cents": 875,
                "category": "food",
                "created_ms": 1_700_000_000_000,
                "modified_ms": 1_700_000_000_000,
            },
        }],
        object(),
        SimpleNamespace(_aw_env=object()),
    )

    assert result == [True]
    assert captured[0].modified_date == 1_700_000_000_000


def test_audio_recorder_index_uses_planned_path_and_microsecond_duration(
    tmp_path: Path,
) -> None:
    database = tmp_path / "records.db"
    sqlite3.connect(database).execute(
        "CREATE TABLE records(name,duration,created,added,path,format,size,"
        "sample_rate,channel_count,bitrate,data,bookmark,waveform_processed,data_str)"
    ).connection.commit()

    class _Controller:
        @contextmanager
        def pull_file(self, _remote, _timeout=None):
            yield str(tmp_path)

        def push_file(self, local, remote, _timeout=None):
            assert Path(local) == database
            assert remote.endswith("records.db")

    _write_audio_recorder_index(
        [{
            "seed_id": "audio_recorder_01",
            "display_name": "Morning memo",
            "content": {
                "path": "Android/data/com.dimowner.audiorecorder/files/Music/records/morning_memo.m4a",
                "duration_db_microseconds": 1_000_000,
                "created_ms": 1_700_000_000_000,
                "added_ms": 1_700_000_001_000,
            },
        }],
        SimpleNamespace(controller=_Controller()),
    )

    row = sqlite3.connect(database).execute(
        "SELECT name,duration,created,added,path,format FROM records"
    ).fetchone()
    assert row == (
        "Morning memo",
        1_000_000,
        1_700_000_000_000,
        1_700_000_001_000,
        "/storage/emulated/0/Android/data/com.dimowner.audiorecorder/files/Music/records/morning_memo.m4a",
        "m4a",
    )


def test_osmand_rows_keep_the_planned_marker_id_when_written(tmp_path: Path) -> None:
    database = tmp_path / "map_markers_db"
    sqlite3.connect(database).execute(
        "CREATE TABLE map_markers(marker_id,marker_lat,marker_lon,marker_description,"
        "marker_active,marker_added,marker_visited,group_name,group_key,marker_color,"
        "marker_next_key,marker_disabled,marker_selected,marker_map_object_name)"
    ).connection.commit()

    class _Controller:
        @contextmanager
        def pull_file(self, _remote):
            yield str(database.parent)

        def push_file(self, local, remote):
            assert Path(local) == database
            assert remote.endswith("map_markers_db")

    objects = [{
        "seed_id": "osmand_01",
        "content": {
            "marker_id": "marker_balzers",
            "latitude": 47.067,
            "longitude": 9.501,
            "serialized_description": "location#Balzers",
            "group_name": "Local markers",
            "group_key": None,
            "marker_next_key": None,
            "marker_added_ms": 1_700_000_000_001,
        },
        "display_name": "Balzers",
    }]

    assert _write_osmand_rows(objects, SimpleNamespace(controller=_Controller())) == [True]
    assert sqlite3.connect(database).execute(
        "SELECT marker_id,group_key FROM map_markers"
    ).fetchone() == ("marker_balzers", None)


def test_broccoli_writer_reads_back_the_exact_planned_row(
    tmp_path: Path, monkeypatch,
) -> None:
    database = tmp_path / "broccoli"
    sqlite3.connect(database).execute(
        "CREATE TABLE recipes(title,imageName,description,servings,preparationTime,"
        "source,ingredients,directions,favorite)"
    ).connection.commit()

    class _Controller:
        @contextmanager
        def pull_file(self, _remote):
            yield str(tmp_path)

        def push_file(self, local, remote):
            assert Path(local) == database
            assert remote.endswith("broccoli")

    monkeypatch.setenv("GUITRAVERSE_FTS_SQLITE_PYTHON", sys.executable)
    rows = _write_broccoli_rows([{
        "title": "Quick salad",
        "description": "A lunch recipe with 3 ingredients.",
        "servings": "2 servings",
        "ingredients": "3 ingredients",
        "directions": "Prepare the lunch recipe and serve.",
        "favorite": 1,
    }], SimpleNamespace(controller=_Controller()))

    assert rows == [{
        "title": "Quick salad",
        "description": "A lunch recipe with 3 ingredients.",
        "servings": "2 servings",
        "ingredients": "3 ingredients",
        "directions": "Prepare the lunch recipe and serve.",
        "favorite": 1,
    }]


def test_joplin_writer_reads_back_planned_notes_and_normalized_rows(
    tmp_path: Path, monkeypatch,
) -> None:
    database = tmp_path / "joplin.sqlite"
    sqlite3.connect(database).executescript("""
        CREATE TABLE folders (id TEXT PRIMARY KEY, title TEXT, created_time INTEGER, updated_time INTEGER, user_created_time INTEGER, user_updated_time INTEGER);
        CREATE TABLE notes (id TEXT PRIMARY KEY, parent_id TEXT, title TEXT, body TEXT, created_time INTEGER, updated_time INTEGER, is_todo INTEGER, todo_completed INTEGER, source TEXT, source_application TEXT, `order` INTEGER, user_created_time INTEGER, user_updated_time INTEGER);
        CREATE TABLE notes_normalized (id TEXT PRIMARY KEY, title TEXT, body TEXT, user_created_time INTEGER, user_updated_time INTEGER, is_todo INTEGER, todo_completed INTEGER, parent_id TEXT, todo_due INTEGER);
    """).connection.commit()

    class _Controller:
        @contextmanager
        def pull_file(self, remote):
            assert remote.endswith("joplin.sqlite")
            yield str(tmp_path)

        def push_file(self, local, remote):
            assert Path(local) == database
            assert remote.endswith("joplin.sqlite")

    monkeypatch.setenv("GUITRAVERSE_FTS_SQLITE_PYTHON", sys.executable)
    observed = _write_joplin_rows([{
        "seed_id": "joplin_01",
        "display_name": "Field note",
        "content": {
            "folder": "Seed Inbox",
            "folder_id": "folder-1",
            "note_id": "note-1",
            "created_ms": 1_700_000_000_000,
            "updated_ms": 1_700_000_001_000,
            "todo": True,
            "todo_completed_ms": 0,
        },
    }], SimpleNamespace(controller=_Controller()))

    assert observed == [{"id": "note-1", "title": "Field note"}]
    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT id,title,body,is_todo,todo_completed,parent_id FROM notes"
    ).fetchone() == (
        "note-1", "Field note", "Field note\n", 1, 0, "folder-1",
    )
    assert connection.execute(
        "SELECT id,title,parent_id,todo_due FROM notes_normalized"
    ).fetchone() == ("note-1", "Field note", "folder-1", 0)


def test_media_asset_copy_retags_only_the_copied_mp3(
    tmp_path: Path, monkeypatch,
) -> None:
    source = tmp_path / "source.mp3"
    destination = tmp_path / "seed.mp3"
    source.write_bytes(b"original-media")
    mutagen = ModuleType("mutagen")
    id3 = ModuleType("mutagen.id3")
    events: list[tuple] = []

    class Tags:
        def delall(self, frame) -> None:
            events.append(("delall", frame))

        def add(self, frame) -> None:
            events.append(("add", frame))

        def save(self, path) -> None:
            events.append(("save", str(path)))

    tags = Tags()
    id3.ID3 = lambda _path: tags
    id3.ID3NoHeaderError = RuntimeError
    id3.TIT2 = lambda **kwargs: ("TIT2", kwargs)
    id3.TPE1 = lambda **kwargs: ("TPE1", kwargs)
    monkeypatch.setitem(sys.modules, "mutagen", mutagen)
    monkeypatch.setitem(sys.modules, "mutagen.id3", id3)

    _copy_audio_asset_with_metadata(
        source, destination, "Morning Walk", "Field Recordings")

    assert source.read_bytes() == b"original-media"
    assert destination.read_bytes() == b"original-media"
    assert events == [
        ("delall", "TIT2"),
        ("delall", "TPE1"),
        ("add", ("TIT2", {"encoding": 3, "text": "Morning Walk"})),
        ("add", ("TPE1", {"encoding": 3, "text": "Field Recordings"})),
        ("save", str(destination)),
    ]


def test_apply_seed_plan_writes_each_sms_object_through_telephony_storage(
    tmp_path: Path, monkeypatch,
) -> None:
    plan = build_collection_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        capability_refs=[{
            "app_id": "simple_sms",
            "seed_objects": ["simple_sms_ref_01"],
        }],
        now_ms=1_700_000_000_000,
    )
    provider_dir = tmp_path / "provider"
    app_dir = tmp_path / "app"
    provider_dir.mkdir()
    app_dir.mkdir()
    database = provider_dir / "mmssms.db"
    connection = sqlite3.connect(database)
    connection.executescript("""
        CREATE TABLE canonical_addresses (_id INTEGER PRIMARY KEY AUTOINCREMENT, address TEXT);
        CREATE TABLE threads (_id INTEGER PRIMARY KEY AUTOINCREMENT, date INTEGER, message_count INTEGER, recipient_ids TEXT, snippet TEXT, snippet_cs INTEGER DEFAULT 0, read INTEGER, archived INTEGER DEFAULT 0, type INTEGER DEFAULT 0, error INTEGER DEFAULT 0, has_attachment INTEGER DEFAULT 0);
        CREATE TABLE sms (_id INTEGER PRIMARY KEY, thread_id INTEGER, address TEXT, date INTEGER, date_sent INTEGER, protocol INTEGER, read INTEGER, status INTEGER, type INTEGER, reply_path_present INTEGER, subject TEXT, body TEXT, service_center TEXT, locked INTEGER, sub_id INTEGER, error_code INTEGER, creator TEXT, seen INTEGER);
        CREATE TABLE words (index_text TEXT, source_id INTEGER, table_to_use INTEGER);
    """)
    connection.commit()
    connection.close()
    application_database = app_dir / "conversations.db"
    connection = sqlite3.connect(application_database)
    connection.executescript("""
        CREATE TABLE conversations (thread_id INTEGER PRIMARY KEY, snippet TEXT, date INTEGER, read INTEGER, title TEXT, photo_uri TEXT, is_group_conversation INTEGER, phone_number TEXT, is_scheduled INTEGER, uses_custom_title INTEGER, archived INTEGER);
        CREATE TABLE messages (id INTEGER PRIMARY KEY, body TEXT, type INTEGER, status INTEGER, participants TEXT, date INTEGER, read INTEGER, thread_id INTEGER, is_mms INTEGER, attachment TEXT, sender_phone_number TEXT, sender_name TEXT, sender_photo_uri TEXT, subscription_id INTEGER, is_scheduled INTEGER);
    """)
    connection.commit()
    connection.close()

    class _Controller:
        @contextmanager
        def pull_file(self, remote):
            if remote.endswith("mmssms.db"):
                yield str(provider_dir)
            elif remote.endswith("conversations.db"):
                yield str(app_dir)
            else:
                raise AssertionError(f"unexpected remote pull: {remote}")

        def push_file(self, local, remote):
            if remote.endswith("mmssms.db"):
                assert Path(local) == database
            elif remote.endswith("conversations.db"):
                assert Path(local) == application_database
            else:
                raise AssertionError(f"unexpected remote push: {remote}")

    class _Device:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(self, *args, **_kwargs) -> str:
            if args[:3] == ("shell", "pm", "path"):
                assert args[-1] == "com.simplemobiletools.smsmessenger"
                return "package:/data/app/sms.apk"
            if args in {
                ("shell", "am", "force-stop", "com.android.providers.telephony"),
                ("shell", "am", "force-stop", "com.simplemobiletools.smsmessenger"),
            }:
                self.calls.append(args)
                return ""
            if args[:5] == (
                "shell", "content", "query", "--uri", "content://sms/inbox"):
                return "Row: address=5550101, body=Trail notes are ready"
            raise AssertionError(f"unexpected device command: {args}")

    monkeypatch.setenv("GUITRAVERSE_FTS_SQLITE_PYTHON", sys.executable)
    device = _Device()

    report = apply_seed_plan(
        plan,
        device,
        expected_snapshot="guitraverse_mobile_clean_base_v1",
        environment=SimpleNamespace(_aw_env=SimpleNamespace(controller=_Controller())),
    )

    assert report["schema"] == "guitraverse.seed_setup.v1"
    assert report["ok"] is True
    assert report["digest"] == plan["digest"]
    assert report["items"] == [{
        "dataset_id": "sms",
        "seed_id": "sms_01",
        "ok": True,
    }]
    assert device.calls == [
        ("shell", "am", "force-stop", "com.android.providers.telephony"),
        ("shell", "am", "force-stop", "com.simplemobiletools.smsmessenger"),
        ("shell", "am", "force-stop", "com.android.providers.telephony"),
        ("shell", "am", "force-stop", "com.simplemobiletools.smsmessenger"),
    ]
    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT address,body,date,type,read,seen FROM sms"
    ).fetchone() == (
        "5550101", "Trail notes are ready", 1_699_999_999_000, 1, 0, 1,
    )
    assert connection.execute(
        "SELECT index_text,table_to_use FROM words"
    ).fetchone() == ("Trail notes are ready", 1)
    connection = sqlite3.connect(application_database)
    assert connection.execute(
        "SELECT thread_id,snippet,date,read,title,phone_number FROM conversations"
    ).fetchone() == (
        1, "Trail notes are ready", 1_699_999_999, 0, "5550101", "5550101",
    )
    assert connection.execute(
        "SELECT id,body,type,status,date,thread_id,is_mms,sender_phone_number,sender_name FROM messages"
    ).fetchone() == (
        1, "Trail notes are ready", 1, -1, 1_699_999_999, 1, 0,
        "5550101", "5550101",
    )


def test_apply_seed_plan_uses_the_registered_app_dataset_adapter() -> None:
    plan = build_traversal_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        app_id="broccoli",
    )
    received: list[dict] = []

    report = apply_seed_plan(
        plan,
        object(),
        expected_snapshot="guitraverse_mobile_clean_base_v1",
        dataset_adapters={
            "broccoli": lambda objects, _device, _environment: (
                received.extend(objects) or [True] * len(objects)
            ),
        },
    )

    assert len(received) == 10
    assert received[0]["content"]["title"] == "Quick salad"
    assert report["ok"] is True
    assert {item["dataset_id"] for item in report["items"]} == {"broccoli"}


class _FileDevice:
    def __init__(self) -> None:
        self.files: dict[str, bytes] = {}

    def push(self, local: Path, remote: str) -> str:
        self.files[remote] = Path(local).read_bytes()
        return ""

    def run(self, *args, **_kwargs) -> str:
        if args[:3] == ("shell", "pm", "path"):
            return "package:/data/app/app.apk"
        if args[:2] == ("shell", "mkdir") or args[:3] == (
                "shell", "am", "broadcast"):
            return ""
        if args[:2] == ("shell", "sha256sum"):
            content = self.files[args[2]]
            return f"{hashlib.sha256(content).hexdigest()}  {args[2]}"
        raise AssertionError(f"unexpected device command: {args}")


def test_apply_seed_plan_pushes_and_hash_reads_back_gallery_media() -> None:
    plan = build_collection_seed_plan(
        MANIFEST,
        base_snapshot="guitraverse_mobile_clean_base_v1",
        capability_refs=[{
            "app_id": "simple_gallery",
            "seed_objects": ["simple_gallery_ref_01"],
        }],
    )

    report = apply_seed_plan(
        plan,
        _FileDevice(),
        expected_snapshot="guitraverse_mobile_clean_base_v1",
    )

    assert report["ok"] is True
    assert report["items"] == [{
        "dataset_id": "shared_files",
        "seed_id": "shared_files_03",
        "ok": True,
    }]
