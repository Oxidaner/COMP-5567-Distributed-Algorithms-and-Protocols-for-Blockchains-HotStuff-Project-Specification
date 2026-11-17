import hashlib
import json

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from .models import Transaction


INITIAL_BALANCES = {"Alice": 100, "Bob": 100, "Charlie": 100}
# Reproducible public classroom fixtures, not keys for real accounts.
CLASSROOM_PRIVATE_KEYS = {
    account: hashlib.sha256(f"COMP5567 classroom key: {account}".encode()).digest()
    for account in INITIAL_BALANCES
}
CLASSROOM_PUBLIC_KEYS = {
    account: Ed25519PrivateKey.from_private_bytes(seed).public_key().public_bytes_raw()
    for account, seed in CLASSROOM_PRIVATE_KEYS.items()
}


def _canonical_payload(sender: str, receiver: str, amount: int, nonce: int) -> bytes:
    return json.dumps(
        {
            "chain": "COMP5567-HotStuff",
            "sender": sender,
            "receiver": receiver,
            "amount": amount,
            "nonce": nonce,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def transaction_id(sender: str, receiver: str, amount: int, nonce: int) -> str:
    """Derive a stable identity from the signed transaction payload."""
    return "Tx-" + hashlib.sha256(
        _canonical_payload(sender, receiver, amount, nonce)
    ).hexdigest()[:24]


def sign_transaction(sender: str, receiver: str, amount: int, nonce: int,
                     private_key: bytes | None = None) -> str:
    """AI-assisted B6: sign the canonical payload with an Ed25519 private seed."""
    key = private_key if private_key is not None else CLASSROOM_PRIVATE_KEYS.get(sender)
    if key is None:
        raise ValueError("Unknown signing account")
    return Ed25519PrivateKey.from_private_bytes(key).sign(
        _canonical_payload(sender, receiver, amount, nonce)
    ).hex()


def verify_transaction(sender: str, receiver: str, amount: int, nonce: int,
                       signature: str, public_key: bytes | None = None) -> bool:
    """AI-assisted B6: verify using only a public key; malformed input is false."""
    if not isinstance(signature, str):
        return False
    try:
        key = public_key if public_key is not None else CLASSROOM_PUBLIC_KEYS[sender]
        Ed25519PublicKey.from_public_bytes(key).verify(
            bytes.fromhex(signature),
            _canonical_payload(sender, receiver, amount, nonce),
        )
    except (InvalidSignature, KeyError, TypeError, ValueError):
        return False
    return True


def verify_transaction_identity(tx: Transaction) -> bool:
    """AI-assisted B6: bind signed identities to their authenticated payload."""
    return (
        type(tx.nonce) is int
        and tx.nonce >= 0
        and verify_transaction(tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature)
        and tx.id == transaction_id(tx.sender, tx.receiver, tx.amount, tx.nonce)
    )


class StateMachine:
    def __init__(self):
        self.accounts = INITIAL_BALANCES.copy()
        # Receipts also make execution idempotent across catch-up and retries.
        self.receipts: dict[str, dict] = {}
        self.nonces = {account: 0 for account in INITIAL_BALANCES}
        # Every committed position has a result, even if its claimed ID is forged.
        self.execution_receipts: dict[str, list[dict]] = {}

    def apply(self, tx: Transaction) -> dict:
        """B3 B4 validate and deterministically execute one committed transaction.
        Called only through the committed-execution path (or isolated unit tests).
        Check known accounts, a strict positive integer amount and available
        funds. A failed transfer changes no balance. Return/store a receipt with
        status committed or rejected and error None or an explanatory string.
        Reusing a transaction ID returns its prior receipt without another debit.
        B6 extends this with signature verification, nonces and stable identities."""
        # AI-assisted B6 fix: authenticate before consulting or reserving an identity.
        if not verify_transaction_identity(tx):
            return {"status": "rejected", "error": "Invalid signature or transaction identity"}
        if tx.id in self.receipts:
            return self.receipts[tx.id].copy()

        if tx.nonce != self.nonces[tx.sender]:
            return {"status": "rejected", "error": "Nonce does not match the next account nonce"}

        error = None
        if tx.sender not in self.accounts or tx.receiver not in self.accounts:
            error = "Unknown account"
        elif type(tx.amount) is not int or tx.amount <= 0:
            error = "Amount must be a positive integer"
        elif self.accounts[tx.sender] < tx.amount:
            error = "Insufficient funds"

        if error is None:
            self.accounts[tx.sender] -= tx.amount
            self.accounts[tx.receiver] += tx.amount
            status = "committed"
        else:
            status = "rejected"

        if error in (None, "Insufficient funds"):
            self.nonces[tx.sender] += 1
        receipt = {"status": status, "error": error}
        self.receipts[tx.id] = receipt
        return receipt.copy()

