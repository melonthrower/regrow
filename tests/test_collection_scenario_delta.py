import hashlib
import json
import math

import pytest

from gui_rewalk.src.core.scenario.collection_scenario_delta import (
    DeltaError,
    apply_scenario_delta,
    evaluate_scenario_delta,
    load_scenario_delta,
)


def _payload(**overrides):
    value = {
        "schema": "guitraverse.scenario_delta.v1",
        "task_id": "markor_reply",
        "base_snapshot": "guitraverse_mobile_seed_v2",
        "mutations": [
            {"kind": "inbound_sms", "sender": "5550101", "body": "Reply with READY"},
            {
                "kind": "text_file",
                "path": "Documents/Markor/GUITRAVERSE/note.md",
                "content": "Draft",
            },
        ],
        "assertions": [
            {"kind": "outgoing_sms_equals", "recipient": "5550102", "from_slot": "reply"},
            {
                "kind": "file_text_equals",
                "path": "Documents/Markor/GUITRAVERSE/note.md",
                "from_slot": "saved_note",
            },
        ],
    }
    value.update(overrides)
    return value


def _write_delta(tmp_path, **overrides):
    path = tmp_path / "scenario_delta.json"
    path.write_text(json.dumps(_payload(**overrides)), encoding="utf-8")
    return path


class _Device:
    def __init__(self, *, sms_output="Row: 0 address=5550101, body=Reply with READY", files=None):
        self.sms_output = sms_output
        self.files = dict(files or {})
        self.calls = []
        self.pushes = []
        self.events = []

    def run(self, *args, timeout, check):
        self.calls.append((args, timeout, check))
        self.events.append(("run", args))
        if args[:4] == ("emu", "sms", "send", "5550101"):
            return "OK"
        if args[:5] in {
            ("shell", "content", "query", "--uri", "content://sms/inbox"),
            ("shell", "content", "query", "--uri", "content://sms/sent"),
        }:
            return self.sms_output
        if args == ("shell", "mkdir", "-p", "/sdcard/Documents/Markor/GUITRAVERSE"):
            return ""
        if args[:2] == ("shell", "cat"):
            return self.files.get(args[2], "")
        raise AssertionError(args)

    def push(self, local, remote):
        self.pushes.append((str(local), remote))
        self.events.append(("push", remote))
        self.files[remote] = open(local, encoding="utf-8").read()
        return "1 file pushed"


