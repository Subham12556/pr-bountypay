import os
import requests
from dotenv import load_dotenv

load_dotenv()

GITHUB_API_BASE = "https://api.github.com"

# Protected paths a contributor PR is NEVER allowed to modify
PROTECTED_PATH_PREFIXES = (
    ".github/",
    "tests/",
    "test/",
)


def _github_headers(accept: str = "application/vnd.github+json") -> dict:
    headers = {
        "Accept": accept,
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "PR-BountyPay-Agent",
    }
    token = os.getenv("GITHUB_TOKEN", "").strip()
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def get_pr_head_sha(repo_full_name: str, pr_number: int) -> str:
    """Fetches the current head commit SHA of the PR to prevent TOCTOU commit swaps."""
    url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}"
    resp = requests.get(url, headers=_github_headers(), timeout=15)
    resp.raise_for_status()
    return resp.json()["head"]["sha"]


def find_prs_for_commit(repo_full_name: str, head_sha: str) -> list[int]:
    """
    Fallback when workflow_run.pull_requests is empty in the webhook payload.
    Queries GitHub API for open PRs associated with head_sha.
    """
    url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/commits/{head_sha}/pulls"
    resp = requests.get(url, headers=_github_headers(), timeout=15)
    if not resp.ok:
        return []
    return [
        pr["number"]
        for pr in resp.json()
        if isinstance(pr, dict) and pr.get("state") == "open" and pr.get("number")
    ]


def fetch_issue_details(repo_full_name: str, issue_number: int) -> dict:
    """Fetches the issue title and body so Gemini knows what bug the PR is supposed to fix."""
    url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/issues/{issue_number}"
    resp = requests.get(url, headers=_github_headers(), timeout=15)
    if not resp.ok:
        return {"title": f"Issue #{issue_number}", "body": ""}
    data = resp.json()
    return {
        "title": data.get("title") or f"Issue #{issue_number}",
        "body": data.get("body") or "",
    }


def inspect_pr_files_and_diff(repo_full_name: str, pr_number: int) -> dict:
    """
    Fetches up to 100 modified files in the PR and the unified git diff.
    Checks whether any modified file touches protected test suites or CI workflows.
    """
    files_url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}/files"
    files_resp = requests.get(
        files_url,
        headers=_github_headers(),
        params={"per_page": 100},
        timeout=15,
    )
    files_resp.raise_for_status()
    files_data = files_resp.json()

    changed_files: list[str] = []
    tampered_files: list[str] = []

    # Guard against PRs with >= 100 files hiding tampered test files on page 2
    if len(files_data) >= 100:
        tampered_files.append("OVER_100_FILES_CHANGED_LIMIT")

    for f in files_data:
        filename = f.get("filename", "")
        changed_files.append(filename)
        lower_name = filename.lower()
        basename = lower_name.rsplit("/", 1)[-1]
        if (
            lower_name.startswith(PROTECTED_PATH_PREFIXES)
            or basename.startswith("test_")
            or basename.endswith("_test.py")
            or basename == "conftest.py"
        ):
            tampered_files.append(filename)

    # Fetch raw unified diff using GitHub's v3 diff media type
    diff_url = f"{GITHUB_API_BASE}/repos/{repo_full_name}/pulls/{pr_number}"
    diff_resp = requests.get(
        diff_url,
        headers=_github_headers(accept="application/vnd.github.v3.diff"),
        timeout=15,
    )
    diff_resp.raise_for_status()

    return {
        "tampered_files": tampered_files,
        "changed_files": changed_files,
        "diff_text": diff_resp.text,
    }