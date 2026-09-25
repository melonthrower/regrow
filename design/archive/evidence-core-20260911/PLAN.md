# Independent evidence-first explorer implementation plan

Goal: implement the approved current-observation/action/evidence loop independently and evaluate records against the VLC Simple Preferences example.
Architecture: immutable frame observations and delivered-action receipts are the primary record; optional Region/function notes and cross-frame identity hypotheses are separate derived records. One Luna call per observed frame; no mandatory second reviewer, canonical IDs, State classification or task reconciliation.
Execution: root agent only, following executing-plans; use focused tests before implementation and verify before claiming success. No subagents (repository instruction).

Files: new core/evidence_explore/{protocol,records,runtime}.py, a standalone desktop entry point, focused tests, current module document and monthly changelog. Existing exploration runtime remains intact.

- [x] Implement framework-owned frame/control/action IDs, immutable record storage and natural-language export; tests for receipt binding and provenance.
- [x] Add compact Luna schema: current surface/controls, previous-action outcome, proposed next action, optional Region/function notes. Bad optional notes must not discard observations or receipts.
- [x] Add one-call loop using existing model transport and attached desktop execution; frame-local controls bind same-turn actions, disabled controls rejected, current box/surface bounds checked. Append planned/delivered/observed separately.
- [x] Test record contracts, graph errors isolated from actions, no fabricated action-supported claims, budget stop and delivery failure.
- [x] Run bounded supervised live VLC preferences experiment, up to 16 Luna requests and 12 GUI actions including restoration/Cancel. Model receives exploration scope and safety constraints, not example answer/expected parameter values. Record natural functions/parameters/conditions plus screenshot/action evidence. Keep failures and unobserved facts explicit.
- [x] Review generated records against the seven-step example, update docs and commit only task-owned paths; integrate verified commit into original branch while preserving its existing modifications.

Acceptance: concrete physical controls; current foreground only; useful parent/child grouping and natural descriptions; actual dropdown values when observed; mode-change conditional observations supported by before/action/after; persistent navigation/footer identity as hypotheses with evidence; no invented co-visible causal edges. Report incomplete items rather than declaring broad general accuracy. Test downstream complex task execution only if this iteration directly reaches that stage; otherwise mark it untested.

Outcome: implementation and bounded evaluation completed; only dropdown and style-condition recording have positive live evidence. Early protocol failures consumed budget, so scrolling/Audio/full seven-step acceptance were not completed. This is not a claim that all acceptance targets passed.
