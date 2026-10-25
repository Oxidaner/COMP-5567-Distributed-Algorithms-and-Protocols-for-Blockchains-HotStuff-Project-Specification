# COMP5567 HotStuff Student Starter 2026

Implement the missing consensus (Task A, 35 marks) and blockchain-system
(Task B, 30 marks) functions. The accompanying project specification defines
the full 100-point assessment. This distribution intentionally has no working
consensus or transfer implementation. The dashboard and HTTP service start;
calling an unimplemented operation returns a clear TODO message (HTTP 501).

## Run

Python 3.10 or newer. From this folder:

```bash
python -m pip install -r requirements.txt
python backend/main.py
```

Open http://localhost:8000. Start runs one logical event every 0.8 seconds;
Next Step runs one event. A missing event pauses and remains available for
retry. Reset restores genesis, three balances of 100, and batch limit 5.
No reference solution is loaded or available through a mode switch.

## Task map

| Item | Marks | Student functions |
| --- | ---: | --- |
| A1 Proposal | 6 | HotStuffDemo.propose |
| A2 Safe voting | 8 | HotStuffDemo.vote; Node.extends, can_vote |
| A3 QC | 6 | HotStuffDemo.form_qc |
| A4 Lock and commit | 8 | Node.receive_qc |
| A5 Normal view changes | 2 | HotStuffDemo.next_view; Node.enter_view |
| A6 Optional recovery | 2 | HotStuffDemo.timeout, recover; crash paths |
| A7 Optional malicious behavior | 3 | inject_attack and validation/delivery changes; equivocation (2), second attack (1) |
| B1 Admission | 5 | HotStuffDemo.submit |
| B2 Payload selection | 5 | HotStuffDemo.select_transactions |
| B3 Execution | 8 | Node.execute_committed; StateMachine.apply |
| B4 Receipts and deduplication | 7 | StateMachine.apply; finalize_transactions |
| B5 Optional batch limit | 2 | configure_batch and payload selection |
| B6 Optional signatures and replay | 3 | Add sign_transaction, verify_transaction, transaction_id; signatures (2), nonce/replay handling (1) |

Shared functions have distinct responsibilities assessed under each row;
the same mechanism is not awarded twice. Keep public interfaces where possible.
You may add helpers. Do not change quorum three or bypass commitment.

## Integration contracts

* Implement Task A with empty blocks first. propose() should call
  select_transactions(parent) only for a nonempty pool; otherwise use [].
* Use the supplied event names: propose, vote, qc, next_view, timeout.
  Event data contracts are described in each TODO docstring.
* form_qc() validates and registers a QC, then calls dispatch_qc(qc).
  The provided helper calls Node.receive_qc() on replicas and obtains ordered
  newly committed block IDs. receive_qc() must not execute transactions.
* dispatch_qc() calls Node.execute_committed() for newly committed nonempty
  payloads, then finalize_transactions(). Empty payloads do not require Task B.
* execute_committed() must reject uncommitted IDs before any state mutation.
  StateMachine.apply() is an execution primitive, not an admission API.
* Keep transactions pending until commit; exclude only the selected parent
  ancestry during packing. A receipt status is committed (successful execution)
  or rejected (failed execution); both can belong to a committed block.
* B5 already has POST /api/config/batch with {"max_txs_per_block": 2}.
  Complete the handler's configure_batch() TODO. Reset restores 5.
* A7 already has POST /api/attacks with {"kind": "equivocation", "node_id": 1}.
  Implement attack injection and recipient-aware delivery as needed. Demonstrate
  conflicting proposals plus duplicate_vote or invalid_qc. Other nodes' identity
  cannot be impersonated under the simulator's trusted identity model.
* B6: add sign_transaction(), verify_transaction() and transaction_id() in a
  module of your choice. Extend Transaction and the request model to carry
  nonce/signature, add a signing client, and follow the specification. Ordinary
  signatures are sufficient; do not implement cryptographic primitives yourself.

The queue, API validation, fault switches, initial state, snapshot generation,
frontend and dispatch_qc are supplied infrastructure, not completed task credit.
The dashboard agreement badge compares live balances and committed chains only;
your tests must also inspect receipts and (for B6) nonces.

## Tests

These framework checks pass in the unmodified starter:

```bash
python -m unittest discover -s tests -p 'test_framework.py' -v
```

The following are acceptance tests. They are EXPECTED TO FAIL with TODO errors
until you implement the assessed functions. Do not skip or remove assertions.

```bash
python -m unittest discover -s tests -p 'test_task_a.py' -v
python -m unittest discover -s tests -p 'test_task_b.py' -v
python -m unittest discover -s tests -v
```

Task A uses empty blocks. Isolated Task B tests inject a committed-history fixture
instead of shipping a reference consensus implementation. This fixture is for
unit tests only; production execution must go through the actual Task A commit.
test_integration.py requires A and B together and retains six baseline cases.

Run the relevant optional tests only when claiming the corresponding extension:

```bash
python -m unittest discover -s extensions_tests -p 'test_recovery.py' -v
python -m unittest discover -s extensions_tests -p 'test_batch.py' -v
```

The five recovery/fault cases plus six integration cases preserve all eleven
original regression tests. Add your own A7 and B6 tests for attack/tampering,
wrong account, replay before/after commit, nonce progression and recovery.
Passing public tests is necessary evidence, not a complete grading rubric.

## Submission and demonstration

Follow the specification: report at most six main-text pages, slides, source,
tests/results, README, changes and individual contributions. Present for four
minutes, operate the running system live for four minutes, then answer questions
for two minutes. A prerecorded replacement earns 0/10 live-demonstration marks.

Record your starter version and final commit. Cite reused material and AI help;
copying the completed public reference into the TODOs is not original work.

## Group workspace

This repository imports the official **student starter** at commit
`1d7d70b2c480cd67b60c4b2e581bdbdc31220dd2` (29 September 2026).
`STARTER_VERSION.json` names `71ef92e...` as the earlier reference commit;
that is **not** the student starter baseline. The imported assessed functions
are still TODOs. The original course specification is in
`docs/COMP5567_HotStuff_Project_2026.pdf`.

Read `docs/WORK_PLAN.md` for three design choices, five function owners,
milestones and the acceptance map. Read `AGENTS.md` and `.agent/WORKFLOW.md`
when using an AI coding assistant. Record actual names, student IDs, commits,
tests, AI assistance and incomplete requirements in `changes.md` before
submission.

Create a personal branch from the shared `main`, make a small PR for each
assessed item, and review another member's PR. Run the relevant isolated
suite while working, then the full suite before merging:

```bash
python -m unittest discover -s tests -p 'test_framework.py' -v
python -m unittest discover -s tests -p 'test_task_a.py' -v
python -m unittest discover -s tests -p 'test_task_b.py' -v
python -m unittest discover -s tests -v
```

GitHub Actions runs framework and core acceptance as separate checks. The
core check is expected to fail while TODOs remain; do not weaken its
assertions to turn it green. The manually started `Selected optional tests`
job can check A6, B5 or both independently. Add automated A7/B6 checks if
claiming those extensions.

The assessed implementation, report, presentation, live demonstration and
final submission archive remain group work. `results/README.md` describes
how to capture genuine test outputs after implementation.
