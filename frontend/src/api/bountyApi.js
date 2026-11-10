const API_BASE = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export async function fetchBounties() {
  const res = await fetch(`${API_BASE}/bounties`);
  if (!res.ok) {
    throw new Error(`Failed to fetch ledger: HTTP ${res.status}`);
  }
  const data = await res.json();
  return data.bounties || [];
}

export async function createBountyOrder({ repoFullName, issueNumber, amountUsd, apiKey }) {
  const res = await fetch(`${API_BASE}/bounties`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
    },
    body: JSON.stringify({
      repo_full_name: repoFullName.trim(),
      issue_number: Number(issueNumber),
      amount_usd: Number(amountUsd).toFixed(2),
      rehearsal_run_id: String(Math.floor(Date.now() / 1000)),
    }),
  });
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return data;
}

export async function authorizeBountyHold({ repoFullName, issueNumber, apiKey }) {
  const [owner, repo] = repoFullName.trim().split("/");
  const res = await fetch(
    `${API_BASE}/bounties/${owner}/${repo}/${Number(issueNumber)}/authorize`,
    {
      method: "POST",
      headers: {
        "X-API-Key": apiKey,
      },
    }
  );
  const data = await res.json();
  if (!res.ok) {
    throw new Error(data.detail || `HTTP ${res.status}`);
  }
  return data;
}