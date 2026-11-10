import hmac
import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field

from core.database import (
    get_bounty,
    list_all_bounties,
    mark_bounty_locked,
    upsert_bounty_order,
)
from services.paypal_service import (
    PayPalAPIError,
    authorize_bounty_order,
    create_bounty_order,
)

load_dotenv()

router = APIRouter(prefix="/bounties", tags=["Bounties"])


def require_maintainer_api_key(x_api_key: Optional[str] = Header(default=None)) -> None:
    """
    Protects write endpoints exposed via ngrok using X-API-Key.
    """
    expected_key = os.getenv("MAINTAINER_API_KEY")
    if not expected_key:
        raise HTTPException(
            status_code=500,
            detail="Server misconfigured: MAINTAINER_API_KEY is not set in .env",
        )
    if not x_api_key or not hmac.compare_digest(expected_key, x_api_key):
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def _mask_email(email: Optional[str]) -> Optional[str]:
    """Masks contributor PayPal email for public GET ledger responses."""
    if not email or "@" not in email:
        return email
    local, domain = email.split("@", 1)
    visible = local[:4] if len(local) > 4 else local[:1]
    return f"{visible}***@{domain}"


class CreateBountyRequest(BaseModel):
    repo_full_name: str = Field(..., examples=["subham/pr-bountypay-demo"])
    issue_number: int = Field(..., gt=0, examples=[1])
    amount_usd: str = Field(..., pattern=r"^\d+(\.\d{2})?$", examples=["120.00"])
    rehearsal_run_id: Optional[str] = Field(
        default=None,
        description="Optional suffix so rehearsal re-runs on the same issue create a fresh PayPal order.",
    )


@router.get("")
def get_all_bounties():
    """Returns all bounties for the AG Grid ledger (with masked emails for privacy)."""
    rows = list_all_bounties()
    for row in rows:
        row["contributor_paypal"] = _mask_email(row.get("contributor_paypal"))
    return {"bounties": rows}


@router.post("", dependencies=[Depends(require_maintainer_api_key)])
def create_bounty_endpoint(req: CreateBountyRequest):
    """
    Step 1: Creates a PayPal Order (intent=AUTHORIZE) and records it in SQLite.
    Protected by X-API-Key.
    """
    try:
        order = create_bounty_order(
            repo_full_name=req.repo_full_name,
            issue_number=req.issue_number,
            amount_usd=req.amount_usd,
            test_run_id=req.rehearsal_run_id,
        )
        upsert_bounty_order(
            repo_full_name=req.repo_full_name,
            issue_number=req.issue_number,
            bounty_amount=req.amount_usd,
            paypal_order_id=order["order_id"],
        )
        return {
            "status": "CREATED",
            "repo_full_name": req.repo_full_name,
            "issue_number": req.issue_number,
            "amount_usd": req.amount_usd,
            "order_id": order["order_id"],
            "approve_url": order["approve_url"],
        }
    except (ValueError, PayPalAPIError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post(
    "/{repo_owner}/{repo_name}/{issue_number}/authorize",
    dependencies=[Depends(require_maintainer_api_key)],
)
def authorize_bounty_endpoint(repo_owner: str, repo_name: str, issue_number: int):
    """
    Step 2: Authorizes the hold and transitions CREATED -> LOCKED.
    Protected by X-API-Key.
    """
    repo_full_name = f"{repo_owner}/{repo_name}"
    bounty = get_bounty(repo_full_name, issue_number)
    if not bounty:
        raise HTTPException(status_code=404, detail="Bounty not found")

    try:
        auth_res = authorize_bounty_order(bounty["paypal_order_id"])
        mark_bounty_locked(repo_full_name, issue_number, auth_res["authorization_id"])
        return {
            "status": "LOCKED",
            "repo_full_name": repo_full_name,
            "issue_number": issue_number,
            "authorization_id": auth_res["authorization_id"],
        }
    except (RuntimeError, PayPalAPIError) as exc:
        raise HTTPException(status_code=400, detail=str(exc))	