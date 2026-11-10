import React, { useEffect, useState } from "react";
import {
  ShieldCheck,
  Lock,
  CheckCircle2,
  DollarSign,
  Plus,
  RefreshCw,
  Search,
  Sparkles,
} from "lucide-react";
import { fetchBounties } from "./api/bountyApi";
import BountyLedgerGrid from "./components/BountyLedgerGrid";
import AuditDrawer from "./components/AuditDrawer";
import CreateBountyModal from "./components/CreateBountyModal";

export default function App() {
  const [bounties, setBounties] = useState([]);
  const [quickFilter, setQuickFilter] = useState("");
  const [selectedBounty, setSelectedBounty] = useState(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const [lastSynced, setLastSynced] = useState(null);

  async function loadLedger() {
    try {
      const rows = await fetchBounties();
      setBounties(rows);
      setLastSynced(new Date().toLocaleTimeString());
      setSelectedBounty((prev) =>
        prev
          ? rows.find(
              (r) =>
                r.repo_full_name === prev.repo_full_name &&
                r.issue_number === prev.issue_number
            ) ?? prev
          : prev
      );
    } catch (err) {
      console.error("Ledger sync error:", err);
    }
  }

  useEffect(() => {
    loadLedger();
    const interval = setInterval(loadLedger, 3000);
    return () => clearInterval(interval);
  }, []);

  const totalEscrowLocked = bounties
    .filter((b) => b.status === "LOCKED")
    .reduce((sum, b) => sum + parseFloat(b.bounty_amount || 0), 0);

  const totalPaidOut = bounties
    .filter((b) => b.status === "PAID")
    .reduce((sum, b) => sum + parseFloat(b.bounty_amount || 0), 0);

  const paidCount = bounties.filter((b) => b.status === "PAID").length;

  return (
    <div className="min-h-screen bg-[#090d16] text-slate-100">
      {/* Top Navbar */}
      <header className="border-b border-slate-800/80 bg-slate-950/60 backdrop-blur-md sticky top-0 z-30">
        <div className="max-w-7xl mx-auto px-6 py-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-10 h-10 rounded-xl bg-blue-600/20 border border-blue-500/40 flex items-center justify-center">
              <ShieldCheck className="w-6 h-6 text-blue-400" />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-lg font-bold tracking-tight text-white">
                  PR-BountyPay
                </h1>
                <span className="text-[11px] font-mono uppercase px-2 py-0.5 rounded-full bg-blue-500/15 text-blue-400 border border-blue-500/30">
                  Autonomous Escrow Agent
                </span>
              </div>
              <p className="text-xs text-slate-400">
                GitHub Actions CI + Gemini code-security audit + instant PayPal sandbox payouts
              </p>
            </div>
          </div>

          <div className="flex items-center gap-3">
            <div className="hidden sm:flex items-center gap-1.5 text-xs text-slate-400 bg-slate-900 px-3 py-1.5 rounded-lg border border-slate-800">
              <span className="w-2 h-2 rounded-full bg-emerald-400 animate-ping" />
              <span>Live Sync ({lastSynced || "..."})</span>
            </div>
            <button
              onClick={() => setIsModalOpen(true)}
              className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-blue-600 hover:bg-blue-500 text-white font-semibold text-xs shadow-lg shadow-blue-600/25 transition cursor-pointer"
            >
              <Plus className="w-4 h-4" />
              Lock New Bounty
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-7xl mx-auto px-6 py-6 space-y-6">
        {/* KPI Metric Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-4 gap-4">
          <div className="bg-slate-900/90 border border-slate-800 p-4 rounded-xl flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">Active Escrow Holds</p>
              <p className="text-2xl font-mono font-bold text-amber-400 mt-1">
                ${totalEscrowLocked.toFixed(2)}
              </p>
            </div>
            <div className="p-3 rounded-lg bg-amber-500/10 text-amber-400">
              <Lock className="w-5 h-5" />
            </div>
          </div>

          <div className="bg-slate-900/90 border border-slate-800 p-4 rounded-xl flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">Autonomously Disbursed</p>
              <p className="text-2xl font-mono font-bold text-emerald-400 mt-1">
                ${totalPaidOut.toFixed(2)}
              </p>
            </div>
            <div className="p-3 rounded-lg bg-emerald-500/10 text-emerald-400">
              <DollarSign className="w-5 h-5" />
            </div>
          </div>

          <div className="bg-slate-900/90 border border-slate-800 p-4 rounded-xl flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">Bounties Settled</p>
              <p className="text-2xl font-mono font-bold text-white mt-1">
                {paidCount} / {bounties.length}
              </p>
            </div>
            <div className="p-3 rounded-lg bg-blue-500/10 text-blue-400">
              <CheckCircle2 className="w-5 h-5" />
            </div>
          </div>

          <div className="bg-slate-900/90 border border-slate-800 p-4 rounded-xl flex items-center justify-between">
            <div>
              <p className="text-xs text-slate-400">Settlement Gate</p>
              <p className="text-sm font-mono font-bold text-purple-300 mt-2">
                CI PASS + Score ≥ 95
              </p>
            </div>
            <div className="p-3 rounded-lg bg-purple-500/10 text-purple-400">
              <Sparkles className="w-5 h-5" />
            </div>
          </div>
        </div>

        {/* Filter Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3">
          <div className="relative flex-1 max-w-md">
            <Search className="w-4 h-4 text-slate-400 absolute left-3.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              placeholder="Search repository, issue #, PR #, PayPal batch ID, or audit verdict..."
              value={quickFilter}
              onChange={(e) => setQuickFilter(e.target.value)}
              className="w-full pl-10 pr-4 py-2 rounded-xl bg-slate-900 border border-slate-800 text-xs text-white placeholder-slate-500 focus:outline-none focus:border-blue-500"
            />
          </div>
          <div className="flex items-center gap-2 text-xs text-slate-400">
            <span>Click any row to inspect PayPal IDs & Gemini security breakdown</span>
            <button
              onClick={loadLedger}
              className="p-2 rounded-lg bg-slate-900 border border-slate-800 hover:bg-slate-800 text-slate-300"
              title="Refresh now"
            >
              <RefreshCw className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>

        {/* AG Grid Table */}
        <BountyLedgerGrid
          bounties={bounties}
          quickFilterText={quickFilter}
          onSelectBounty={(row) => setSelectedBounty(row)}
        />
      </main>

      {/* Side Drawer & Create Modal */}
      <AuditDrawer
        bounty={selectedBounty}
        onClose={() => setSelectedBounty(null)}
      />
      <CreateBountyModal
        isOpen={isModalOpen}
        onClose={() => setIsModalOpen(false)}
        onSuccess={loadLedger}
      />
    </div>
  );
}