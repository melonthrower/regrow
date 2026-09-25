# GUITRAVERSE Mobile Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a reproducible GUITRAVERSE Android baseline and make modular Luna exploration recover from transient surfaces without logging in, clearing app data, or accepting visibly ineffective actions.

**Architecture:** Keep the existing modular exploration harness and Android lifecycle. Add small deterministic guards around it: Prompt policy for interruptions, one fresh-grounding retry for an unchanged click, and one data-preserving process restart after bounded Back/recover failures. A separate manifest-driven out-of-band tool owns synthetic seed creation and whole-AVD snapshots; the traversal CLI only gains an explicit snapshot-at-boot option, and each collection starts the existing read-only Android environment from that snapshot.

**Tech Stack:** Python 3, pytest, PyYAML, Pillow, standard-library PDF helpers, ffmpeg for a deterministic synthetic MP3, ADB/emulator console, PowerShell, existing `gui_rewalk.src.core.explore` and `AndroidGUIGenEnv` modules.

**Spec:** `design/modules/guitraverse_mobile_baseline_design.md`

## Global Constraints

- New assets, profiles, snapshots, and tools use the `guitraverse` name; the existing `gui_rewalk` package and historical schemas are not renamed.
- Ordinary recovery never runs `pm clear`; process recovery is `force-stop + launch` through `restart_app_preserving_data()`.
- External sign-in/account/authorization controls are recorded but never executed by exploration.
- Seed and snapshot operations are out-of-band setup evidence and never become ActionAttempt, Capability, or instruction trajectory evidence.
- Every `apply` or snapshot mutation requires an exact `emulator-<port>` serial, the expected dedicated AVD name, and explicit confirmation.
- Existing user-owned changes in `gui_rewalk/src/core/scenario/live_state_locator.py`, `tests/test_live_state_locator.py`, and `.mobile_project_d63d0025.tar` remain unstaged.

---

### Task 1: Interruption and ineffective-action recovery

**Files:**
- Modify: `gui_rewalk/src/core/explore/prompts.py`
- Modify: `gui_rewalk/src/core/explore/scope.py`
- Modify: `gui_rewalk/src/core/explore/runtime.py`
- Modify: `tests/test_explore_kernel.py`
- Modify: `tests/test_operation_centered_settlement.py`
- Modify: `design/modules/explore_kernel/action_transition.md`
- Modify: `design/modules/explore_kernel/agent_context.md`
- Modify: `design/modules/explore_kernel/runtime_and_artifacts.md`
- Modify: `design/changelog/2026-08.md`

**Interfaces:**
- Consumes: existing `ScopeGuard.recover()`, injected `relaunch_fn`, `visible_change_ratio()`, and owner-centered pending settlement.
- Produces: `ScopeGuard.restart_preserving_data() -> Any`, runtime field `restart_recovery_task_id: str`, and a two-attempt no-effect limit for the same execute Operation.

- [ ] **Step 1: Write failing recovery tests**

Add tests that prove: Back recovery still happens first; after two same-task no-effect recover Attempts the runtime requests exactly one data-preserving relaunch and keeps the task active; a later repeated failure becomes a failed gap; relaunch does not call cache/data clearing.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `python -m pytest tests/test_explore_kernel.py -q --tb=short -p no:cacheprovider --basetemp artifacts/scratch/pytest_guitraverse_recovery_red`

Expected: the new restart escalation assertion fails because the current runtime immediately fails the task after two recover Attempts.

- [ ] **Step 3: Implement the minimal restart escalation**

Add `ScopeGuard.restart_preserving_data()` as a thin call to the already injected `relaunch_fn`. In `_fail_repeated_no_effect_recovery()`, request one out-of-band restart before failing the task; in the main loop, consume that request before another model call, clear only confirmed-frame bindings, retain the active Task/Operation, and observe a fresh screenshot. A second exhausted recovery sequence for the same Task records the existing failed gap.

- [ ] **Step 4: Write and run the click-settlement RED test**

Add a test where Luna reports the dispatched click owner completed but `visible_change_ratio()` is exactly `0.0`. Assert that the Attempt is `no_effect`, the Operation stays pending, and the first retry remains active. Add a second same-Operation no-effect Attempt and assert it closes as a failed gap rather than consuming the generic twelve-action budget.

Run: `python -m pytest tests/test_operation_centered_settlement.py -q --tb=short -p no:cacheprovider --basetemp artifacts/scratch/pytest_guitraverse_click_red`

Expected: the first new assertion fails because completed-owner settlement currently wins over identical-frame evidence.

