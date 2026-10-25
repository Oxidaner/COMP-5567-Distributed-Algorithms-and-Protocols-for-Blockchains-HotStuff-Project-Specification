from dataclasses import dataclass, field


@dataclass(frozen=True)
class Transaction:
    id: str
    sender: str
    receiver: str
    amount: int


@dataclass(frozen=True)
class QC:
    block_id: str
    view: int
    voters: tuple[int, ...]


@dataclass
class Block:
    id: str
    parent_id: str | None
    view: int
    proposer: int
    transactions: list[Transaction] = field(default_factory=list)
    # The proposal's justification: a QC certifying its parent, not itself.
    qc: QC | None = None

