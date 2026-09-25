# API observation harness pilot — final scoped plan

User approved trying API subagent-style observation and asks about paper framing. Root implements; Terra testing remains stopped; old framework unchanged.

The first milestone deliberately isolates registration on frozen screenshots. Live refresh/dispatch would mix action errors with visual localization and is deferred until observation evidence warrants integration.

- [x] Native Responses inspect_region and update_inventory(commit); explicit history, bounded HTTP, immutable source and response evidence.
- [x] Square views with original coordinate mapping; keyed full-record upserts preserve unspecified records. Geometry/schema errors return tool feedback. Commit validates references and frozen-frame restrictions.
- [x] Independent saved-image CLI with matched one-shot mode; old and existing evidence traversal defaults untouched.
- [x] Tests first; 10 harness tests and 27 directly adjacent tests pass.
- [x] Same-image/same-target/same-model API pilot on Writer/Calculator. Seven successful HTTP, one network failure, zero GUI. Target localization 4/5 vs5/5; unequal cost, no broad accuracy conclusion.
- [x] Current docs, research hypothesis/evidence boundary, monthly verification log.

Deferred: live refresh with stale-view invalidation; runtime integration and shared per-run budget; changed-before-dispatch; delete/split of committed identities; live smoke; held-out equal-cost experiments. These are not current implemented capabilities. Tool update preserves unspecified records, not arbitrary unspecified fields inside a supplied control record.