- [ ] **Step 5: Implement minimal click no-effect and retry behavior**

Before `settle_completed_actions()`, override only a dispatched `click` with effectively unchanged application content to `no_effect`; do not certify its owner. Keep the existing near-repeat guard so retry must use a fresh screenshot and meaningfully different point. After two actual execute no-effects for the same Operation, fail that Operation with a precise grounding-or-application-validation gap.

- [ ] **Step 6: Add interruption policy to the stable Prompt**

State that nonblocking overlays do not justify wait; wait requires visible loading/countdown/scan/progress evidence and is bounded; safe visible dismissal/gesture precedes Back; external sign-in/account/authorization is never clicked and is registered as a deferred prerequisite with `external_auth_required` in its reason when it blocks core functionality. Keep Page/Region/Operation schema unchanged.

- [ ] **Step 7: Verify Task 1 and commit**

Run the two focused files plus `tests/test_native_return_actions.py`. Update the three matching module documents and monthly changelog with exact offline evidence, stage only Task 1 paths, run `git diff --cached --check`, and commit as `Fix mobile interruption and semantic retry`.

---

### Task 2: Manifest-driven synthetic seed tool

**Files:**
- Create: `data/dev_seed/guitraverse_mobile_seed_v1.yaml`
- Create: `tools/guitraverse_mobile_seed.py`
- Create: `tests/test_guitraverse_mobile_seed.py`
- Modify: `design/modules/guitraverse_mobile_baseline_design.md`
- Modify: `design/modules/env_and_config.md`
- Modify: `design/changelog/2026-08.md`

**Interfaces:**
- Consumes: PyYAML, Pillow, standard-library PDF/WAV helpers, and an explicit ADB executable.
- Produces: `load_manifest(path) -> SeedManifest`, `canonical_manifest_digest(manifest) -> str`, `build_seed_plan(manifest) -> dict`, and CLI commands `plan`, `apply`, `verify`, `snapshot-save`, `snapshot-load`.

- [ ] **Step 1: Write manifest-validation RED tests**

Test literal valid manifest output and rejection of non-versioned profile names, duplicate names/numbers/paths, absolute or parent-traversing device paths, URLs/emails/credential-shaped fields, non-reserved phone numbers, and external-send operations.

- [ ] **Step 2: Run validation tests and verify RED**

Run: `python -m pytest tests/test_guitraverse_mobile_seed.py -q --tb=short -p no:cacheprovider --basetemp artifacts/scratch/pytest_guitraverse_seed_red`

Expected: import failure because the seed tool does not exist.

- [ ] **Step 3: Implement manifest parsing, validation, digest, and plan**

Use frozen dataclasses for system, contacts, files, messages, calendar, and photos. Canonicalize parsed data as sorted-key compact UTF-8 JSON before SHA-256. `plan` emits deterministic JSON with profile, AVD, snapshot, digest, required packages, read-only verification queries, and ordered high-level mutations; it executes no ADB command.

- [ ] **Step 4: Write guarded mutation RED tests**

Exercise the CLI with a fake command boundary. Assert that missing `--confirm-apply`, a TCP-forward serial, offline device, wrong AVD name, wrong boot state, or missing required package stops before the first mutation. Assert that `verify` runs only query/list/getprop commands.

- [ ] **Step 5: Implement the ADB adapter and seed application**

Preflight exact device identity before mutations. Apply system settings, generated synthetic files/photos/audio plus media scans, inbound emulator SMS, local Contacts provider rows, and Calendar provider events. Generate local media in a temporary directory and remove it afterward. Verify every manifest item by provider/file/media query. Never invoke an AndroidWorld task `initialize_task()` and never invoke external send, browser, login, or account intents.

- [ ] **Step 6: Implement guarded snapshot commands and reports**

`snapshot-save` and `snapshot-load` accept only `guitraverse_mobile_seed_vN`, check the exact dedicated AVD, require their own confirmation flag, call emulator-console snapshot commands, and then query the snapshot list. Every subcommand writes a secret-free report containing manifest digest, device identity, commands by operation kind, outcomes, and timestamp.

- [ ] **Step 7: Verify Task 2 and commit**

Run the seed tests and `python -m py_compile tools/guitraverse_mobile_seed.py`. Update design status/docs/changelog, stage only Task 2 paths, run `git diff --cached --check`, and commit as `Add guarded GUITRAVERSE mobile seed tool`.

---

### Task 3: Explicit whole-snapshot traversal start

