# Repository working rules

## Development navigation

For current stepwise traversal work, start with [DEVELOPMENT.md](DEVELOPMENT.md)
and its module/test index. The active framework is now `src/regrow/` directly
under this GUI-ReWalk root. Historical worktrees under artifacts are preserved
evidence, not development targets. Other framework work retains its existing
module routing. The project name is regrow; this does not rename historical imports.
Keep daily work notes in `devlog/YYYY-MM-DD.md` and its date index.

Before changing framework code:

1. Read `design/CURRENT_FRAMEWORK.md` (the short global index and shared
   contracts).
2. Read only the matching current-state document(s) listed in its module map.
3. Read `design/changelog/` or other historical documents only when the task
   depends on an earlier decision, experiment, or regression.

For every code change under `src/regrow/` or `gui_rewalk/`, or a behavior-affecting change under
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
synchronize the approved source export to `melonthrower/regrow`
repository without asking for push permission again. User update (2026-11-04):
keep this repository public; exclude API keys and other credentials. Development
snapshots must explicitly distinguish unapproved drafts and unverified behavior
from accepted changes; synchronization does not approve Prompt modifications. This is separate from the
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

## Framework simplicity memory (user confirmed 2026-10-16)

- Keep each business decision in one responsible implementation: recognition identifies objects; traversal selects and advances work; records persist accepted results. Consumers reuse that implementation instead of independently interpreting the same rule.
- Keep one authoritative record for each fact. Select history and prompt material from those records; do not maintain parallel summaries that require manual synchronization.
- Design each call from its question and required output, then select only necessary material. Do not construct the entire ledger first and trim it in rendering.
- Add rules only for an explicit requirement or evidenced failure. Put deterministic checks in code; do not automatically turn each failure into a permanent prompt prohibition. Retain semantic guidance the model needs to answer correctly.
- Replace superseded logic in the same change, including obsolete branches, forwarding interfaces, and current documentation. Preserve historical evidence outside the active maintenance path.
- Group cohesive responsibilities in readable files. Avoid trivial forwarding files and avoid mixing recognition, scheduling, and persistence merely to reduce file count.
- For each change, show the concrete problem, responsible implementation, and retired logic. For model-behavior changes, also show representative complete prompt/history/output. Use proportionate verification and the required unfamiliar-reader review; do not substitute a short excerpt or schema validity for semantic correctness.
- When a small requirement needs the same judgment patched in many places, inspect ownership and interfaces before adding patches. Necessary cross-module wiring is allowed; duplicated business decisions are the warning sign.
- Next agreed focus: first trace foreground/interactive-region information through recognition, scheduling, candidate selection, execution checks, and registration. Separate scene advice from evidence-based operation validation, preserving task ownership and actual-action evidence. Then consolidate history selection at its production entry. These are pending work, not implemented or accepted behavior; do not expand features before clarifying these chains.

## Traversal responsibility memory (user confirmed 2026-10-16)

Luna interprets current UI semantics and actively explores; the framework supplies relevant historical identities/knowledge so Luna can distinguish old objects from new, maintains stable records and graph relationships, and executes/verifies actual operations. Do not expect Luna to remember all prior controls without supplied context. Improve (1) semantic structure registration, (2) framework visual recall and identity association with Luna confirmation, and (3) informed exploration using those records.

Foreground is a shared prompt concept used where needed, including action selection, not exclusively discovery. Observed objects and visual candidates are evidence aids, not an operation whitelist; absence is not proof of inoperability, and a match is not proof of operability or success. Keyboard/global actions require their focus and scope to be considered. Do not introduce mandatory per-step foreground output merely to share its definition. These principles supersede earlier suggestions to restrict foreground guidance to discovery. Existing interactive_regions gates still operate; changing their restrictive use is pending implementation. Do not claim this memory edit removed them. Preserve current-region priority, task/preparation ownership, shared identity, and summary timing.

## 纠错信息可读性记忆（用户确认 2026-10-22）

- 给用户解释问题和给 Luna 提供纠错上下文时，使用具体控件名、所属区块和简短的问题描述；同名对象只补充必要的区分信息。
- 不把 JSON 路径、数组下标或通用“格式错误、按格式修订”当作错误说明。底层路径和完整校验堆栈留在调试日志。
- 纠错说明必须针对最新失败回复，说清哪个对象、哪里有问题、实际内容和必要要求；不要重复整份回复来代替定位问题。
- 不在每个对象、每轮历史中重复固定解释，不堆括号补充说明。共享字段含义在定义处说明一次；上下文只提供本次判断需要的材料。
- 本记忆是后续实现和沟通要求，不表示现有纠错实现已经修改或验证。

