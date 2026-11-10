# PR-BountyPay

**An autonomous escrow agent for GitHub bounties.** A maintainer locks money on an issue. When a contributor's pull request passes the tests *and* an AI security review, the agent pays them through PayPal automatically. Anything suspicious is held, and the dashboard shows why.

> Built for the PayPal AI Hackathon. Runs entirely on the **PayPal Sandbox** (test money).

- Demo video: `<YouTube link>`
- Demo repository the agent runs against: https://github.com/Subham12556/pr-bountypay-demo
  - Paid: [PR #4](https://github.com/Subham12556/pr-bountypay-demo/pull/4) | Secret blocked: [PR #6](https://github.com/Subham12556/pr-bountypay-demo/pull/6) | Tests edited, CI failed: [PR #8](https://github.com/Subham12556/pr-bountypay-demo/pull/8)

## The problem

Paying outside contributors is slow and risky. Someone has to check that the fix is real, watch for spam or malicious code, and move the money by hand. Contributors fear doing the work and never being paid. PR-BountyPay enforces fixed rules the same way every time.

## How it works

1. **Lock.** The maintainer locks a bounty on an issue from the dashboard. PayPal places an authorization hold (funds reserved, not moved).
2. **Claim.** A contributor opens a PR with these lines in the description. The first PR to claim an issue wins, and the payout email is locked once CI has run.
   ```
   Fixes #5
   paypal-bounty: contributor@example.com
   ```
3. **Test.** GitHub Actions runs the unit tests. A PR that edits `tests/` or `.github/` fails automatically.
4. **Audit.** If tests pass, the agent reads the diff. It runs a fixed pattern scan for hard-coded secrets, checks for tampered protected files, then asks Gemini for a structured security review (score, secrets, prompt-injection attempt, verdict).
5. **Pay.** Only if tests pass, no secrets are found, no injection is detected and the score is **95 or higher**, the agent captures the hold and sends a PayPal Payout.
6. **Hold.** Otherwise nothing moves, and the ledger shows the reason.

### Outcomes tested on the sandbox

| Scenario | Result |
|---|---|
| Correct fix using constant-time comparison | CI passed, audit 100/100, **$120 paid** |
| First version of the fix using `==` | audit 90/100, **payout blocked** |
| PR that adds a hard-coded credential | CI passed, audit 0/100, **secret leak, funds held** |
| PR that deletes a test | **CI failed**, no audit, no payout |

## Architecture

```
Maintainer --(dashboard)--> FastAPI backend --> PayPal Orders (AUTHORIZE hold)
Contributor --(PR)--> GitHub --webhook--> FastAPI backend
                         |                    |-- verify signature, link PR to bounty
                         +-- Actions CI ------|-- CI result (workflow_run)
                                              |-- fetch diff -> secret scan -> Gemini audit
                                              |-- all gates pass -> PayPal capture + Payout
React + AG Grid dashboard <---- GET /bounties (live ledger, SQLite)
```

- **Backend:** Python, FastAPI, SQLite ledger with a strict state machine (`CREATED, LOCKED, SETTLING, CAPTURE_COMPLETED, PAID`)
- **AI:** Google Gemini (`google-genai`), typed JSON schema output, retry on temporary errors
- **Payments:** PayPal Orders v2 (`AUTHORIZE`), Payments v2 (capture), Payouts
- **Frontend:** React, Vite, Tailwind CSS, AG Grid

## Safeguards

- GitHub webhook signatures (HMAC) are verified. Write endpoints need an API key.
- The audit is pinned to the commit CI tested. If new commits arrive, the newer run decides.
- Payout email locks after the first CI result, and the first PR to claim an issue wins.
- Secrets are caught by a fixed pattern scan, not only by the model. The diff is treated as untrusted text.
- Oversized diffs are held, not truncated. A failed audit never pays.
- The ledger is re-read right before paying. Payments use deterministic PayPal request/batch IDs plus ledger guards, so a redelivered webhook cannot pay twice.
- Public ledger emails are masked.

## Run it yourself

**Prerequisites:** Python 3.11+, Node 20+, a [PayPal Developer](https://developer.paypal.com) sandbox, a Gemini API key, a GitHub repo you control, and a tunnel such as ngrok.

### 1. PayPal sandbox setup
- Create a **Business** and a **Personal (buyer)** sandbox account, both with country **United States** (accounts registered in other countries cannot send Payouts). Create a second US Personal account to receive payouts.
- Under *Apps & Credentials* (Sandbox), create an app on the US Business account and enable **Payouts**.

### 2. Backend
```bash
cd backend
python -m venv venv
venv\Scripts\activate          # macOS/Linux: source venv/bin/activate
pip install -r requirements.txt
copy .env.example .env         # macOS/Linux: cp .env.example .env
```
Fill in `.env`:

| Variable | What it is |
|---|---|
| `PAYPAL_CLIENT_ID`, `PAYPAL_CLIENT_SECRET` | Sandbox app credentials |
| `PAYPAL_BASE_URL` | `https://api-m.sandbox.paypal.com` |
| `GITHUB_WEBHOOK_SECRET` | Random string you invent (`python -c "import secrets; print(secrets.token_hex(32))"`) |
| `MAINTAINER_API_KEY` | Random string you invent, entered in the dashboard |
| `GEMINI_API_KEY`, `GEMINI_MODEL` | Google AI Studio key and a current Flash model |
| `GITHUB_TOKEN` | Optional read-only token (avoids rate limits) |

```bash
uvicorn main:app --reload --port 8000
```

### 3. Frontend
```bash
cd frontend
npm install
npm run dev
```
Open http://localhost:5173.

### 4. Connect GitHub
- In the repo you want to run it on, add `.github/workflows/ci.yml` (see below) and a test suite in `tests/`.
- Expose the backend: `ngrok http 8000`.
- Repo *Settings > Webhooks > Add webhook*: URL `https://<tunnel>/webhooks/github`, content type `application/json`, secret = `GITHUB_WEBHOOK_SECRET`, events: **Pull requests** and **Workflow runs**.

<details>
<summary>ci.yml</summary>

```yaml
name: CI

on:
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with:
          fetch-depth: 0
      - name: Block edits to tests or workflows
        env:
          BASE: ${{ github.base_ref }}
        run: |
          CHANGED=$(git diff --name-only "origin/$BASE" HEAD)
          echo "$CHANGED"
          if echo "$CHANGED" | grep -E '^(tests/|\.github/)'; then
            echo "::error::PR modifies protected paths (tests/ or .github/)"
            exit 1
          fi
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install pytest
      - name: Run unit tests
        run: python -m pytest -q
```
</details>

### 5. Try it
1. Create an issue in your repo.
2. Dashboard: **Lock New Bounty**, enter the issue number and amount, approve the PayPal sandbox checkout with the buyer account, then confirm.
3. Open a PR from a branch with `Fixes #N` and `paypal-bounty: <developer sandbox email>` in the description.
4. Watch the ledger. A good fix is paid. A bad one is held.

To check the PayPal flow alone: `python backend/scripts/test_paypal_day1.py`.

## Known limitations

- **Sandbox only.** Live use needs live PayPal credentials and Payouts enabled by PayPal.
- `PAID` currently means PayPal accepted the payout batch. Production needs reconciliation against payout item status and PayPal webhooks, plus a recovery state for ambiguous capture timeouts.
- PayPal authorization holds expire after days, so long-open bounties need re-authorization.
- The audit reads the PR diff, not the whole repository. Fork PRs are not supported yet.
- The ledger endpoint is read-only and open (sandbox data). Add authentication and pagination before any public deployment.
- Planned: a static analyzer (Bandit/Semgrep) in CI, stricter path policy for renamed test files, and automatic merging.

## License

MIT, see [LICENSE](LICENSE).