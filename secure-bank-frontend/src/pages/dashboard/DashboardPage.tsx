// src/pages/dashboard/DashboardPage.tsx
// User dashboard — matches Image 1 from Stitch.
// Analyst/admin additions rendered conditionally via hasRole().
//
// Real API calls:
//   GET /api/v1/transactions/?page=1&page_size=5   → Ledger Activity table
//   GET /api/v1/fraud/alerts/?status=open          → fraud alert count (admin/analyst only)
//   GET /api/v1/audit/logs/?page=1&page_size=3     → recent audit entries (admin only)
//   User profile comes from AuthContext (already fetched at login)
//
// Balance/liquidity figures are simulated — the backend has no account
// balance endpoint. In a real deployment, this would come from a core
// banking ledger API. For the Masters demo, we use realistic static values.

import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AppShell } from '../../components/layout/AppShell'
import { useAuth } from '../../contexts/AuthContext'
import { http } from '../../lib/http'
import type { TransactionListResponse, TransactionResponse, FraudAlertListResponse } from '../../types/api'

// ── Helpers ───────────────────────────────────────────────────────────────

function initials(name: string): string {
  return name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
}

// ── Status badge ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const styles: Record<string, string> = {
    completed:  'bg-emerald-50  text-emerald-700  border-emerald-200',
    pending:    'bg-amber-50    text-amber-700    border-amber-200',
    processing: 'bg-blue-50     text-blue-700     border-blue-200',
    failed:     'bg-red-50      text-red-700      border-red-200',
    blocked:    'bg-red-100     text-red-800      border-red-300',
    flagged:    'bg-orange-50   text-orange-700   border-orange-200',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-bold tracking-widest uppercase border ${styles[status] ?? 'bg-gray-50 text-gray-600 border-gray-200'}`}>
      {status}
    </span>
  )
}

// ── Transaction row avatar ────────────────────────────────────────────────

const AVATAR_COLOURS = [
  'bg-slate-700', 'bg-indigo-700', 'bg-emerald-700',
  'bg-amber-700', 'bg-rose-700', 'bg-teal-700',
]

function TxnAvatar({ name, index }: { name: string; index: number }) {
  const colour = AVATAR_COLOURS[index % AVATAR_COLOURS.length]
  return (
    <div className={`w-8 h-8 rounded-full ${colour} flex items-center justify-center shrink-0`}>
      <span className="text-white text-[10px] font-bold">{initials(name)}</span>
    </div>
  )
}

// ── Stat card ─────────────────────────────────────────────────────────────

interface StatCardProps {
  icon: React.ReactNode
  badge: string
  badgeColour: string
  value: string
  label: string
  border?: string
}

function StatCard({ icon, badge, badgeColour, value, label, border }: StatCardProps) {
  return (
    <div className={`bg-white rounded-xl border ${border ?? 'border-black/5'} p-5 flex flex-col gap-3`}>
      <div className="flex items-center justify-between">
        <span className="text-[#aaa]">{icon}</span>
        <span className={`text-[10px] font-bold tracking-widest uppercase ${badgeColour}`}>
          {badge}
        </span>
      </div>
      <div>
        <p className="text-[#0A0F0A] text-2xl font-bold tracking-tight">{value}</p>
        <p className="text-[#888] text-xs mt-0.5 uppercase tracking-wider">{label}</p>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

type TxnFilter = 'ALL' | 'OUTFLOW' | 'INFLOW'

export function DashboardPage() {
  const { user, hasRole } = useAuth()
  const navigate = useNavigate()

  const [transactions, setTransactions] = useState<TransactionResponse[]>([])
  const [txnFilter, setTxnFilter] = useState<TxnFilter>('ALL')
  const [txnLoading, setTxnLoading] = useState(true)

  const [openAlerts, setOpenAlerts] = useState(0)
  const [alertsLoading, setAlertsLoading] = useState(true)

  // Fetch recent transactions
  useEffect(() => {
    http.get<TransactionListResponse>('/transactions/?page=1&page_size=5')
      .then(r => setTransactions(r.data.transactions ?? r.data.items ?? []))
      .catch(() => setTransactions([]))
      .finally(() => setTxnLoading(false))
  }, [])

  // Fetch open fraud alert count (all roles — users can see their own)
  useEffect(() => {
    http.get<FraudAlertListResponse>('/fraud/alerts/?status=open')
      .then(r => setOpenAlerts(r.data.total ?? 0))
      .catch(() => setOpenAlerts(0))
      .finally(() => setAlertsLoading(false))
  }, [])

  // Filter transactions for the ledger activity tabs
  const filteredTxns = transactions.filter(t => {
    if (txnFilter === 'OUTFLOW') return parseFloat(t.amount) < 0 || ['transfer', 'payment', 'withdrawal'].includes(t.transaction_type)
    if (txnFilter === 'INFLOW')  return t.transaction_type === 'deposit'
    return true
  })

  return (
    <AppShell>
      <div className="p-6 max-w-[1400px] mx-auto">

        {/* ── Hero section ──────────────────────────────────────────── */}
        <div className="flex items-start justify-between mb-8">
          <div>
            <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">
              Available Funds
            </p>

            {/* Large balance number — simulated for demo */}
            <div className="flex items-end gap-1">
              <span
                className="text-[#0A0F0A] text-5xl font-bold tracking-tight leading-none"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                $2,482,190
              </span>
              <span className="text-[#0A0F0A] text-3xl font-bold leading-none mb-0.5">.42</span>
            </div>

            {/* Chips row */}
            <div className="flex items-center gap-3 mt-3">
              <div className="flex items-center gap-1.5 bg-emerald-50 border border-emerald-200 rounded-full px-3 py-1">
                <svg className="w-3 h-3 text-emerald-600" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 7h8m0 0v8m0-8l-8 8-4-4-6 6" />
                </svg>
                <span className="text-emerald-700 text-[10px] font-bold tracking-wider uppercase">+2.4% This Month</span>
              </div>
              <div className="flex items-center gap-1.5 bg-[#F2F2EF] border border-[#E0E0DC] rounded-full px-3 py-1">
                <svg className="w-3 h-3 text-[#888]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                </svg>
                <span className="text-[#666] text-[10px] font-bold tracking-wider uppercase">Last Sync: 2m Ago</span>
              </div>
            </div>
          </div>

          {/* Action buttons */}
          <div className="flex items-center gap-2 mt-2">
            <Link
              to="/transactions/new"
              className="flex items-center gap-2 px-5 py-2.5 bg-[#0A0F0A] text-white text-xs font-bold tracking-widest uppercase rounded-lg hover:bg-[#1c2a1c] transition-all"
            >
              Transfer
            </Link>
            <Link
              to="/transactions"
              className="flex items-center gap-2 px-5 py-2.5 bg-white border border-[#E0E0DC] text-[#0A0F0A] text-xs font-bold tracking-widest uppercase rounded-lg hover:bg-[#F8F8F5] transition-all"
            >
              Activity
            </Link>
          </div>
        </div>

        {/* ── Main grid: left content + right panel ─────────────────── */}
        <div className="flex gap-5">

          {/* ── Left: stat cards + ledger activity ──────────────────── */}
          <div className="flex-1 min-w-0 space-y-5">

            {/* Stat cards row */}
            <div className="grid grid-cols-3 gap-4">
              <StatCard
                icon={
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 14v3m4-3v3m4-3v3M3 21h18M3 10h18M3 7l9-4 9 4M4 10h16v11H4V10z" />
                  </svg>
                }
                badge="Available"
                badgeColour="text-emerald-600"
                value="$840,000"
                label="Liquid Balance"
              />
              <StatCard
                icon={
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                  </svg>
                }
                badge="Pending"
                badgeColour="text-amber-600"
                value={txnLoading ? '—' : `$${transactions.filter(t => t.status === 'pending').reduce((s, t) => s + parseFloat(t.amount), 0).toLocaleString('en-US', { minimumFractionDigits: 2 })}`}
                label={`${transactions.filter(t => t.status === 'pending').length} Transactions`}
              />
              <StatCard
                icon={
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                }
                badge={user?.mfa_enabled ? 'Secure' : 'Action Required'}
                badgeColour={user?.mfa_enabled ? 'text-emerald-600' : 'text-red-600'}
                value={user?.mfa_enabled ? '98/100' : '72/100'}
                label="Account Security"
                border={!user?.mfa_enabled ? 'border-red-200' : undefined}
              />
            </div>

            {/* Fraud alert stat — analyst/admin only */}
            {hasRole('analyst') && !alertsLoading && openAlerts > 0 && (
              <div className="bg-red-50 border border-red-200 rounded-xl p-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className="w-8 h-8 rounded-full bg-red-100 flex items-center justify-center">
                    <svg className="w-4 h-4 text-red-600" fill="currentColor" viewBox="0 0 24 24">
                      <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-red-800 text-sm font-semibold">{openAlerts} Active Fraud Alert{openAlerts !== 1 ? 's' : ''} Require Action</p>
                    <p className="text-red-600 text-xs">Open cases awaiting analyst review</p>
                  </div>
                </div>
                <Link to="/analyst/fraud" className="text-[10px] font-bold tracking-widest uppercase text-red-700 hover:text-red-900 transition-colors">
                  Review →
                </Link>
              </div>
            )}

            {/* Ledger Activity */}
            <div className="bg-white rounded-xl border border-black/5 overflow-hidden">
              {/* Header */}
              <div className="flex items-center justify-between px-6 py-4 border-b border-[#F0F0EC]">
                <h2 className="text-[#0A0F0A] text-base font-semibold" style={{ fontFamily: "'Playfair Display', serif" }}>
                  Transaction Activity
                </h2>
                {/* Filter tabs */}
                <div className="flex items-center gap-1">
                  {(['ALL', 'OUTFLOW', 'INFLOW'] as TxnFilter[]).map(f => (
                    <button
                      key={f}
                      onClick={() => setTxnFilter(f)}
                      className={`px-3 py-1 text-[10px] font-bold tracking-widest rounded transition-all ${
                        txnFilter === f
                          ? 'text-[#0A0F0A] bg-[#F2F2EF]'
                          : 'text-[#aaa] hover:text-[#555]'
                      }`}
                    >
                      {f}
                    </button>
                  ))}
                </div>
              </div>

              {/* Table header */}
              <div className="grid grid-cols-[2fr_1fr_1fr_1fr] px-6 py-2 border-b border-[#F8F8F5]">
                {['Recipient / Sender', 'Ref', 'Amount', 'Status'].map(h => (
                  <p key={h} className="text-[#aaa] text-[10px] font-bold tracking-widest uppercase">{h}</p>
                ))}
              </div>

              {/* Rows */}
              {txnLoading ? (
                <div className="flex items-center justify-center py-12 text-[#aaa] text-sm">
                  Loading activity…
                </div>
              ) : filteredTxns.length === 0 ? (
                <div className="flex items-center justify-center py-12 text-[#aaa] text-sm">
                  No transactions yet.{' '}
                  <Link to="/transactions/new" className="text-[#1a4a25] ml-1 font-medium hover:underline">
                    Create one
                  </Link>
                </div>
              ) : (
                filteredTxns.map((txn, i) => (
                  <div
                    key={txn.id}
                    onClick={() => navigate(`/transactions/${txn.id}`)}
                    className={`grid grid-cols-[2fr_1fr_1fr_1fr] px-6 py-3.5 items-center cursor-pointer hover:bg-[#FAFAF8] transition-all border-b border-[#F8F8F5] last:border-0
                      ${txn.status === 'blocked' ? 'bg-red-50/50' : ''}
                      ${txn.status === 'flagged' ? 'bg-amber-50/50' : ''}`}
                  >
                    {/* Entity */}
                    <div className="flex items-center gap-3">
                      <TxnAvatar
                        name={txn.recipient_name ?? txn.transaction_type}
                        index={i}
                      />
                      <div>
                        <p className={`text-sm font-medium ${txn.status === 'blocked' ? 'text-red-700' : 'text-[#0A0F0A]'}`}>
                          {txn.recipient_name ?? txn.transaction_type.charAt(0).toUpperCase() + txn.transaction_type.slice(1)}
                        </p>
                      </div>
                    </div>
                    {/* Ref + date */}
                    <div>
                      <p className={`text-xs font-mono ${txn.status === 'blocked' ? 'text-red-500' : 'text-[#aaa]'}`}>
                        TXN_{txn.id.slice(0, 8).toUpperCase()}
                      </p>
                      <p className="text-[#bbb] text-xs">{new Date(txn.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}</p>
                    </div>
                    {/* Amount */}
                    <p className={`text-sm font-semibold ${
                      txn.transaction_type === 'deposit' ? 'text-emerald-600' :
                      txn.status === 'blocked' ? 'text-red-600' : 'text-[#0A0F0A]'
                    }`}>
                      {txn.transaction_type === 'deposit' ? '+' : '−'}${parseFloat(txn.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                    </p>
                    {/* Status */}
                    <StatusBadge status={txn.status} />
                  </div>
                ))
              )}
            </div>
          </div>

          {/* ── Right panel ─────────────────────────────────────────── */}
          <div className="w-[260px] shrink-0 space-y-4">

            {/* OPERATIONS grid */}
            <div className="bg-[#0A0F0A] rounded-xl p-5">
              <p className="text-white/30 text-[10px] font-bold tracking-widest uppercase mb-4">Operations</p>
              <div className="grid grid-cols-2 gap-2">
                {[
                  {
                    label: 'Transfer', href: '/transactions/new',
                    icon: <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" /></svg>
                  },
                  {
                    label: 'Pay Bills', href: '/transactions/new',
                    icon: <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 7h6m0 10v-3m-3 3h.01M9 17h.01M9 14h.01M12 14h.01M15 11h.01M12 11h.01M9 11h.01M7 21h10a2 2 0 002-2V5a2 2 0 00-2-2H7a2 2 0 00-2 2v14a2 2 0 002 2z" /></svg>
                  },
                  {
                    label: 'Devices', href: '/settings/devices',
                    icon: <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9.75 17L9 20l-1 1h8l-1-1-.75-3M3 13h18M5 17h14a2 2 0 002-2V5a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" /></svg>
                  },
                  {
                    label: 'Security', href: '/settings',
                    icon: <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" /></svg>
                  },
                ].map(op => (
                  <Link
                    key={op.label}
                    to={op.href}
                    className="flex flex-col items-center gap-2 p-3 bg-white/5 hover:bg-white/10 rounded-xl transition-all group"
                  >
                    <span className="text-white/50 group-hover:text-white/80 transition-colors">{op.icon}</span>
                    <span className="text-white/50 text-[10px] font-bold tracking-widest uppercase group-hover:text-white/80 transition-colors">
                      {op.label}
                    </span>
                  </Link>
                ))}
              </div>
            </div>

            {/* ACTIVE SECURITY card */}
            <div className="bg-white rounded-xl border border-black/5 p-5 space-y-4">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-emerald-500" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                </svg>
                <p className="text-[#0A0F0A] text-[10px] font-bold tracking-widest uppercase">Active Security</p>
              </div>

              <div className="flex items-center justify-between py-2 border-b border-[#F0F0EC]">
                <div>
                  <p className="text-[#0A0F0A] text-xs font-medium">MFA Status</p>
                  <p className="text-[#888] text-[10px]">{user?.mfa_enabled ? 'TOTP Enabled' : 'Not configured'}</p>
                </div>
                <span className={`text-[10px] font-bold tracking-widest uppercase ${user?.mfa_enabled ? 'text-emerald-600' : 'text-red-500'}`}>
                  {user?.mfa_enabled ? 'Active' : 'Setup Required'}
                </span>
              </div>

              {!user?.mfa_enabled && (
                <Link
                  to="/mfa/setup"
                  className="w-full inline-flex items-center justify-center py-2.5 rounded-lg bg-[#0A0F0A] text-white text-[10px] font-bold tracking-widest uppercase hover:bg-[#1c2a1c] transition-colors"
                >
                  Set Up MFA
                </Link>
              )}

              <div className="flex items-center justify-between py-2">
                <div>
                  <p className="text-[#0A0F0A] text-xs font-medium">Last Login Device</p>
                  <p className="text-[#888] text-[10px]">Current browser session</p>
                </div>
                <span className="text-[#888] text-[10px] font-bold tracking-wider uppercase">Just Now</span>
              </div>

              {/* Unusual activity alert — shows when fraud alerts exist */}
              {openAlerts > 0 && (
                <div className="flex gap-2 p-3 bg-red-50 border border-red-100 rounded-lg">
                  <svg className="w-4 h-4 text-red-500 shrink-0 mt-0.5" fill="currentColor" viewBox="0 0 24 24">
                    <path fillRule="evenodd" d="M8.257 3.099c.765-1.36 2.722-1.36 3.486 0l5.58 9.92c.75 1.334-.213 2.98-1.742 2.98H4.42c-1.53 0-2.493-1.646-1.743-2.98l5.58-9.92zM11 13a1 1 0 11-2 0 1 1 0 012 0zm-1-8a1 1 0 00-1 1v3a1 1 0 002 0V6a1 1 0 00-1-1z" clipRule="evenodd" />
                  </svg>
                  <div>
                    <p className="text-red-700 text-[10px] font-bold tracking-widest uppercase">Unusual Activity Detected</p>
                    <p className="text-red-600 text-[10px] mt-0.5 leading-relaxed">
                      {openAlerts} alert{openAlerts !== 1 ? 's' : ''} flagged on your account. Review in Security.
                    </p>
                  </div>
                </div>
              )}
            </div>

            {/* Exchange rate widget — static, matches Stitch */}
            <div className="bg-white rounded-xl border border-black/5 p-5">
              {/* Mini chart placeholder */}
              <div className="h-20 bg-[#0A0F0A] rounded-lg mb-3 flex items-center justify-center overflow-hidden">
                <svg className="w-full h-full opacity-30" viewBox="0 0 200 80" preserveAspectRatio="none">
                  <polyline points="0,60 30,50 60,55 90,35 120,40 150,20 180,25 200,15" fill="none" stroke="#34d399" strokeWidth="2" />
                </svg>
              </div>
              <p className="text-[#888] text-[10px] tracking-wider uppercase mb-1">GBP / USD</p>
              <div className="flex items-baseline gap-2">
                <span className="text-[#0A0F0A] text-xl font-bold tracking-tight">1.2184</span>
                <span className="text-emerald-600 text-xs font-semibold">+0.12%</span>
              </div>
              <button className="mt-2 text-[10px] font-bold tracking-widest uppercase text-[#888] hover:text-[#333] transition-colors">
                View Markets →
              </button>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