## 功能实现与验证方式偏好

用户于2026-10-22明确要求：不要自行增加发送指纹、图片哈希、额外工具扩展或为这些扩展编写测试。不要将功能工作扩大成审计工程。实现已对齐的功能后，选少量当时的真实上下文和截图，沿正常框架调用 Luna，检查实际回复和登记结果；发现问题就针对修复。该要求优先于此前会导致扩大审计或验证范围的约定。

## 词项/字段对齐与变更前讨论（用户确认 2026-10-23）

- 每当一个词项/字段出现问题，或准备修改它的定义、输入输出、解释方式、判定条件及引发的行为，先调查现状，再用定义和具体示例与用户讨论清楚；不得先改实现或 prompt 再解释。
- 对齐时明确四件事：它表示什么、不表示什么、谁负责判断和写入、变化后框架应该做什么。给出具体正例、反例和必要边界例；优先使用当时的真实案例，并区分已有事实与拟议行为。
- 修改前展示“当前定义/行为 → 问题及原因 → 拟修改定义/行为”，点明会影响哪些已有约定。不能只说“理解了”，不能在实现时偷偷增加没有对齐的前提、门槛或另一套判断。
- 讨论清楚后按用户授权范围执行；如果实现中发现需要改变已对齐的含义，再拿出具体例子讨论。不能以重命名字段、增加校验或修复 bug 为由绕过语义对齐。
- 始终分别说明：已约定的目标语义、代码实际实现、真实验证结果。确认定义不等于代码已实现，程序检查通过不等于模型/GUI行为已经接受。
- 确认后的定义写回现有对象说明和 prompt，保持一个维护来源；不另建需要手动同步的平行术语表。以下是协作及目标语义约定，不宣称当前候选已全部实现或验收。

当前核心约定：
- task 是待解决探索问题的唯一清单。Luna判断问题及进展，框架保存归属、状态和真实过程；不在 tasks 之外再维护必须清零的“清点疑问清单”。pending、blocked 均表示未解决；blocked 可先保留，继续顺序中的其他可推进任务。
- knowledge 是对控件或区块已有的认识，包含适用条件和不确定性，归对应对象保存；后续任务直接使用，不另存一套重复的任务答案。
- inventory 服务于本次给定范围的考虑和必要任务提出，不是另一套待解决问题，也不成为区块完成的第二道独立门槛。
- 区块探索完成：已经进行过任务提出，且本区块范围内有效任务均已解决。第一次提出任务前不能因空列表判完成；不额外要求总结刷新、所有历史控件重现或每个按钮都点过。
- 离开区块与区块完成不同：当前没有可推进工作时可转去其他区块，同时保留未完成任务；不为了把完成标记置真而困住遍历。

共同核对例：历史 Show All 当前未出现且不影响已有任务，不因此强制解释、补查或新建验证任务；“闹钟”标签用途明显但目标内容尚未了解，仍须提出入口探索任务；某任务暂挂而下一任务可执行，继续下一任务；对象知识已足够回答原问题时直接结算，不要求重复提交任务答案。漏任务修任务提出，任务困难落回对应 task，不增设平行完成标准。

## Prompt 泛用性与审阅顺序（用户确认 2026-11-02）

- 通用 Prompt 的正文及正反例不使用具体应用名称或应用专属场景。正反例应以不依赖特定应用的对象关系、观察差异和判断依据说明规则，不能把遇到的个案直接写成通用示例或专用处理规则。
- 真实应用案例可用于与用户讨论需求、诊断及行为验证；这不等于允许将案例写入通用 Prompt。实际调用的截图、任务和历史仍保留真实上下文，不为泛用性删减验收材料。
- 所有 Prompt 修改先向用户展示设计理由、完整候选及修改对照，用户确认后才能修改源文件；审查、讨论或打包请求不视为实施确认。
- 本次纠正：曾把用于解释登记范围的具体应用案例直接拟为 Prompt 正反例，混淆了讨论材料与通用提示。后续先提炼可迁移的判断依据，再编写通用示例。本条是协作要求，不表示相关 Prompt 已修改或验收。
