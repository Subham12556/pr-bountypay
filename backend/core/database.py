import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

DB_PATH = Path(__file__).resolve().parent.parent / "bounties.db"


class SettlementInProgressError(RuntimeError):
    """Raised ONLY when a concurrent worker is actively settling the bounty."""


@contextmanager
def get_db_connection():
    """Context manager yielding a thread-safe SQLite connection with row factory."""
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    """Initializes the bounties ledger table if it does not exist."""
    with get_db_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS bounties (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                repo_full_name TEXT NOT NULL,
                issue_number INTEGER NOT NULL,
                bounty_amount TEXT NOT NULL,
                paypal_order_id TEXT,
                paypal_auth_id TEXT,
                pr_number INTEGER,
                contributor_paypal TEXT,
                ci_tests_status TEXT DEFAULT 'PENDING',
                gemini_score INTEGER,
                secrets_detected INTEGER DEFAULT 0,
                audit_summary TEXT,
                paypal_capture_id TEXT,
                paypal_payout_batch_id TEXT,
                status TEXT NOT NULL DEFAULT 'CREATED',
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                UNIQUE(repo_full_name, issue_number)
            )
            """
        )


def upsert_bounty_order(
    repo_full_name: str, issue_number: int, bounty_amount: str, paypal_order_id: str
) -> None:
    """
    Records a newly created bounty order.
    Raises ValueError if the bounty for this issue is already beyond the 'CREATED' state.
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO bounties (repo_full_name, issue_number, bounty_amount, paypal_order_id, status)
            VALUES (?, ?, ?, ?, 'CREATED')
            ON CONFLICT(repo_full_name, issue_number) DO UPDATE SET
                bounty_amount = excluded.bounty_amount,
                paypal_order_id = excluded.paypal_order_id,
                updated_at = CURRENT_TIMESTAMP
            WHERE status = 'CREATED'
            """,
            (repo_full_name, issue_number, bounty_amount, paypal_order_id),
        )
        if cursor.rowcount == 0:
            existing = conn.execute(
                "SELECT status FROM bounties WHERE repo_full_name = ? AND issue_number = ?",
                (repo_full_name, issue_number),
            ).fetchone()
            status_str = existing["status"] if existing else "UNKNOWN"
            raise ValueError(
                f"Cannot create/overwrite order for {repo_full_name}#{issue_number}: "
                f"bounty is already in state '{status_str}'."
            )


def mark_bounty_locked(
    repo_full_name: str, issue_number: int, paypal_auth_id: str
) -> None:
    """
    Records the active PayPal Authorization ID and transitions CREATED -> LOCKED.
    Strictly guarded with `AND status = 'CREATED'` so it can never move a PAID/SETTLING row backwards.
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE bounties
            SET paypal_auth_id = ?,
                status = 'LOCKED',
                updated_at = CURRENT_TIMESTAMP
            WHERE repo_full_name = ?
              AND issue_number = ?
              AND status = 'CREATED'
            """,
            (paypal_auth_id, repo_full_name, issue_number),
        )
        if cursor.rowcount == 0:
            raise RuntimeError(
                f"Failed to lock bounty {repo_full_name}#{issue_number}: "
                "row does not exist or is no longer in 'CREATED' status."
            )


def acquire_settlement_lock(
    repo_full_name: str, issue_number: int, pr_number: int, contributor_paypal: str
) -> bool:
    """
    ATOMIC IDEMPOTENCY GUARD (with 5-minute stale-lock recovery for process crashes):
    Transitions the bounty to 'SETTLING' if it is currently in:
      - 'LOCKED'
      - 'CAPTURE_COMPLETED'
      - 'SETTLING' but updated_at is older than 5 minutes (crashed worker recovery)
    Returns True if this worker acquired the lock, False otherwise.
    """
    with get_db_connection() as conn:
        cursor = conn.execute(
            """
            UPDATE bounties
            SET status = 'SETTLING',
                pr_number = ?,
                contributor_paypal = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE repo_full_name = ?
              AND issue_number = ?
              AND (
                  status IN ('LOCKED', 'CAPTURE_COMPLETED')
                  OR (status = 'SETTLING' AND updated_at < datetime('now', '-5 minutes'))
              )
            """,
            (pr_number, contributor_paypal, repo_full_name, issue_number),
        )
        return cursor.rowcount == 1


def release_settlement_lock(
    repo_full_name: str, issue_number: int, back_to_status: str
) -> None:
    """
    Restores the bounty status to 'LOCKED' or 'CAPTURE_COMPLETED' if an exception
    occurs mid-settlement, allowing subsequent retries to proceed immediately.
    """
    if back_to_status not in ("LOCKED", "CAPTURE_COMPLETED"):
        raise ValueError(f"Invalid rollback status: {back_to_status}")

    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE bounties
            SET status = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE repo_full_name = ?
              AND issue_number = ?
              AND status IN ('SETTLING', 'CAPTURE_COMPLETED')
            """,
            (back_to_status, repo_full_name, issue_number),
        )


