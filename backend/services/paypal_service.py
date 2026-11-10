import json
import os
import re
from typing import Optional
import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.getenv("PAYPAL_CLIENT_ID")
CLIENT_SECRET = os.getenv("PAYPAL_CLIENT_SECRET")
BASE_URL = os.getenv("PAYPAL_BASE_URL", "https://api-m.sandbox.paypal.com")


class PayPalAPIError(Exception):
    """Custom exception that preserves HTTP status code and full PayPal error payload."""

    def __init__(self, context: str, status_code: int, raw_body: str):
        self.context = context
        self.status_code = status_code
        self.raw_body = raw_body
        super().__init__(f"[{context}] HTTP {status_code}: {raw_body}")


def _sanitize_key(raw: str) -> str:
    """Strips non-alphanumeric characters so repo names are safe for PayPal headers/batch IDs."""
    return re.sub(r"[^a-zA-Z0-9_-]", "_", raw)


def _handle_paypal_response(response: requests.Response, context: str) -> dict:
    """
    Inspects the PayPal HTTP response. If it failed (>= 400), prints the formatted
    JSON error payload (including debug_id and issue details) before raising.
    """
    if not response.ok:
        print(f"\n[PAYPAL ERROR] Operation : {context}")
        print(f"[PAYPAL ERROR] HTTP Code : {response.status_code}")
        try:
            err_json = response.json()
            print(f"[PAYPAL ERROR] Name      : {err_json.get('name')}")
            print(f"[PAYPAL ERROR] Message   : {err_json.get('message')}")
            print(f"[PAYPAL ERROR] Debug ID  : {err_json.get('debug_id')}")
            if "details" in err_json:
                print(
                    f"[PAYPAL ERROR] Details   : {json.dumps(err_json['details'], indent=2)}"
                )
            else:
                print(f"[PAYPAL ERROR] Full Body : {json.dumps(err_json, indent=2)}")
        except ValueError:
            print(f"[PAYPAL ERROR] Raw Text  : {response.text}")

        raise PayPalAPIError(
            context=context,
            status_code=response.status_code,
            raw_body=response.text,
        )

    return response.json() if response.text else {}


def get_paypal_access_token() -> str:
    """Authenticates with PayPal Sandbox and returns an OAuth2 Bearer token."""
    if not CLIENT_ID or not CLIENT_SECRET:
        raise ValueError("Missing PAYPAL_CLIENT_ID or PAYPAL_CLIENT_SECRET in .env")

    url = f"{BASE_URL}/v1/oauth2/token"
    response = requests.post(
        url,
        auth=(CLIENT_ID, CLIENT_SECRET),
        headers={"Accept": "application/json", "Accept-Language": "en_US"},
        data={"grant_type": "client_credentials"},
        timeout=15,
    )
    data = _handle_paypal_response(response, context="OAuth2 Token Exchange")
    return data["access_token"]


def create_bounty_order(
    repo_full_name: str,
    issue_number: int,
    amount_usd: str,
    test_run_id: Optional[str] = None,
) -> dict:
    """
    Creates a PayPal Order with intent='AUTHORIZE'.
    Uses a deterministic PayPal-Request-Id per repo + issue_number (capped at 100 chars).
    """
    token = get_paypal_access_token()
    url = f"{BASE_URL}/v2/checkout/orders"
    safe_repo = _sanitize_key(repo_full_name)[:50]

    suffix = f"-{_sanitize_key(test_run_id)}" if test_run_id else ""
    request_id = f"order-{safe_repo}-issue-{issue_number}{suffix}"[:100]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "PayPal-Request-Id": request_id,
    }
    payload = {
        "intent": "AUTHORIZE",
        "purchase_units": [
            {
                "reference_id": f"{safe_repo}_ISSUE_{issue_number}"[:127],
                "description": f"Bounty Hold for {repo_full_name} Issue #{issue_number}"[:127],
                "amount": {"currency_code": "USD", "value": amount_usd},
            }
        ],
        "payment_source": {
            "paypal": {
                "experience_context": {
                    "return_url": "https://example.com/bounty-locked",
                    "cancel_url": "https://example.com/bounty-cancelled",
                    "user_action": "CONTINUE",
                }
            }
        },
    }
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    data = _handle_paypal_response(
        response, context=f"Create Order ({repo_full_name}#{issue_number})"
    )

    approve_url = next(
        link["href"] for link in data["links"] if link["rel"] == "payer-action"
    )
    return {"order_id": data["id"], "approve_url": approve_url}


