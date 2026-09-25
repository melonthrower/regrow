# GUITRAVERSE Traversal Seed v2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and publish an auditable `guitraverse_mobile_seed_v2` with all 16 AndroidWorld third-party apps, traversal-oriented representative data, per-app GUI smoke evidence, and read-only snapshot isolation.

**Architecture:** Preserve the v1 CLI as a compatibility shim while moving reusable behavior into a small `tools/guitraverse_seed` package. A manifest plus APK/asset lock files drive mechanism-based adapters; every stage emits structured reports, and a certificate gates whole-AVD publication. Live installation and seed work occurs only after offline guards pass and only on the dedicated v2 builder derived from immutable v1.

**Tech Stack:** Python 3.11, pytest, PyYAML, Pillow, Android SDK `adb/aapt/apksigner/emulator`, AndroidWorld controller for out-of-band onboarding, SQLite for version-locked private-app adapters, OpenAI-compatible Luna specialist for GUI smoke, PowerShell/Linux shell wrappers.

**Spec:** `docs/superpowers/specs/2026-08-30-guitraverse-traversal-seed-v2-design.md`

## Global Constraints

- The release ID and every mutation confirmation are exactly `guitraverse_mobile_seed_v2`.
- v1, existing runs, user secrets, unrelated AVDs, and user-owned worktree changes are immutable inputs.
- Never call AndroidWorld task initialization, evaluator, teardown, app snapshot, whole-provider `pm clear`, whole-table DELETE, or broad `/sdcard` cleanup.
- A newly installed third-party package may be cleared exactly once before its first setup; traversal and published snapshots never use `pm clear`.
- APK download is restricted to the official AndroidWorld GCS objects and must be verified by size, SHA-256, package, versionCode/versionName, signer digest, ABI, SDK, source and license before install.
- Seed writes are idempotent and scoped to stable GUITRAVERSE IDs; SQLite fallback requires exact app/schema fingerprint, force-stop, DB/WAL/SHM backup, write verification and rollback on failure.
- Seed/setup/verify/GUI-smoke/snapshot evidence remains outside exploration Attempt, Capability, instruction and benchmark-evaluator evidence.
- `guitraverse_mobile_seed_v2` is not saved unless 16/16 mandatory installation/setup/data/GUI gates pass.
- Use focused Tier 3 tests; do not run the full framework release gate unless separately requested.
- Stage exact task-owned paths only; preserve `live_state_locator.py`, its test, and `.mobile_project_d63d0025.tar`.

---

### Task 1: Extract the v1 CLI into a compatible seed package

**Files:**
- Create: `tools/guitraverse_seed/__init__.py`
- Create: `tools/guitraverse_seed/contracts.py`
- Create: `tools/guitraverse_seed/adb.py`
- Create: `tools/guitraverse_seed/manifest_v1.py`
- Create: `tools/guitraverse_seed/shared_v1.py`
- Create: `tools/guitraverse_seed/reports.py`
- Create: `tools/guitraverse_seed/cli.py`
- Modify: `tools/guitraverse_mobile_seed.py`
- Create: `tests/test_guitraverse_seed_v1_compat.py`
- Modify: `tests/test_guitraverse_mobile_seed.py`

**Interfaces:**
- Consumes: existing `SeedManifest`, `AdbClient`, `plan/apply/verify/snapshot-*` behavior.
- Produces: import-stable re-exports from `tools.guitraverse_mobile_seed`; package functions `load_v1_manifest()`, `build_v1_plan()`, `apply_v1_seed()`, `verify_v1_seed()`, `save_snapshot()`, `load_snapshot()`, and `main()`.

- [ ] **Step 1: Write the failing compatibility tests**

Assert that importing every current public symbol from `tools.guitraverse_mobile_seed` and the new package resolves to behaviorally equivalent functions. Execute `plan` against v1 and compare the literal schema/profile/digest/mutation kinds; execute existing fake-ADB verify and compare the complete result object.

- [ ] **Step 2: Run RED**

Run: `python -m pytest tests/test_guitraverse_seed_v1_compat.py -q --tb=short -p no:cacheprovider --basetemp C:\Users\Admin\AppData\Local\Temp\gt_v2_task1_red`

