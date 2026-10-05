# Repository working rules

## Project identity and development memory

The project is named **regrow**. Use this name in current explanations and new
documentation. `GUI-ReWalk`, `gui_rewalk`, and dated source directories are
historical filesystem or import names; this naming decision does not rename them.

For current stepwise traversal work, start with [DEVELOPMENT.md](DEVELOPMENT.md)
and its [code map](design/modules/stepwise/CODE_MAP.md). Organize changes around
discovery and task preparation, action selection and execution, result updates,
and their shared recovery, map/history, identity/evidence, and runtime modules.
Follow request construction through validation, registration, and the next read;
keep shared logic in one implementation. Check the active checkout and preserve
unaccepted working-tree candidates instead of treating every file as verified.

Before changing framework code:

1. Read `design/CURRENT_FRAMEWORK.md` (the short global index and shared
   contracts).
2. Read only the matching current-state document(s) listed in its module map.
3. Read `design/changelog/` or other historical documents only when the task
   depends on an earlier decision, experiment, or regression.

For every code change under `gui_rewalk/`, or a behavior-affecting change under
`ops/` or `tools/`:

1. Append an entry to `design/changelog/YYYY-MM.md`.
2. Update `design/CURRENT_FRAMEWORK.md` only when an entry point, default,
   cross-module architecture, shared data contract, output layout, supported
   platform, module routing, or global known-risk status changes.
3. Update the matching `design/modules/*.md` current-state document when module
   behavior changes.
4. Record the verification command and result in the monthly change log. Do not
   claim runtime validation
   when only static or offline checks were run.

## Research prototype scope

This repository prioritizes rapid research iteration, testing ideas, and making
the requested current functionality work. It is not a production-readiness
project. Prefer the simplest readable implementation that is sufficient for the
current experiment.

Unless the user explicitly requests it or the current experiment directly
requires it, do not add production-grade abstraction or generalization,
comprehensive compatibility or migration layers, deployment or operations
hardening, load/performance/scale/fault-injection testing, exhaustive edge-case
handling, or stacked defensive layers. Verification should demonstrate that the
requested function and directly affected paths work; it is not intended to prove
production reliability for the whole system.

Research scope does not relax the non-negotiable boundaries: never expose
secrets, never present static or offline checks as runtime validation, and avoid
damaging research data or artifacts. Real devices, irreversible live actions,
and safety-sensitive work still require proportionate validation and an explicit
account of what was and was not exercised.

Choose the smallest sufficient verification tier from the changed contract and
its impact. Test volume must be proportional to risk; a test mentioned in an old
change-log entry does not become mandatory for later unrelated work.

- **Tier 1 — documentation or non-behavioral change:** review the rendered/text
  change and run applicable documentation, diff, or static checks. Runtime tests
  are not required unless the edit changes an executable contract.
- **Tier 2 — module-local behavior change:** run focused tests for the changed
  behavior, tests for directly affected adjacent contracts, and applicable
  syntax/static checks.
- **Tier 3 — shared framework contract change:** for changes to shared data
  contracts, entry points, defaults, schema, Router, resume, completion, or
  cross-module architecture, run focused tests for the directly affected shared
  contracts, necessary adjacent-contract tests, and applicable syntax/static
  checks. A shared-contract change does not automatically trigger the full
  framework regression gate.

Run the explicit full framework regression gate in Section 8 of
`design/CURRENT_FRAMEWORK.md` only when the user requests it or when preparing a
release, baseline, certification, or formal external result. Only when that gate
is explicitly required, record any omitted command, its reason, and the resulting
validation gap.

Never place API keys, tokens, passwords, private endpoints, or other credentials
in documentation or source defaults. Historical documents under `research/` are
snapshots, not the current source of truth.

## Research-goal memory

`design/RESEARCH_GOAL.md` is the durable source of truth for the current research
question, contribution boundary, target method chain, and experiment acceptance
criteria. Read it before work that changes paper framing, Region/capability
claims, task synthesis, trajectory collection, or evaluation design.

Update it in the same task when those goals or evidence boundaries change. Mark
an item complete only after its stated implementation and verification are both
finished. Remove rejected, superseded, or disproven directions from the current
document instead of retaining an obsolete-plan section; Git and
`design/changelog/` provide history. Unchecked goals are not current framework
truth and must not override `design/CURRENT_FRAMEWORK.md` or module documents.

