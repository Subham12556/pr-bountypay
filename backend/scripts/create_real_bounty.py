import sys
import time
import webbrowser
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))

from dotenv import load_dotenv
from core.database import get_bounty, init_db, mark_bounty_locked, upsert_bounty_order
from services.paypal_service import (
    authorize_bounty_order,
    create_bounty_order,
    get_order_status,
)

load_dotenv()

POLL_TIMEOUT_SECONDS = 300  # 5 minutes


def lock_real_repo_bounty(repo_full_name: str, issue_number: int, amount_usd: str):
    init_db()
    # Passing test_run_id ensures rehearsal re-runs on the same issue number
    # always get a brand-new PayPal Order instead of a cached already-used Order.
    rehearsal_id = str(int(time.time()))

    print(
        f"\n[CREATE BOUNTY] Repo: {repo_full_name} | Issue: #{issue_number} | Amount: ${amount_usd}"
    )

    order = create_bounty_order(
        repo_full_name=repo_full_name,
        issue_number=issue_number,
        amount_usd=amount_usd,
        test_run_id=rehearsal_id,
    )
    upsert_bounty_order(repo_full_name, issue_number, amount_usd, order["order_id"])
    print(f"Order ID : {order['order_id']}")
    print(f"Approve  : {order['approve_url']}\n")

    try:
        webbrowser.open(order["approve_url"])
    except Exception:
        pass

    print(
        f"Waiting for buyer approval in browser (polling every 3s, timeout={POLL_TIMEOUT_SECONDS}s)..."
    )
    start_time = time.time()
    while time.time() - start_time < POLL_TIMEOUT_SECONDS:
        status = get_order_status(order["order_id"])
        if status == "APPROVED":
            print("   -> Order APPROVED! Locking authorization hold...")
            break
        print(f"   ... current status: {status}")
        time.sleep(3)
    else:
        raise TimeoutError(
            f"Timed out after {POLL_TIMEOUT_SECONDS} seconds waiting for buyer approval "
            f"on Order {order['order_id']}."
        )

    auth_res = authorize_bounty_order(order["order_id"])
    mark_bounty_locked(repo_full_name, issue_number, auth_res["authorization_id"])

    row = get_bounty(repo_full_name, issue_number)
    print(f"\n[SUCCESS] Bounty LOCKED in bounties.db!")
    print(f"  Repo             : {row['repo_full_name']}")
    print(f"  Issue            : #{row['issue_number']}")
    print(f"  Amount           : ${row['bounty_amount']}")
    print(f"  Authorization ID : {row['paypal_auth_id']}")
    print(f"  DB Status        : {row['status']}")


if __name__ == "__main__":
    if len(sys.argv) < 3:
        print("Usage: python scripts/create_real_bounty.py <owner/repo> <issue_number> [amount_usd]")
        print("Example: python scripts/create_real_bounty.py subham/bounty-demo 1 120.00")
        sys.exit(1)

    repo_arg = sys.argv[1].strip()
    issue_arg = int(sys.argv[2])
    amount_arg = sys.argv[3] if len(sys.argv) >= 4 else "120.00"
    lock_real_repo_bounty(repo_arg, issue_arg, amount_arg)