Expected: collection fails because `tools.guitraverse_seed` does not exist.

- [ ] **Step 3: Define the shared contracts**

Implement in `contracts.py`:

```python
@dataclass(frozen=True)
class SeedContext:
    serial: str
    avd_name: str
    release_id: str
    manifest_digest: str
    sdk: int
    locale: str
    system_fingerprint: str

@dataclass(frozen=True)
class StageResult:
    app_id: str
    status: Literal["passed", "failed", "skipped"]
    evidence: tuple[str, ...] = ()
    reason: str = ""
```

Move v1 records without changing field names or serialized order. Move `AdbClient` into `adb.py`, manifest parsing into `manifest_v1.py`, shared seed logic into `shared_v1.py`, and report functions into `reports.py`. Keep the old file as imports plus `raise SystemExit(main())`.

- [ ] **Step 4: Run GREEN and existing v1 regression**

Run the compatibility file and `tests/test_guitraverse_mobile_seed.py`; require byte-equivalent canonical digest and all existing assertions green.

- [ ] **Step 5: Update docs/changelog and commit**

Record this as behavior-preserving extraction and commit exact paths as `Refactor GUITRAVERSE seed v1 into package`.

---

### Task 2: Implement v2 manifest, APK lock, asset lock and certificate contracts

**Files:**
- Create: `tools/guitraverse_seed/manifest_v2.py`
- Create: `tools/guitraverse_seed/locks.py`
- Create: `tools/guitraverse_seed/certificate.py`
- Create: `data/dev_seed/guitraverse_explore_seed_v2.yaml`
- Create after verified download: `data/dev_seed/guitraverse_mobile_apps_v2.lock.yaml`
- Create: `data/dev_seed/guitraverse_mobile_assets_v2.lock.yaml`
- Create: `tests/test_guitraverse_seed_v2_contracts.py`

**Interfaces:**
- Produces: `TraversalSeedProfile`, `ApkLockEntry`, `AssetLockEntry`, `SeedCertificate`, `load_v2_manifest()`, `load_apps_lock()`, `load_assets_lock()`, `canonical_digest()` and `certificate_ready()`.

- [ ] **Step 1: Write RED contract tests**

Use literal fixtures to reject missing/duplicate adapter IDs, non-GCS APK URLs, empty hashes, wrong package syntax, unversioned release IDs, unknown license state, non-reserved phone numbers, external URLs in synthetic content, count-shape violations, and certificate aggregate success when one app is partial.

- [ ] **Step 2: Implement strict frozen records and loaders**

`ApkLockEntry` contains:

```python
adapter_id, display_name, gcs_object, sha256, size_bytes,
package, version_name, version_code, signer_sha256,
abis, min_sdk, target_sdk, upstream_url, upstream_revision,
spdx_license, redistributable, trademark_note, verified_at
```

The v2 manifest contains exact expected seed IDs and shape tags for core/shared and per-app datasets. Certificate readiness requires 16 installed/setup/data/gui passed, shared domains passed, snapshot listed, and isolation passed.

- [ ] **Step 3: Add the traversal-oriented v2 profile**

Define 10 contacts, 10 inbound SMS, 10 system calendar events including recurring entries, 10–15 shared files/media, 10 call logs, explicit Clock representatives, and adapter datasets from the spec. Data records use stable ASCII IDs and separate natural display text. Do not add a persona narrative or benchmark task object.

- [ ] **Step 4: Run GREEN and deterministic roundtrip tests**

Verify YAML key reordering does not change canonical digest; expanded objects, counts and shape tags have literal expected values.

- [ ] **Step 5: Commit schema/profile without an unverified APK lock**

Commit contract/profile/asset-generator metadata as `Add GUITRAVERSE traversal seed v2 contracts`. The APK lock is committed only in Task 3 after real object/metadata verification.

---

### Task 3: Build the verified APK downloader, metadata locker and installer

**Files:**
- Create: `tools/guitraverse_seed/installer.py`
- Create: `tools/guitraverse_seed/androidworld_apps.py`
- Create: `tests/test_guitraverse_seed_installer.py`
- Modify: `tools/guitraverse_seed/cli.py`

