import hashlib
import hmac
import json
import os
import re
from typing import Optional
from dotenv import load_dotenv
from fastapi import APIRouter, BackgroundTasks, Header, HTTPException, Request

from core.database import (
    SettlementInProgressError,
    get_bounty,
    record_audit_result,
    record_ci_result,
    register_pr_submission,
    release_pr_claim,
)
from services.gemini_service import audit_pr_with_gemini
from services.github_service import (
    fetch_issue_details,
    find_prs_for_commit,
    get_pr_head_sha,
    inspect_pr_files_and_diff,
)
from services.paypal_service import settle_bounty_idempotently

load_dotenv()

router = APIRouter(prefix="/webhooks", tags=["GitHub Webhooks"])

# Strictly requires closing keywords: Fixes #1, Closes #1, Resolves #1
ISSUE_REF_REGEX = re.compile(
    r"\b(?:fix(?:es|ed)?|close(?:s|d)?|resolve(?:s|d)?)\s+#(\d+)\b",
    re.IGNORECASE,
)

# Matches "paypal-bounty: sb-xxx@personal.example.com" in the PR description
PAYPAL_EMAIL_REGEX = re.compile(
    r"paypal-bounty:\s*([a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+)",
    re.IGNORECASE,
)


def verify_github_signature(raw_body: bytes, signature_header: Optional[str]) -> None:
    """
    Verifies the X-Hub-Signature-256 HMAC signature sent by GitHub.
    Fails closed if GITHUB_WEBHOOK_SECRET is not configured.
    """
    secret = os.getenv("GITHUB_WEBHOOK_SECRET")
    if not secret:
        if os.getenv("ALLOW_UNSIGNED_WEBHOOKS", "false").lower() == "true":
            print("[WEBHOOK WARNING] ALLOW_UNSIGNED_WEBHOOKS=true; skipping HMAC check.")
            return
        raise HTTPException(
            status_code=500,
            detail="Server misconfigured: GITHUB_WEBHOOK_SECRET is not set.",
        )

    if not signature_header or not signature_header.startswith("sha256="):
        raise HTTPException(
            status_code=401, detail="Missing or invalid X-Hub-Signature-256 header"
        )

    expected_mac = hmac.new(
        key=secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
    expected_sig = f"sha256={expected_mac}"

    if not hmac.compare_digest(expected_sig, signature_header):
        raise HTTPException(status_code=401, detail="GitHub webhook signature mismatch")


def parse_pr_metadata(pr_body: str) -> tuple[Optional[int], Optional[str]]:
    """Extracts (issue_number, contributor_paypal_email) from the PR description text."""
    if not pr_body:
        return None, None

    issue_match = ISSUE_REF_REGEX.search(pr_body)
    email_match = PAYPAL_EMAIL_REGEX.search(pr_body)

    issue_number = int(issue_match.group(1)) if issue_match else None
    paypal_email = email_match.group(1).strip() if email_match else None
    return issue_number, paypal_email


def run_gemini_audit_and_settle(bounty_row: dict, ci_head_sha: str) -> None:
    """
    Background worker triggered when CI unit tests pass:
    1. Verifies the PR's current head_sha still matches ci_head_sha (prevents commit-swap race).
    2. Fetches PR files & diff from GitHub (checking for test/workflow tampering).
    3. Runs deterministic secret regex scan + Gemini security audit.
    4. Re-verifies the DB ledger state and pays strictly to latest["contributor_paypal"].
    """
    repo_full_name = bounty_row["repo_full_name"]
    issue_number = bounty_row["issue_number"]
    pr_number = bounty_row["pr_number"]

    print("\n" + "*" * 65)
    print(
        f"[AUTONOMOUS AGENT] Starting Gemini Audit for {repo_full_name} "
        f"PR #{pr_number} (Issue #{issue_number}, SHA {ci_head_sha[:7]})"
    )

    try:
        if get_pr_head_sha(repo_full_name, pr_number) != ci_head_sha:
            print(
                "  [AUDIT SKIPPED] PR has newer commits than the tested one; a new CI run will decide."
            )
            print("*" * 65)
            return

        pr_inspection = inspect_pr_files_and_diff(repo_full_name, pr_number)
        issue_info = fetch_issue_details(repo_full_name, issue_number)

        audit = audit_pr_with_gemini(
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            issue_title=issue_info["title"],
            issue_body=issue_info["body"],
            pr_number=pr_number,
            diff_text=pr_inspection["diff_text"],
            tampered_files=pr_inspection["tampered_files"],
        )

        record_audit_result(
            repo_full_name=repo_full_name,
            issue_number=issue_number,
            gemini_score=audit.security_score,
            secrets_detected=audit.secrets_found,
            audit_summary=audit.summary,
        )

        print(f"  [GEMINI AUDIT] Score            : {audit.security_score}/100")
        print(f"  [GEMINI AUDIT] Secrets Found    : {audit.secrets_found}")
        print(f"  [GEMINI AUDIT] Prompt Injection : {audit.prompt_injection_attempt}")
        print(f"  [GEMINI AUDIT] Summary          : {audit.summary}")
        if audit.issues:
            print(f"  [GEMINI AUDIT] Issues Flagged   : {audit.issues}")

        # THE GOLDEN SETTLEMENT RULE:
        # Tests Passed AND No Secrets AND No Prompt Injection AND Security Score >= 95
        if (
            not audit.secrets_found
            and not audit.prompt_injection_attempt
            and audit.security_score >= 95
        ):
            latest = get_bounty(repo_full_name, issue_number)
            if not (
                latest
                and latest["pr_number"] == pr_number
                and latest["status"] in ("LOCKED", "CAPTURE_COMPLETED")
                and latest["ci_tests_status"] == "PASSED"
                and latest.get("contributor_paypal")
            ):
                print(
                    "  [PAYOUT BLOCKED] Ledger changed during the audit (new commit or claim released)."
                )
                print("*" * 65)
                return

            print(
                f"  [RULE PASSED] Score {audit.security_score} >= 95, 0 secrets, 0 injection! "
                f"Triggering autonomous PayPal Capture & Payout to {latest['contributor_paypal']}..."
            )
            settlement = settle_bounty_idempotently(
                repo_full_name=repo_full_name,
                issue_number=issue_number,
                pr_number=pr_number,
                contributor_paypal=latest["contributor_paypal"],
            )
            print(f"  [PAYPAL SETTLED] Capture ID     : {settlement['capture_id']}")
            print(f"  [PAYPAL SETTLED] Payout Batch ID: {settlement['payout_batch_id']}")
            print("*" * 65)
        else:
            print(
                f"  [PAYOUT BLOCKED] PR #{pr_number} did not meet settlement threshold "
                f"(score={audit.security_score}, secrets={audit.secrets_found}, "
                f"injection={audit.prompt_injection_attempt}). Hold remains LOCKED."
            )
            print("*" * 65)

    except SettlementInProgressError as exc:
        print(f"  [IDEMPOTENCY] {exc}")
        print("*" * 65)
    except Exception as exc:
        print(
            f"  [AGENT ERROR] Audit/Settlement failed for {repo_full_name}#{issue_number}: {exc}"
        )
        print("*" * 65)


@router.post("/github")
async def github_webhook_listener(
    request: Request,
    background_tasks: BackgroundTasks,
    x_github_event: str = Header(default="unknown"),
    x_github_delivery: str = Header(default="unknown"),
    x_hub_signature_256: Optional[str] = Header(default=None),
):
    raw_body = await request.body()
    verify_github_signature(raw_body, x_hub_signature_256)

    try:
        payload = json.loads(raw_body.decode("utf-8"))
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")

    # 1. Handle GitHub's initial setup ping
    if x_github_event == "ping":
        repo_name = payload.get("repository", {}).get("full_name", "unknown/repo")
        print(f"\n[GITHUB PING] Webhook successfully connected to repo: {repo_name}")
        return {"status": "pong", "repo": repo_name, "delivery_id": x_github_delivery}

    # 2. Handle Pull Request events
    if x_github_event == "pull_request":
        action = payload.get("action")
        pr = payload.get("pull_request", {})
        repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
        pr_number = pr.get("number")
        pr_title = pr.get("title", "")
        pr_author = pr.get("user", {}).get("login", "unknown")
        pr_body = pr.get("body") or ""
        head_sha = pr.get("head", {}).get("sha", "")[:7]

        print("\n" + "=" * 65)
        print(f"[GITHUB WEBHOOK] Event: pull_request | Action: {action}")
        print(f"  Repo        : {repo_full_name}")
        print(f"  PR          : #{pr_number} - {pr_title} (by @{pr_author}, commit {head_sha})")

        # Release bounty claim if PR is closed without merging
        if action == "closed":
            if pr.get("merged"):
                print(f"  [PR MERGED] PR #{pr_number} merged.")
                print("=" * 65)
                return {"status": "processed", "action": "closed", "merged": True}
            released = release_pr_claim(repo_full_name, pr_number)
            print(
                f"  [CLAIM RELEASED] PR #{pr_number} closed unmerged; bounty reopened for others."
                if released
                else "  [NO CLAIM TO RELEASE]"
            )
            print("=" * 65)
            return {"status": "processed", "action": "closed", "claim_released": released}

        if action not in ("opened", "synchronize", "reopened", "edited"):
            print(f"  -> Ignoring pull_request action '{action}'")
            print("=" * 65)
            return {"status": "ignored", "reason": f"Action '{action}' not tracked"}

        issue_number, paypal_email = parse_pr_metadata(pr_body)
        print(
            f"  Linked Issue: #{issue_number}"
            if issue_number
            else "  Linked Issue: None (require 'Fixes #<num>' in PR body)"
        )
        print(
            f"  PayPal Email: {paypal_email}"
            if paypal_email
            else "  PayPal Email: None (require 'paypal-bounty: <email>' in PR body)"
        )

        reg_result = {"linked": False, "reason": "missing_metadata"}
        if issue_number and paypal_email:
            try:
                reg_result = register_pr_submission(
                    repo_full_name=repo_full_name,
                    issue_number=issue_number,
                    pr_number=pr_number,
                    contributor_paypal=paypal_email,
                    webhook_action=action,
                )
                if reg_result["linked"]:
                    print(
                        f"  [DB UPDATED] Linked PR #{pr_number} ({paypal_email}) "
                        f"to {repo_full_name} Issue #{issue_number}"
                    )
                else:
                    print(
                        f"  [SECURITY / DB GUARD] Rejected PR #{pr_number} update -> "
                        f"reason: {reg_result['reason']}"
                    )
            except SettlementInProgressError as exc:
                print(f"  [IDEMPOTENCY] {exc}")
                return {"status": "ignored", "reason": str(exc)}

        print("=" * 65)
        return {
            "status": "processed",
            "event": "pull_request",
            "action": action,
            "repo": repo_full_name,
            "pr_number": pr_number,
            "linked_issue": issue_number,
            "contributor_paypal": paypal_email,
            "registration": reg_result,
        }

    # 3. Handle CI results from GitHub Actions -> Trigger Gemini Audit & Settlement on PASSED
    if x_github_event == "workflow_run":
        run = payload.get("workflow_run", {})
        repo_full_name = payload.get("repository", {}).get("full_name", "unknown/repo")
        if payload.get("action") != "completed" or run.get("name") != "CI":
            return {"status": "ignored", "reason": "not a completed CI run"}

        conclusion = run.get("conclusion")
        head_sha = run.get("head_sha", "")
        pr_numbers = [
            p.get("number") for p in run.get("pull_requests", []) if p.get("number")
        ]

        # Fallback if GitHub leaves pull_requests empty in the workflow_run payload
        if not pr_numbers and head_sha:
            pr_numbers = find_prs_for_commit(repo_full_name, head_sha)

        print("\n" + "=" * 65)
        print(f"[GITHUB WEBHOOK] Event: workflow_run | Conclusion: {conclusion}")
        print(
            f"  Repo: {repo_full_name} | Commit: {head_sha[:7]} | PRs: {pr_numbers}"
        )

        status = {"success": "PASSED", "failure": "FAILED"}.get(conclusion)
        if not status or not pr_numbers:
            print("  -> Ignoring (cancelled/skipped run or no linked PR)")
            print("=" * 65)
            return {"status": "ignored", "conclusion": conclusion}

        results = []
        for pr_num in pr_numbers:
            row = record_ci_result(repo_full_name, pr_num, status)
            if row:
                print(f"  [CI RESULT] PR #{pr_num} -> {status}")
                if status == "PASSED" and row["status"] == "LOCKED":
                    print(
                        f"  [TRIGGER] Queuing Gemini Security Audit & PayPal Settlement for PR #{pr_num}..."
                    )
                    background_tasks.add_task(
                        run_gemini_audit_and_settle, row, head_sha
                    )
                elif status == "PASSED" and row["status"] != "LOCKED":
                    print(
                        f"  [NOTE] CI passed, but bounty status is '{row['status']}' (must be 'LOCKED' to settle)."
                    )
            else:
                print(f"  [CI NOTE] PR #{pr_num} has no active bounty claim")
            results.append({"pr_number": pr_num, "recorded": bool(row)})

        print("=" * 65)
        return {"status": "processed", "ci_status": status, "results": results}

    print(
        f"\n[GITHUB WEBHOOK] Received unhandled event '{x_github_event}' "
        f"(Delivery: {x_github_delivery})"
    )
    return {"status": "ignored", "event": x_github_event}