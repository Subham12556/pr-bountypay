import React, { useMemo } from "react";
import { AgGridReact } from "ag-grid-react";
import { AllCommunityModule, ModuleRegistry, themeQuartz } from "ag-grid-community";
import { ExternalLink, ShieldAlert, ShieldCheck, Clock, Lock, CheckCircle2 } from "lucide-react";

ModuleRegistry.registerModules([AllCommunityModule]);

const darkGridTheme = themeQuartz.withParams({
  backgroundColor: "#0f172a",
  foregroundColor: "#e2e8f0",
  headerBackgroundColor: "#1e293b",
  headerTextColor: "#94a3b8",
  oddRowBackgroundColor: "#0b1120",
  rowHoverColor: "#1e293b",
  borderColor: "#1e293b",
  accentColor: "#3b82f6",
  fontFamily: "inherit",
});

function StatusBadgeRenderer({ value }) {
  const styles = {
    PAID: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    LOCKED: "bg-amber-500/15 text-amber-400 border-amber-500/30",
    SETTLING: "bg-blue-500/15 text-blue-400 border-blue-500/30 animate-pulse",
    CAPTURE_COMPLETED: "bg-indigo-500/15 text-indigo-400 border-indigo-500/30",
    CREATED: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  };
  const Icons = {
    PAID: CheckCircle2,
    LOCKED: Lock,
    SETTLING: Clock,
    CREATED: Clock,
  };
  const Icon = Icons[value] || Clock;
  return (
    <span
      className={`inline-flex items-center gap-1.5 px-2.5 py-0.5 rounded-full text-xs font-semibold border ${
        styles[value] || styles.CREATED
      }`}
    >
      <Icon className="w-3.5 h-3.5" />
      {value}
    </span>
  );
}

function CiBadgeRenderer({ value }) {
  const styles = {
    PASSED: "bg-emerald-500/15 text-emerald-400 border-emerald-500/30",
    FAILED: "bg-rose-500/15 text-rose-400 border-rose-500/30",
    PENDING: "bg-slate-500/15 text-slate-400 border-slate-500/30",
  };
  return (
    <span
      className={`inline-flex items-center px-2.5 py-0.5 rounded-md text-xs font-mono font-medium border ${
        styles[value] || styles.PENDING
      }`}
    >
      {value || "PENDING"}
    </span>
  );
}

function GeminiScoreRenderer({ data }) {
  const score = data?.gemini_score;
  const secrets = data?.secrets_detected;

  if (score === null || score === undefined) {
    return <span className="text-slate-500 text-xs italic">Awaiting CI</span>;
  }

  const passed = score >= 95 && !secrets;
  return (
    <div className="flex items-center gap-2">
      <span
        className={`inline-flex items-center gap-1 px-2.5 py-0.5 rounded-full text-xs font-bold border ${
          passed
            ? "bg-emerald-500/15 text-emerald-400 border-emerald-500/30"
            : "bg-rose-500/15 text-rose-400 border-rose-500/30"
        }`}
      >
        {passed ? <ShieldCheck className="w-3.5 h-3.5" /> : <ShieldAlert className="w-3.5 h-3.5" />}
        {score}/100
      </span>
      {secrets ? (
        <span className="text-[11px] bg-rose-600/30 text-rose-300 px-1.5 py-0.5 rounded">
          SECRET LEAK
        </span>
      ) : null}
    </div>
  );
}