**Interfaces:**
- Produces: `download_apks(source_specs, cache_root)`, `inspect_apk(path, sdk_tools)`, `render_lock(entries)`, `verify_locked_apk(entry, path)`, and `install_locked_apk(entry, context, adb)`.

- [ ] **Step 1: Write downloader and metadata RED tests**

Use local byte fixtures and fake command results to prove: redirects outside `storage.googleapis.com/gresearch/android_world/` fail; size/hash mismatch stops before `adb install`; `aapt dump badging` package/version/SDK mismatch fails; `apksigner verify --print-certs` signer mismatch fails; install success without exact `pm path` and `dumpsys package` metadata fails.

- [ ] **Step 2: Register the exact 16 AndroidWorld sources**

Register Markor, Clipper, Simple Calendar, Tasks, Simple Draw, Simple Gallery, Simple SMS, Audio Recorder, MiniWoB, Pro Expense, Broccoli, OsmAnd, OpenTracks, VLC x86_64 candidate, Joplin and Retro Music using the official filenames from `android_world/env/setup_device/apps.py`. Do not include the AndroidWorld visualizer APK.

- [ ] **Step 3: Implement fail-closed download/inspection/install**

Download to a temporary filename, hash and inspect before atomic cache rename. `lock-apks` writes a candidate report, never silently updates the tracked lock. `install-apps` requires a complete tracked lock and confirmation `guitraverse_mobile_seed_v2`.

- [ ] **Step 4: Run offline GREEN**

Run installer tests and CLI `--help`; verify no network/device call occurs for plan/lock validation.

- [ ] **Step 5: Resolve the real lock on js1**

Run `lock-apks` with no emulator, archive raw responses and metadata, inspect all 16 entries including licenses/upstream revisions, copy the candidate lock locally, run contract tests, and commit it as `Lock AndroidWorld APK metadata for GUITRAVERSE v2`.

---

### Task 4: Implement adapter registry, setup steps and exclusive runtime roles

**Files:**
- Create: `tools/guitraverse_seed/adapters/__init__.py`
- Create: `tools/guitraverse_seed/adapters/base.py`
- Create: `tools/guitraverse_seed/adapters/setup.py`
- Create: `tools/guitraverse_seed/registry.py`
- Create: `tests/test_guitraverse_seed_setup_adapters.py`

**Interfaces:**
- Produces: `AppAdapter` protocol, `AdapterSpec`, `SetupStep`, `AdapterRegistry`, `execute_setup()`, and `prepare_runtime()`.

- [ ] **Step 1: Write RED registry/setup tests**

Assert 16 unique adapter IDs/packages, exact version-bound setup recipes, explicit permission allowlists, no broad storage delete, no default-role mutation in baseline for Simple SMS, and failure when any expected postcondition is absent. A fixed sleep without a postcondition must be rejected by schema.

- [ ] **Step 2: Implement declarative setup steps**

Support only `launch`, `click_text`, `grant_permission`, `set_appop`, `set_role`, `assert_activity`, `assert_permission`, and `close`. `click_text` uses out-of-band AndroidWorld controller and records before/action/after screenshots. Setup failure returns failed and blocks certificate; it is never downgraded to warning.

- [ ] **Step 3: Port the 16 version-specific onboarding/permission recipes**

Translate official setup behavior while removing implicit whole-package clear and app snapshots. Baseline roles remain Google Messages/Google Dialer/Chrome. Simple SMS `prepare_runtime()` switches SMS role only in its read-only smoke/traversal overlay and verifies restoration in a new instance.

- [ ] **Step 4: Run GREEN and commit**

Run registry/setup tests, py_compile and diff check; commit as `Add versioned GUITRAVERSE app setup adapters`.

---

### Task 5: Expand shared provider, file and deterministic media seed

**Files:**
- Create: `tools/guitraverse_seed/adapters/shared.py`
- Create: `tools/guitraverse_seed/assets.py`
- Create: `tests/test_guitraverse_seed_shared_v2.py`
- Modify: `data/dev_seed/guitraverse_mobile_assets_v2.lock.yaml`

