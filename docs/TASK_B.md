# Task B implementation and verification

## Transaction flow

1. `HotStuffDemo.submit()` validates the request and inserts it into the shared
   pending pool. It does not change balances or account nonces.
2. `select_transactions(parent)` selects pending transactions in insertion order,
   with a default limit of five. It excludes authenticated identities on that
   branch, retaining transactions on abandoned proposals for reproposal.
3. Task A certifies blocks and commits a consecutive three-chain. The provided
   `dispatch_qc()` passes ordered committed IDs to each replica's
   `Node.execute_committed()`. All IDs are checked before any transaction runs;
   reversed delivery or skipping an earlier unexecuted payload is rejected
   before changing application state.
4. `StateMachine.apply()` validates and executes transactions in block/payload
   order. Insufficient funds produces a final `rejected` receipt without changing
   balances. Successful execution produces a `committed` receipt.
5. `Node.execute_committed()` saves the result of every committed payload position
   in `StateMachine.execution_receipts`, keyed by block and position. Re-delivery
   returns the first result without executing again, including rejected entries.
6. `finalize_transactions()` removes entries only when a canonical terminal
   transaction receipt exists. A malicious attempt cannot clear a legitimate
   pending request by borrowing its ID.

## B5 batch configuration

`POST /api/config/batch` accepts `{"max_txs_per_block": 2}`. Positive integers
are accepted; bools, zero, negatives, strings and non-integers are rejected.
Limits 1, 2 and 5 are tested through real consensus and available in the dashboard.
Reset restores 5.

## B6 signature and identity policy

Signatures use Ed25519 from `cryptography==50.0.2`. Verification uses an account's
public key. Reproducible classroom private seeds and their public keys are in
`backend/blockchain.py`; these are public test fixtures.

The signed bytes are UTF-8 JSON, sorted by key and without whitespace. The exact
fields are `chain` (`COMP5567-HotStuff`), `sender`, `receiver`, `amount`, `nonce`.
The signature is a hex-encoded Ed25519 signature. The identity is `Tx-` followed
by the first 24 hex digits of SHA-256 over those bytes. It does not depend on the
signature string or its hex case. Previous HMAC signatures are not compatible.

Admission verifies the sender signature. Execution verifies it again and
recomputes the ID before reading any cached receipt. Removing the signature
fields from a `Tx-` transaction cannot convert it into an unsigned transaction.
Malformed signatures, modified payloads, wrong account keys and relabelled IDs
are rejected without changing balances, nonces or terminal receipts.

All admissions and executions require signatures, including the dashboard.
Missing or null signature/nonce fields are rejected at the HTTP boundary; direct
admission also rejects unsigned requests. The old `Tx1`, `Tx2`, ... unsigned path
is removed. The browser uses native Web Crypto Ed25519 to sign the same canonical
bytes with the same public classroom fixtures; no server signing endpoint exists.

## Nonces, retries and invalid proposals

- Every account's nonce starts at 0. Admission accepts the next nonce after the
  current nonce and its contiguous pending queue. For example, pending nonces
  0 and 1 allow nonce 2 but reject 3. At most one distinct pending payload may
  use an account/nonce pair. Nonces do not advance on admission or proposal.
- An identical authenticated retry returns the same pending transaction, or the
  same final receipt in the API's transaction state. It does not re-enter the pool.
- Only committed execution consumes a matching nonce, once. Authenticated
  insufficient-funds execution also consumes that nonce and has a final receipt.
- Invalid identities, signatures and wrong nonces receive a final execution
  receipt for that block/position but do not reserve a canonical transaction
  receipt. Thus a malicious block cannot permanently occupy a legitimate
  transaction's identity. A later valid occurrence can execute once; replaying
  the original rejected block always returns its original rejection.
- `GET /api/state` exposes all position results as `execution_receipts`; the
  dashboard receipt list includes both successes and rejections. Canonical
  receipts remain the source of admitted transaction status and deduplication.
- Unauthenticated ancestor entries do not exclude legitimate pending requests.
  A committed entry without a terminal receipt does not exclude later requests
  either. This permits a previously premature nonce to execute after earlier
  nonces commit, while uncommitted authenticated ancestry still prevents packing
  the same pending request twice on one branch.
- Recovery copies balances, canonical/position receipts and nonces from a live
  peer. Reset clears these states and restores every nonce to 0.

## Signing client

Start the backend and run from the repository root:

```bash
python -m tools.sign_transaction Alice Bob 10 --nonce 0
python -m tools.sign_transaction Alice Bob 10 --nonce 0 --submit
```

The first command prints the signed JSON without sending it. The second posts
to `http://127.0.0.1:8000/api/transactions`; `--url` changes the demo base URL.
Read `GET /api/state` for the current `nonces` and advance consensus with the
dashboard or `POST /api/control/step`. Repeating the same command is idempotent.
The dashboard chooses the next nonce after the pending queue automatically.
Its retry button resends the previous signed request unchanged, even after commit.

## Verification and AI assistance

```bash
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
python -m unittest discover -s extensions_tests -v
```

The core suite includes HTTP validation, signed retries and the offline client.
`extensions_tests/test_security.py` checks public-key verification independently
with the library API, tampering, wrong keys/domain, receipt poisoning, forged
identities, nonce use, recovery and real-consensus attack regressions. CI runs
B5 and B6 on each PR and push to main. Captured outputs are in `results/`.

The public tests were adapted to B6's required signature fields using signed
fixtures in `tests/helpers.py`, while retaining admission, batching, orphan,
insufficient-funds and idempotency assertions. The former hardcoded `Tx2`
expectation now uses the submitted transaction's payload-derived ID. Security
regressions cover the former unsigned API/execution bypass and rejected block
replay. There is no signature-disable mode.

## Task B acceptance map

| Item | Implementation and evidence |
| --- | --- |
| B1 (5) | Strict accounts/amount validation, signed admission, pending pool, no balance/nonce changes; core/API tests. |
| B2 (5) | Default five, chosen-branch deduplication, empty blocks and orphan reproposal; core, batch and security tests. |
| B3 (8) | Real consensus commitment gates ordered execution; prevalidation of all IDs, dependent transfers and replica agreement. |
| B4 (7) | Success/failure records, canonical ID deduplication, position-level replay protection and final pool cleanup. |
| B5 (2) | API/dashboard batch limits 1/2/5, invalid setting rejection, real-consensus batch tests. |
| B6 (3) | Standard Ed25519, canonical domain/payload, dual verification, contiguous nonces, stable retries and recovery. |

These are verified technical behaviors, not an awarded mark. Report, presentation,
live demonstration and individual-contribution deliverables remain separate.

AI assisted the existing Task B implementation and this review/fix: the affected
functions are `sign_transaction`, `verify_transaction`, `transaction_id`,
`verify_transaction_identity`, `StateMachine.apply`, `HotStuffDemo.submit`,
`select_transactions`, `finalize_transactions`, `Node.execute_committed`, and the
signing clients' `transaction_request`, `main` and browser `signTransfer`, plus
the dashboard submission and receipt display. Assistance included code,
failure reproduction, automated tests, CI and this explanation. No human review
or ownership is asserted here. `changes.md` remains unchanged as requested; the
final submission's actual contributions and disclosure still need reconciliation.
