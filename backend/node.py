from dataclasses import asdict

from .blockchain import StateMachine
from .models import Block, QC


class Node:
    def __init__(self, node_id: int, genesis: Block, genesis_qc: QC):
        self.id = node_id
        self.view = 1
        self.role = "Leader" if node_id == 1 else "Replica"
        self.high_qc = genesis_qc
        self.locked_qc = genesis_qc
        self.blocks = {genesis.id: genesis}
        self.committed_blocks = [genesis.id]
        self.machine = StateMachine()
        self.last_voted_view = 0
        self.last_voted_block = None
        self.crashed = False
        self.withhold_vote = False

    def enter_view(self, view: int, leader_id: int):
        """A5 update local view and role for a live replica.
        A crashed replica remains frozen. Never erase voting history or locks."""
        if self.crashed:
            return
        self.view = view
        self.role = "Leader" if self.id == leader_id else "Replica"

    def extends(self, block_id: str, ancestor_id: str) -> bool:
        """Check ancestry using known local blocks without changing state."""
        current_id = block_id
        visited = set()

        while current_id is not None and current_id not in visited:
            block = self.blocks.get(current_id)

            if block is None:
                return False

            if current_id == ancestor_id:
                return True

            visited.add(current_id)
            current_id = block.parent_id

        return False

    def can_vote(self, block: Block) -> bool:
        """A2 decide whether this replica may vote for a proposal.
        Enforce availability, current view, one vote per view and the safe-node
        lock rule. Return a Boolean; vote() records the actual cast vote.
        The coordinator validates the proposal leader and parent certificate."""
        # AI-assisted implementation; the student owner must review and explain it.
        if self.crashed or self.withhold_vote:
            return False
        if block.view != self.view or self.last_voted_view >= block.view:
            return False

        extends_lock = self.extends(block.parent_id, self.locked_qc.block_id)
        has_newer_qc = block.qc is not None and block.qc.view > self.locked_qc.view
        return extends_lock or has_newer_qc

    def receive_qc(self, qc: QC) -> list[str]:
        """A4 update certificate/lock state and decide committed block IDs.
        Return newly committed IDs in ancestor-first order; a crashed node
        returns no progress. Check the linked, consecutive-view three-chain
        contract. Preserve existing commits and prevent repeated commitment.
        Do not execute transactions here: dispatch_qc() invokes Task B.
        A7 may add certificate validation at this boundary as needed."""
        # AI-assisted validation: an embedded certificate must justify its
        # actual parent before it may change a lock or cause commitment.
        if self.crashed:
            return []

        def valid_certificate(certificate: QC, certified: Block) -> bool:
            return (
                isinstance(certificate, QC)
                and certificate.block_id == certified.id
                and type(certificate.view) is int
                and certificate.view == certified.view
                and isinstance(certificate.voters, tuple)
                and len(certificate.voters) >= 3
                and all(type(voter) is int and 1 <= voter <= 4
                        for voter in certificate.voters)
                and len(set(certificate.voters)) == len(certificate.voters)
            )

        block = (self.blocks.get(qc.block_id)
                 if isinstance(qc, QC) and type(qc.block_id) is str else None)
        if block is None or not valid_certificate(qc, block):
            return []

        genesis_id = self.committed_blocks[0]
        current = block
        visited = set()
        while current.id != genesis_id:
            if current.id in visited:
                return []
            visited.add(current.id)
            ancestor = (self.blocks.get(current.parent_id)
                        if type(current.parent_id) is str else None)
            if (
                ancestor is None
                or type(current.parent_id) is not str
                or type(current.view) is not int
                or type(ancestor.view) is not int
                or current.view <= ancestor.view
                or not valid_certificate(current.qc, ancestor)
            ):
                return []
            current = ancestor

        parent = self.blocks.get(block.parent_id)
        if parent is None:
            return []

        if self.high_qc.view < qc.view:
            self.high_qc = qc
        if block.qc.view > self.locked_qc.view:
            self.locked_qc = block.qc

        grandparent = self.blocks.get(parent.parent_id)
        three_chain = (
            grandparent is not None
            and parent.qc is not None
            and parent.qc.block_id == grandparent.id
            and parent.qc.view == grandparent.view
            and grandparent.view + 1 == parent.view
            and parent.view + 1 == block.view
        )
        if not three_chain:
            return []

        target_id = grandparent.id
        if target_id in self.committed_blocks:
            return []
        if not self.extends(target_id, self.committed_blocks[-1]):
            return []

        chain = []
        current = grandparent
        visited = set()
        while current is not None and current.id not in visited:
            visited.add(current.id)
            chain.append(current.id)
            if current.parent_id is None:
                break
            current = self.blocks.get(current.parent_id)
        chain.reverse()
        new_commits = [
            block_id for block_id in chain
            if block_id not in self.committed_blocks
        ]
        self.committed_blocks.extend(new_commits)
        return new_commits



    def execute_committed(self, block_ids: list[str]):
        """B3 execute only blocks already in this replica's committed history.
        Reject uncommitted IDs before applying any transaction. Preserve block
        and payload order; call machine.apply() and rely on B4 receipt semantics
        for repeat delivery. A crashed replica must not execute new work.
        """
        if self.crashed:
            raise RuntimeError("Crashed replicas cannot execute committed blocks")
        if not isinstance(block_ids, list):
            raise ValueError("Committed block IDs must be a list")
        for block_id in block_ids:
            if block_id not in self.committed_blocks or block_id not in self.blocks:
                raise ValueError(f"Block {block_id} is not committed on this replica")
        positions = [self.committed_blocks.index(block_id) for block_id in block_ids]
        if positions != sorted(positions):
            raise ValueError("Committed blocks must execute in committed-history order")
        if positions:
            requested = set(block_ids)
            for block_id in self.committed_blocks[:positions[-1] + 1]:
                if (
                    self.blocks[block_id].transactions
                    and block_id not in self.machine.execution_receipts
                    and block_id not in requested
                ):
                    raise ValueError(f"Earlier committed block {block_id} has not executed")

        # AI-assisted B4/B6: persist results per committed position, not untrusted ID.
        receipts = []
        for block_id in block_ids:
            if block_id not in self.machine.execution_receipts:
                records = []
                for index, tx in enumerate(self.blocks[block_id].transactions):
                    records.append({
                        **asdict(tx), **self.machine.apply(tx),
                        "block_id": block_id, "transaction_index": index,
                    })
                self.machine.execution_receipts[block_id] = records
            receipts.extend(
                receipt.copy() for receipt in self.machine.execution_receipts[block_id]
            )
        return receipts