def record_capture_success(
    repo_full_name: str, issue_number: int, capture_id: str
) -> None:
    """Saves the capture_id immediately while keeping the row in CAPTURE_COMPLETED."""
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE bounties
            SET paypal_capture_id = ?,
                status = 'CAPTURE_COMPLETED',
                updated_at = CURRENT_TIMESTAMP
            WHERE repo_full_name = ?
              AND issue_number = ?
              AND status = 'SETTLING'
            """,
            (capture_id, repo_full_name, issue_number),
        )


def mark_bounty_paid(
    repo_full_name: str, issue_number: int, payout_batch_id: str
) -> None:
    """Finalizes the bounty state as PAID."""
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE bounties
            SET paypal_payout_batch_id = ?,
                status = 'PAID',
                updated_at = CURRENT_TIMESTAMP
            WHERE repo_full_name = ?
              AND issue_number = ?
              AND status IN ('SETTLING', 'CAPTURE_COMPLETED')
            """,
            (payout_batch_id, repo_full_name, issue_number),
        )


def get_bounty(repo_full_name: str, issue_number: int) -> Optional[dict]:
    """Fetches the current state of a bounty."""
    with get_db_connection() as conn:
        row = conn.execute(
            "SELECT * FROM bounties WHERE repo_full_name = ? AND issue_number = ?",
            (repo_full_name, issue_number),
        ).fetchone()
        return dict(row) if row else None


def register_pr_submission(
    repo_full_name: str,
    issue_number: int,
    pr_number: int,
    contributor_paypal: str,
    webhook_action: str = "opened",
) -> dict:
    """
    Links an incoming GitHub PR and contributor PayPal email to an active bounty.
    Anti-Fraud & Hijack Guards:
    1. First-PR-Wins: Only accepts registration if `pr_number IS NULL` or `pr_number = ?`.
       A second PR cannot hijack a bounty already claimed by an earlier PR.
    2. Post-CI Email Lock: If `webhook_action == 'edited'`, only permits updating the
       PayPal email while `ci_tests_status = 'PENDING'`. Once CI has recorded a result,
       description edits cannot swap the payout address.
    3. Commit Reset: If `webhook_action in ('opened', 'synchronize', 'reopened')`,
       resets `ci_tests_status = 'PENDING'` so new code commits must pass CI fresh.
    """
    with get_db_connection() as conn:
        if webhook_action == "edited":
            cursor = conn.execute(
                """
                UPDATE bounties
                SET pr_number = ?,
                    contributor_paypal = ?,
                    updated_at = CURRENT_TIMESTAMP
                WHERE repo_full_name = ?
                  AND issue_number = ?
                  AND status IN ('CREATED', 'LOCKED')
                  AND (pr_number IS NULL OR pr_number = ?)
                  AND ci_tests_status = 'PENDING'
                """,
                (pr_number, contributor_paypal, repo_full_name, issue_number, pr_number),
            )
        else:
            # opened, synchronize, reopened -> new/updated code requires fresh CI
            cursor = conn.execute(
                """
                UPDATE bounties
                SET pr_number = ?,
                    contributor_paypal = ?,
                    ci_tests_status = 'PENDING',
                    updated_at = CURRENT_TIMESTAMP
                WHERE repo_full_name = ?
                  AND issue_number = ?
                  AND status IN ('CREATED', 'LOCKED')
                  AND (pr_number IS NULL OR pr_number = ?)
                """,
                (pr_number, contributor_paypal, repo_full_name, issue_number, pr_number),
            )

        if cursor.rowcount == 1:
            return {"linked": True, "reason": "ok"}

        # Diagnose why the update was rejected for clear terminal/judge logging
        existing = conn.execute(
            "SELECT status, pr_number, ci_tests_status FROM bounties WHERE repo_full_name = ? AND issue_number = ?",
            (repo_full_name, issue_number),
        ).fetchone()

        if not existing:
            return {"linked": False, "reason": "no_bounty_for_issue"}
        if existing["status"] not in ("CREATED", "LOCKED"):
            return {"linked": False, "reason": f"bounty_already_{existing['status'].lower()}"}
        if existing["pr_number"] is not None and existing["pr_number"] != pr_number:
            return {
                "linked": False,
                "reason": f"hijack_blocked_claimed_by_pr_{existing['pr_number']}",
            }
        if webhook_action == "edited" and existing["ci_tests_status"] != "PENDING":
            return {
                "linked": False,
                "reason": f"email_edit_locked_after_ci_{existing['ci_tests_status'].lower()}",
            }
        return {"linked": False, "reason": "unmatched_state"}