def authorize_bounty_order(order_id: str) -> dict:
    """
    Locks the funds after the maintainer approves the order in their browser.
    Idempotent via fixed PayPal-Request-Id: f"auth-{order_id}"[:100].
    """
    token = get_paypal_access_token()
    url = f"{BASE_URL}/v2/checkout/orders/{order_id}/authorize"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "PayPal-Request-Id": f"auth-{order_id}"[:100],
    }
    response = requests.post(url, headers=headers, json={}, timeout=15)
    data = _handle_paypal_response(response, context=f"Authorize Order ({order_id})")

    auth_obj = data["purchase_units"][0]["payments"]["authorizations"][0]
    return {
        "authorization_id": auth_obj["id"],
        "status": auth_obj["status"],
    }

def get_order_status(order_id: str) -> str:
    """
    Fetches the current lifecycle status of a PayPal Order
    ('CREATED', 'SAVED', 'APPROVED', 'VOIDED', 'COMPLETED', 'PAYER_ACTION_REQUIRED').
    """
    token = get_paypal_access_token()
    url = f"{BASE_URL}/v2/checkout/orders/{order_id}"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
    }
    response = requests.get(url, headers=headers, timeout=15)
    data = _handle_paypal_response(response, context=f"Get Order ({order_id})")
    return data["status"]    


def capture_bounty_authorization(authorization_id: str, amount_usd: str) -> dict:
    """
    Autonomously captures the locked authorization hold.
    Strictly idempotent via PayPal-Request-Id: f"cap-{authorization_id}"[:100].
    """
    token = get_paypal_access_token()
    url = f"{BASE_URL}/v2/payments/authorizations/{authorization_id}/capture"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "PayPal-Request-Id": f"cap-{authorization_id}"[:100],
    }
    payload = {
        "amount": {"currency_code": "USD", "value": amount_usd},
        "final_capture": True,
        "note_to_payer": "PR passed CI unit tests and Gemini Security Audit (95+).",
    }
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    data = _handle_paypal_response(
        response, context=f"Capture Authorization ({authorization_id})"
    )
    return {"capture_id": data["id"], "status": data["status"]}


def payout_to_developer(
    receiver_email: str,
    amount_usd: str,
    repo_full_name: str,
    issue_number: int,
    pr_number: int,
) -> dict:
    """
    Disburses the bounty to the developer's PayPal email.
    - sender_batch_id is kept up to 127 chars.
    - PayPal-Request-Id header is strictly truncated to 100 chars (PayPal limit is ~108).
    """
    token = get_paypal_access_token()
    url = f"{BASE_URL}/v1/payments/payouts"
    safe_repo = _sanitize_key(repo_full_name)[:60]

    batch_id = f"BOUNTY_{safe_repo}_ISSUE_{issue_number}_PR_{pr_number}"[:127]
    request_id_header = batch_id[:100]
    item_id = f"ITEM_ISSUE_{issue_number}_PR_{pr_number}"[:63]

    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {token}",
        "PayPal-Request-Id": request_id_header,
    }
    payload = {
        "sender_batch_header": {
            "sender_batch_id": batch_id,
            "email_subject": f"Bounty Paid! PR #{pr_number} verified on {repo_full_name}",
            "email_message": (
                f"Your pull request #{pr_number} fixing Issue #{issue_number} on "
                f"{repo_full_name} passed all CI unit tests and the Gemini security audit."
            ),
        },
        "items": [
            {
                "recipient_type": "EMAIL",
                "amount": {"value": amount_usd, "currency": "USD"},
                "note": f"PR-BountyPay settlement for {repo_full_name} PR #{pr_number}",
                "sender_item_id": item_id,
                "receiver": receiver_email,
            }
        ],
    }
    response = requests.post(url, headers=headers, json=payload, timeout=15)
    data = _handle_paypal_response(
        response, context=f"Developer Payout ({batch_id})"
    )
    return {
        "payout_batch_id": data["batch_header"]["payout_batch_id"],
        "batch_status": data["batch_header"]["batch_status"],
    }


