"""Deterministic event queue. One step is one visible protocol action.

Transport and the timeout pacemaker are simulated by this coordinator. Votes,
locks, blocks, committed chains and account execution remain per-node state.
"""
from collections import deque
from copy import deepcopy
from dataclasses import asdict

from .blockchain import INITIAL_BALANCES
from .models import Block, QC, Transaction
from .node import Node


class HotStuffDemo:
    NODE_COUNT = 4
    QUORUM = 3
    TIMEOUT_TICKS = 3

    def __init__(self):
        self.reset()

    @property
    def leader_id(self):
        return (self.view - 1) % self.NODE_COUNT + 1

    def log(self, message: str, kind: str = "info"):
        self.log_sequence += 1
        self.logs.append({"id": self.log_sequence, "step": self.steps,
                          "view": self.view, "kind": kind, "message": message})

    def reset(self):
        genesis = Block("B0", None, 0, 0)
        genesis_qc = QC("B0", 0, (1, 2, 3, 4))
        self.view = 1
        self.nodes = [Node(i, genesis, genesis_qc) for i in range(1, 5)]
        self.blocks = {genesis.id: genesis}
        self.qcs = {genesis.id: genesis_qc}
        self.transactions: dict[str, Transaction] = {}
        self.mempool: list[str] = []
        self.votes: dict[str, set[int]] = {}
        self.qc_scheduled: set[str] = set()
        self.events = deque([("propose", None)])
        self.logs = deque(maxlen=400)
        self.log_sequence = 0
        self.steps = 0
        self.running = False
        self.max_txs_per_block = 5
        self.next_tx_number = 1
        self.phase = "Ready for proposal"
        self.log("Genesis B0 committed · Enter View 1 · Leader N1", "view")

    def submit(self, sender: str, receiver: str, amount: int,
               nonce: int | None = None, signature: str | None = None) -> Transaction:
        """B1 implement transaction admission and mempool insertion.
        Return a Transaction; validate account names and a strict integer amount
        in [1, 1000000]. Invalid requests must not modify state. Allocate Tx1,
        Tx2, ... for the basic task. B6 may extend this interface for signed input.
        Do not execute transfers here."""
        if sender not in INITIAL_BALANCES or receiver not in INITIAL_BALANCES:
            raise ValueError("Unknown account")
        if type(amount) is not int or not 1 <= amount <= 1_000_000:
            raise ValueError("Amount must be an integer in [1, 1000000]")
        if (nonce is None) != (signature is None):
            raise ValueError("Signed transactions require both nonce and signature")

        if nonce is None:
            tx_id = f"Tx{self.next_tx_number}"
            self.next_tx_number += 1
        else:
            from .blockchain import transaction_id, verify_transaction
            if type(nonce) is not int or nonce < 0:
                raise ValueError("Nonce must be a non-negative integer")
            if not isinstance(signature, str) or not signature:
                raise ValueError("Signature is required")
            if not verify_transaction(sender, receiver, amount, nonce, signature):
                raise ValueError("Invalid transaction signature")
            tx_id = transaction_id(sender, receiver, amount, nonce)
            existing = self.transactions.get(tx_id)
            if existing is not None:
                return existing
            live = [node for node in self.nodes if not node.crashed]
            source = max(live, key=lambda node: len(node.committed_blocks)) if live else self.nodes[0]
            current_nonce = source.machine.nonces.get(sender, 0)
            if nonce < current_nonce:
                raise ValueError("Nonce has already been used")
            if nonce > current_nonce:
                raise ValueError("Nonce must equal the next account nonce")
            if any(
                self.transactions[pending_id].sender == sender
                and self.transactions[pending_id].nonce == nonce
                for pending_id in self.mempool
            ):
                raise ValueError("A transaction with this nonce is already pending")

        tx = Transaction(tx_id, sender, receiver, amount, nonce, signature)
        self.transactions[tx.id] = tx
        self.mempool.append(tx.id)
        self.log(f"{tx.id} submitted · {sender} → {receiver} · {amount}", "transaction")
        return tx

    def step(self):
        """Provided event dispatcher; a missing TODO pauses without losing work."""
        checkpoint = deepcopy(self.__dict__)
        try:
            if not self.events:
                self.events.append(("propose", None))
            action, data = self.events.popleft()
            self.steps += 1
            {"propose": self.propose, "vote": self.vote, "qc": self.form_qc,
             "next_view": self.next_view, "timeout": self.timeout}[action](data)
        except NotImplementedError as exc:
            self.__dict__.clear()
            self.__dict__.update(checkpoint)
            self.running = False
            self.phase = str(exc)
            self.log(str(exc), "todo")
            raise

    def propose(self, _):
        """A1 implement a leader proposal for the current view.
        Select a justified parent, allocate a unique block ID, populate the
        proposal and distribute it to live replicas. Register an empty vote set
        and enqueue ("vote", (node_id, block_id)) for the intended recipients.
        Call select_transactions(parent) only when the mempool is nonempty;
        otherwise use an empty payload, allowing independent Task A work.
        A6: handle a crashed leader using the timeout event. No balances change."""
        leader = self.nodes[self.leader_id - 1]
        if leader.crashed:
            self.phase = f"Leader N{leader.id} unavailable · waiting for timeout"
            self.log(f"Leader N{leader.id} unavailable in view {self.view}", "fault")
            if not any(action == "timeout" for action, _ in self.events):
                self.events.append(("timeout", self.TIMEOUT_TICKS))
            return

        parent_id = leader.high_qc.block_id
        parent = self.blocks.get(parent_id)
        if parent is None:
            raise ValueError(f"HighQC references unknown block {parent_id}")

        block_id = f"B{len(self.blocks)}"
        while block_id in self.blocks:
            block_id = f"B{int(block_id[1:]) + 1}"
        transactions = self.select_transactions(parent) if self.mempool else []
        block = Block(block_id, parent.id, self.view, leader.id, transactions, leader.high_qc)

        self.blocks[block.id] = block
        self.votes[block.id] = set()
        for node in self.nodes:
            if not node.crashed:
                node.blocks[block.id] = block
                self.events.append(("vote", (node.id, block.id)))

        self.phase = f"{block.id} proposed · awaiting votes"
        self.log(f"{block.id} proposed by N{leader.id} · parent {parent.id}", "proposal")

    def vote(self, data):
        """A2 implement proposal validation and one safe vote per replica/view.
        data is (node_id, block_id). Validate current leader, view, parent and
        its registered QC, then consult Node.can_vote(). Track voting state and
        distinct voters. Once a quorum is reached, enqueue a single ("qc", id)
        event. Reject invalid proposals without changing voting or account state.
        A6: schedule a timeout if this round cannot obtain a QC."""
        if not isinstance(data, tuple) or len(data) != 2:
            return False
        node_id, block_id = data
        if (type(node_id) is not int or node_id not in range(1, self.NODE_COUNT + 1)
                or type(block_id) is not str):
            return False
        node = self.nodes[node_id - 1]
        block = self.blocks.get(block_id)
        if block is None or block_id not in node.blocks:
            return False
        if (
            node.crashed
            or self.nodes[self.leader_id - 1].crashed
            or type(block.view) is not int
            or block.view != self.view
            or type(block.proposer) is not int
            or block.proposer != self.leader_id
        ):
            return False

        parent_qc = block.qc
        parent = self.blocks.get(block.parent_id) if type(block.parent_id) is str else None
        if (
            parent is None
            or block.parent_id not in node.blocks
            or not isinstance(parent_qc, QC)
        ):
            return False
        if parent_qc.block_id != parent.id or parent_qc.view != parent.view:
            return False
        if not self._valid_qc(parent_qc):
            return False
        if not node.can_vote(block):
            return False

        voters = self.votes.setdefault(block.id, set())
        if node.id in voters:
            return False
        voters.add(node.id)
        node.last_voted_view = block.view
        node.last_voted_block = block.id
        self.log(f"N{node.id} voted for {block.id}", "vote")

        if len(voters) >= self.QUORUM:
            if block.id not in self.qc_scheduled:
                self.qc_scheduled.add(block.id)
                self.events.append(("qc", block.id))
        else:
            possible = len(voters)
            for candidate in self.nodes:
                if candidate.id in voters or candidate.crashed:
                    continue
                if candidate.blocks.get(block.id) is not None and candidate.can_vote(block):
                    possible += 1
            if possible < self.QUORUM:
                self._schedule_timeout()
        return True

    def form_qc(self, block_id):
        """A3 construct a certificate from distinct valid matching votes.
        Validate the block, view and authorized voters; fewer than QUORUM must
        never create a QC. Register the valid certificate, call dispatch_qc(qc),
        and enqueue ("next_view", "QC"). A6 handles a crashed collector.
        Do not implement transaction processing in this function."""
        # AI-assisted A7 hardening: only authenticated, distinct votes for a
        # valid current-view proposal may contribute to a certificate.
        if type(block_id) is not str:
            return False
        block = self.blocks.get(block_id)
        if block is None or type(block.view) is not int or block.view != self.view:
            return False
        parent = self.blocks.get(block.parent_id) if type(block.parent_id) is str else None
        if (
            type(block.proposer) is not int
            or block.proposer != self.leader_id
            or parent is None
            or not isinstance(block.qc, QC)
            or block.qc.block_id != parent.id
            or block.qc.view != parent.view
            or not self._valid_qc(block.qc)
        ):
            return False
        voters = self.votes.get(block_id, set())
        if not isinstance(voters, (set, list, tuple)):
            return False
        valid_voters = sorted(
            {voter for voter in voters
            if type(voter) is int
            and voter in range(1, self.NODE_COUNT + 1)
            and self.nodes[voter - 1].last_voted_view == block.view
            and self.nodes[voter - 1].last_voted_block == block.id}
        )
        if len(valid_voters) < self.QUORUM:
            return False
        if block.id in self.qcs:
            return False

        qc = QC(block.id, block.view, tuple(valid_voters))
        self.qcs[block.id] = qc
        self.log(f"QC formed for {block.id} · voters N{', N'.join(map(str, valid_voters))}", "qc")
        self.dispatch_qc(qc)
        self.events.append(("next_view", "QC"))
        return True

    def timeout(self, remaining):
        """A6 implement logical timeout countdown and leader replacement.
        remaining is the number of logical ticks left. Eventually schedule
        ("next_view", "timeout") while preserving the quorum and safety state."""
        if type(remaining) is not int:
            return False
        if remaining > 1:
            self.phase = f"View {self.view} timeout · {remaining - 1} ticks remaining"
            self.events.append(("timeout", remaining - 1))
        else:
            self.log(f"View {self.view} timed out · rotating leader", "fault")
            self.events.append(("next_view", "timeout"))
        return True

    def next_view(self, reason):
        """A5 implement view increment, leader rotation and replica updates.
        Preserve QCs, locks and committed history. Call each node's enter_view
        as appropriate and enqueue the next proposal event."""
        self.view += 1
        for node in self.nodes:
            node.enter_view(self.view, self.leader_id)
        self.events.clear()
        self.events.append(("propose", None))
        if reason == "timeout":
            self.phase = f"View {self.view} · Leader N{self.leader_id} after timeout"
            self.log(f"Entered view {self.view} · Leader N{self.leader_id} after timeout", "view")
        else:
            self.phase = f"View {self.view} · Leader N{self.leader_id}"
            self.log(f"Entered view {self.view} · Leader N{self.leader_id}", "view")
        return True

    def crash_leader(self):
        leader = self.nodes[self.leader_id - 1]
        if not leader.crashed:
            leader.crashed = True
            self.log(f"Leader N{leader.id} crashed", "fault")

    def set_byzantine(self, node_id: int | None):
        if node_id is not None and node_id not in range(1, 5):
            raise ValueError("Node ID must be 1–4")
        for node in self.nodes:
            node.withhold_vote = node.id == node_id
        self.log(f"N{node_id} Byzantine: withholds votes only" if node_id else
                 "All nodes vote normally", "fault")

    def recover(self):
        """A6 restore crashed replicas from a trusted live peer.
        Catch up blocks, QCs, locks, committed chain and application state.
        Preserve voting history so a replica cannot vote twice in one view.
        Restore balances and receipts, and B6 nonces if implemented. If no live
        peer is available, reject recovery without inventing state. No disk
        persistence is required. Clear simulated faults and rejoin safely."""
        live = [node for node in self.nodes if not node.crashed]
        if not live:
            raise ValueError("No live peer is available for recovery")
        source = max(live, key=lambda node: (len(node.committed_blocks), node.view))
        for node in self.nodes:
            if not node.crashed:
                continue
            # AI-assisted recovery: a replica must not forget a justified
            # higher lock or QC that it held before crashing.
            previous_blocks = node.blocks
            previous_high_qc = node.high_qc
            previous_locked_qc = node.locked_qc
            previous_last_vote = node.last_voted_view
            previous_last_block = node.last_voted_block
            node.blocks = deepcopy(source.blocks)
            node.blocks.update(deepcopy({
                block_id: block for block_id, block in previous_blocks.items()
                if self.blocks.get(block_id) == block
            }))
            node.high_qc = deepcopy(source.high_qc)
            node.locked_qc = deepcopy(source.locked_qc)
            if (previous_high_qc.view > node.high_qc.view
                    and self.qcs.get(previous_high_qc.block_id) == previous_high_qc
                    and previous_high_qc.block_id in node.blocks):
                node.high_qc = deepcopy(previous_high_qc)
            if (previous_locked_qc.view > node.locked_qc.view
                    and self.qcs.get(previous_locked_qc.block_id) == previous_locked_qc
                    and previous_locked_qc.block_id in node.blocks):
                node.locked_qc = deepcopy(previous_locked_qc)
            node.committed_blocks = source.committed_blocks.copy()
            node.machine = deepcopy(source.machine)
            node.last_voted_view = max(previous_last_vote, source.last_voted_view)
            node.last_voted_block = (
                previous_last_block
                if previous_last_vote >= source.last_voted_view
                else source.last_voted_block
            )
            node.crashed = False
            node.withhold_vote = False
            node.enter_view(self.view, self.leader_id)
        for node in self.nodes:
            node.withhold_vote = False
        self.log("Crashed replicas recovered from a live peer", "fault")
        self.phase = f"View {self.view} · Nodes recovered"
        return True

    def snapshot(self):
        source = max(self.nodes, key=lambda n: len(n.committed_blocks))
        committed = set(source.committed_blocks)
        node_states = []
        for node in self.nodes:
            node_states.append({
                "id": node.id, "view": node.view, "role": node.role,
                "crashed": node.crashed, "withhold_vote": node.withhold_vote,
                "high_qc": asdict(node.high_qc), "locked_qc": asdict(node.locked_qc),
                "latest_block": max(node.blocks.values(), key=lambda b: b.view).id,
                "committed_blocks": node.committed_blocks.copy(),
                "accounts": node.machine.accounts.copy(),
                "nonces": node.machine.nonces.copy(),
            })
        blocks = [{**asdict(block), "certificate": asdict(self.qcs[block.id]) if block.id in self.qcs else None,
                   "committed": block.id in committed,
                   "votes": sorted(self.votes.get(block.id, []))}
                  for block in self.blocks.values()]
        transactions = [{**asdict(tx), **source.machine.receipts.get(tx.id, {"status": "pending", "error": None})}
                        for tx in self.transactions.values()]
        live = [n for n in self.nodes if not n.crashed]
        consistent = bool(live) and all(n.machine.accounts == live[0].machine.accounts
                                       and n.committed_blocks == live[0].committed_blocks for n in live)
        return {"view": self.view, "leader_id": self.leader_id, "running": self.running,
                "steps": self.steps, "phase": self.phase, "nodes": node_states,
                "blocks": blocks, "mempool": [asdict(self.transactions[t]) for t in self.mempool],
                "transactions": transactions, "accounts": source.machine.accounts.copy(),
                "nonces": source.machine.nonces.copy(),
                "committed_chain": source.committed_blocks.copy(), "consistent": consistent,
                "logs": list(self.logs), "quorum": self.QUORUM,
                "next_event": self.events[0][0] if self.events else "propose"}



    def select_transactions(self, parent: Block) -> list[Transaction]:
        """B2 select eligible pending transactions without consuming them.
        Return at most max_txs_per_block (default 5), excluding transaction IDs
        on the selected parent chain. An abandoned branch does not exclude an ID.
        Empty input returns an empty list. Keep IDs in the pool until commit.
        """
        if parent is None:
            return []
        selected_ancestry = set()
        current = parent
        visited = set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            selected_ancestry.update(tx.id for tx in current.transactions)
            if current.parent_id is None:
                break
            current = self.blocks.get(current.parent_id)
        return [
            self.transactions[tx_id]
            for tx_id in self.mempool
            if tx_id not in selected_ancestry
        ][:self.max_txs_per_block]

    def finalize_transactions(self, committed_ids: list[str]):
        """B4 finalize pool entries after per-replica execution.
        committed_ids is ordered and contains newly committed blocks. Remove
        their transaction IDs from the pool, including rejected executions,
        and record useful transaction events. Repeated finalization is harmless.
        This method does not execute transfers or decide consensus.
        """
        committed_tx_ids = set()
        for block_id in committed_ids:
            block = self.blocks.get(block_id)
            if block is None:
                continue
            committed_tx_ids.update(tx.id for tx in block.transactions)
        if not committed_tx_ids:
            return
        self.mempool[:] = [
            tx_id for tx_id in self.mempool if tx_id not in committed_tx_ids
        ]
        live = [node for node in self.nodes if not node.crashed]
        source = max(live, key=lambda node: len(node.committed_blocks)) if live else self.nodes[0]
        receipts = source.machine.receipts
        for tx_id in sorted(committed_tx_ids):
            receipt = receipts.get(tx_id)
            if receipt is None:
                self.log(f"{tx_id} finalized without a receipt", "transaction")
            else:
                self.log(f"{tx_id} finalized · {receipt['status']}", "transaction")

    def configure_batch(self, limit):
        """B5 set a positive integer batch limit and return the accepted value.
        Reject bool, zero, negatives and non-integers without changing state.
        Reset restores the default value 5 in this starter contract.
        """
        if type(limit) is not int or limit <= 0:
            raise ValueError("Batch limit must be a positive integer")
        self.max_txs_per_block = limit
        self.log(f"Batch limit set to {limit}", "info")
        return limit

    def inject_attack(self, kind: str, node_id: int):
        """A7 inject an active Byzantine action in the current experiment.
        Implement equivocation by the current leader plus duplicate_vote OR
        invalid_qc. Extend message delivery as needed so honest replicas receive
        the attack through normal validation paths. Log the action and supply
        assertions. Do not count the supplied withholding switch as this task.
        A malicious replica controls only its own simulator identity.
        """
        if type(node_id) is not int or node_id not in range(1, self.NODE_COUNT + 1):
            raise ValueError("Node ID must be 1–4")
        if kind not in {"equivocation", "duplicate_vote", "invalid_qc"}:
            raise ValueError("Unknown attack kind")

        if kind == "equivocation":
            if node_id != self.leader_id:
                raise ValueError("Equivocation requires the current leader")
            leader = self.nodes[node_id - 1]
            if leader.crashed:
                raise ValueError("A crashed leader cannot equivocate")
            parent = self.blocks.get(leader.high_qc.block_id)
            if parent is None:
                raise ValueError("Leader HighQC references an unknown block")
            # Keep votes and QCs already scheduled for this view. Only replace
            # the untouched automatic proposal with the two conflicting ones.
            self.events = deque(
                (action, data) for action, data in self.events
                if action != "propose"
            )
            block_ids = []
            for _ in range(2):
                block_id = self._new_block_id()
                block = Block(block_id, parent.id, self.view, node_id, [], leader.high_qc)
                self.blocks[block_id] = block
                self.votes[block_id] = set()
                block_ids.append(block_id)
                for node in self.nodes:
                    if not node.crashed:
                        node.blocks[block_id] = block
            for block_id in block_ids:
                for node in self.nodes:
                    if not node.crashed:
                        self.events.append(("vote", (node.id, block_id)))
            self.log(f"N{node_id} equivocated with {block_ids[0]} and {block_ids[1]}", "fault")
            return block_ids

        if kind == "duplicate_vote":
            candidate = self._current_view_block()
            if candidate is None:
                self.propose(None)
                candidate = self._current_view_block()
            if candidate is None:
                raise ValueError("No proposal available for duplicate vote")
            self.events.append(("vote", (node_id, candidate.id)))
            self.events.append(("vote", (node_id, candidate.id)))
            self.log(f"Injected duplicate vote by N{node_id} for {candidate.id}", "fault")
            return candidate.id

        invalid_id = f"invalid-qc-v{self.view}-n{node_id}"
        self.events.append(("qc", invalid_id))
        self.log(f"Injected invalid QC evidence from N{node_id}", "fault")
        return invalid_id

    def dispatch_qc(self, qc: QC):
        """Provided integration wiring. Caller must validate/register the QC.

        Task A reports committed IDs; Task B executes their payload and cleans
        the pool. Empty payloads bypass Task B, not consensus validation.
        """
        newly_committed = set()
        for node in self.nodes:
            committed = node.receive_qc(qc)
            newly_committed.update(committed)
            if committed and any(node.blocks[b].transactions for b in committed):
                node.execute_committed(committed)
        ordered = sorted(newly_committed, key=lambda b: self.blocks[b].view)
        for block_id in ordered:
            self.log(f"{block_id} committed", "commit")
        if any(self.blocks[b].transactions for b in ordered):
            self.finalize_transactions(ordered)
        return ordered

    def _valid_qc(self, qc: QC) -> bool:
        return (
            isinstance(qc, QC)
            and type(qc.block_id) is str
            and type(qc.view) is int
            and qc.view >= 0
            and isinstance(qc.voters, tuple)
            and len(qc.voters) >= self.QUORUM
            and all(type(voter) is int and voter in range(1, self.NODE_COUNT + 1)
                    for voter in qc.voters)
            and len(set(qc.voters)) == len(qc.voters)
            and qc.block_id in self.blocks
            and self.blocks[qc.block_id].view == qc.view
            and self.qcs.get(qc.block_id) == qc
        )

    def _schedule_timeout(self):
        if not any(action == "timeout" for action, _ in self.events):
            self.events.append(("timeout", self.TIMEOUT_TICKS))

    def _new_block_id(self):
        index = len(self.blocks)
        block_id = f"B{index}"
        while block_id in self.blocks:
            index += 1
            block_id = f"B{index}"
        return block_id

    def _current_view_block(self):
        for block in self.blocks.values():
            if block.view == self.view and block.proposer == self.leader_id:
                return block
        return None
