# Stepwise quality inspector implementation plan

Root implements inline; fresh unfamiliar reader reviews after implementation.

Goal: read-only automated graph inspection and Codex per-call registration inspection,
with portable visual reports and independent, bounded reviewer accounting.

User-approved contract: reasonable alternative partitions are accepted; later refinement
is not an earlier mistake. Unknown, unchecked and erroneous are distinct. Luna graph
checks use at most one original frame per request. No source graph mutation, automatic
identity merge, new traversal prompt, or collection change.

- [x] Add focused failing tests: frozen source immutability, source-image containment,
  temporal snapshot differences, coverage, cited judgments and budget failures.
- [x] Implement stepwise snapshot/call adapters and structural checks; reuse existing
  source files rather than translating into the older Page/Variant graph contract.
- [x] Implement Codex exec and Luna API reviewers, one request per item, explicit
  independent invocation/HTTP limit, preserved failed calls and strict citations.
- [x] Implement standalone browser report with filters, images, record differences,
  reviewer judgments and append-only human feedback.
- [x] Run focused tests and actual Clock read-only report generation; inspect browser.
- [x] Fresh-reader review, fix findings, focused re-review; real reviewer calibration explicitly omitted by user (zero paid calls). No live GUI execution is needed for this tool.
- [ ] Update current contracts/changelog, commit task-owned changes, synchronize
  verified source export and deliver source-pinned design/change map and review ZIP.

Verification scope: Tier 2 for the new reader/reviewer/report tool. Model quality
validation is reported separately from offline plumbing, no accuracy claim from mocks.
Work in new files in the shared checkout to preserve the extensive pre-existing edits;
do not stage those edits. Design and concrete source map travel with the final export.
