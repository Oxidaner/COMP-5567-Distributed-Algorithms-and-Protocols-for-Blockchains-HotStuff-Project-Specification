"""Signed fixtures preserve the starter tests' transaction and batching intent."""
from backend.blockchain import sign_transaction, transaction_id
from backend.models import Transaction


def signed_transaction(sender="Alice", receiver="Bob", amount=10, nonce=0):
    return Transaction(
        transaction_id(sender, receiver, amount, nonce),
        sender, receiver, amount, nonce,
        sign_transaction(sender, receiver, amount, nonce),
    )


def submit_signed(demo, sender, receiver, amount):
    source = max(demo.nodes, key=lambda node: len(node.committed_blocks))
    nonce = source.machine.nonces.get(sender, 0)
    pending = [
        demo.transactions[tx_id].nonce
        for tx_id in demo.mempool
        if demo.transactions[tx_id].sender == sender
    ]
    if pending:
        nonce = max(nonce, max(pending) + 1)
    # Invalid-account tests still reach admission's own account validation.
    signature = (
        sign_transaction(sender, receiver, amount, nonce)
        if sender in source.machine.nonces else ""
    )
    return demo.submit(sender, receiver, amount, nonce, signature)