**Interfaces:**
- Produces: `SharedPlatformAdapter`, `generate_assets(profile, output)`, `apply_shared_v2()`, and `verify_shared_v2()`.

- [ ] **Step 1: Write RED shape/idempotency tests**

Require literal IDs/counts and coverage tags: 10 contacts, 10 SMS across multiple senders/conversations, 10 calendar events with past/today/future/recurring, 10 call logs, mixed files/media, Clock representatives, and an empty subdirectory/no-result query. Applying twice must not change observed counts.

- [ ] **Step 2: Implement deterministic assets and lock verification**

Generate text/PDF/images locally. Generate tagged audio/video only through the assets-lock declared generator/version; hash every output and reject host-dependent output drift. Shared media is pushed once and scanned for Files/Photos/Gallery/VLC/Retro.

- [ ] **Step 3: Extend provider adapters safely**

Use seed-owned upserts for Contacts/SMS/Calendar/CallLog; preserve non-seed rows. Clock app-private seed uses a version-specific adapter or deterministic build-time UI setup, not an unverified DB guess. Verify exact IDs, shape tags and current default roles.

- [ ] **Step 4: Run GREEN and commit**

Run v1 compatibility plus shared-v2 tests; commit as `Add traversal-oriented shared mobile seed data`.

---

### Task 6: Add file/media application adapters

**Files:**
- Create: `tools/guitraverse_seed/adapters/markor.py`
- Create: `tools/guitraverse_seed/adapters/simple_draw.py`
- Create: `tools/guitraverse_seed/adapters/simple_gallery.py`
- Create: `tools/guitraverse_seed/adapters/audio_recorder.py`
- Create: `tools/guitraverse_seed/adapters/vlc.py`
- Create: `tools/guitraverse_seed/adapters/retro_music.py`
- Create: `tests/test_guitraverse_seed_file_media_adapters.py`

**Interfaces:**
- Produces adapters for Markor, Simple Draw, Simple Gallery, Audio Recorder, VLC and Retro Music.

- [ ] **Step 1: Write RED per-app plan/verify tests**

Use literal expected remote paths, seed IDs and MediaStore queries. Verify Markor 10 notes and folders, Gallery 10 images, Draw 5 drawings, Recorder 5 audio objects, VLC scan, and Retro title/artist/duration coverage. Tests reject broad directory clearing and duplicated shared media.

- [ ] **Step 2: Implement mechanism-shared adapters**

Reuse shared assets without copying semantic objects. Each adapter owns only app-specific paths/index/setup and returns independent verification results.

- [ ] **Step 3: Run GREEN and commit**

Run adapter/shared/v1 compatibility tests; commit as `Add GUITRAVERSE file and media adapters`.

---

### Task 7: Add version-locked private database adapters

**Files:**
- Create: `tools/guitraverse_seed/sqlite_txn.py`
- Create: `tools/guitraverse_seed/adapters/clipper.py`
- Create: `tools/guitraverse_seed/adapters/simple_calendar.py`
- Create: `tools/guitraverse_seed/adapters/tasks_org.py`
- Create: `tools/guitraverse_seed/adapters/pro_expense.py`
- Create: `tools/guitraverse_seed/adapters/broccoli.py`
- Create: `tools/guitraverse_seed/adapters/joplin.py`
- Create: `tests/test_guitraverse_seed_sqlite_adapters.py`

**Interfaces:**
- Produces `SQLiteSeedTransaction` and adapters for Clipper, Simple Calendar, Tasks, Pro Expense, Broccoli and Joplin.

- [ ] **Step 1: Write RED transaction tests**

Create SQLite fixtures with WAL enabled. Assert exact schema fingerprint is required; only seed-owned PKs are upserted; non-seed rows survive; DB/WAL/SHM backups are restored on write/query failure; force-stop occurs before pull and app relaunch/query after push.

- [ ] **Step 2: Implement the transaction helper**

The helper copies DB plus existing sidecars, checkpoints or consistently handles WAL, runs parameterized SQL, validates counts/IDs locally, pushes atomically within the fixed package, restores SELinux context/owner, relaunches and re-queries. It never issues whole-table DELETE.

- [ ] **Step 3: Implement six app adapters**

