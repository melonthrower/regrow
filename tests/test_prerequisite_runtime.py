"""Offline contract tests for the shared prerequisite/fixture runtime.

No VM, VLM, network, or filesystem fixture is used.  The callbacks below are
small in-memory simulations of the adapters traversal and M13 will inject.
"""

from __future__ import annotations

import unittest
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gui_rewalk.src.core.scenario.prerequisite_runtime import (
    ActionResult,
    AuthorizationPolicy,
    CheckResult,
    Prerequisite,
    PrerequisiteKind,
    PrerequisiteRuntime,
    RuntimeAction,
    RuntimeContext,
    SetupRecipe,
)


def _action(action_id: str, cost: int = 1) -> RuntimeAction:
    return RuntimeAction(action_id=action_id, gui_action_cost=cost)


class PrerequisiteRuntimeTests(unittest.TestCase):
    def test_existing_resource_is_bound_without_setup_or_cleanup(self) -> None:
        external = {"alarms": ["alarm-existing"]}
        action_calls = []

        def check(prerequisite, _context):
            self.assertEqual(prerequisite.resource_slot, "alarm_ref")
            return CheckResult(
                satisfied=bool(external["alarms"]),
                bindings={"alarm_ref": external["alarms"][0]},
                facts={"alarm_exists": True},
                evidence=["existing alarm observed"],
            )

        def execute(action, _prerequisite, _context):
            action_calls.append(action.action_id)
            return True

        prerequisite = Prerequisite(
            prerequisite_id="alarm_exists",
            kind="resource",
            resource_slot="alarm_ref",
            produces={"alarm_exists": True},
            setup_recipes=(SetupRecipe(
                recipe_id="create_alarm",
                actions=(_action("create_alarm"),),
                cleanup_actions=(_action("delete_alarm"),),
            ),),
        )
        runtime = PrerequisiteRuntime(
            check_callback=check, action_callback=execute)

        report = runtime.resolve([prerequisite])

        self.assertTrue(report.ready)
        self.assertEqual(report.gui_action_count, 0)
        self.assertEqual(report.results[0].status, "satisfied")
        self.assertEqual(report.resource_bindings["alarm_ref"], "alarm-existing")
        self.assertEqual(report.world_facts["alarm_exists"], True)
        self.assertEqual(runtime.owned_resources, ())
        self.assertEqual(action_calls, [])
        self.assertEqual(runtime.cleanup().status, "already_clean")

    def test_missing_resource_uses_shortest_recipe_and_cleans_only_created_resource(self) -> None:
        external = {"alarms": []}
        action_calls = []

        def check(_prerequisite, _context):
            if external["alarms"]:
                return CheckResult(
                    satisfied=True,
                    bindings={"alarm_ref": external["alarms"][0]},
                    facts={"alarm_exists": True},
                    evidence=["temporary alarm visible"],
                )
            return CheckResult(satisfied=False, evidence=["alarm list empty"])

        def execute(action, _prerequisite, context):
            action_calls.append(action.action_id)
            if action.action_id == "save_short_alarm":
                external["alarms"].append("alarm-run-owned")
                return ActionResult(
                    success=True,
                    gui_action_count=1,
                    facts={"alarm_exists": True},
                    bindings={"alarm_ref": "alarm-run-owned"},
                    evidence=["alarm saved"],
                )
            if action.action_id == "delete_alarm":
                self.assertEqual(
                    context.resource_bindings["alarm_ref"], "alarm-run-owned")
                external["alarms"].remove("alarm-run-owned")
                return ActionResult(
                    success=True,
                    gui_action_count=1,
                    facts={"alarm_exists": False},
                    evidence=["temporary alarm deleted"],
                )
            return True

        long_recipe = SetupRecipe(
            recipe_id="long_create",
            actions=(
                _action("open_long_form"),
                _action("fill_long_form"),
                _action("save_long_alarm"),
            ),
            cleanup_actions=(_action("delete_alarm"),),
        )
        short_recipe = SetupRecipe(
            recipe_id="short_create",
            actions=(_action("open_short_form"), _action("save_short_alarm")),
            cleanup_actions=(_action("delete_alarm"),),
        )
        prerequisite = Prerequisite(
            prerequisite_id="alarm_exists",
            kind=PrerequisiteKind.RESOURCE,
            resource_slot="alarm_ref",
            produces={"alarm_exists": True},
            setup_recipes=(long_recipe, short_recipe),
        )
        runtime = PrerequisiteRuntime(
            check_callback=check, action_callback=execute)

        report = runtime.resolve([prerequisite])

        self.assertEqual(report.status, "ready")
        self.assertEqual(report.gui_action_count, 2)
        self.assertEqual(report.results[0].status, "setup_completed")
        self.assertEqual(report.results[0].recipe_id, "short_create")
        self.assertEqual(action_calls, ["open_short_form", "save_short_alarm"])
        self.assertEqual(len(runtime.owned_resources), 1)
        self.assertEqual(
            runtime.owned_resources[0]["bindings"], {"alarm_ref": "alarm-run-owned"})

        cleanup = runtime.cleanup()
        self.assertEqual(cleanup.status, "complete")
        self.assertEqual(cleanup.gui_action_count, 1)
        self.assertEqual(action_calls[-1], "delete_alarm")
        self.assertEqual(external["alarms"], [])
        self.assertNotIn("alarm_ref", cleanup.resource_bindings)
        self.assertFalse(cleanup.world_facts["alarm_exists"])

        again = runtime.cleanup()
        self.assertEqual(again.status, "already_clean")
        self.assertEqual(again.gui_action_count, 0)
        self.assertEqual(action_calls.count("delete_alarm"), 1)

    def test_resource_cleanup_is_reverse_order(self) -> None:
        external = {"alarm": None, "event": None}
        action_calls = []

        def check(prerequisite, _context):
            value = external[prerequisite.prerequisite_id]
            if value is None:
                return False
            return CheckResult(
                satisfied=True,
                bindings={prerequisite.resource_slot: value},
            )

        def execute(action, prerequisite, _context):
            action_calls.append(action.action_id)
            if action.action_id.startswith("create_"):
                value = f"{prerequisite.prerequisite_id}-owned"
                external[prerequisite.prerequisite_id] = value
                return ActionResult(
                    success=True,
                    bindings={prerequisite.resource_slot: value},
                )
            external[prerequisite.prerequisite_id] = None
            return True

        def fixture(name):
            return Prerequisite(
                prerequisite_id=name,
                kind="resource",
                resource_slot=f"{name}_ref",
                setup_recipes=(SetupRecipe(
                    recipe_id=f"setup_{name}",
                    actions=(_action(f"create_{name}"),),
                    cleanup_actions=(_action(f"delete_{name}"),),
                ),),
            )

        runtime = PrerequisiteRuntime(
            check_callback=check, action_callback=execute)
        report = runtime.resolve([fixture("alarm"), fixture("event")])
        self.assertTrue(report.ready)

        cleanup = runtime.cleanup()

        self.assertEqual(cleanup.status, "complete")
        self.assertEqual(action_calls, [
            "create_alarm", "create_event", "delete_event", "delete_alarm"])
        self.assertEqual(external, {"alarm": None, "event": None})

    def test_requires_and_produces_form_a_dependency_order(self) -> None:
        calls = []

        def execute(action, _prerequisite, _context):
            calls.append(action.action_id)
            return True

        create_alarm = Prerequisite(
            prerequisite_id="create_alarm_state",
            kind="state",
            produces={"alarm_exists": True},
            setup_recipes=(SetupRecipe(
                recipe_id="create_alarm",
                actions=(_action("create_alarm"),),
            ),),
        )
        open_detail = Prerequisite(
            prerequisite_id="open_alarm_detail",
            kind="state",
            requires={"alarm_exists": True},
            produces={"alarm_detail_open": True},
            setup_recipes=(SetupRecipe(
                recipe_id="open_detail",
                actions=(_action("open_detail"),),
            ),),
        )
        runtime = PrerequisiteRuntime(action_callback=execute)

        # Deliberately reversed: the runtime must wait for alarm_exists.
        report = runtime.resolve([open_detail, create_alarm])

        self.assertTrue(report.ready)
        self.assertEqual(calls, ["create_alarm", "open_detail"])
        self.assertEqual(
            [result.prerequisite_id for result in report.results],
            ["create_alarm_state", "open_alarm_detail"],
        )
        self.assertEqual(report.world_facts, {
            "alarm_exists": True,
            "alarm_detail_open": True,
        })

    def test_state_setup_and_action_count_are_explicit(self) -> None:
        external = {"bluetooth_on": False}

        def check(_prerequisite, _context):
            return CheckResult(
                satisfied=external["bluetooth_on"],
                facts={"bluetooth_on": external["bluetooth_on"]},
            )

        def execute(action, _prerequisite, _context):
            self.assertEqual(action.action_id, "turn_bluetooth_on")
            external["bluetooth_on"] = True
            return ActionResult(
                success=True,
                gui_action_count=1,
                facts={"bluetooth_on": True},
            )

        prerequisite = Prerequisite(
            prerequisite_id="bluetooth_enabled",
            kind="state",
            produces={"bluetooth_on": True},
            setup_recipes=(SetupRecipe(
                recipe_id="enable_bluetooth",
                actions=(_action("turn_bluetooth_on"),),
            ),),
        )
        report = PrerequisiteRuntime(
            check_callback=check, action_callback=execute).resolve([prerequisite])

        self.assertTrue(report.ready)
        self.assertEqual(report.gui_action_count, 1)
        self.assertEqual(report.results[0].status, "setup_completed")
        evidence_codes = {
            item["code"] for item in report.results[0].to_dict()["evidence"]}
        self.assertIn("minimum_setup_recipe_selected", evidence_codes)
        self.assertIn("setup_verified", evidence_codes)

    def test_sandbox_authorization_is_allowed_without_password(self) -> None:
        context = RuntimeContext()
        policy = AuthorizationPolicy()
        self.assertTrue(policy.sandbox)
        self.assertTrue(policy.allow_system_authorization)
        self.assertIsNone(policy.password)
        prerequisite = Prerequisite(
            prerequisite_id="system_settings_authorized",
            kind="authorization",
            produces={"system_authorized": True},
        )

        report = PrerequisiteRuntime(
            context=context, authorization_policy=policy).resolve([prerequisite])

        self.assertTrue(report.ready)
        self.assertEqual(report.gui_action_count, 0)
        self.assertEqual(report.results[0].status, "satisfied")
        self.assertTrue(report.world_facts["system_authorized"])

    def test_locked_system_surface_runs_password_free_unlock_recipe(self) -> None:
        external = {"unlocked": False}
        calls = []

        def check(_prerequisite, _context):
            return CheckResult(satisfied=external["unlocked"])

        def execute(action, _prerequisite, _context):
            calls.append(action.action_id)
            external["unlocked"] = True
            return ActionResult(
                success=True,
                facts={"settings_unlocked": True},
            )

        prerequisite = Prerequisite(
            prerequisite_id="settings_unlocked",
            kind="authorization",
            produces={"settings_unlocked": True},
            setup_recipes=(SetupRecipe(
                recipe_id="click_unlock",
                actions=(_action("click_unlock"),),
            ),),
        )
        runtime = PrerequisiteRuntime(
            check_callback=check,
            action_callback=execute,
            authorization_policy=AuthorizationPolicy(password=None),
        )

        report = runtime.resolve([prerequisite])

        self.assertTrue(report.ready)
        self.assertEqual(calls, ["click_unlock"])
        self.assertEqual(report.gui_action_count, 1)
        self.assertTrue(report.world_facts["settings_unlocked"])

    def test_unmet_application_login_always_returns_needs_user(self) -> None:
        calls = []

        def execute(action, _prerequisite, _context):
            calls.append(action.action_id)
            return True

        prerequisite = Prerequisite(
            prerequisite_id="github_login",
            kind="login",
            check_key="github_session_visible",
            setup_recipes=(SetupRecipe(
                recipe_id="must_not_auto_login",
                actions=(_action("enter_credentials"),),
            ),),
        )
        runtime = PrerequisiteRuntime(
            check_callback=lambda _p, _c: False,
            action_callback=execute,
        )

        report = runtime.resolve([prerequisite])

        self.assertEqual(report.status, "needs_user")
        self.assertFalse(report.ready)
        self.assertEqual(report.gui_action_count, 0)
        self.assertEqual(report.results[0].status, "needs_user")
        self.assertEqual(calls, [])
        codes = [e.code for e in report.results[0].evidence]
        self.assertIn("application_login_requires_user", codes)

    def test_cleanup_resume_is_idempotent_after_partial_failure(self) -> None:
        external = {"resource": None, "delete_attempts": 0}
        calls = []

        def check(_prerequisite, _context):
            if external["resource"] is None:
                return False
            return CheckResult(
                satisfied=True,
                bindings={"item_ref": external["resource"]},
            )

        def execute(action, _prerequisite, _context):
            calls.append(action.action_id)
            if action.action_id == "create_item":
                external["resource"] = "owned-item"
                return ActionResult(
                    success=True, bindings={"item_ref": "owned-item"})
            if action.action_id == "close_item":
                return True
            external["delete_attempts"] += 1
            if external["delete_attempts"] == 1:
                return ActionResult(success=False, gui_action_count=1)
            external["resource"] = None
            return True

        prerequisite = Prerequisite(
            prerequisite_id="item",
            kind="resource",
            resource_slot="item_ref",
            setup_recipes=(SetupRecipe(
                recipe_id="create_item",
                actions=(_action("create_item"),),
                cleanup_actions=(
                    _action("close_item"), _action("delete_item")),
            ),),
        )
        runtime = PrerequisiteRuntime(
            check_callback=check, action_callback=execute)
        self.assertTrue(runtime.resolve([prerequisite]).ready)

        first = runtime.cleanup()
        second = runtime.cleanup()
        third = runtime.cleanup()

        self.assertEqual(first.status, "partial_failure")
        self.assertEqual(first.gui_action_count, 2)
        self.assertEqual(second.status, "complete")
        self.assertEqual(second.gui_action_count, 1)
        self.assertEqual(third.status, "already_clean")
        self.assertEqual(calls.count("close_item"), 1)
        self.assertEqual(calls.count("delete_item"), 2)
        self.assertIsNone(external["resource"])

    def test_partially_created_resource_is_still_owned_and_cleanable(self) -> None:
        external = {"resource": None}
        calls = []

        def check(_prerequisite, _context):
            # The second setup action fails, so the prerequisite never becomes
            # satisfied even though a concrete resource now exists.
            return CheckResult(
                satisfied=False,
                bindings=({"draft_ref": external["resource"]}
                          if external["resource"] else {}),
            )

        def execute(action, _prerequisite, _context):
            calls.append(action.action_id)
            if action.action_id == "create_draft":
                external["resource"] = "partial-draft"
                return ActionResult(
                    success=True,
                    bindings={"draft_ref": "partial-draft"},
                )
            if action.action_id == "finish_draft":
                return ActionResult(success=False, gui_action_count=1)
            external["resource"] = None
            return True

        prerequisite = Prerequisite(
            prerequisite_id="draft",
            kind="resource",
            resource_slot="draft_ref",
            setup_recipes=(SetupRecipe(
                recipe_id="create_draft",
                actions=(_action("create_draft"), _action("finish_draft")),
                cleanup_actions=(_action("delete_draft"),),
            ),),
        )
        runtime = PrerequisiteRuntime(
            check_callback=check, action_callback=execute)

        report = runtime.resolve([prerequisite])
        self.assertEqual(report.status, "failed")
        self.assertEqual(len(runtime.owned_resources), 1)

        cleanup = runtime.cleanup()
        self.assertEqual(cleanup.status, "complete")
        self.assertEqual(calls, ["create_draft", "finish_draft", "delete_draft"])
        self.assertIsNone(external["resource"])

    def test_resource_without_cleanup_is_rejected_before_creation(self) -> None:
        calls = []
        prerequisite = Prerequisite(
            prerequisite_id="unsafe_resource",
            kind="resource",
            resource_slot="unsafe_ref",
            setup_recipes=(SetupRecipe(
                recipe_id="unsafe_create",
                actions=(_action("create_unsafe"),),
            ),),
        )
        runtime = PrerequisiteRuntime(
            check_callback=lambda _p, _c: False,
            action_callback=lambda action, _p, _c: calls.append(action.action_id) or True,
        )

        report = runtime.resolve([prerequisite])

        self.assertEqual(report.status, "failed")
        self.assertEqual(report.gui_action_count, 0)
        self.assertEqual(calls, [])
        self.assertEqual(report.results[0].error,
                         "resource setup has no cleanup recipe")


if __name__ == "__main__":
    unittest.main(verbosity=2)
