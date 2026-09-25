"""Exact, on-demand selections from the frozen v2 seed inventory.

This module deliberately plans *which* declared records belong to one run.  It
does not turn capability text into new data, nor does it treat the historical
full v2 development snapshot as a runtime input.
"""

from __future__ import annotations

import hashlib
import json
import os
import sqlite3
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import time
from typing import Any, Mapping, Sequence

from .contracts import TraversalSeedDataset, TraversalSeedObject
from .manifest_v2 import load_v2_manifest
from .runtime_apps import dataset_id_for_runtime_app


SEED_PLAN_SCHEMA = "guitraverse.seed_plan.v1"
_NO_OBJECT_DATASETS = frozenset({
    "miniwob", "simple_gallery", "simple_sms", "vlc", "retro_music",
})


def build_traversal_seed_plan(
    manifest_path: str | Path,
    *,
    base_snapshot: str,
    app_id: str,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Select one app's declared traversal dataset and required shared data."""
    profile, digest = _profile_and_digest(manifest_path)
    dataset_id = dataset_id_for_runtime_app(app_id)
    selected = _select_traversal_objects(profile, dataset_id)
    return _make_plan(
        base_snapshot=base_snapshot,
        manifest_digest=digest,
        apps=[app_id],
        datasets=[dataset_id],
        objects=selected,
        scenario_delta=None,
        resolved_at_ms=_resolved_time_ms(now_ms),
    )


def build_collection_seed_plan(
    manifest_path: str | Path,
    *,
    base_snapshot: str,
    capability_refs: Sequence[Mapping[str, Any]],
    scenario_delta: Any = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Select only the object IDs explicitly declared by instruction refs.

    A capability may carry ``seed_objects`` in its immutable authority record.
    The runner copies that list into the hydrated ref; neither this function nor
    a model may infer extra records from capability wording.
    """
    profile, digest = _profile_and_digest(manifest_path)
    selected: dict[str, tuple[str, TraversalSeedObject]] = {}
    apps: set[str] = set()
    datasets: set[str] = set()
    for index, ref in enumerate(capability_refs):
        if not isinstance(ref, Mapping):
            raise ValueError(f"capability_refs[{index}] must be an object")
        app_id = _required_text(ref.get("app_id"), f"capability_refs[{index}].app_id")
        apps.add(app_id)
        dataset_id = dataset_id_for_runtime_app(app_id)
        datasets.add(dataset_id)
        object_ids = ref.get("seed_objects")
        if object_ids is None:
            continue
        if not isinstance(object_ids, list) or not object_ids:
            raise ValueError(
                f"capability_refs[{index}] must declare non-empty seed_objects")
        for raw_seed_id in object_ids:
            seed_id = _required_text(raw_seed_id, "seed_objects entry")
            object_dataset_id, obj = _object_for_app(
                profile, dataset_id, seed_id)
            selected[obj.seed_id] = (object_dataset_id, obj)
    delta_payload = _scenario_payload(scenario_delta)
    return _make_plan(
        base_snapshot=base_snapshot,
        manifest_digest=digest,
        apps=sorted(apps),
        datasets=sorted(datasets),
        objects=list(selected.values()),
        scenario_delta=delta_payload,
        resolved_at_ms=_resolved_time_ms(now_ms),
    )


def write_seed_plan(path: str | Path, plan: Mapping[str, Any]) -> Path:
    """Persist a self-digested plan for environment provenance."""
    validated = _validate_plan(plan)
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(validated, ensure_ascii=False, sort_keys=True, indent=2),
        encoding="utf-8",
    )
    temporary.replace(output)
    return output


def load_seed_plan(path: str | Path) -> dict[str, Any]:
    """Load a plan only when its content still matches its declared digest."""
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"unable to load seed plan: {exc}") from exc
    if not isinstance(value, Mapping):
        raise ValueError("seed plan root must be an object")
    return _validate_plan(value)


def apply_seed_plan(
    plan: Mapping[str, Any],
    device: Any,
    *,
    expected_snapshot: str,
    environment: Any = None,
    dataset_adapters: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Apply declared records and read them back before any GUI runtime starts.

    A dataset without a registered adapter is a hard setup failure rather than
    permission to fall back to the old full snapshot.
    """
    validated = _validate_plan(plan)
    if validated["base_snapshot"] != expected_snapshot:
        raise ValueError("seed plan base_snapshot does not match the live snapshot")
    adapters = _default_dataset_adapters()
    adapters.update(dict(dataset_adapters or {}))
    grouped: dict[str, list[dict[str, Any]]] = {
        dataset_id: [] for dataset_id in validated["datasets"]
    }
    for item in validated["objects"]:
        grouped.setdefault(item["dataset_id"], []).append(item)
    items = []
    dataset_checks = []
    for dataset_id, objects in grouped.items():
        if not objects and dataset_id not in _NO_OBJECT_DATASETS:
            dataset_checks.append({"dataset_id": dataset_id, "ok": True})
            continue
        adapter = adapters.get(dataset_id)
        if adapter is None:
            raise ValueError(
                f"no on-demand injector is registered for dataset {dataset_id!r}")
        outcomes = list(adapter(objects, device, environment))
        if len(outcomes) != len(objects) or not all(isinstance(value, bool) for value in outcomes):
            raise ValueError(f"{dataset_id!r} injector must return one boolean per object")
        dataset_checks.append({
            "dataset_id": dataset_id,
            "ok": all(outcomes) if objects else True,
        })
        items.extend({
            "dataset_id": item["dataset_id"],
            "seed_id": item["seed_id"],
            "ok": ok,
        } for item, ok in zip(objects, outcomes))
    return {
        "schema": "guitraverse.seed_setup.v1",
        "base_snapshot": validated["base_snapshot"],
        "manifest_digest": validated["manifest_digest"],
        "digest": validated["digest"],
        "ok": all(item["ok"] for item in items) and all(
            item["ok"] for item in dataset_checks),
        "items": items,
        "dataset_checks": dataset_checks,
    }


def _profile_and_digest(path: str | Path) -> tuple[Any, str]:
    manifest = Path(path).expanduser().resolve()
    if not manifest.is_file():
        raise ValueError(f"v2 manifest does not exist: {manifest}")
    return load_v2_manifest(manifest), hashlib.sha256(manifest.read_bytes()).hexdigest()


def _select_traversal_objects(
    profile: Any, dataset_id: str,
) -> list[tuple[str, TraversalSeedObject]]:
    apps = _datasets(profile.app_datasets)
    if dataset_id not in apps:
        raise ValueError(f"v2 manifest has no traversal dataset for {dataset_id!r}")
    dataset = apps[dataset_id]
    if not dataset.reference_only:
        return [(dataset.dataset_id, item) for item in dataset.objects]
    return [
        _resolve_reference(profile, dataset, item)
        for item in dataset.objects
    ]


def _object_for_app(
    profile: Any,
    dataset_id: str,
    seed_id: str,
) -> tuple[str, TraversalSeedObject]:
    apps = _datasets(profile.app_datasets)
    if dataset_id not in apps:
        raise ValueError(f"v2 manifest has no dataset for {dataset_id!r}")
    dataset = apps[dataset_id]
    ref_dataset, ref_object = _find_object(dataset, seed_id)
    if not dataset.reference_only:
        return ref_dataset.dataset_id, ref_object
    resolved_dataset, resolved_object = _resolve_reference(profile, dataset, ref_object)
    return resolved_dataset, resolved_object


def _resolve_reference(
    profile: Any,
    dataset: TraversalSeedDataset,
    reference: TraversalSeedObject,
) -> tuple[str, TraversalSeedObject]:
    target_id = _plain(dict(reference.data).get("shared_seed_id"))
    if not isinstance(target_id, str):
        raise ValueError(f"{dataset.dataset_id} reference has no shared_seed_id")
    for shared in profile.shared_datasets:
        for item in shared.objects:
            if item.seed_id == target_id:
                return shared.dataset_id, item
    raise ValueError(f"{dataset.dataset_id} reference targets unknown {target_id!r}")


def _find_object(
    dataset: TraversalSeedDataset,
    seed_id: str,
) -> tuple[TraversalSeedDataset, TraversalSeedObject]:
    for item in dataset.objects:
        if item.seed_id == seed_id:
            return dataset, item
    raise ValueError(f"{seed_id!r} is not declared for dataset {dataset.dataset_id!r}")


def _datasets(values: Sequence[TraversalSeedDataset]) -> dict[str, TraversalSeedDataset]:
    return {item.dataset_id: item for item in values}


def _make_plan(
    *,
    base_snapshot: str,
    manifest_digest: str,
    apps: Sequence[str],
    datasets: Sequence[str],
    objects: Sequence[tuple[str, TraversalSeedObject]],
    scenario_delta: Mapping[str, Any] | None,
    resolved_at_ms: int,
) -> dict[str, Any]:
    snapshot = _required_text(base_snapshot, "base_snapshot")
    entries = [
        {
            "dataset_id": dataset_id,
            "seed_id": item.seed_id,
            "display_name": item.display_name,
            "shape_tags": list(item.shape_tags),
            "data": _plain(dict(item.data)),
            "content": _concrete_content(
                dataset_id, item, resolved_at_ms, index),
        }
        for index, (dataset_id, item) in enumerate(objects, 1)
    ]
    entries.sort(key=lambda item: (item["dataset_id"], item["seed_id"]))
    payload: dict[str, Any] = {
        "schema": SEED_PLAN_SCHEMA,
        "base_snapshot": snapshot,
        "manifest_digest": manifest_digest,
        "apps": sorted(set(apps)),
        "datasets": sorted(set(datasets)),
        "resolved_at_ms": resolved_at_ms,
        "objects": entries,
        "scenario_delta_digest": (
            str(scenario_delta["digest"]) if scenario_delta is not None else ""
        ),
        "scenario_delta": scenario_delta,
    }
    payload["digest"] = _digest(payload)
    return payload


def _scenario_payload(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        payload = dict(value)
    else:
        payload = {
            "schema": getattr(value, "schema", ""),
            "task_id": getattr(value, "task_id", ""),
            "base_snapshot": getattr(value, "base_snapshot", ""),
            "mutations": [vars(item) for item in getattr(value, "mutations", ())],
            "assertions": [vars(item) for item in getattr(value, "assertions", ())],
            "digest": getattr(value, "digest", ""),
        }
    digest = payload.get("digest")
    if not isinstance(digest, str) or len(digest) != 64:
        raise ValueError("scenario delta must carry a 64-character digest")
    return _plain(payload)


def _validate_plan(value: Mapping[str, Any]) -> dict[str, Any]:
    plan = _plain(dict(value))
    expected_fields = {
        "schema", "base_snapshot", "manifest_digest", "apps", "objects",
        "datasets", "resolved_at_ms", "scenario_delta_digest", "scenario_delta", "digest",
    }
    if set(plan) != expected_fields:
        raise ValueError("seed plan fields must match schema v1 exactly")
    if plan["schema"] != SEED_PLAN_SCHEMA:
        raise ValueError("unsupported seed plan schema")
    _required_text(plan["base_snapshot"], "base_snapshot")
    if (
        not isinstance(plan["resolved_at_ms"], int)
        or isinstance(plan["resolved_at_ms"], bool)
        or plan["resolved_at_ms"] < 0
    ):
        raise ValueError("seed plan resolved_at_ms must be a non-negative integer")
    if (
        not isinstance(plan["datasets"], list)
        or not plan["datasets"]
        or any(not isinstance(item, str) or not item for item in plan["datasets"])
        or len(set(plan["datasets"])) != len(plan["datasets"])
    ):
        raise ValueError("seed plan datasets must be a unique non-empty string list")
    for field in ("manifest_digest", "digest"):
        if not isinstance(plan[field], str) or len(plan[field]) != 64:
            raise ValueError(f"seed plan {field} must be a SHA-256 digest")
    if _digest({key: value for key, value in plan.items() if key != "digest"}) != plan["digest"]:
        raise ValueError("seed plan digest mismatch")
    return plan


def _digest(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def _plain(value: Any) -> Any:
    if isinstance(value, tuple):
        if all(isinstance(item, tuple) and len(item) == 2 and isinstance(item[0], str) for item in value):
            return {key: _plain(item) for key, item in value}
        return [_plain(item) for item in value]
    if isinstance(value, list):
        return [_plain(item) for item in value]
    if isinstance(value, Mapping):
        return {str(key): _plain(item) for key, item in value.items()}
    return value


def _required_text(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be non-empty text")
    return value.strip()


def _concrete_content(
    dataset_id: str,
    item: TraversalSeedObject,
    resolved_at_ms: int,
    index: int,
) -> dict[str, Any]:
    data = _plain(dict(item.data))
    if dataset_id == "shared_files":
        content = dict(data)
        kind = _required_text(content.get("kind"), f"{item.seed_id}.kind")
        if kind == "text":
            content["text"] = item.display_name + "\n"
        elif kind in {"pdf", "image", "video"}:
            content["label"] = item.display_name
        return content
    if dataset_id != "broccoli":
        return _resolved_dataset_content(
            dataset_id, item, data, resolved_at_ms, index)
    category = _required_text(data.get("category"), f"{item.seed_id}.category")
    ingredient_count = data.get("ingredients")
    if not isinstance(ingredient_count, int) or ingredient_count < 1:
        raise ValueError(f"{item.seed_id}.ingredients must be a positive integer")
    return {
        "title": item.display_name,
        "description": f"A {category} recipe with {ingredient_count} ingredients.",
        "servings": "2 servings",
        "ingredients": f"{ingredient_count} ingredients",
        "directions": f"Prepare the {category} recipe and serve.",
        "favorite": int("favorite" in item.shape_tags),
    }


def _resolved_dataset_content(
    dataset_id: str,
    item: TraversalSeedObject,
    data: dict[str, Any],
    resolved_at_ms: int,
    index: int,
) -> dict[str, Any]:
    content = dict(data)
    stable_id = hashlib.md5(
        f"guitraverse.seedplan.v1:{item.seed_id}".encode("utf-8"),
        usedforsecurity=False,
    ).hexdigest()
    if dataset_id == "simple_calendar":
        relative_day = content.get("relative_day", 0)
        if not isinstance(relative_day, int):
            raise ValueError(f"{item.seed_id}.relative_day must be an integer")
        base_day = (resolved_at_ms // 86_400_000) * 86_400
        content["start_ts"] = base_day + relative_day * 86400 + 43200
        content["end_ts"] = content["start_ts"] + 3600
    elif dataset_id == "tasks_org":
        shapes = set(item.shape_tags)
        content.update({
            "remote_id": stable_id,
            "created_ms": resolved_at_ms - index * 3_600_000,
            "modified_ms": resolved_at_ms,
            "completed_ms": resolved_at_ms - index * 60_000 if "complete" in shapes else 0,
            "due_ms": resolved_at_ms + index * 86_400_000 if "future" in shapes else 0,
        })
    elif dataset_id == "audio_recorder":
        content.update({
            "created_ms": resolved_at_ms - index * 60_000,
            "added_ms": resolved_at_ms - index * 1_000,
        })
    elif dataset_id == "sms":
        content["received_ms"] = resolved_at_ms - index * 1_000
    elif dataset_id == "pro_expense":
        shapes = set(item.shape_tags)
        if "future" in shapes:
            timestamp_ms = resolved_at_ms + index * 86_400_000
        elif "today" in shapes:
            timestamp_ms = resolved_at_ms - index * 60_000
        else:
            timestamp_ms = resolved_at_ms - index * 86_400_000
        content.update({
            "created_ms": timestamp_ms,
            "modified_ms": timestamp_ms,
        })
    elif dataset_id == "osmand":
        content["marker_added_ms"] = resolved_at_ms + index
    elif dataset_id == "open_tracks":
        duration_ms = int(content["duration_minutes"]) * 60_000
        stop_ms = resolved_at_ms - index * 86_400_000
        content.update({
            "start_ms": stop_ms - duration_ms,
            "stop_ms": stop_ms,
            "uuid_hex": stable_id,
        })
    elif dataset_id == "joplin":
        folder = _required_text(content.get("folder"), f"{item.seed_id}.folder")
        content.update({
            "note_id": stable_id,
            "folder_id": hashlib.md5(
                f"guitraverse.seedplan.v1:folder:{folder}".encode("utf-8"),
                usedforsecurity=False,
            ).hexdigest(),
            "created_ms": resolved_at_ms - index * 1_000,
            "updated_ms": resolved_at_ms,
            "todo_completed_ms": resolved_at_ms if "complete" in item.shape_tags else 0,
        })
    return content


def _resolved_time_ms(value: int | None) -> int:
    if value is None:
        return int(time.time() * 1000)
    if not isinstance(value, int) or isinstance(value, bool) or value < 0:
        raise ValueError("now_ms must be a non-negative integer")
    return value


def _apply_sms(
    objects: Sequence[Mapping[str, Any]], device: Any, environment: Any,
) -> list[bool]:
    return _write_sms_rows(objects, device, _require_androidworld(environment, "sms"))


def _write_sms_rows(
    objects: Sequence[Mapping[str, Any]], device: Any, aw_env: Any,
) -> list[bool]:
    """Write plan-fixed incoming SMS rows through TelephonyProvider storage."""
    remote_db = "/data/user/0/com.android.providers.telephony/databases/mmssms.db"
    remote_cache = (
        "/data/data/com.simplemobiletools.smsmessenger/databases/conversations.db")
    rows = []
    for item in objects:
        content = item["content"]
        received_ms = content.get("received_ms")
        if not isinstance(received_ms, int) or isinstance(received_ms, bool):
            raise ValueError(f"{item['seed_id']}.received_ms must be an integer")
        rows.append({
            "sender": _required_text(content.get("sender"), f"{item['seed_id']}.sender"),
            "body": _required_text(content.get("body"), f"{item['seed_id']}.body"),
            "received_ms": received_ms,
        })
    device.run(
        "shell", "am", "force-stop", "com.android.providers.telephony",
        timeout=30, check=True,
    )
    device.run(
        "shell", "am", "force-stop", "com.simplemobiletools.smsmessenger",
        timeout=30, check=True,
    )
    with aw_env.controller.pull_file(remote_db) as directory:
        local_db = Path(directory) / "mmssms.db"
        payload = Path(directory) / "seed_sms_rows.json"
        payload.write_text(json.dumps(rows, ensure_ascii=False), encoding="utf-8")
        with aw_env.controller.pull_file(remote_cache) as cache_directory:
            local_cache = Path(cache_directory) / "conversations.db"
            script = (
                "import json, sqlite3, sys\n"
                "db, cache_db, payload = sys.argv[1:4]\n"
                "rows = json.load(open(payload, encoding='utf-8'))\n"
                "conn = sqlite3.connect(db)\n"
                "cache = sqlite3.connect(cache_db)\n"
                "result = []\n"
                "for row in rows:\n"
                "  existing = conn.execute('SELECT _id,thread_id FROM sms WHERE address=? AND body=? ORDER BY _id LIMIT 1', (row['sender'], row['body'])).fetchone()\n"
                "  if existing is None:\n"
                "    address = conn.execute('SELECT _id FROM canonical_addresses WHERE address=?', (row['sender'],)).fetchone()\n"
                "    address_id = address[0] if address else conn.execute('INSERT INTO canonical_addresses(address) VALUES (?)', (row['sender'],)).lastrowid\n"
                "    recipient_ids = str(address_id)\n"
                "    thread = conn.execute('SELECT _id FROM threads WHERE recipient_ids=?', (recipient_ids,)).fetchone()\n"
                "    thread_id = thread[0] if thread else conn.execute('INSERT INTO threads(date,message_count,recipient_ids,read) VALUES (?,0,?,1)', (row['received_ms'], recipient_ids)).lastrowid\n"
                "    message_id = conn.execute('INSERT INTO sms(thread_id,address,date,date_sent,protocol,read,status,type,reply_path_present,body,locked,sub_id,error_code,creator,seen) VALUES (?,?,?,?,0,0,-1,1,0,?,0,1,0,?,1)', (thread_id,row['sender'],row['received_ms'],row['received_ms'],row['body'],'com.simplemobiletools.smsmessenger')).lastrowid\n"
                "    conn.execute('INSERT INTO words(index_text,source_id,table_to_use) VALUES (?,?,1)', (row['body'], message_id))\n"
                "  else:\n"
                "    message_id, thread_id = existing\n"
                "  received_s = row['received_ms'] // 1000\n"
                "  participant = {'anniversaries': [], 'birthdays': [], 'contactId': 0, 'name': row['sender'], 'phoneNumbers': [{'isPrimary': False, 'label': '', 'normalizedNumber': row['sender'], 'type': 0, 'value': row['sender']}], 'photoUri': '', 'rawId': 0}\n"
                "  participants = json.dumps([participant], ensure_ascii=False, separators=(',', ':'))\n"
                "  cache.execute('INSERT OR REPLACE INTO conversations(thread_id,snippet,date,read,title,photo_uri,is_group_conversation,phone_number,is_scheduled,uses_custom_title,archived) VALUES (?,?,?,?,?,?,?,?,?,?,?)', (thread_id,row['body'],received_s,0,row['sender'],'',0,row['sender'],0,0,0))\n"
                "  cache.execute('INSERT OR REPLACE INTO messages(id,body,type,status,participants,date,read,thread_id,is_mms,attachment,sender_phone_number,sender_name,sender_photo_uri,subscription_id,is_scheduled) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)', (message_id,row['body'],1,-1,participants,received_s,0,thread_id,0,'null',row['sender'],row['sender'],'',1,0))\n"
                "  result.append({'sender':row['sender'],'body':row['body'],'message_id':message_id,'thread_id':thread_id})\n"
                "conn.commit()\n"
                "cache.commit()\n"
                "conn.close()\n"
                "cache.close()\n"
                "print(json.dumps(result, ensure_ascii=False))\n"
            )
            completed = subprocess.run(
                [_fts_sqlite_runner(), "-c", script, str(local_db), str(local_cache), str(payload)],
                capture_output=True,
                text=True,
                check=False,
            )
            if completed.returncode != 0:
                raise ValueError(
                    "SMS SQLite patch failed: "
                    + ((completed.stderr or completed.stdout).strip()[:500]))
            try:
                observed = json.loads(completed.stdout)
            except json.JSONDecodeError as exc:
                raise ValueError("SMS SQLite runner returned invalid readback") from exc
            if not isinstance(observed, list) or len(observed) != len(rows):
                raise ValueError("SMS SQLite runner returned incomplete readback")
            aw_env.controller.push_file(local_db, remote_db)
            aw_env.controller.push_file(local_cache, remote_cache)
    device.run(
        "shell", "am", "force-stop", "com.android.providers.telephony",
        timeout=30, check=True,
    )
    device.run(
        "shell", "am", "force-stop", "com.simplemobiletools.smsmessenger",
        timeout=30, check=True,
    )
    live_readback = device.run(
        "shell", "content", "query", "--uri", "content://sms/inbox",
        "--projection", "address:body", timeout=30, check=True,
    )
    return [
        _sms_row_contains(str(live_readback), row["sender"], row["body"])
        for row in rows
    ]


def _apply_broccoli(
    objects: Sequence[Mapping[str, Any]], _device: Any, environment: Any,
) -> list[bool]:
    if environment is None or getattr(environment, "_aw_env", None) is None:
        raise ValueError("broccoli injection requires an attached AndroidWorld environment")
    rows = [dict(item["content"]) for item in objects]
    observed = _write_broccoli_rows(rows, environment._aw_env)
    return [
        any(
            row["title"] == expected["title"]
            and row["description"] == expected["description"]
            and row["servings"] == expected["servings"]
            and row["ingredients"] == expected["ingredients"]
            and row["directions"] == expected["directions"]
            and row["favorite"] == expected["favorite"]
            for row in observed
        )
        for expected in rows
    ]


def _write_broccoli_rows(rows: Sequence[Mapping[str, Any]], aw_env: Any) -> list[dict[str, Any]]:
    """Patch Broccoli with an FTS4-capable SQLite runner, then read it back."""
    remote_db = "/data/data/com.flauschcode.broccoli/databases/broccoli"
    with aw_env.controller.pull_file(remote_db) as directory:
        local_db = Path(directory) / "broccoli"
        payload = Path(directory) / "seed_rows.json"
        payload.write_text(json.dumps(list(rows), ensure_ascii=False), encoding="utf-8")
        script = (
            "import json, sqlite3, sys\n"
            "db, payload = sys.argv[1:3]\n"
            "rows = json.load(open(payload, encoding='utf-8'))\n"
            "conn = sqlite3.connect(db)\n"
            "conn.execute('PRAGMA foreign_keys=ON')\n"
            "conn.execute('DELETE FROM recipes')\n"
            "for row in rows:\n"
            "  conn.execute('INSERT INTO recipes(title,imageName,description,servings,preparationTime,source,ingredients,directions,favorite) VALUES (?,?,?,?,?,?,?,?,?)', (row['title'], '', row['description'], row['servings'], '', '', row['ingredients'], row['directions'], row['favorite']))\n"
            "conn.commit()\n"
            "result = [dict(zip(('title','description','servings','ingredients','directions','favorite'), item)) for item in conn.execute('SELECT title,description,servings,ingredients,directions,favorite FROM recipes')]\n"
            "conn.close()\n"
            "print(json.dumps(result, ensure_ascii=False))\n"
        )
        runner = _fts_sqlite_runner()
        completed = subprocess.run(
            [runner, "-c", script, str(local_db), str(payload)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError(
                "Broccoli SQLite patch failed: "
                + ((completed.stderr or completed.stdout).strip()[:500]))
        try:
            observed = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Broccoli SQLite runner returned invalid readback") from exc
        if not isinstance(observed, list):
            raise ValueError("Broccoli SQLite runner returned non-list readback")
        aw_env.controller.push_file(local_db, remote_db)
    return [dict(row) for row in observed if isinstance(row, Mapping)]


def _fts_sqlite_runner() -> str:
    configured = str(os.environ.get("GUITRAVERSE_FTS_SQLITE_PYTHON") or "").strip()
    if configured:
        return configured
    options = {row[0] for row in sqlite3.connect(":memory:").execute("PRAGMA compile_options")}
    if any(option in {"ENABLE_FTS4", "ENABLE_FTS3"} for option in options):
        return sys.executable
    raise ValueError(
        "seed requires an FTS3/4-capable Python; set GUITRAVERSE_FTS_SQLITE_PYTHON")


def _default_dataset_adapters() -> dict[str, Any]:
    """The literal v2 dataset set; each handler owns its native storage tier."""
    return {
        "markor": _apply_markor,
        "clipper": _apply_clipper,
        "simple_calendar": _apply_simple_calendar,
        "tasks_org": _apply_tasks_org,
        "simple_draw": _apply_simple_draw,
        "audio_recorder": _apply_audio_recorder,
        "pro_expense": _apply_pro_expense,
        "broccoli": _apply_broccoli,
        "osmand": _apply_osmand,
        "open_tracks": _apply_open_tracks,
        "joplin": _apply_joplin,
        "miniwob": _no_data_adapter("miniwob"),
        "simple_gallery": _no_data_adapter("simple_gallery"),
        "simple_sms": _no_data_adapter("simple_sms"),
        "vlc": _no_data_adapter("vlc"),
        "retro_music": _no_data_adapter("retro_music"),
        "sms": _apply_sms,
        "shared_files": _apply_shared_files,
    }


def _require_androidworld(environment: Any, dataset_id: str) -> Any:
    aw_env = getattr(environment, "_aw_env", None) if environment is not None else None
    if aw_env is None:
        raise ValueError(
            f"{dataset_id} injection requires an attached AndroidWorld environment")
    return aw_env


def _no_data_adapter(dataset_id: str) -> Any:
    return lambda objects, device, environment: _apply_no_data_app(
        dataset_id, objects, device, environment)


def _apply_no_data_app(
    dataset_id: str,
    objects: Sequence[Mapping[str, Any]], device: Any, _environment: Any,
) -> list[bool]:
    if objects:
        raise ValueError("no-data app adapter received unexpected objects")
    from .runtime_apps import package_for_dataset
    package = package_for_dataset(dataset_id)
    output = device.run("shell", "pm", "path", package, timeout=30, check=True)
    if "package:" not in str(output):
        raise ValueError(f"no-data app package is not installed: {package}")
    return []


def _apply_markor(
    objects: Sequence[Mapping[str, Any]], device: Any, _environment: Any,
) -> list[bool]:
    results = []
    for item in objects:
        content = dict(item["content"])
        relative = _safe_device_path(content.get("path"), item["seed_id"])
        remote = "/sdcard/" + relative
        text = "# " + str(item["display_name"]) + "\n\n" + _required_text(
            content.get("text"), f"{item['seed_id']}.text") + "\n"
        results.append(_push_text_and_readback(device, remote, text))
    return results


def _push_text_and_readback(device: Any, remote: str, text: str) -> bool:
    with tempfile.TemporaryDirectory(prefix="guitraverse_text_") as directory:
        local = Path(directory) / Path(remote).name
        local.write_text(text, encoding="utf-8")
        device.run("shell", "mkdir", "-p", remote.rsplit("/", 1)[0], timeout=30, check=True)
        device.push(local, remote)
    observed = device.run("shell", "cat", remote, timeout=30, check=True)
    return str(observed) == text


def _apply_clipper(
    objects: Sequence[Mapping[str, Any]], _device: Any, environment: Any,
) -> list[bool]:
    aw_env = _require_androidworld(environment, "clipper")
    android_env = getattr(environment, "_android_env", None)
    if android_env is None:
        raise ValueError("clipper injection requires the AndroidEnvInterface")
    try:
        from android_world.env import adb_utils
    except ImportError as exc:
        raise ValueError("clipper injection requires the AndroidWorld adapter") from exc
    results = []
    for item in objects:
        text = _required_text(item["data"].get("text"), f"{item['seed_id']}.text")
        adb_utils.set_clipboard_contents(text, android_env)
        results.append(adb_utils.get_clipboard_contents(android_env) == text)
    return results


def _apply_simple_calendar(
    objects: Sequence[Mapping[str, Any]], _device: Any, environment: Any,
) -> list[bool]:
    aw_env = _require_androidworld(environment, "simple_calendar")
    try:
        from android_world.task_evals.utils import sqlite_schema_utils, sqlite_utils
    except ImportError as exc:
        raise ValueError("calendar injection requires the AndroidWorld adapter") from exc
    rows = []
    for item in objects:
        content = dict(item["content"])
        rows.append(sqlite_schema_utils.CalendarEvent(
            start_ts=content["start_ts"],
            end_ts=content["end_ts"],
            title=str(item["display_name"]),
            repeat_interval=1 if content.get("recurrence") == "weekly" else 0,
            repeat_rule=1 if content.get("recurrence") == "weekly" else 0,
        ))
    table = "events"
    database = "/data/data/com.simplemobiletools.calendar.pro/databases/events.db"
    sqlite_utils.delete_all_rows_from_table(table, database, aw_env, "simple calendar pro")
    sqlite_utils.insert_rows_to_remote_db(
        rows, "id", table, database, "simple calendar pro", aw_env)
    observed = sqlite_utils.get_rows_from_remote_device(
        table,
        database,
        sqlite_schema_utils.CalendarEvent,
        aw_env,
    )
    return [any(row.title == expected.title for row in observed) for expected in rows]


def _apply_tasks_org(
    objects: Sequence[Mapping[str, Any]], _device: Any, environment: Any,
) -> list[bool]:
    aw_env = _require_androidworld(environment, "tasks_org")
    try:
        from android_world.task_evals.utils import sqlite_schema_utils, sqlite_utils
    except ImportError as exc:
        raise ValueError("tasks injection requires the AndroidWorld adapter") from exc
    rows = []
    for item in objects:
        shapes = set(item["shape_tags"])
        content = dict(item["content"])
        rows.append(sqlite_schema_utils.Task(
            title=str(item["display_name"]),
            importance=3 if "priority" in shapes else 0,
            dueDate=content["due_ms"],
            created=content["created_ms"],
            modified=content["modified_ms"],
            completed=content["completed_ms"],
            remoteId=content["remote_id"],
        ))
    table = "tasks"
    database = "/data/data/org.tasks/databases/database"
    sqlite_utils.delete_all_rows_from_table(table, database, aw_env, "tasks")
    sqlite_utils.insert_rows_to_remote_db(rows, "_id", table, database, "tasks", aw_env)
    observed = sqlite_utils.get_rows_from_remote_device(
        table, database, sqlite_schema_utils.Task, aw_env)
    return [any(row.title == expected.title for row in observed) for expected in rows]


def _apply_simple_draw(
    objects: Sequence[Mapping[str, Any]], device: Any, _environment: Any,
) -> list[bool]:
    color_map = {
        "blue": "#2e5d9f", "red": "#a94848", "green": "#4d8c57",
        "yellow": "#b99a32", "white": "#eeeeee",
    }
    outcomes = []
    for item in objects:
        data = dict(item["data"])
        relative = _safe_device_path(data.get("path"), item["seed_id"])
        remote = "/sdcard/" + relative
        with tempfile.TemporaryDirectory(prefix="guitraverse_draw_") as directory:
            local = Path(directory) / Path(relative).name
            from .shared_v1 import _make_image
            _make_image(local, str(item["display_name"]), color_map.get(str(data.get("color")), "#385170"))
            device.run("shell", "mkdir", "-p", remote.rsplit("/", 1)[0], timeout=30, check=True)
            device.push(local, remote)
            digest = hashlib.sha256(local.read_bytes()).hexdigest()
        outcomes.append(_sha256sum_matches(
            str(device.run("shell", "sha256sum", remote, timeout=30, check=True)), digest))
    return outcomes


def _apply_audio_recorder(
    objects: Sequence[Mapping[str, Any]], device: Any, environment: Any,
) -> list[bool]:
    aw_env = _require_androidworld(environment, "audio_recorder")
    try:
        from pydub import AudioSegment
    except ImportError as exc:
        raise ValueError("audio recorder injection requires pydub and ffmpeg") from exc
    outcomes = []
    file_digests: dict[str, str] = {}
    for item in objects:
        content = dict(item["content"])
        remote = "/sdcard/" + _safe_device_path(content.get("path"), item["seed_id"])
        duration = int(content["duration_seconds"]) * 1000
        with tempfile.TemporaryDirectory(prefix="guitraverse_recorder_") as directory:
            local = Path(directory) / Path(remote).name
            source = _audio_recorder_asset(item["seed_id"])
            if source is not None:
                shutil.copyfile(source, local)
            else:
                AudioSegment.silent(duration=duration).export(local, format="ipod")
            device.run("shell", "mkdir", "-p", remote.rsplit("/", 1)[0], timeout=30, check=True)
            device.push(local, remote)
            file_digests[item["seed_id"]] = hashlib.sha256(local.read_bytes()).hexdigest()
        device.run(
            "shell", "am", "broadcast", "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d",
            f"file://{remote}", timeout=30, check=False,
        )
    indexed = _write_audio_recorder_index(objects, aw_env)
    for item in objects:
        remote = "/sdcard/" + _safe_device_path(item["content"].get("path"), item["seed_id"])
        file_ok = _sha256sum_matches(
            str(device.run("shell", "sha256sum", remote, timeout=30, check=True)),
            file_digests[item["seed_id"]],
        )
        outcomes.append(file_ok and indexed[item["seed_id"]])
    return outcomes


def _audio_recorder_asset(seed_id: str) -> Path | None:
    configured = str(os.environ.get("GUITRAVERSE_AUDIO_RECORDER_ASSET_ROOT") or "").strip()
    if not configured:
        return None
    match = re.fullmatch(r"audio_recorder_(\d{2})", seed_id)
    if match is None:
        raise ValueError(f"invalid audio recorder seed id: {seed_id!r}")
    path = Path(configured).expanduser() / f"recording_{match.group(1)}.m4a"
    if not path.is_file():
        raise ValueError(f"audio recorder asset is missing: {path}")
    return path


def _write_audio_recorder_index(
    objects: Sequence[Mapping[str, Any]], aw_env: Any,
) -> dict[str, bool]:
    """Write the app-owned records.db rows using its live inspected schema."""
    remote_db = "/data/data/com.dimowner.audiorecorder/databases/records.db"
    with aw_env.controller.pull_file(remote_db) as directory:
        local_db = Path(directory) / "records.db"
        connection = sqlite3.connect(local_db)
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        for item in objects:
            content = dict(item["content"])
            relative = _safe_device_path(content.get("path"), item["seed_id"])
            device_path = "/storage/emulated/0/" + relative
            duration = content.get("duration_db_microseconds")
            created = content.get("created_ms")
            added = content.get("added_ms")
            if not all(isinstance(value, int) and value >= 0 for value in (duration, created, added)):
                raise ValueError(
                    f"{item['seed_id']} needs planned records.db duration/created/added values")
            connection.execute("DELETE FROM records WHERE path=?", (device_path,))
            connection.execute(
                "INSERT INTO records(name,duration,created,added,path,format,size,"
                "sample_rate,channel_count,bitrate,data,bookmark,waveform_processed,data_str) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    str(item["display_name"]), duration, created, added,
                    device_path, "m4a", 0, 44100, 1, 96000, b"\x80" * 540,
                    0, 0, b"",
                ),
            )
        connection.commit()
        connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        rows = {
            row[0]: row[1:]
            for row in connection.execute(
                "SELECT path,name,duration,created,added,format FROM records")
        }
        connection.close()
        aw_env.controller.push_file(local_db, remote_db)
    results = {}
    for item in objects:
        content = dict(item["content"])
        path = "/storage/emulated/0/" + _safe_device_path(
            content.get("path"), item["seed_id"])
        row = rows.get(path)
        results[item["seed_id"]] = row == (
            str(item["display_name"]),
            content["duration_db_microseconds"],
            content["created_ms"],
            content["added_ms"],
            "m4a",
        )
    return results


def _apply_pro_expense(
    objects: Sequence[Mapping[str, Any]], _device: Any, environment: Any,
) -> list[bool]:
    aw_env = _require_androidworld(environment, "pro_expense")
    try:
        from android_world.task_evals.utils import sqlite_schema_utils, sqlite_utils
    except ImportError as exc:
        raise ValueError("expense injection requires the AndroidWorld adapter") from exc
    category_ids = {
        "food": 3, "transit": 7, "supplies": 1, "archive": 1,
        "media": 6, "routes": 7, "notes": 1, "empty": 1,
    }
    table = "expense"
    database = "/data/data/com.arduia.expense/databases/accounting.db"
    _ensure_database_template(aw_env, database, "accounting.db", table)
    rows = [
        sqlite_schema_utils.Expense(
            name=str(item["display_name"]),
            amount=int(item["content"]["amount_cents"]),
            category=category_ids.get(str(item["content"].get("category")), 1),
            note=str(item["content"].get("category") or ""),
            created_date=item["content"]["created_ms"],
            modified_date=item["content"]["modified_ms"],
        )
        for item in objects
    ]
    sqlite_utils.delete_all_rows_from_table(table, database, aw_env, "pro expense")
    sqlite_utils.insert_rows_to_remote_db(
        rows, "expense_id", table, database, "pro expense", aw_env)
    observed = sqlite_utils.get_rows_from_remote_device(
        table, database, sqlite_schema_utils.Expense, aw_env)
    return [
        any(row.name == expected.name and row.amount == expected.amount for row in observed)
        for expected in rows
    ]


def _apply_osmand(
    objects: Sequence[Mapping[str, Any]], _device: Any, environment: Any,
) -> list[bool]:
    aw_env = _require_androidworld(environment, "osmand")
    _ensure_database_template(
        aw_env,
        "/data/data/net.osmand/databases/map_markers_db",
        "map_markers_db",
        "map_markers",
    )
    return _write_osmand_rows(objects, aw_env)


def _ensure_database_template(
    aw_env: Any,
    remote_db: str,
    template_name: str,
    required_table: str,
) -> None:
    try:
        with aw_env.controller.pull_file(remote_db) as directory:
            local_db = Path(directory) / Path(remote_db).name
            connection = sqlite3.connect(local_db)
            present = connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (required_table,),
            ).fetchone() is not None
            connection.close()
    except Exception:
        present = False
    if present:
        return
    root = str(os.environ.get("GUITRAVERSE_DB_TEMPLATE_ROOT") or "").strip()
    template = Path(root) / template_name if root else Path()
    if not template.is_file():
        raise ValueError(
            f"{required_table} schema is absent and template is missing: {template}")
    aw_env.controller.push_file(template, remote_db)


def _write_osmand_rows(
    objects: Sequence[Mapping[str, Any]], aw_env: Any,
) -> list[bool]:
    """Use the inspected map_markers schema, including marker_id and NULL fields."""
    database = "/data/data/net.osmand/databases/map_markers_db"
    with aw_env.controller.pull_file(database) as directory:
        local_db = Path(directory) / "map_markers_db"
        connection = sqlite3.connect(local_db)
        connection.execute("DELETE FROM map_markers")
        for item in objects:
            content = dict(item["content"])
            connection.execute(
                "INSERT INTO map_markers(marker_id,marker_lat,marker_lon,marker_description,"
                "marker_active,marker_added,marker_visited,group_name,group_key,marker_color,"
                "marker_next_key,marker_disabled,marker_selected,marker_map_object_name) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    content["marker_id"], content["latitude"], content["longitude"],
                    content["serialized_description"], 1, content["marker_added_ms"], 0,
                    content["group_name"], content.get("group_key"), 1,
                    content.get("marker_next_key"), 0, 0, item["display_name"],
                ),
            )
        connection.commit()
        observed_ids = {
            row[0] for row in connection.execute("SELECT marker_id FROM map_markers")
        }
        connection.close()
        aw_env.controller.push_file(local_db, database)
    return [str(item["content"]["marker_id"]) in observed_ids for item in objects]


def _apply_open_tracks(
    objects: Sequence[Mapping[str, Any]], _device: Any, environment: Any,
) -> list[bool]:
    aw_env = _require_androidworld(environment, "open_tracks")
    try:
        from android_world.task_evals.utils import sqlite_schema_utils, sqlite_utils
    except ImportError as exc:
        raise ValueError("OpenTracks injection requires the AndroidWorld adapter") from exc
    rows = []
    for item in objects:
        content = dict(item["content"])
        duration = content["stop_ms"] - content["start_ms"]
        distance = float(content["distance_meters"])
        start = content["start_ms"]
        rows.append(sqlite_schema_utils.SportsActivity(
            name=str(item["display_name"]),
            category="walking",
            activity_type="walking",
            totaldistance=distance,
            starttime=start,
            stoptime=content["stop_ms"],
            totaltime=duration,
            movingtime=duration,
            avgspeed=distance / max(duration / 1000.0, 1.0),
            avgmovingspeed=distance / max(duration / 1000.0, 1.0),
            uuid=bytes.fromhex(content["uuid_hex"]),
        ))
    table = "tracks"
    database = "/data/data/de.dennisguse.opentracks/databases/database.db"
    sqlite_utils.delete_all_rows_from_table(table, database, aw_env, "activity tracker")
    sqlite_utils.insert_rows_to_remote_db(rows, "_id", table, database, "activity tracker", aw_env)
    observed = sqlite_utils.get_rows_from_remote_device(
        table, database, sqlite_schema_utils.SportsActivity, aw_env)
    return [any(row.name == expected.name for row in observed) for expected in rows]


def _apply_joplin(
    objects: Sequence[Mapping[str, Any]], _device: Any, environment: Any,
) -> list[bool]:
    aw_env = _require_androidworld(environment, "joplin")
    observed = _write_joplin_rows(objects, aw_env)
    return [
        any(
            row["id"] == item["content"]["note_id"]
            and row["title"] == item["display_name"]
            for row in observed
        )
        for item in objects
    ]


def _write_joplin_rows(
    objects: Sequence[Mapping[str, Any]], aw_env: Any,
) -> list[dict[str, str]]:
    """Patch Joplin's FTS-backed note tables with the plan-fixed values."""
    database = "/data/data/net.cozic.joplin/databases/joplin.sqlite"
    rows = []
    folders: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(objects, 1):
        content = dict(item["content"])
        title = str(item["display_name"])
        folder_id = _required_text(content.get("folder_id"), f"{item['seed_id']}.folder_id")
        note_id = _required_text(content.get("note_id"), f"{item['seed_id']}.note_id")
        folder_title = _required_text(content.get("folder"), f"{item['seed_id']}.folder")
        created_ms = content.get("created_ms")
        updated_ms = content.get("updated_ms")
        todo_completed_ms = content.get("todo_completed_ms")
        if not all(isinstance(value, int) and not isinstance(value, bool) for value in (
                created_ms, updated_ms, todo_completed_ms)):
            raise ValueError(f"{item['seed_id']} Joplin timestamps must be integers")
        folders.setdefault(folder_id, {
            "id": folder_id,
            "title": folder_title,
            "created_ms": created_ms,
            "updated_ms": updated_ms,
        })
        rows.append({
            "id": note_id,
            "parent_id": folder_id,
            "title": title,
            "body": title + "\n",
            "created_ms": created_ms,
            "updated_ms": updated_ms,
            "is_todo": int(bool(content.get("todo"))),
            "todo_completed_ms": todo_completed_ms,
            "order": updated_ms + index,
        })
    with aw_env.controller.pull_file(database) as directory:
        local_db = Path(directory) / "joplin.sqlite"
        payload = Path(directory) / "seed_joplin_rows.json"
        payload.write_text(
            json.dumps({"folders": list(folders.values()), "notes": rows}, ensure_ascii=False),
            encoding="utf-8",
        )
        script = (
            "import json, sqlite3, sys\n"
            "db, payload = sys.argv[1:3]\n"
            "seed = json.load(open(payload, encoding='utf-8'))\n"
            "conn = sqlite3.connect(db)\n"
            "conn.execute('DELETE FROM notes_normalized')\n"
            "conn.execute('DELETE FROM notes')\n"
            "conn.execute('DELETE FROM folders')\n"
            "for folder in seed['folders']:\n"
            "  conn.execute('INSERT INTO folders(id,title,created_time,updated_time,user_created_time,user_updated_time) VALUES (?,?,?,?,?,?)', (folder['id'],folder['title'],folder['created_ms'],folder['updated_ms'],folder['created_ms'],folder['updated_ms']))\n"
            "for note in seed['notes']:\n"
            "  conn.execute('INSERT INTO notes(id,parent_id,title,body,created_time,updated_time,is_todo,todo_completed,source,source_application,`order`,user_created_time,user_updated_time) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)', (note['id'],note['parent_id'],note['title'],note['body'],note['created_ms'],note['updated_ms'],note['is_todo'],note['todo_completed_ms'],'joplin','net.cozic.joplin-mobile',note['order'],note['created_ms'],note['updated_ms']))\n"
            "  conn.execute('INSERT INTO notes_normalized(id,title,body,user_created_time,user_updated_time,is_todo,todo_completed,parent_id,todo_due) VALUES (?,?,?,?,?,?,?,?,?)', (note['id'],note['title'],note['body'],note['created_ms'],note['updated_ms'],note['is_todo'],note['todo_completed_ms'],note['parent_id'],0))\n"
            "conn.commit()\n"
            "result = [dict(zip(('id','title'), row)) for row in conn.execute('SELECT id,title FROM notes ORDER BY id')]\n"
            "normalized = {row[0] for row in conn.execute('SELECT id FROM notes_normalized')}\n"
            "conn.close()\n"
            "if {row['id'] for row in result} != normalized: raise RuntimeError('notes_normalized readback mismatch')\n"
            "print(json.dumps(result, ensure_ascii=False))\n"
        )
        completed = subprocess.run(
            [_fts_sqlite_runner(), "-c", script, str(local_db), str(payload)],
            capture_output=True,
            text=True,
            check=False,
        )
        if completed.returncode != 0:
            raise ValueError(
                "Joplin SQLite patch failed: "
                + ((completed.stderr or completed.stdout).strip()[:500]))
        try:
            observed = json.loads(completed.stdout)
        except json.JSONDecodeError as exc:
            raise ValueError("Joplin SQLite runner returned invalid readback") from exc
        if not isinstance(observed, list) or len(observed) != len(rows):
            raise ValueError("Joplin SQLite runner returned incomplete readback")
        aw_env.controller.push_file(local_db, database)
    return [
        {"id": str(row["id"]), "title": str(row["title"])}
        for row in observed
        if isinstance(row, Mapping) and isinstance(row.get("id"), str)
        and isinstance(row.get("title"), str)
    ]


def _apply_shared_files(
    objects: Sequence[Mapping[str, Any]], device: Any, environment: Any,
) -> list[bool]:
    outcomes = []
    for item in objects:
        content = dict(item["content"])
        relative = _safe_device_path(content.get("path"), item["seed_id"])
        kind = _required_text(content.get("kind"), f"{item['seed_id']}.kind")
        remote = "/sdcard/" + relative
        if kind == "audio":
            outcomes.append(_apply_audio(item, content, remote, device, environment))
            continue
        if kind == "video":
            outcomes.append(_apply_video(item, content, remote, device, environment))
            continue
        with tempfile.TemporaryDirectory(prefix="guitraverse_seed_plan_") as directory:
            local = Path(directory) / Path(relative).name
            if kind == "text":
                local.write_text(
                    _required_text(content.get("text"), f"{item['seed_id']}.text"),
                    encoding="utf-8",
                )
            elif kind == "pdf":
                from .shared_v1 import _make_pdf
                _make_pdf(local, _required_text(content.get("label"), f"{item['seed_id']}.label"))
            elif kind == "image":
                from .shared_v1 import _make_image
                _make_image(
                    local,
                    _required_text(content.get("label"), f"{item['seed_id']}.label"),
                    "#385170",
                )
            else:
                raise ValueError(f"unsupported shared file kind: {kind!r}")
            device.run("shell", "mkdir", "-p", remote.rsplit("/", 1)[0], timeout=30, check=True)
            device.push(local, remote)
            expected_digest = hashlib.sha256(local.read_bytes()).hexdigest()
        observed = device.run("shell", "sha256sum", remote, timeout=30, check=True)
        outcomes.append(_sha256sum_matches(str(observed), expected_digest))
        device.run(
            "shell", "am", "broadcast", "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d",
            f"file://{remote}", timeout=30, check=False,
        )
    return outcomes


def _apply_audio(
    item: Mapping[str, Any],
    content: Mapping[str, Any], remote: str, device: Any, environment: Any,
) -> bool:
    asset = _shared_media_asset(item["seed_id"])
    if asset is not None:
        title = _required_text(content.get("title"), "audio.title")
        artist = _required_text(content.get("artist"), "audio.artist")
        with tempfile.TemporaryDirectory(prefix="guitraverse_audio_asset_") as directory:
            local_asset = Path(directory) / Path(remote).name
            _copy_audio_asset_with_metadata(asset, local_asset, title, artist)
            device.run("shell", "mkdir", "-p", remote.rsplit("/", 1)[0], timeout=30, check=True)
            device.push(local_asset, remote)
        device.run(
            "shell", "am", "broadcast", "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d",
            f"file://{remote}", timeout=30, check=False,
        )
        time.sleep(1.0)
        observed = device.run(
            "shell", "content", "query", "--uri", "content://media/external/audio/media",
            "--projection", "_display_name:title:artist", timeout=30, check=True,
        )
        return _media_row_contains(
            str(observed), Path(remote).name,
            title, artist,
        )
    if environment is None or getattr(environment, "_aw_env", None) is None:
        raise ValueError("audio injection requires an attached AndroidWorld environment")
    try:
        from android_world.task_evals.utils import user_data_generation
    except ImportError as exc:
        raise ValueError("audio injection requires the AndroidWorld media adapter") from exc
    title = _required_text(content.get("title"), "audio.title")
    artist = _required_text(content.get("artist"), "audio.artist")
    duration = content.get("duration_seconds")
    if not isinstance(duration, int) or duration < 1:
        raise ValueError("audio.duration_seconds must be a positive integer")
    user_data_generation.write_mp3_file_to_device(
        remote, environment._aw_env, artist=artist, title=title,
        duration_milliseconds=duration * 1000,
    )
    observed = device.run(
        "shell", "content", "query", "--uri", "content://media/external/audio/media",
        "--projection", "_display_name:title:artist", timeout=30, check=True,
    )
    return _media_row_contains(str(observed), Path(remote).name, title, artist)


def _apply_video(
    item: Mapping[str, Any],
    content: Mapping[str, Any], remote: str, device: Any, environment: Any,
) -> bool:
    asset = _shared_media_asset(item["seed_id"])
    if asset is not None:
        device.run("shell", "mkdir", "-p", remote.rsplit("/", 1)[0], timeout=30, check=True)
        device.push(asset, remote)
        device.run(
            "shell", "am", "broadcast", "-a",
            "android.intent.action.MEDIA_SCANNER_SCAN_FILE", "-d",
            f"file://{remote}", timeout=30, check=False,
        )
        time.sleep(1.0)
        observed = device.run(
            "shell", "content", "query", "--uri", "content://media/external/video/media",
            "--projection", "_display_name", timeout=30, check=True,
        )
        return Path(remote).name in str(observed)
    if environment is None or getattr(environment, "_aw_env", None) is None:
        raise ValueError("video injection requires an attached AndroidWorld environment")
    try:
        from android_world.task_evals.utils import user_data_generation
    except ImportError as exc:
        raise ValueError("video injection requires the AndroidWorld media adapter") from exc
    user_data_generation.write_video_file_to_device(
        Path(remote).name,
        remote.rsplit("/", 1)[0],
        environment._aw_env,
        messages=[_required_text(content.get("label"), "video.label")],
    )
    observed = device.run(
        "shell", "content", "query", "--uri", "content://media/external/video/media",
        "--projection", "_display_name", timeout=30, check=True,
    )
    return Path(remote).name in str(observed)


def _copy_audio_asset_with_metadata(
    source: Path, destination: Path, title: str, artist: str,
) -> None:
    """Copy a fixed MP3 asset and set only the plan-visible ID3 labels."""
    try:
        from mutagen.id3 import ID3, ID3NoHeaderError, TIT2, TPE1
    except ImportError as exc:
        raise ValueError("shared audio assets require mutagen for ID3 metadata") from exc
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    try:
        tags = ID3(destination)
    except ID3NoHeaderError:
        tags = ID3()
    tags.delall("TIT2")
    tags.delall("TPE1")
    tags.add(TIT2(encoding=3, text=title))
    tags.add(TPE1(encoding=3, text=artist))
    tags.save(destination)


def _shared_media_asset(seed_id: str) -> Path | None:
    root = str(os.environ.get("GUITRAVERSE_SHARED_MEDIA_ASSET_ROOT") or "").strip()
    if not root:
        return None
    names = {
        "shared_files_06": "Music/tone_01.mp3",
        "shared_files_07": "Music/tone_02.mp3",
        "shared_files_08": "Music/tone_03.mp3",
        "shared_files_09": "Movies/seed_clip.mp4",
        "shared_files_10": "Movies/route_clip.mp4",
        "shared_files_12": "Music/tone_04.mp3",
        "shared_files_18": "Music/tone_05.mp3",
        "shared_files_19": "Music/tone_06.mp3",
        "shared_files_20": "Music/tone_07.mp3",
        "shared_files_21": "Music/tone_08.mp3",
        "shared_files_22": "Music/tone_09.mp3",
        "shared_files_23": "Music/tone_10.mp3",
    }
    relative = names.get(seed_id)
    if relative is None:
        return None
    path = Path(root) / relative
    if not path.is_file():
        raise ValueError(f"shared media asset is missing: {path}")
    return path


def _safe_device_path(value: Any, label: str) -> str:
    path = _required_text(value, f"{label}.path")
    if not path.isascii() or path.startswith("/") or "\\" in path:
        raise ValueError(f"{label}.path must be a relative ASCII POSIX path")
    parts = path.split("/")
    if any(not part or part in {".", ".."} for part in parts):
        raise ValueError(f"{label}.path has unsafe segments")
    return path


def _sha256sum_matches(output: str, expected: str) -> bool:
    for line in output.splitlines():
        if line.strip().split(maxsplit=1)[:1] == [expected]:
            return True
    return False


def _media_row_contains(output: str, filename: str, title: str, artist: str) -> bool:
    return any(
        filename in line and title in line and artist in line
        for line in output.splitlines()
    )


def _sms_row_contains(output: str, sender: str, body: str) -> bool:
    for line in output.splitlines():
        sender_match = re.search(r"(?:^|[\s,])address=([^,\s]+)(?=,|$)", line)
        body_match = re.search(r"(?:^|[\s,])body=(.*)$", line)
        if (
            sender_match is not None
            and body_match is not None
            and sender_match.group(1) == sender
            and body_match.group(1) == body
        ):
            return True
    return False


__all__ = [
    "SEED_PLAN_SCHEMA",
    "apply_seed_plan",
    "build_collection_seed_plan",
    "build_traversal_seed_plan",
    "load_seed_plan",
    "write_seed_plan",
]
