"""Offline tests for the screenshot-only visual prerequisite adapter.

The fake VLM and live adapters are in-memory.  No VM, VLM service, network, or
filesystem fixture is used.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gui_rewalk.src.core.scenario.visual_prerequisite_agent import (
    VisualPrerequisiteAgent,
)


class _Agent:
    def __init__(self, callback):
        self.callback = callback
        self.calls = []

    def predict_mm(self, prompt, images):
        self.calls.append((prompt, list(images)))
        return self.callback(prompt, list(images))


class _Adapter:
    def __init__(self, screen="empty", elements=None):
        self.screen = screen
        self.elements = list(elements or [])
        self.executed = []
        self.grounded = []
        self.ground_failure = False
        self.activations = 0

    def activate(self):
        self.activations += 1
        return {"success": True}

    def capture(self):
        return {"screenshot": f"image:{self.screen}"}

    def grounded_elements(self, _observation):
        return list(self.elements)

    def ground(self, action_spec, _observation):
        self.grounded.append(dict(action_spec))
        if self.ground_failure:
            return None
        return dict(action_spec)

    def execute(self, grounded_action):
        action = str(
            grounded_action.get("action")
            or grounded_action.get("instruction")
            or grounded_action.get("element_label")
            or ""
        )
        self.executed.append(action)
        if action == "save_short_alarm":
            self.screen = "alarm_present"
            return {
                "success": True,
                "gui_action_count": 1,
                "created_resource": "08:00 test alarm",
                "facts": {"alarm_exists": True},
            }
        if action == "delete_test_alarm":
            self.screen = "empty"
            return {
                "success": True,
                "facts": {"alarm_exists": False},
            }
        if action == "create_draft":
            self.screen = "draft_created"
            # Deliberately omit created_resource/bindings.  The visual adapter
            # must establish provisional run ownership before post-check.
            return {"success": True}
        if action == "delete_draft":
            self.screen = "empty"
            return {"success": True}
        if grounded_action.get("element_label") == "Unlock":
            self.screen = "unlocked"
            return {"success": True}
        if action == "turn_bluetooth_on":
            self.screen = "bluetooth_on"
            return {"success": True, "facts": {"bluetooth_on": True}}
        return {"success": True}

    def settle(self, _execution=None):
        return None


def _context(adapter):
    return {
        "current_app_id": "clock",
        "adapter": adapter,
        "blackboard": {},
    }


def _ref(**updates):
    value = {
        "app_id": "clock",
        "capability_id": "edit_alarm",
        "name": "Edit alarm detail",
        "node_id": "alarm_list",
        "elements": ["alarm-row", "add-alarm"],
    }
    value.update(updates)
    return value


class VisualPrerequisiteAgentTests(unittest.TestCase):
    def test_existing_resource_binds_visible_instance_and_skips_setup(self) -> None:
        adapter = _Adapter(
            screen="alarm_present",
            elements=[{"id": "alarm-row", "label": "08:00"}],
        )
        agent = _Agent(lambda _prompt, images: {
            "kind": "resource",
            "satisfied": images[0] == "image:alarm_present",
            "facts": {"alarm_exists": True},
            "bindings": {"alarm_ref": "08:00 existing alarm"},
            "evidence": {"message": "An 08:00 alarm row is visible."},
        })
        resolver = VisualPrerequisiteAgent(agent)
        ref = _ref(setup_recipe=[{
            "action": "create_alarm_should_not_run",
            "action_steps": 1,
        }], cleanup=[{"action": "delete_test_alarm"}])

        result = resolver(
            {
                "kind": "resource",
                "fact": "alarm_exists",
                "resource_slot": "alarm_ref",
            },
            ref,
            _context(adapter),
        )

        self.assertTrue(result["satisfied"])
        self.assertEqual(result["status"], "ready")
        self.assertEqual(result["gui_action_count"], 0)
        self.assertEqual(result["resource_bindings"]["alarm_ref"],
                         "08:00 existing alarm")
        self.assertFalse(result["owned_by_run"])
        self.assertEqual(adapter.executed, [])
        self.assertEqual(resolver.cleanup().status, "already_clean")
        self.assertIn("alarm-row", agent.calls[0][0])

    def test_missing_resource_uses_vlm_generated_shortest_recipe_and_cleanup(self) -> None:
        adapter = _Adapter(
            screen="empty",
            elements=[{"id": "add-alarm", "label": "Add alarm"}],
        )

        def judge(_prompt, images):
            if images[0] == "image:alarm_present":
                return {
                    "kind": "resource",
                    "satisfied": True,
                    "facts": {"alarm_exists": True},
                    "bindings": {"alarm_ref": "08:00 test alarm"},
                    "evidence": "Created alarm is visible.",
                }
            return {
                "kind": "resource",
                "satisfied": False,
                "facts": {"alarm_exists": False},
                "evidence": "Alarm list is empty.",
                "setup_recipes": [
                    {
                        "recipe_id": "long_create",
                        "estimated_gui_actions": 3,
                        "actions": [
                            {"action": "open_long_alarm_form"},
                            {"action": "fill_long_alarm_form"},
                            {"action": "save_long_alarm"},
                        ],
                        "cleanup": [{"action": "delete_test_alarm"}],
                    },
                    {
                        "recipe_id": "short_create",
                        "estimated_gui_actions": 2,
                        "actions": [
                            {"action": "open_short_alarm_form"},
                            {"action": "save_short_alarm"},
                        ],
                        "cleanup": [{"action": "delete_test_alarm"}],
                    },
                ],
            }

        resolver = VisualPrerequisiteAgent(_Agent(judge))
        result = resolver(
            {
                "kind": "resource",
                "fact": "alarm_exists",
                "resource_slot": "alarm_ref",
            },
            _ref(),
            _context(adapter),
        )

        self.assertTrue(result["satisfied"])
        self.assertEqual(result["gui_action_count"], 2)
        self.assertEqual(len(result["action_events"]), 2)
        self.assertEqual(
            [event["action_spec"]["action"]
             for event in result["action_events"]],
            ["open_short_alarm_form", "save_short_alarm"],
        )
        self.assertEqual(
            sum(event["action_steps"] for event in result["action_events"]),
            result["gui_action_count"],
        )
        self.assertEqual(
            result["action_events"][-1]["observation_after"]["screenshot"],
            "image:alarm_present",
        )
        self.assertEqual(adapter.executed,
                         ["open_short_alarm_form", "save_short_alarm"])
        self.assertTrue(result["owned_by_run"])
        self.assertEqual(result["resource_bindings"]["alarm_ref"],
                         "08:00 test alarm")
        self.assertTrue(all(
            item["owned_by_run"] for item in adapter.grounded[:2]))

        cleanup = resolver.cleanup()
        self.assertEqual(cleanup.status, "complete")
        self.assertEqual(cleanup.gui_action_count, 1)
        self.assertEqual(adapter.executed[-1], "delete_test_alarm")
        self.assertEqual(adapter.screen, "empty")
        self.assertEqual(adapter.activations, 1)
        self.assertEqual(resolver.cleanup().status, "already_clean")
        self.assertEqual(adapter.executed.count("delete_test_alarm"), 1)

    def test_declared_setup_recipe_takes_priority_over_vlm_generated_recipe(self) -> None:
        adapter = _Adapter(screen="bluetooth_off")

        def judge(_prompt, images):
            return {
                "kind": "state",
                "satisfied": images[0] == "image:bluetooth_on",
                "facts": {"bluetooth_on": images[0] == "image:bluetooth_on"},
                "evidence": "Bluetooth state is visible.",
                "setup_recipes": [{
                    "recipe_id": "hallucinated_shortcut",
                    "estimated_gui_actions": 0,
                    "actions": [{"action": "do_not_use_generated"}],
                }],
            }

        resolver = VisualPrerequisiteAgent(_Agent(judge))
        result = resolver(
            {"kind": "state", "fact": "bluetooth_on"},
            _ref(
                app_id="settings",
                capability_id="bluetooth_toggle",
                setup_recipe=[{
                    "recipe_id": "declared_toggle",
                    "actions": [{"action": "turn_bluetooth_on"}],
                }],
            ),
            {"current_app_id": "settings", "adapter": adapter},
        )

        self.assertTrue(result["satisfied"])
        self.assertEqual(adapter.executed, ["turn_bluetooth_on"])
        self.assertNotIn("do_not_use_generated", adapter.executed)

    def test_password_free_system_unlock_is_synthesized_and_verified(self) -> None:
        adapter = _Adapter(
            screen="locked",
            elements=[{"id": "unlock", "label": "Unlock"}],
        )

        def judge(_prompt, images):
            unlocked = images[0] == "image:unlocked"
            return {
                "kind": "authorization",
                "satisfied": unlocked,
                "facts": {"settings_unlocked": unlocked},
                "evidence": "Unlock bar is visible." if not unlocked else "Settings are unlocked.",
            }

        resolver = VisualPrerequisiteAgent(_Agent(judge))
        result = resolver(
            {"kind": "authorization", "fact": "settings_unlocked"},
            _ref(app_id="settings", capability_id="add_user"),
            {"current_app_id": "settings", "adapter": adapter},
        )

        self.assertTrue(result["satisfied"])
        self.assertEqual(result["gui_action_count"], 1)
        self.assertEqual(adapter.screen, "unlocked")
        self.assertEqual(adapter.grounded[0]["element_label"], "Unlock")
        self.assertNotIn("password", adapter.grounded[0])
        self.assertEqual(adapter.grounded[0]["authorization_mode"],
                         "password_free")
        self.assertFalse(adapter.grounded[0]["password_required"])

    def test_unmet_application_login_returns_needs_user_without_actions(self) -> None:
        adapter = _Adapter(screen="login_required")
        resolver = VisualPrerequisiteAgent(_Agent(lambda *_args: {
            "kind": "login",
            "satisfied": False,
            "facts": {"signed_in": False},
            "evidence": "A sign-in form is visible.",
        }))

        result = resolver(
            {
                "kind": "login",
                "fact": "signed_in",
                "setup_recipe": [{"action": "open_login_and_enter_credentials"}],
            },
            _ref(app_id="vscode", capability_id="sync_settings"),
            {"current_app_id": "vscode", "adapter": adapter},
        )

        self.assertFalse(result["satisfied"])
        self.assertEqual(result["status"], "needs_user")
        self.assertTrue(result["needs_user"])
        self.assertEqual(result["gui_action_count"], 0)
        self.assertEqual(adapter.executed, [])

    def test_login_boundary_survives_vlm_kind_misclassification(self) -> None:
        adapter = _Adapter(screen="login_required")
        resolver = VisualPrerequisiteAgent(_Agent(lambda *_args: {
            "kind": "state",
            "satisfied": False,
            "facts": {"signed_in": False},
            "setup_recipes": [{"actions": [{"action": "Sign in automatically"}]}],
            "evidence": "A sign-in surface is visible.",
        }))

        result = resolver(
            {"fact": "signed_in"},
            _ref(app_id="vscode", capability_id="sync_settings"),
            {"current_app_id": "vscode", "adapter": adapter},
        )

        self.assertEqual(result["status"], "needs_user")
        self.assertTrue(result["needs_user"])
        self.assertFalse(result["satisfied"])
        self.assertEqual(adapter.executed, [])

    def test_login_semantic_action_is_never_executed_as_generic_state(self) -> None:
        adapter = _Adapter(screen="sync_off")
        resolver = VisualPrerequisiteAgent(_Agent(lambda *_args: {
            "kind": "state",
            "satisfied": False,
            "facts": {"sync_enabled": False},
            "evidence": "Sync requires sign in.",
        }))

        result = resolver(
            {
                "kind": "state",
                "fact": "sync_enabled",
                "setup_recipe": [{"action": "Sign in to enable sync"}],
            },
            _ref(app_id="vscode", capability_id="sync_settings"),
            {"current_app_id": "vscode", "adapter": adapter},
        )

        self.assertEqual(result["status"], "needs_user")
        self.assertTrue(result["needs_user"])
        self.assertEqual(adapter.executed, [])

    def test_vlm_parse_and_kind_mismatch_fail_closed(self) -> None:
        adapter = _Adapter(screen="anything")
        malformed = VisualPrerequisiteAgent(_Agent(
            lambda *_args: "this is not JSON"))

        bad_json = malformed(
            {"kind": "state", "fact": "bluetooth_on"},
            _ref(),
            _context(adapter),
        )
        self.assertEqual(bad_json["status"], "failed")
        self.assertFalse(bad_json["satisfied"])
        self.assertEqual(adapter.executed, [])

        mismatch = VisualPrerequisiteAgent(_Agent(lambda *_args: {
            "kind": "state",
            "satisfied": True,
            "facts": {"alarm_exists": True},
        }))
        wrong_kind = mismatch(
            {
                "kind": "resource",
                "fact": "alarm_exists",
                "resource_slot": "alarm_ref",
            },
            _ref(),
            _context(adapter),
        )
        self.assertEqual(wrong_kind["status"], "failed")
        self.assertIn("kind mismatch", wrong_kind["reason"])
        self.assertEqual(adapter.executed, [])

    def test_grounding_failure_does_not_execute_or_claim_state(self) -> None:
        adapter = _Adapter(screen="bluetooth_off")
        adapter.ground_failure = True

        def judge(_prompt, images):
            return {
                "kind": "state",
                "satisfied": images[0] == "image:bluetooth_on",
                "facts": {"bluetooth_on": False},
                "evidence": "Bluetooth is off.",
            }

        resolver = VisualPrerequisiteAgent(_Agent(judge))
        result = resolver(
            {
                "kind": "state",
                "fact": "bluetooth_on",
                "setup_recipe": [{"action": "turn_bluetooth_on"}],
            },
            _ref(app_id="settings"),
            {"current_app_id": "settings", "adapter": adapter},
        )

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["gui_action_count"], 0)
        self.assertEqual(adapter.executed, [])

    def test_missing_resource_cleanup_is_rejected_before_live_action(self) -> None:
        adapter = _Adapter(screen="empty")
        resolver = VisualPrerequisiteAgent(_Agent(lambda *_args: {
            "kind": "resource",
            "satisfied": False,
            "facts": {"alarm_exists": False},
            "setup_recipes": [{
                "recipe_id": "unsafe_create",
                "actions": [{"action": "create_without_cleanup"}],
            }],
        }))

        result = resolver(
            {
                "kind": "resource",
                "fact": "alarm_exists",
                "resource_slot": "alarm_ref",
            },
            _ref(),
            _context(adapter),
        )

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["satisfied"])
        self.assertEqual(result["gui_action_count"], 0)
        self.assertEqual(adapter.executed, [])
        self.assertIn("cleanup", result["reason"])

    def test_post_create_vlm_failure_keeps_resource_owned_and_cleanable(self) -> None:
        adapter = _Adapter(screen="empty")

        def judge(_prompt, images):
            if images[0] == "image:draft_created":
                return "malformed post-create output"
            return {
                "kind": "resource",
                "satisfied": False,
                "facts": {"draft_exists": False},
                "evidence": "No draft is visible.",
            }

        resolver = VisualPrerequisiteAgent(_Agent(judge))
        result = resolver(
            {
                "kind": "resource",
                "fact": "draft_exists",
                "resource_slot": "draft_ref",
                "setup_recipe": [{
                    "recipe_id": "create_draft",
                    "actions": [{"action": "create_draft"}],
                    "cleanup": [{"action": "delete_draft"}],
                }],
            },
            _ref(capability_id="draft_detail"),
            _context(adapter),
        )

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["satisfied"])
        self.assertTrue(result["owned_by_run"])
        provisional = result["resource_bindings"]["draft_ref"]
        self.assertTrue(provisional["owned_by_run"])
        self.assertEqual(adapter.executed, ["create_draft"])

        cleanup = resolver.cleanup()
        self.assertEqual(cleanup.status, "complete")
        self.assertEqual(adapter.executed, ["create_draft", "delete_draft"])
        self.assertEqual(adapter.screen, "empty")
        self.assertEqual(adapter.activations, 1)

    def test_satisfied_resource_without_binding_fails_closed(self) -> None:
        adapter = _Adapter(screen="alarm_present")
        resolver = VisualPrerequisiteAgent(_Agent(lambda *_args: {
            "kind": "resource",
            "satisfied": True,
            "facts": {"alarm_exists": True},
            "evidence": "Alarm row is visible but was not bound.",
        }))

        result = resolver(
            {
                "kind": "resource",
                "fact": "alarm_exists",
                "resource_slot": "alarm_ref",
            },
            _ref(),
            _context(adapter),
        )

        self.assertEqual(result["status"], "failed")
        self.assertFalse(result["satisfied"])
        self.assertIn("binding", result["reason"])
        self.assertEqual(adapter.executed, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
