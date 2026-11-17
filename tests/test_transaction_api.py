"""Task B checks at the HTTP boundary, including the classroom signing client."""
from contextlib import redirect_stdout
from io import StringIO
import json
import unittest

import httpx

from backend import main as service
from backend.blockchain import CLASSROOM_PRIVATE_KEYS, sign_transaction, verify_transaction
from backend.hotstuff import HotStuffDemo
from tools.sign_transaction import main as signing_client, transaction_request


class SigningClientTests(unittest.TestCase):
    def test_offline_command_produces_a_verifiable_request(self):
        output = StringIO()
        with redirect_stdout(output):
            signing_client(["Alice", "Bob", "10", "--nonce", "0"])
        payload = json.loads(output.getvalue())
        self.assertEqual(set(payload), {"sender", "receiver", "amount", "nonce", "signature"})
        self.assertTrue(verify_transaction(**payload))
        self.assertEqual(payload["nonce"], 0)


class TransactionAPITests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.previous_demo = service.demo
        self.demo = HotStuffDemo()
        service.demo = self.demo
        self.client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=service.app), base_url="http://test"
        )

    async def asyncTearDown(self):
        await self.client.aclose()
        service.demo = self.previous_demo

    async def test_invalid_signatures_are_400_without_state_mutation(self):
        request = transaction_request("Alice", "Bob", 10, 0)
        for signature in (
            "", "00", "not-hex", "\u7b7e\u540d",
            sign_transaction("Alice", "Bob", 10, 0, CLASSROOM_PRIVATE_KEYS["Bob"]),
        ):
            with self.subTest(signature=signature):
                response = await self.client.post(
                    "/api/transactions", json={**request, "signature": signature}
                )
                self.assertEqual(response.status_code, 400, response.text)
        self.assertFalse(self.demo.mempool)
        self.assertFalse(self.demo.transactions)
        self.assertEqual(self.demo.nodes[0].machine.nonces["Alice"], 0)

    async def test_signed_request_retries_return_pending_identity_and_final_receipt(self):
        request = transaction_request("Alice", "Bob", 10, 0)
        first = await self.client.post("/api/transactions", json=request)
        self.assertEqual(first.status_code, 200)
        tx_id = first.json()["transaction_id"]
        state = first.json()["state"]
        self.assertEqual(state["accounts"]["Alice"], 100)
        self.assertEqual(state["nonces"]["Alice"], 0)
        self.assertEqual(state["transactions"][0]["status"], "pending")
        retry = await self.client.post("/api/transactions", json=request)
        self.assertEqual(retry.json()["transaction_id"], tx_id)
        self.assertEqual(len(retry.json()["state"]["mempool"]), 1)
        for _ in range(100):
            response = await self.client.post("/api/control/step")
            self.assertEqual(response.status_code, 200)
            state = response.json()
            if not state["mempool"]:
                break
        else:
            self.fail("HTTP stepping did not commit the transaction")
        final = (await self.client.post("/api/transactions", json=request)).json()
        self.assertEqual(final["transaction_id"], tx_id)
        self.assertEqual(final["state"]["accounts"]["Alice"], 90)
        self.assertEqual(final["state"]["nonces"]["Alice"], 1)
        receipt = next(tx for tx in final["state"]["transactions"] if tx["id"] == tx_id)
        self.assertEqual(receipt["status"], "committed")
        self.assertFalse(final["state"]["mempool"])

    async def test_missing_signature_or_nonce_cannot_bypass_authentication(self):
        request = transaction_request("Alice", "Bob", 10, 0)
        for payload in (
            {key: value for key, value in request.items() if key not in ("nonce", "signature")},
            {**request, "signature": None},
            {**request, "nonce": None},
        ):
            with self.subTest(payload=payload):
                response = await self.client.post("/api/transactions", json=payload)
                self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(self.demo.mempool, [])
        self.assertEqual(self.demo.transactions, {})
        self.assertEqual(self.demo.nodes[0].machine.accounts["Alice"], 100)

    async def test_batch_limits_and_input_validation_through_api(self):
        for limit in (1, 2, 5):
            response = await self.client.post(
                "/api/config/batch", json={"max_txs_per_block": limit}
            )
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["max_txs_per_block"], limit)
        for invalid in (0, -1, True, 1.5, "2"):
            response = await self.client.post(
                "/api/config/batch", json={"max_txs_per_block": invalid}
            )
            self.assertEqual(response.status_code, 422)
            self.assertEqual(self.demo.max_txs_per_block, 5)
        for invalid in (0, -1, True, 1.5, "10", 1_000_001):
            response = await self.client.post(
                "/api/transactions",
                json={"sender": "Alice", "receiver": "Bob", "amount": invalid},
            )
            self.assertEqual(response.status_code, 422)
        self.assertFalse(self.demo.mempool)