def release_pr_claim(repo_full_name: str, pr_number: int) -> bool:
    """
    Releases the PR claim on a bounty when an unmerged PR is closed,
    allowing another contributor's PR to claim the issue.
    """
    with get_db_connection() as conn:
        cur = conn.execute(
            """
            UPDATE bounties
            SET pr_number = NULL,
                contributor_paypal = NULL,
                ci_tests_status = 'PENDING',
                gemini_score = NULL,
                secrets_detected = 0,
                audit_summary = NULL,
                updated_at = CURRENT_TIMESTAMP
            WHERE repo_full_name = ?
              AND pr_number = ?
              AND status IN ('CREATED', 'LOCKED')
            """,
            (repo_full_name, pr_number),
        )
        return cur.rowcount == 1

def list_all_bounties() -> list[dict]:
    """Returns all bounties ordered newest first (feeds the AG Grid ledger)."""
    with get_db_connection() as conn:
        rows = conn.execute(
            "SELECT * FROM bounties ORDER BY created_at DESC, id DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def record_ci_result(repo_full_name: str, pr_number: int, status: str) -> Optional[dict]:
    """Stores PASSED/FAILED for the PR's bounty. Returns the bounty row if updated."""
    if status not in ("PASSED", "FAILED"):
        raise ValueError(f"Invalid CI status: {status}")
    with get_db_connection() as conn:
        cur = conn.execute(
            """
            UPDATE bounties
            SET ci_tests_status = ?, updated_at = CURRENT_TIMESTAMP
            WHERE repo_full_name = ? AND pr_number = ?
              AND status IN ('CREATED', 'LOCKED')
            """,
            (status, repo_full_name, pr_number),
        )
        if cur.rowcount != 1:
            return None
        row = conn.execute(
            "SELECT * FROM bounties WHERE repo_full_name = ? AND pr_number = ?",
            (repo_full_name, pr_number),
        ).fetchone()
        return dict(row)   

def record_audit_result(
    repo_full_name: str,
    issue_number: int,
    gemini_score: int,
    secrets_detected: bool,
    audit_summary: str,
) -> None:
    """Stores the Gemini security score, secret detection flag, and summary on the bounty row."""
    with get_db_connection() as conn:
        conn.execute(
            """
            UPDATE bounties
            SET gemini_score = ?,
                secrets_detected = ?,
                audit_summary = ?,
                updated_at = CURRENT_TIMESTAMP
            WHERE repo_full_name = ? AND issue_number = ?
            """,
            (
                int(gemini_score),
                1 if secrets_detected else 0,
                audit_summary,
                repo_full_name,
                issue_number,
            ),
        )    