**Files:**
- Modify: `gui_rewalk/env/android_gui_gen_env.py`
- Modify: `gui_rewalk/run_visual_traversal.py`
- Create: `ops/run_guitraverse_seeded_mobile.ps1`
- Create: `tests/test_guitraverse_snapshot_start.py`
- Modify: `design/CURRENT_FRAMEWORK.md`
- Modify: `design/modules/env_and_config.md`
- Modify: `design/modules/guitraverse_mobile_baseline_design.md`
- Modify: `design/changelog/2026-08.md`

**Interfaces:**
- Consumes: existing Android read-only emulator lifecycle and `--modular-explore` CLI.
- Produces: `AndroidGUIGenEnv(..., boot_from_snapshot: bool = False)`, CLI option `--android_snapshot_name`, and a PowerShell wrapper with a non-mutating `-PlanOnly` mode.

- [ ] **Step 1: Write snapshot-start RED tests**

Assert that no explicit snapshot preserves the current emulator command, while an explicit versioned snapshot adds `-snapshot <name>` together with the existing `-read-only` and `-no-snapshot-save`. Assert that the traversal CLI forwards the option. Execute the PowerShell wrapper in `-PlanOnly` mode and assert the emitted argv contains the dedicated AVD and snapshot with no `--clean_start`.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest tests/test_guitraverse_snapshot_start.py -q --tb=short -p no:cacheprovider --basetemp artifacts/scratch/pytest_guitraverse_snapshot_red`

Expected: failures for the missing constructor/CLI option and wrapper.

- [ ] **Step 3: Implement explicit boot snapshot and wrapper**

Add the opt-in emulator boot flag without changing the default `init_state` behavior. The wrapper validates `guitraverse_mobile_seed_vN`, derives repo paths relative to itself, invokes one modular traversal, and relies on the existing `finally` path to terminate the read-only emulator. It never clears app data and never writes back the snapshot.

- [ ] **Step 4: Verify Task 3 and commit**

Run the snapshot tests, Android env lifecycle/log-guard tests, CLI startup tests, and syntax checks. Update CURRENT_FRAMEWORK because the public CLI gains an entry option; update module docs/changelog; stage only Task 3 paths; run `git diff --cached --check`; commit as `Start Android traversal from GUITRAVERSE snapshot`.

---

### Task 4: Integrated offline gate and live acceptance

**Files:**
- Modify only if evidence changes current truth: `design/modules/guitraverse_mobile_baseline_design.md`
- Modify: `design/changelog/2026-08.md`
- Create at runtime only: `artifacts/guitraverse_seed_reports/guitraverse_mobile_seed_v1/**`

**Interfaces:**
- Consumes: Task 1-3 commits and the dedicated writable AVD selected at live preflight.
- Produces: separate offline, saved-frame/API, live-seed, snapshot-restore, teacher-supervised traversal, and later unsupervised acceptance reports.

- [ ] **Step 1: Run the Tier 3 offline gate**

Run the focused exploration, seed, snapshot, lifecycle, API-contract, and MobileWorld adapter test files with a fresh short `--basetemp`; run `py_compile` for all changed Python files; run PowerShell `-PlanOnly`; run `git diff --check` and inspect `git status --porcelain`.

- [ ] **Step 2: Perform read-only live preflight**

On the selected server, query ADB inventory, exact serial, AVD name, boot state, installed required packages, snapshot list, disk space, and running emulator ownership. Stop if the instance is not the dedicated GUITRAVERSE writable seed AVD.

- [ ] **Step 3: Apply and verify seed, then publish snapshot**

Run `plan`, inspect the report, run confirmed `apply`, run read-only `verify`, save `guitraverse_mobile_seed_v1`, and verify it appears in the emulator snapshot list. Keep seed evidence outside traversal run roots.

- [ ] **Step 4: Verify two-run isolation**

Start read-only run A, mutate one synthetic contact/file/system value, stop it; start read-only run B and verify the original manifest is restored. Record this separately from any Luna traversal evidence.

- [ ] **Step 5: Run supervised Clock smoke and report evidence classes separately**

Run mobile Clock from the snapshot with Codex supervision. Verify Back can be followed by data-preserving force-stop/relaunch, unchanged clicks do not certify owners, and external login is not selected. Do not call this Luna-only acceptance; save that for a later fixed-Prompt unsupervised run.

- [ ] **Step 6: Final documentation checkpoint**

Record exact live commands/results and remaining gaps. Commit only source/docs/test changes; do not commit runtime reports, secrets, temporary media, or user-owned files.