When understanding or changing Region traversal, experience reuse, instruction
generation, or graph-guided collection, also read
`design/REGION_TRAVERSAL_ALIGNMENT.md`. Keep its worked examples (including the
Gmail monthly-report if/else task), code locations, and implementation status
current in the same task as relevant changes. Examples explain the intended
design; they are not application-specific rules to encode in the framework.

## Root implementation and independent review

Use the root agent directly for investigation, planning, implementation, tests,
and reporting. Do not delegate implementation or testing by default.

The user explicitly requires a fresh unfamiliar-reader agent after every change.
This is standing authorization for review, including prompt, code, configuration,
and documentation changes. Give the reviewer no conversation history or intended
conclusion: first let it infer meaning and behavior from the changed artifact and
necessary adjacent context, then compare that reading against the user's intent.
Preserve the independent reading and the subsequent comparison separately. Resolve
material findings and obtain a focused follow-up review of resulting revisions
before reporting completion; do not recursively review review reports alone.

Other subagents still require an explicit user request. Keep the task in the root
agent even when it spans multiple files or modules; use a short plan only when
helpful, without turning small changes into delegated work packages.

Do not mechanically rerun a command that already has complete, credible evidence
unless code changed after verification, the result failed or is incomplete, an
important environment difference exists, or the user explicitly requests an
independent rerun.

## Verified-change checkpointing

At the start of every change task, record `git status --porcelain` and treat all
pre-existing modifications as user-owned state. After the task's requested
success criteria, required documentation updates, and smallest sufficient
verification tier all pass, create a local Git commit without waiting for a
separate save request.

Stage only the exact task-owned paths or hunks. Never use `git add .` or
`git add -A`, and do not include pre-existing changes, unrelated edits, runtime
artifacts, caches, or temporary test directories. Before committing, inspect the
staged path list and summary and run `git diff --cached --check`.

Do not commit when required verification failed or remains incomplete, when the
task's changes cannot be separated safely from pre-existing work, or when the
staged scope contains an unexpected path. Report that condition instead. An
offline Tier 1, 2, or 3 task may still be committed when that is the required
verification scope; record any live or full-gate validation that was not run.
Create an incomplete checkpoint only when the user explicitly requests one.

Automatic saving means a local commit only. Do not push, open a pull request,
tag a release, or modify a remote unless the user separately requests it. Report
the commit hash, committed scope, verification result, and remaining worktree
state at handoff.

## Remote evidence transfer safety

For the prepared personal-server workspace or an SSH/Handoff continuation, read
`design/SERVER_HANDOFF.md` for the environment, current stopped runs, and evidence
boundaries before resuming GUI work.

Never recursively download an entire remote run root with `scp -r`. Remote
`repo/` directories may contain `OSWorld` symbolic links, and recursive SCP
dereferences those links. Use `ops/pull_remote_run_evidence.ps1`, which transfers
only `results/` and root-level run logs/status files, refuses symbolic links and
oversized evidence, and never downloads `repo/`, `OSWorld/`, or deployment
archives.

## Test files and historical designs

- Maintained automated tests belong in `tests/`.
- Put disposable test scripts, saved-frame probes, pytest temporary directories,
  and their outputs together in `artifacts/tmp_tests/<unique-task-or-run>/`.
  Set pytest `--basetemp` inside that run directory; parallel runs must use
  different directories. Do not create test directories at the repository root.
- Store superseded design documents and implementation plans in
  `design/archive/<topic-or-date>/`. Its contents are historical context, not
  current instructions. Keep current contracts in `design/CURRENT_FRAMEWORK.md`
  and `design/modules/`; monthly change logs remain in `design/changelog/`.
- Real traversal requests, replies, screenshots, checkpoints, and collected
  trajectories are research evidence, not disposable test output. Keep each run
  together under the runtime/data boundary; do not delete it merely because it
  is old or contains duplicate screenshots.
- Before cleanup, verify ownership, references, resolved paths, and that the
  producing process has stopped. Delete only confirmed disposable material;
  never follow dependency links such as `OSWorld` or a shared `artifacts` link.

## User communication preferences

