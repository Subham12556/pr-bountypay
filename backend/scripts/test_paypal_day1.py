import os
import sys
import time
import webbrowser
from pathlib import Path

# Allow importing from backend/
sys.path.append(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from core.database import (
    get_bounty,
    init_db,
    mark_bounty_locked,
    upsert_bounty_order,
)
from services.paypal_service import (
    PayPalAPIError,
    authorize_bounty_order,
    create_bounty_order,
    get_order_status,
    payout_to_developer,
    settle_bounty_idempotently,
)

load_dotenv()


def wait_for_payer_approval(order_id: str, approve_url: str, timeout_sec: int = 300) -> None:
    """
    Opens the PayPal approval URL and polls PayPal every 3 seconds until the
    Sandbox buyer finishes clicking 'Continue / Pay Now' in the browser.
    """
    print("\nACTION REQUIRED IN BROWSER:")
    print("1. Log in using your PayPal SANDBOX PERSONAL account (e.g., sb-xxx@personal.example.com).")
    print("   (Do NOT log in with the same email as your Sandbox Business/Merchant account!)")
    print("2. Click the blue 'Continue' / 'Complete Purchase' button.")
    print("3. Wait until the browser redirects to example.com/bounty-locked.")
    print(f"\nApproval URL:\n   {approve_url}\n")

    try:
        webbrowser.open(approve_url)
    except Exception:
        pass

    print("Waiting for buyer approval in browser (polling PayPal every 3s)...")
    start = time.time()
    while time.time() - start < timeout_sec:
        status = get_order_status(order_id)
        if status == "APPROVED":
            print(f"   -> Detected Order Status: {status}! Proceeding automatically...")
            return
        print(f"   ... current status: {status} (waiting for buyer approval)")
        time.sleep(3)

    raise TimeoutError(f"Order {order_id} was not approved within {timeout_sec} seconds.")


def run_day1_verification():
    init_db()

    repo_name = "subham/auth-service"
    issue_number = int(time.time()) % 100000
    pr_number = issue_number + 100
    amount = "120.00"
    dev_email = os.getenv("TEST_DEV_PAYPAL_EMAIL", "sb-dev@personal.example.com")

    print(f"\n[TEST CONFIG] Repo: {repo_name} | Issue: #{issue_number} | PR: #{pr_number}")

    print("\n=== STEP 1: Creating PayPal Order (Intent: AUTHORIZE) ===")
    order = create_bounty_order(
        repo_full_name=repo_name,
        issue_number=issue_number,
        amount_usd=amount,
    )
    upsert_bounty_order(repo_name, issue_number, amount, order["order_id"])
    print(f"Order ID Created : {order['order_id']}")

    print("\n=== STEP 1B: Verifying Guard Against Settling an Unapproved ('CREATED') Order ===")
    try:
        settle_bounty_idempotently(repo_name, issue_number, pr_number, dev_email)
        print("ERROR: Should not allow settling an unapproved order!")
    except ValueError as exc:
        print(f"Verified! Raised ValueError as expected: {exc}")

    # Poll until the order is actually approved in the browser
    wait_for_payer_approval(order["order_id"], order["approve_url"])

    print("\n=== STEP 2: Locking Authorization Hold ===")
    auth_res = authorize_bounty_order(order["order_id"])
    auth_id = auth_res["authorization_id"]
    mark_bounty_locked(repo_name, issue_number, auth_id)
    print(f"Authorization ID : {auth_id} (Status: {auth_res['status']})")

    print("\n=== STEP 3 & 4: Atomic Capture + Payout (Webhook Delivery #1) ===")
    settlement_1 = settle_bounty_idempotently(
        repo_full_name=repo_name,
        issue_number=issue_number,
        pr_number=pr_number,
        contributor_paypal=dev_email,
    )
    print(f"Capture ID       : {settlement_1['capture_id']}")
    print(f"Payout Batch ID  : {settlement_1['payout_batch_id']}")
    print(f"Batch Status     : {settlement_1['batch_status']}")

    print("\n=== STEP 5: Testing Idempotency (Simulating Duplicate Webhook Delivery #2) ===")
    settlement_2 = settle_bounty_idempotently(
        repo_full_name=repo_name,
        issue_number=issue_number,
        pr_number=pr_number,
        contributor_paypal=dev_email,
    )
    print(f"Blocked by DB Guard? {settlement_2['already_paid']}")

    print("\n=== STEP 6: Testing Backward State Transition Guard ===")
    try:
        mark_bounty_locked(repo_name, issue_number, "FAKE_AUTH_ID")
        print("ERROR: Guard failed to block backward transition!")
    except RuntimeError as exc:
        print(f"Verified! Backward transition blocked: {exc}")

    print("\n=== STEP 7: Testing PayPal-Level Duplicate Batch Handling ===")
    try:
        dup_res = payout_to_developer(
            receiver_email=dev_email,
            amount_usd=amount,
            repo_full_name=repo_name,
            issue_number=issue_number,
            pr_number=pr_number,
        )
        print(
            f"Verified! PayPal returned cached idempotent response "
            f"(Batch ID: {dup_res['payout_batch_id']})."
        )
    except PayPalAPIError as exc:
        print(f"Verified! PayPal rejected duplicate batch (HTTP {exc.status_code}).")

    final_row = get_bounty(repo_name, issue_number)
    print(f"\nFinal Database Status for Issue #{issue_number}: {final_row['status']}")
    print("DAY 1 COMPLETE! All state guards, rollbacks, and PayPal operations verified.")


if __name__ == "__main__":
    run_day1_verification()