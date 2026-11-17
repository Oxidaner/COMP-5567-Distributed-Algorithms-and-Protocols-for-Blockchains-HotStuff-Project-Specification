"""Generate a signed request or submit it: python -m tools.sign_transaction --help."""
import argparse
import json
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from backend.blockchain import INITIAL_BALANCES, sign_transaction


def transaction_request(sender: str, receiver: str, amount: int, nonce: int) -> dict:
    """AI-assisted B6 client: sign locally and send only the signature and payload."""
    return {
        "sender": sender,
        "receiver": receiver,
        "amount": amount,
        "nonce": nonce,
        "signature": sign_transaction(sender, receiver, amount, nonce),
    }


def main(argv=None):
    """AI-assisted B6 CLI: print JSON offline, or POST it to the running demo."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sender", choices=INITIAL_BALANCES)
    parser.add_argument("receiver", choices=INITIAL_BALANCES)
    parser.add_argument("amount", type=int)
    parser.add_argument("--nonce", type=int, required=True)
    parser.add_argument("--submit", action="store_true", help="Submit instead of printing the request")
    parser.add_argument("--url", default="http://127.0.0.1:8000", help="Demo base URL")
    args = parser.parse_args(argv)
    if not 1 <= args.amount <= 1_000_000:
        parser.error("amount must be in [1, 1000000]")
    if args.nonce < 0:
        parser.error("nonce must be non-negative")
    payload = transaction_request(args.sender, args.receiver, args.amount, args.nonce)
    if args.submit:
        request = Request(
            args.url.rstrip("/") + "/api/transactions",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urlopen(request, timeout=10) as response:
                payload = json.load(response)
        except HTTPError as exc:
            parser.exit(1, f"HTTP {exc.code}: {exc.read().decode()}\n")
        except URLError as exc:
            parser.exit(1, f"Connection failed: {exc.reason}\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