function IssuePrLinkRenderer({ data }) {
  const repo = data?.repo_full_name;
  const issue = data?.issue_number;
  const pr = data?.pr_number;
  return (
    <div className="flex items-center gap-2 text-xs">
      <a
        href={`https://github.com/${repo}/issues/${issue}`}
        target="_blank"
        rel="noreferrer"
        onClick={(e) => e.stopPropagation()}
        className="text-blue-400 hover:text-blue-300 font-semibold inline-flex items-center gap-1"
      >
        Issue #{issue}
        <ExternalLink className="w-3 h-3" />
      </a>
      {pr ? (
        <>
          <span className="text-slate-600">→</span>
          <a
            href={`https://github.com/${repo}/pull/${pr}`}
            target="_blank"
            rel="noreferrer"
            onClick={(e) => e.stopPropagation()}
            className="text-purple-400 hover:text-purple-300 font-semibold inline-flex items-center gap-1"
          >
            PR #{pr}
            <ExternalLink className="w-3 h-3" />
          </a>
        </>
      ) : (
        <span className="text-slate-500 italic">No PR yet</span>
      )}
    </div>
  );
}

export default function BountyLedgerGrid({ bounties, quickFilterText, onSelectBounty }) {
  const columnDefs = useMemo(
    () => [
      {
        field: "repo_full_name",
        headerName: "Repository",
        minWidth: 210,
        flex: 1.2,
        filter: true,
        cellClass: "font-mono text-xs text-slate-200 font-medium",
      },
      {
        headerName: "Issue / Claimed PR",
        minWidth: 185,
        flex: 1,
        valueGetter: (p) => `Issue #${p.data?.issue_number} PR #${p.data?.pr_number ?? ""}`,
        cellRenderer: IssuePrLinkRenderer,
      },
      {
        field: "bounty_amount",
        headerName: "Bounty (USD)",
        width: 135,
        valueFormatter: (p) => (p.value ? `$${p.value}` : "$0.00"),
        cellClass: "font-mono font-bold text-emerald-400",
      },
      {
        field: "status",
        headerName: "Escrow Status",
        width: 155,
        filter: true,
        cellRenderer: StatusBadgeRenderer,
      },
      {
        field: "ci_tests_status",
        headerName: "GitHub CI",
        width: 130,
        filter: true,
        cellRenderer: CiBadgeRenderer,
      },
      {
        field: "gemini_score",
        headerName: "Gemini Audit",
        width: 230,
        cellRenderer: GeminiScoreRenderer,
      },
      {
        field: "contributor_paypal",
        headerName: "Contributor PayPal",
        minWidth: 195,
        flex: 1,
        cellClass: "font-mono text-xs text-slate-300",
        valueFormatter: (p) => p.value || "—",
      },
      {
        field: "paypal_payout_batch_id",
        headerName: "PayPal Batch / Auth ID",
        minWidth: 190,
        flex: 1,
        cellClass: "font-mono text-xs text-slate-400",
        valueGetter: (p) =>
          p.data?.paypal_payout_batch_id
            ? `PAID: ${p.data.paypal_payout_batch_id}`
            : p.data?.paypal_auth_id
            ? `AUTH: ${p.data.paypal_auth_id}`
            : `ORD: ${p.data?.paypal_order_id || "—"}`,
      },
      {
        field: "audit_summary",
        headerName: "AI Security Verdict",
        minWidth: 280,
        flex: 1.8,
        cellClass: "text-xs text-slate-300 truncate",
        valueFormatter: (p) => p.value || "Waiting for Pull Request & CI...",
      },
    ],
    []
  );

  const defaultColDef = useMemo(
    () => ({
      sortable: true,
      resizable: true,
    }),
    []
  );

  return (
    <div className="w-full h-[520px] rounded-xl overflow-hidden border border-slate-800 shadow-2xl">
      <AgGridReact
        theme={darkGridTheme}
        rowData={bounties}
        getRowId={(p) => String(p.data.id)}
        columnDefs={columnDefs}
        defaultColDef={defaultColDef}
        quickFilterText={quickFilterText}
        animateRows={true}
        rowHeight={52}
        headerHeight={44}
        onRowClicked={(e) => onSelectBounty(e.data)}
        overlayNoRowsTemplate="<span class='text-slate-400 text-sm'>No bounties in ledger yet. Click 'Lock New Bounty' to create one.</span>"
      />
    </div>
  );
}