def test_load_valid_delta_is_frozen_and_has_a_canonical_digest(tmp_path):
    delta = load_scenario_delta(_write_delta(tmp_path))

    assert delta.schema == "guitraverse.scenario_delta.v1"
    assert delta.task_id == "markor_reply"
    assert delta.mutations[0].kind == "inbound_sms"
    assert delta.assertions[1].path == "Documents/Markor/GUITRAVERSE/note.md"
    expected = hashlib.sha256(json.dumps(
        _payload(), ensure_ascii=True, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")).hexdigest()
    assert delta.digest == expected
    with pytest.raises(AttributeError):
        delta.task_id = "other"


@pytest.mark.parametrize("change", [
    {"unexpected": True},
    {"schema": "guitraverse.scenario_delta.v2"},
    {"mutations": [{"kind": "inbound_sms", "sender": "5550101", "body": ""}]},
    {"mutations": [{"kind": "inbound_sms", "sender": "5550201", "body": "ok"}]},
    {"mutations": [{"kind": "text_file", "path": "Documents/GUITRAVERSE/../bad.txt", "content": "x"}]},
    {"assertions": [{"kind": "file_text_equals", "path": "Documents/GUITRAVERSE/a.py", "from_slot": "value"}]},
])
def test_load_rejects_unrecognized_or_unsafe_delta_values(tmp_path, change):
    payload = _payload()
    for key, value in change.items():
        if key == "unexpected":
            payload[key] = value
        else:
            payload[key] = value
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(DeltaError):
        load_scenario_delta(path)


@pytest.mark.parametrize("unsafe_path", [
    "Documents/GUITRAVERSE/x;id;#.txt",
    "Documents/GUITRAVERSE/x space.txt",
    "Documents/GUITRAVERSE/x$HOME.txt",
    "Documents/GUITRAVERSE/x&y.txt",
    "Documents/GUITRAVERSE/x|y.txt",
    "Documents/GUITRAVERSE/x'quote.txt",
    "Documents/GUITRAVERSE/x`quote.txt",
    "Documents/GUITRAVERSE/x\nnewline.txt",
])
def test_load_rejects_shell_metacharacters_in_text_file_segments(tmp_path, unsafe_path):
    with pytest.raises(DeltaError):
        load_scenario_delta(_write_delta(tmp_path, mutations=[{
            "kind": "text_file", "path": unsafe_path, "content": "x",
        }], assertions=[]))


def test_apply_requires_the_exact_base_snapshot_before_mutating(tmp_path):
    delta = load_scenario_delta(_write_delta(tmp_path))
    device = _Device()

    with pytest.raises(DeltaError, match="base_snapshot"):
        apply_scenario_delta(delta, device, "other_snapshot")

    assert device.calls == []
    assert device.pushes == []


def test_apply_uses_fixed_adb_operations_and_reads_each_mutation_back(tmp_path):
    delta = load_scenario_delta(_write_delta(tmp_path))
    remote = "/sdcard/Documents/Markor/GUITRAVERSE/note.md"
    device = _Device(files={remote: "Draft"})

    report = apply_scenario_delta(delta, device, "guitraverse_mobile_seed_v2")

    assert report == {
        "schema": "guitraverse.scenario_setup.v1",
        "task_id": "markor_reply",
        "digest": delta.digest,
        "ok": True,
        "items": [
            {"kind": "inbound_sms", "ok": True, "sender": "5550101"},
            {"kind": "text_file", "ok": True, "path": "Documents/Markor/GUITRAVERSE/note.md"},
        ],
    }
    assert device.calls[0][0] == ("emu", "sms", "send", "5550101", "Reply with READY")
    assert device.calls[1][0] == (
        "shell", "content", "query", "--uri", "content://sms/inbox",
        "--projection", "address:body",
    )
    assert device.calls[2][0] == (
        "shell", "mkdir", "-p", "/sdcard/Documents/Markor/GUITRAVERSE"
    )
    assert device.pushes[0][1] == remote
    assert device.events.index((
        "run", ("shell", "mkdir", "-p", "/sdcard/Documents/Markor/GUITRAVERSE")
    )) < device.events.index(("push", remote))
    assert device.calls[-1][0] == ("shell", "cat", remote)
    assert all(timeout > 0 and check is True for _, timeout, check in device.calls)


def test_apply_reports_failed_readback_without_claiming_success(tmp_path):
    delta = load_scenario_delta(_write_delta(tmp_path, mutations=[
        {"kind": "inbound_sms", "sender": "5550101", "body": "Reply with READY"},
    ], assertions=[]))

    report = apply_scenario_delta(
        delta, _Device(sms_output="Row: 0 address=5550101, body=other"),
        "guitraverse_mobile_seed_v2",
    )

    assert report["ok"] is False
    assert report["items"] == [{"kind": "inbound_sms", "ok": False, "sender": "5550101"}]


def test_evaluate_checks_scalar_bound_values_against_device_evidence(tmp_path):
    delta = load_scenario_delta(_write_delta(tmp_path))
    remote = "/sdcard/Documents/Markor/GUITRAVERSE/note.md"
    device = _Device(
        sms_output="Row: 0 address=5550102, body=READY",
        files={remote: "Saved locally"},
    )

    report = evaluate_scenario_delta(
        delta, device, {"reply": "READY", "saved_note": "Saved locally"})

    assert report["ok"] is True
    assert report["schema"] == "guitraverse.scenario_evaluation.v1"
    assert report["items"] == [
        {"kind": "outgoing_sms_equals", "ok": True, "recipient": "5550102", "from_slot": "reply"},
        {"kind": "file_text_equals", "ok": True, "path": "Documents/Markor/GUITRAVERSE/note.md", "from_slot": "saved_note"},
    ]
    assert device.calls[0][0] == (
        "shell", "content", "query", "--uri", "content://sms/sent",
        "--projection", "address:body",
    )


@pytest.mark.parametrize("bindings", [
    {"reply": "", "saved_note": "Saved locally"},
    {"reply": ["READY"], "saved_note": "Saved locally"},
    {"reply": math.inf, "saved_note": "Saved locally"},
])
def test_evaluate_rejects_empty_or_non_scalar_bindings(tmp_path, bindings):
    delta = load_scenario_delta(_write_delta(tmp_path))

    with pytest.raises(DeltaError, match="binding"):
        evaluate_scenario_delta(delta, _Device(), bindings)


def test_evaluate_requires_sms_recipient_and_body_on_the_same_row(tmp_path):
    delta = load_scenario_delta(_write_delta(tmp_path, mutations=[], assertions=[
        {"kind": "outgoing_sms_equals", "recipient": "5550102", "from_slot": "reply"},
    ]))
    device = _Device(sms_output="Row: 0 address=5550102\nRow: 1 body=READY")

    report = evaluate_scenario_delta(delta, device, {"reply": "READY"})

    assert report["ok"] is False
    assert report["items"] == [{
        "kind": "outgoing_sms_equals", "ok": False,
        "recipient": "5550102", "from_slot": "reply",
    }]


@pytest.mark.parametrize(("output", "reply", "expected_ok"), [
    ("Row: 0 address=55501020, body=READY", "READY", False),
    ("Row: 0 address=5550102, body=READY NOW", "READY", False),
    ("Row: 0 address=5550102, body=READY, WITH COMMA", "READY, WITH COMMA", True),
])
def test_evaluate_sms_fields_require_exact_values_with_comma_body(
    tmp_path, output, reply, expected_ok,
):
    delta = load_scenario_delta(_write_delta(tmp_path, mutations=[], assertions=[{
        "kind": "outgoing_sms_equals", "recipient": "5550102", "from_slot": "reply",
    }]))

    report = evaluate_scenario_delta(delta, _Device(sms_output=output), {"reply": reply})

    assert report["ok"] is expected_ok