- After each test round, package the report, referenced screenshots, relevant
  requests/replies and ledgers, related source/diffs, and verification logs for
  Astra in `to_astra/<test-name>/`. Include a ZIP with working relative report
  links and a short contents/version note. Remove credentials and private
  endpoints from exported copies, preserve original evidence, distinguish frozen
  runtime source from current source, and never overwrite an older delivery.

- When explaining GUI traversal or visual execution, show the corresponding real
  screenshot (or an existing evidence crop) for each step, with a short caption.
  Identify reused frames, blocked actions, and later recovery explicitly; never
  invent an execution screenshot for a step that did not happen.
- Keep explanations and documentation brief. Prefer screenshots and concise
  conclusions to long design documents; maintain only the necessary current
  contracts and verification records required by this file.

- Prefer one maintained execution path. Do not add CLI feature switches unless
  explicitly requested; consolidate accepted experimental behavior and remove
  superseded branches instead of retaining parallel legacy variants.

- Keep API and GUI budgets in framework accounting and enforcement; do not put
  remaining-budget counters into Luna prompts.

## Collection development boundary

Instruction-generation and trajectory-collection work must not modify the
traversal framework, its prompts, active runs, or source graphs. Develop and
verify collection changes separately, using a frozen, read-only graph and
separate collection outputs. Reuse existing visual matching through a pinned
read-only implementation; do not change traversal behavior to fix collection.
Keep control identity crops and click areas distinct: locate the recorded
appearance in the current screenshot, then compare Luna's coordinates with the
current click area. Missing or ambiguous visual evidence is not proof that a
coordinate is wrong, and geometric agreement is not proof of action success.

Collection graph routes are advisory. If a later route control is already visible
and operable on the current active surface, the collector may use it directly to
reach the current goal, skipping unnecessary navigation. This does not authorize
skipping required business prerequisites, condition observations, or confirmations.

## Traversal change review preference

For future traversal framework/prompt behavior changes, after focused verification,
ask an independent unfamiliar-reader agent to review the relevant generated prompts,
screenshots, and changed contracts. Address findings, then validate with an actual
Luna call on representative saved evidence before declaring the behavior accepted.
This is explicit user authorization for that review subagent, not implementation
delegation. Preserve requests/replies and distinguish saved-frame model validation
from executed GUI validation. Do not claim successful navigation without a real
post-action observation.

## Native framework validation requirement

For future framework or prompt behavior changes, acceptance tests must use requests
built by the normal framework entry points from real run records, including their
normal task, history, scope, and screenshot context. Use the actual Luna replies
unchanged and pass them through the framework's normal validation, correction,
and registration path. Inspect the resulting identities, tasks, and images;
schema validity or successful submission alone is not semantic acceptance.

Do not use hand-built or reduced prompt contexts, edited model replies, or isolated
crop-writer probes as behavior acceptance evidence. Saved-frame tests may use an
isolated copy of a real run, but must preserve its actual context and dependencies;
label them separately from live GUI execution. Unit/static checks remain auxiliary
code checks and cannot replace this framework-level validation. Preserve failed
calls and correction history, and report unresolved regressions as not accepted.

## Cohesive functionality and file boundaries

Keep reasonably independent, separable functionality in a dedicated file with a
clear responsibility and a small interface, so it is easy to locate and debug.
Consolidate shared logic there rather than duplicating it across workflow steps.
Reuse existing modules; do not split tightly coupled trivial helpers into many
files or introduce unnecessary abstraction merely to reduce file length.

## GitHub synchronization and design handoff

User authorization (2026-09-25): after each verified code/documentation batch,
synchronize the approved source export to the private `melonthrower/regrow`
repository without asking for push permission again. This is separate from the
workspace's existing origin. Preserve remote history; do not force-push. Do not
upload runtime records, screenshots, credentials, private endpoints, dependency
links, or unverified edits as accepted changes. A research snapshot must clearly
state its limited verification scope and does not imply a release/full gate.

After every design, deliver a separate design document and concrete change map
for external Astra review. Pin the map to the exported GitHub commit; include
repository-relative file paths, verified line anchors/ranges, function names,
current behavior, proposed edits, and acceptance cases. Label new files as new
(no invented existing line numbers). Distinguish proposed changes, implemented
changes, and behavior actually validated. If the source changes, issue a new
version rather than silently retaining stale line references. Include the
matching source/diff and a portable review package when needed.