def settle_bounty_idempotently(
    repo_full_name: str,
    issue_number: int,
    pr_number: int,
    contributor_paypal: str,
) -> dict:
    """
    High-level orchestrator enforcing Database + PayPal idempotency with rollback recovery:
    - Raises ValueError if bounty doesn't exist or is still in 'CREATED' (unapproved hold).
    - Returns early with already_paid=True if status is 'PAID'.
    - Raises SettlementInProgressError ONLY if status is actively 'SETTLING'.
    """
    from core.database import (
        SettlementInProgressError,
        acquire_settlement_lock,
        get_bounty,
        mark_bounty_paid,
        record_capture_success,
        release_settlement_lock,
    )

    bounty = get_bounty(repo_full_name, issue_number)
    if not bounty:
        raise ValueError(f"No bounty registered for {repo_full_name} #{issue_number}")

    if bounty["status"] == "PAID":
        print(
            f"[IDEMPOTENCY GUARD] Bounty {repo_full_name}#{issue_number} is already PAID "
            f"(Batch: {bounty['paypal_payout_batch_id']}). Ignoring duplicate webhook."
        )
        return {
            "already_paid": True,
            "capture_id": bounty["paypal_capture_id"],
            "payout_batch_id": bounty["paypal_payout_batch_id"],
        }

    if bounty["status"] == "CREATED":
        raise ValueError(
            f"Cannot settle {repo_full_name}#{issue_number}: bounty order is still in "
            "'CREATED' state (maintainer has not approved and locked the PayPal hold yet)."
        )

    locked = acquire_settlement_lock(
        repo_full_name=repo_full_name,
        issue_number=issue_number,
        pr_number=pr_number,
        contributor_paypal=contributor_paypal,
    )
    if not locked:
        # Re-fetch to inspect exact status after lock contention
        current = get_bounty(repo_full_name, issue_number)
        current_status = current["status"] if current else "UNKNOWN"

        if current_status == "PAID":
            return {
                "already_paid": True,
                "capture_id": current["paypal_capture_id"],
                "payout_batch_id": current["paypal_payout_batch_id"],
            }
        if current_status == "SETTLING":
            raise SettlementInProgressError(
                f"[IDEMPOTENCY GUARD] Bounty {repo_full_name}#{issue_number} is actively "
                "SETTLING in another worker."
            )
        raise ValueError(
            f"Cannot settle {repo_full_name}#{issue_number}: unexpected status '{current_status}'."
        )

    try:
        bounty = get_bounty(repo_full_name, issue_number)
        amount_usd = bounty["bounty_amount"]
        auth_id = bounty["paypal_auth_id"]

        # Step A: Capture Hold (skip if a previous attempt already captured it)
        if bounty["paypal_capture_id"]:
            capture_id = bounty["paypal_capture_id"]
            print(f"[IDEMPOTENCY] Reusing existing Capture ID: {capture_id}")
        else:
            cap_res = capture_bounty_authorization(auth_id, amount_usd=amount_usd)
            capture_id = cap_res["capture_id"]
            record_capture_success(repo_full_name, issue_number, capture_id)

        # Step B: Disburse Payout using deterministic sender_batch_id
        payout_res = payout_to_developer(
            receiver_email=contributor_paypal,
            amount_usd=amount_usd,
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            pr_number=pr_number,
        )
        payout_batch_id = payout_res["payout_batch_id"]

        # Step C: Finalize DB state as PAID
        mark_bounty_paid(repo_full_name, issue_number, payout_batch_id)

        return {
            "already_paid": False,
            "capture_id": capture_id,
            "payout_batch_id": payout_batch_id,
            "batch_status": payout_res["batch_status"],
        }
    except Exception:
        fresh = get_bounty(repo_full_name, issue_number)
        back_to = (
            "CAPTURE_COMPLETED"
            if (fresh and fresh.get("paypal_capture_id"))
            else "LOCKED"
        )
        release_settlement_lock(repo_full_name, issue_number, back_to)
        print(
            f"[RECOVERY] Settlement failed mid-flight; rolled back {repo_full_name}#{issue_number} "
            f"status to '{back_to}' so it can be safely retried."
        )
        raise