from .models import Transaction


INITIAL_BALANCES = {"Alice": 100, "Bob": 100, "Charlie": 100}


class StateMachine:
    def __init__(self):
        self.accounts = INITIAL_BALANCES.copy()
        # Receipts also make execution idempotent across catch-up and retries.
        self.receipts: dict[str, dict] = {}

    def apply(self, tx: Transaction) -> dict:
        """B3 B4 validate and deterministically execute one committed transaction.
        Called only through the committed-execution path (or isolated unit tests).
        Check known accounts, a strict positive integer amount and available
        funds. A failed transfer changes no balance. Return/store a receipt with
        status committed or rejected and error None or an explanatory string.
        Reusing a transaction ID returns its prior receipt without another debit.
        B6 extends this with signature verification, nonces and stable identities."""
        raise NotImplementedError('TODO B3 B4 validate and deterministically execute one committed transaction.')

