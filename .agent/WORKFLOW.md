# Human-led implementation workflow

This course permits AI assistance only for the implementation or debugging of
**individual functions**. A human member owns each function, its integration,
tests, explanation and submission. Before assisting, identify the specific
function and the member's question. Stop at that function's scope; ask the
owner to integrate and explain it. Mark AI-assisted code clearly at the
function and record the function, help received and owner in `changes.md` for
the report. Never import completed reference solution code into assessed TODOs.

For each owned function:

1. Read its starter docstring, the applicable A/B row in the specification and
   related public tests. Confirm the caller/callee contract with other owners.
2. Work in a personal branch/worktree. Change only the function and minimal
   supporting interface/tests required for that item; preserve the supplied
   event queue, API routes, `dispatch_qc()` and visible state.
3. Run the isolated suite for the item, then the full core suite when the
   dependent item is ready. Report both passing and failing cases honestly;
   untouched TODOs are expected to fail during development.
4. In the PR, state requirement ID, changed functions, review partner, exact
   test command/results and AI assistance. Merge only after another member
   checks the interface and the core CI result is understood. Update
   `changes.md` with the actual contribution and incomplete features.

For Task A, prove empty-block consensus before transaction integration. For
Task B, execute only through committed IDs; the isolated fixture does not
replace real consensus. If claiming an extension, add and run evidence for
its edge cases. Before submission, capture genuine outputs in `results/`,
complete the contribution table, rehearse the live operation and audit the
archive against `docs/WORK_PLAN.md`.
