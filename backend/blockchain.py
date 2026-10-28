import hashlib
import hmac
import json

from .models import Transaction


INITIAL_BALANCES = {"Alice": 100, "Bob": 100, "Charlie": 100}
CLASSROOM_KEYS = {
    "Alice": "classroom-key-alice",
    "Bob": "classroom-key-bob",
    "Charlie": "classroom-key-charlie",
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
                     private_key: str | None = None) -> str:
    """Create a classroom signature for the optional signed path."""
    key = private_key if private_key is not None else CLASSROOM_KEYS.get(sender)
    if key is None:
        raise ValueError("Unknown signing account")
    return hmac.new(
        key.encode("utf-8"),
        _canonical_payload(sender, receiver, amount, nonce),
        hashlib.sha256,
    ).hexdigest()


def verify_transaction(sender: str, receiver: str, amount: int, nonce: int,
                       signature: str, public_key: str | None = None) -> bool:
    """Verify a classroom signature without deriving identity from it."""
    key = public_key if public_key is not None else CLASSROOM_KEYS.get(sender)
    if key is None or not isinstance(signature, str):
        return False
    expected = sign_transaction(sender, receiver, amount, nonce, key)
    return hmac.compare_digest(expected, signature)


class StateMachine:
    def __init__(self):
        self.accounts = INITIAL_BALANCES.copy()
        # Receipts also make execution idempotent across catch-up and retries.
        self.receipts: dict[str, dict] = {}
        self.nonces = {account: 0 for account in INITIAL_BALANCES}

    def apply(self, tx: Transaction) -> dict:
        """B3 B4 validate and deterministically execute one committed transaction.
        Called only through the committed-execution path (or isolated unit tests).
        Check known accounts, a strict positive integer amount and available
        funds. A failed transfer changes no balance. Return/store a receipt with
        status committed or rejected and error None or an explanatory string.
        Reusing a transaction ID returns its prior receipt without another debit.
        B6 extends this with signature verification, nonces and stable identities."""
        if tx.id in self.receipts:
            return self.receipts[tx.id].copy()

        signed = tx.nonce is not None or tx.signature is not None
        error = None
        if signed and (
            type(tx.nonce) is not int
            or tx.nonce < 0
            or not isinstance(tx.signature, str)
            or not verify_transaction(
                tx.sender, tx.receiver, tx.amount, tx.nonce, tx.signature
            )
        ):
            error = "Invalid signature or nonce"
        elif signed and (
            tx.sender not in self.nonces
            or tx.nonce != self.nonces[tx.sender]
        ):
            error = "Nonce does not match the next account nonce"
        elif tx.sender not in self.accounts or tx.receiver not in self.accounts:
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

        if signed and error in (None, "Insufficient funds"):
            self.nonces[tx.sender] += 1
        receipt = {"status": status, "error": error}
        self.receipts[tx.id] = receipt
        return receipt.copy()

