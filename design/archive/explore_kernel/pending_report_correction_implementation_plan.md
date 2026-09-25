# Pending Report Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Give Luna precise owner-settlement errors and deterministically release a pending Attempt after one failed correction without repeating the GUI action.

**Architecture:** `settlement.py` raises typed contract errors. `runtime.py` owns a per-attempt two-report budget, projects a correction card, and conservatively settles/fails the actual Operation when exhausted. No model output field or persistent graph schema is added.

**Tech Stack:** Python dataclasses, existing owner-centered contracts, pytest.

**Spec:** `design/modules/explore_kernel/pending_report_correction_design.md`

## Global Constraints

- One GUI action creates one ActionAttempt only.
- A correction turn cannot execute a GUI action.
- Maximum valid semantic reports for one pending Attempt is two.
- Do not parse natural-language reason to classify errors.
- Preserve user-owned `live_state_locator.py` and its test.

### Task 1: Typed Settlement Errors

- [x] Add RED tests for code/path/expected/received on owner, primitive, function Region and parameter errors.
- [x] Implement `SettlementContractError` and replace settlement ValueErrors.
- [x] Keep `resolve_action_operation()` callers compatible with ValueError.

### Task 2: Pending Correction Card and Budget

- [x] Add a RED runtime test: first repeated invalid report keeps pending and exposes a correction card.
- [x] Add a RED runtime test: second invalid report releases pending, records no-effect/uncertain and fails the actual Operation without another action.
- [x] Implement per-attempt count, structured context projection and deterministic forced settlement.
- [x] Treat `agent.decide()` two-parser-attempt exhaustion as an already exhausted pending report.

### Task 3: Prompt, Documentation and Verification

- [x] Add a short Prompt rule: correction card means action/page_report must be null and only previous_action may change.
- [x] Update current framework, action transition, agent context, runtime artifacts and changelog.
- [x] Run owner settlement/runtime tests, full explore-kernel focused regression, py_compile and diff check.
- [x] Commit exact task-owned paths and report saved/offline evidence separately from live acceptance.
