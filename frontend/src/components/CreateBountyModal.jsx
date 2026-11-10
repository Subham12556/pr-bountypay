import React, { useState } from "react";
import { X, Lock, ExternalLink, CheckCircle2 } from "lucide-react";
import { createBountyOrder, authorizeBountyHold } from "../api/bountyApi";

export default function CreateBountyModal({ isOpen, onClose, onSuccess }) {
  const [repoFullName, setRepoFullName] = useState("Subham12556/pr-bountypay-demo");
  const [issueNumber, setIssueNumber] = useState("2");
  const [amountUsd, setAmountUsd] = useState("150.00");
  const [apiKey, setApiKey] = useState("");
  const [step, setStep] = useState("CREATE"); // CREATE | APPROVE
  const [orderData, setOrderData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  if (!isOpen) return null;

  async function handleCreateOrder(e) {
    e.preventDefault();
    setError("");
    setLoading(true);
    try {
      const res = await createBountyOrder({
        repoFullName,
        issueNumber,
        amountUsd,
        apiKey,
      });
      setOrderData(res);
      setStep("APPROVE");
      window.open(res.approve_url, "_blank");
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  async function handleAuthorizeHold() {
    setError("");
    setLoading(true);
    try {
      await authorizeBountyHold({
        repoFullName,
        issueNumber,
        apiKey,
      });
      onSuccess();
      onClose();
      setStep("CREATE");
      setOrderData(null);
    } catch (err) {
      setError(err.message);
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 backdrop-blur-xs p-4">
      <div className="w-full max-w-md bg-slate-900 border border-slate-800 rounded-2xl p-6 shadow-2xl space-y-5">
        <div className="flex items-center justify-between border-b border-slate-800 pb-3">
          <div className="flex items-center gap-2">
            <Lock className="w-5 h-5 text-blue-400" />
            <h3 className="text-base font-bold text-white">
              Lock New GitHub Issue Bounty
            </h3>
          </div>
          <button onClick={onClose} className="text-slate-400 hover:text-white">
            <X className="w-5 h-5" />
          </button>
        </div>

        {error && (
          <div className="p-3 rounded-lg bg-rose-500/15 border border-rose-500/30 text-xs text-rose-300">
            {error}
          </div>
        )}

        {step === "CREATE" ? (
          <form onSubmit={handleCreateOrder} className="space-y-4 text-sm">
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                GitHub Repository (owner/repo)
              </label>
              <input
                type="text"
                required
                value={repoFullName}
                onChange={(e) => setRepoFullName(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono text-xs"
              />
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Issue Number (#)
                </label>
                <input
                  type="number"
                  min="1"
                  required
                  value={issueNumber}
                  onChange={(e) => setIssueNumber(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono text-xs"
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">
                  Bounty Amount (USD)
                </label>
                <input
                  type="text"
                  required
                  value={amountUsd}
                  onChange={(e) => setAmountUsd(e.target.value)}
                  className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-emerald-400 font-mono font-bold text-xs"
                />
              </div>
            </div>
            <div>
              <label className="block text-xs text-slate-400 mb-1">
                Maintainer API Key (X-API-Key)
              </label>
              <input
                type="password"
                required
                placeholder="From backend/.env MAINTAINER_API_KEY"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                className="w-full px-3 py-2 rounded-lg bg-slate-950 border border-slate-800 text-white font-mono text-xs"
              />
            </div>
            <button
              type="submit"
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-blue-600 hover:bg-blue-500 disabled:opacity-50 text-white font-semibold text-xs transition"
            >
              {loading ? "Creating PayPal Order..." : "1. Create PayPal Authorization Order"}
            </button>
          </form>
        ) : (
          <div className="space-y-4 text-xs">
            <div className="p-3 rounded-lg bg-blue-500/10 border border-blue-500/30 text-blue-200 space-y-2">
              <p className="font-semibold">
                Order Created: <span className="font-mono">{orderData?.order_id}</span>
              </p>
              <p>
                Approve the hold in the PayPal Sandbox tab that just opened, then click
                below to lock the Authorization Hold.
              </p>
              <a
                href={orderData?.approve_url}
                target="_blank"
                rel="noreferrer"
                className="inline-flex items-center gap-1 text-blue-400 underline font-semibold"
              >
                Re-open PayPal Approval Checkout <ExternalLink className="w-3.5 h-3.5" />
              </a>
            </div>

            <button
              onClick={handleAuthorizeHold}
              disabled={loading}
              className="w-full py-2.5 rounded-lg bg-emerald-600 hover:bg-emerald-500 disabled:opacity-50 text-white font-semibold text-xs flex items-center justify-center gap-1.5"
            >
              <CheckCircle2 className="w-4 h-4" />
              {loading ? "Locking Authorization Hold..." : "2. Confirm & Lock Authorization Hold"}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}