Seed 10 clips, 10 calendar events, 10 tasks, 10 expenses, 10 recipes and 10 Joplin notes in 3 folders using the exact locked APK schemas. Joplin normalized rows and folder IDs are generated deterministically.

- [ ] **Step 4: Run GREEN and commit**

Run SQLite fixtures, package metadata locks and v1 compatibility; commit as `Add GUITRAVERSE private database adapters`.

---

### Task 8: Add specialized OsmAnd, OpenTracks, Simple SMS and MiniWoB adapters

**Files:**
- Create: `tools/guitraverse_seed/adapters/osmand.py`
- Create: `tools/guitraverse_seed/adapters/open_tracks.py`
- Create: `tools/guitraverse_seed/adapters/simple_sms.py`
- Create: `tools/guitraverse_seed/adapters/miniwob.py`
- Create: `tests/test_guitraverse_seed_specialized_adapters.py`

**Interfaces:**
- Produces OsmAnd map/marker, OpenTracks track, Simple SMS runtime-role and MiniWoB built-in-smoke adapters.

- [ ] **Step 1: Write RED specialized tests**

Assert locked offline-map hash/path/context, 10 marker IDs, 3–5 structurally valid tracks, Simple SMS role switch/restoration report, and MiniWoB no-fake-data behavior. Tests reject network map download from unlisted URLs and baseline SMS-role mutation.

- [ ] **Step 2: Implement specialized adapters**

Use the official locked map asset and exact app-private schema for markers/tracks; route all private writes through `SQLiteSeedTransaction`. MiniWoB verifies launcher and built-in page only.

- [ ] **Step 3: Run GREEN and commit**

Run specialized/SQLite/setup tests; commit as `Add GUITRAVERSE specialized Android adapters`.

---

### Task 9: Implement orchestration, resume-safe reports, GUI smoke and certificate

**Files:**
- Create: `tools/guitraverse_seed/orchestrator.py`
- Create: `tools/guitraverse_seed/gui_smoke.py`
- Modify: `tools/guitraverse_seed/certificate.py`
- Modify: `tools/guitraverse_seed/cli.py`
- Create: `tests/test_guitraverse_seed_orchestrator.py`
- Create: `tests/test_guitraverse_seed_gui_smoke.py`

**Interfaces:**
- Produces CLI stages `inspect`, `plan`, `lock-apks`, `install-apps`, `setup-apps`, `seed-shared`, `seed-apps`, `verify-data`, `gui-smoke`, `certificate`, and existing snapshot commands.

- [ ] **Step 1: Write RED stage/resume tests**

Assert strict stage ordering, exact manifest/lock/device digest binding, no repeated one-time clear/setup after a passed report, per-app partial visibility, and snapshot/certificate refusal when any mandatory result is missing. Initialization failures must remain distinct from Agent failures.

- [ ] **Step 2: Implement append-only stage reports**

Reports include stage ID, inputs/digests, exact command kinds, app results, timestamps and evidence paths, without secrets. Resume reads the latest matching successful stage; changed code/manifest/lock/device invalidates downstream stages.

- [ ] **Step 3: Implement GUI smoke**

For each app, launch exact package/activity, capture initial and data-list frames, run version-specific setup/runtime preparation, and invoke a strict seed-visibility specialist or deterministic selector evidence. Save `installed/setup_complete/data_verified/gui_verified/snapshot_verified/partial_reason` separately.

- [ ] **Step 4: Run GREEN and commit**

Run orchestration/GUI-smoke/all seed tests; commit as `Add GUITRAVERSE seed orchestration and certificate`.

---

### Task 10: Build the writable v2 AVD and install all 16 apps

**Files:**
- Runtime only: `artifacts/guitraverse_seed_reports/guitraverse_mobile_seed_v2/**`
- Update after evidence: `design/modules/guitraverse_mobile_baseline_design.md`
- Modify: `design/changelog/2026-08.md`

**Interfaces:**
- Consumes: complete locks/adapters/orchestrator.
- Produces: draft builder state and install/setup reports; no v2 snapshot yet.

- [ ] **Step 1: Final read-only server preflight**

