import React from "react";
import { X, ShieldCheck, ShieldAlert, Receipt, GitPullRequest, CheckCircle2 } from "lucide-react";

export default function AuditDrawer({ bounty, onClose }) {
    if (!bounty) return null;

    const passedAudit =
        bounty.gemini_score !== null &&
        bounty.gemini_score >= 95 &&
        !bounty.secrets_detected;

    return (
        <div className="fixed inset-0 z-50 flex justify-end bg-black/60 backdrop-blur-xs">
            <div className="w-full max-w-lg bg-slate-900 border-l border-slate-800 h-full p-6 overflow-y-auto flex flex-col justify-between">
                <div className="space-y-6">
                    <div className="flex items-center justify-between border-b border-slate-800 pb-4">
                        <div>
                            <span className="text-xs font-mono uppercase tracking-wider text-blue-400">
                                Bounty Inspection Drawer
                            </span>
                            <h2 className="text-lg font-bold text-white mt-0.5">
                                {bounty.repo_full_name} #{bounty.issue_number}
                            </h2>
                        </div>
                        <button
                            onClick={onClose}
                            className="p-2 rounded-lg text-slate-400 hover:text-white hover:bg-slate-800"
                        >
                            <X className="w-5 h-5" />
                        </button>
                    </div>

                    {/* Bounty & Status Summary */}
                    <div className="grid grid-cols-2 gap-4 bg-slate-950/70 p-4 rounded-xl border border-slate-800">
                        <div>
                            <p className="text-xs text-slate-400">Escrow Amount</p>
                            <p className="text-2xl font-mono font-bold text-emerald-400">
                                ${bounty.bounty_amount}
                            </p>
                        </div>
                        <div>
                            <p className="text-xs text-slate-400">Settlement Status</p>
                            <p className="text-lg font-bold text-white mt-1">{bounty.status}</p>
                        </div>
                    </div>

                    {/* GitHub PR & CI Section */}
                    <div className="space-y-2 bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                        <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                            <GitPullRequest className="w-4 h-4 text-purple-400" />
                            GitHub Pull Request & Unit Tests
                        </div>
                        <div className="grid grid-cols-2 gap-2 text-xs pt-2">
                            <div className="text-slate-400">Claimed PR:</div>
                            <div className="font-mono text-slate-200">
                                {bounty.pr_number ? `PR #${bounty.pr_number}` : "Unclaimed"}
                            </div>
                            <div className="text-slate-400">CI Test Suite:</div>
                            <div className="font-mono font-semibold text-slate-200">
                                {bounty.ci_tests_status}
                            </div>
                            <div className="text-slate-400">Contributor PayPal:</div>
                            <div className="font-mono text-slate-200">
                                {bounty.contributor_paypal || "—"}
                            </div>
                        </div>
                    </div>

                    {/* Gemini Security Audit Section */}
                    <div className="space-y-3 bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                        <div className="flex items-center justify-between">
                            <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                                {passedAudit ? (
                                    <ShieldCheck className="w-4 h-4 text-emerald-400" />
                                ) : (
                                    <ShieldAlert className="w-4 h-4 text-amber-400" />
                                )}
                                Gemini Code-Security Audit
                            </div>
                            {bounty.gemini_score !== null && (
                                <span
                                    className={`px-2.5 py-0.5 rounded-full text-xs font-bold ${passedAudit
                                            ? "bg-emerald-500/20 text-emerald-300"
                                            : "bg-rose-500/20 text-rose-300"
                                        }`}
                                >
                                    Score: {bounty.gemini_score}/100
                                </span>
                            )}
                        </div>

                        <div className="text-xs text-slate-300 bg-slate-900 p-3 rounded-lg border border-slate-800 leading-relaxed">
                            {bounty.audit_summary ||
                                "No audit executed yet. Triggered automatically when GitHub Actions CI passes."}
                        </div>

                        <div className="flex items-center justify-between text-xs text-slate-400 pt-1">
                            <span>Hardcoded Secrets Scan:</span>
                            <span
                                className={
                                    bounty.secrets_detected ? "text-rose-400 font-bold" : "text-emerald-400"
                                }
                            >
                                {bounty.secrets_detected ? "SECRETS DETECTED (BLOCKED)" : "0 Secrets Found"}
                            </span>
                        </div>
                    </div>

                    {/* PayPal Transaction Chain */}
                    <div className="space-y-2 bg-slate-950/50 p-4 rounded-xl border border-slate-800">
                        <div className="flex items-center gap-2 text-sm font-semibold text-slate-200">
                            <Receipt className="w-4 h-4 text-blue-400" />
                            PayPal Sandbox Transaction Ledger
                        </div>
                        <div className="space-y-2 text-xs pt-2 font-mono">
                            <div className="flex justify-between">
                                <span className="text-slate-400">1. Order ID:</span>
                                <span className="text-slate-200">{bounty.paypal_order_id || "—"}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-400">2. Auth Hold ID:</span>
                                <span className="text-amber-300">{bounty.paypal_auth_id || "—"}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-400">3. Capture ID:</span>
                                <span className="text-blue-300">{bounty.paypal_capture_id || "—"}</span>
                            </div>
                            <div className="flex justify-between">
                                <span className="text-slate-400">4. Payout Batch ID:</span>
                                <span className="text-emerald-400 font-bold">
                                    {bounty.paypal_payout_batch_id || "—"}
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                <div className="pt-4 border-t border-slate-800 text-[11px] text-slate-500 flex items-center justify-between">
                    <span>Updated: {bounty.updated_at}</span>
                    <span className="inline-flex items-center gap-1 text-emerald-400">
                        <CheckCircle2 className="w-3.5 h-3.5" /> Idempotent State Guard Active
                    </span>
                </div>
            </div>
        </div>
    );
}