Verify js1 disk/load, exact AVD inventory, no owned 5612 process, v1 snapshot listed, code archive hash, Android SDK tools and locked cache requirements. Record baseline processes/devices before starting.

- [ ] **Step 2: Create a dedicated writable v2 builder from v1**

Start the dedicated `guitraverse_mobile_seed` AVD on console/grpc `5612/8612` without `-read-only`, explicitly load `guitraverse_mobile_seed_v1`, keep `-no-snapshot-save -feature -Vulkan`, and verify the snapshot list still contains v1 before any write. Save PID/log ownership and stop on snapshot-load, port, or AVD-name mismatch.

- [ ] **Step 3: Download/verify/install 16 APKs**

Run locked installer sequentially. After each install, verify package/version/signer/launcher and save a per-app report. Any failure stops before setup and leaves v2 draft.

- [ ] **Step 4: Execute setup adapters**

Run version-bound onboarding/permission steps and postconditions for all apps. Keep Google baseline roles. Inspect screenshots for every warning/failure; no warning counts as pass.

- [ ] **Step 5: Update evidence docs and checkpoint commit**

Record actual results separately from offline tests. Commit only source/docs, never APK cache, snapshot files or runtime reports.

---

### Task 11: Seed and verify all shared/app datasets

**Files:**
- Runtime reports/evidence only unless a live mismatch requires a TDD source fix.
- Modify after verified evidence: the exact adapter module from Tasks 5–8, its named test file, `design/modules/guitraverse_mobile_baseline_design.md`, and `design/changelog/2026-08.md`.

- [ ] **Step 1: Apply shared seed and read-only verify**

Require expected counts/IDs/shapes for core providers/files/media/default roles. On mismatch, write a failing fixture/test before changing code.

- [ ] **Step 2: Apply file/media adapters**

Apply and independently verify Markor/Gallery/Draw/Recorder/VLC/Retro data.

- [ ] **Step 3: Apply private DB adapters**

Apply one adapter at a time with backup/rollback evidence and GUI relaunch. Verify non-seed rows remain.

- [ ] **Step 4: Apply specialized adapters**

Verify map, markers, tracks, MiniWoB and baseline role state. Simple SMS data visibility waits for overlay GUI smoke.

- [ ] **Step 5: Run full read-only data gate**

Certificate input must show every mandatory `data_verified=true`; otherwise v2 remains draft.

---

### Task 12: Run 16-app GUI smoke, publish v2, and prove isolation

**Files:**
- Runtime evidence: per-app screenshots/results and release certificate.
- Modify: `design/CURRENT_FRAMEWORK.md`
- Modify: `design/RESEARCH_GOAL.md` only for achieved evidence boundaries.
- Modify: `design/modules/env_and_config.md`
- Modify: `design/modules/guitraverse_mobile_baseline_design.md`
- Modify: `design/changelog/2026-08.md`

- [ ] **Step 1: Run sequential 16-app GUI smoke**

Start each app from controlled builder state, handle only adapter-declared onboarding/runtime preconditions, capture two evidence frames, and verify a seed representative plus one shape-specific surface. Simple SMS uses an independent read-only overlay role switch and proves the baseline role restores afterward.

- [ ] **Step 2: Generate draft certificate and audit failures**

Require 16/16 install/setup/data/gui passes and shared domains pass. If any failure remains, publish only draft/partial report and do not save v2.

- [ ] **Step 3: Save and list v2 snapshot**

Only with a ready certificate, save `guitraverse_mobile_seed_v2`, list it, verify v1 still exists, and bind snapshot evidence to manifest/lock/code hashes.

- [ ] **Step 4: Run two-overlay isolation acceptance**

Run A mutates one shared Provider, one `/sdcard` file, one app-private DB row and one system setting; verify the expected four failures, destroy A, start B, and require every v2 data/role/app gate to return true.

- [ ] **Step 5: Run final verification and commit docs**

Run all seed-focused tests, adjacent Android lifecycle/API tests, py_compile, PowerShell plan mode and diff check. Update current docs with exact offline/live/saved-frame/GUI-smoke/snapshot evidence separated. Commit exact docs/source; keep branch local and do not push.
