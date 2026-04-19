// src/pages/transactions/TransactionsPage.tsx
// Transaction list page — matches the established design language.
// Real API: GET /api/v1/transactions/?page=N&page_size=20

import { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { AppShell } from '../../components/layout/AppShell'
import { http } from '../../lib/http'
import type { TransactionListResponse, TransactionResponse, TransactionStatus, TransactionType } from '../../types/api'

// ── Helpers ───────────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: TransactionStatus }) {
  const map: Record<TransactionStatus, string> = {
    completed:  'bg-emerald-50 text-emerald-700 border-emerald-200',
    pending:    'bg-amber-50   text-amber-700   border-amber-200',
    processing: 'bg-blue-50    text-blue-700    border-blue-200',
    failed:     'bg-red-50     text-red-700     border-red-200',
    blocked:    'bg-red-100    text-red-800     border-red-300',
    flagged:    'bg-orange-50  text-orange-700  border-orange-200',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-bold tracking-widest uppercase border ${map[status] ?? 'bg-gray-50 text-gray-600 border-gray-200'}`}>
      {status}
    </span>
  )
}

function TypeBadge({ type }: { type: TransactionType }) {
  const map: Record<TransactionType, string> = {
    transfer:   'bg-purple-50 text-purple-700 border-purple-200',
    payment:    'bg-blue-50   text-blue-700   border-blue-200',
    withdrawal: 'bg-amber-50  text-amber-700  border-amber-200',
    deposit:    'bg-emerald-50 text-emerald-700 border-emerald-200',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[10px] font-bold tracking-widest uppercase border ${map[type]}`}>
      {type}
    </span>
  )
}

const AVATAR_COLOURS = ['bg-slate-700','bg-indigo-700','bg-emerald-700','bg-amber-700','bg-rose-700','bg-teal-700']

function Avatar({ name, index }: { name: string; index: number }) {
  const ini = name.split(' ').map(w => w[0]).join('').toUpperCase().slice(0, 2)
  return (
    <div className={`w-8 h-8 rounded-full ${AVATAR_COLOURS[index % AVATAR_COLOURS.length]} flex items-center justify-center shrink-0`}>
      <span className="text-white text-[10px] font-bold">{ini}</span>
    </div>
  )
}

// ── Page ──────────────────────────────────────────────────────────────────

const STATUS_OPTIONS: Array<{ label: string; value: string }> = [
  { label: 'All Status', value: '' },
  { label: 'Pending', value: 'pending' },
  { label: 'Completed', value: 'completed' },
  { label: 'Processing', value: 'processing' },
  { label: 'Failed', value: 'failed' },
  { label: 'Blocked', value: 'blocked' },
  { label: 'Flagged', value: 'flagged' },
]

const TYPE_OPTIONS: Array<{ label: string; value: string }> = [
  { label: 'All Types', value: '' },
  { label: 'Transfer', value: 'transfer' },
  { label: 'Payment', value: 'payment' },
  { label: 'Withdrawal', value: 'withdrawal' },
  { label: 'Deposit', value: 'deposit' },
]

export function TransactionsPage() {
  const navigate = useNavigate()
  const [transactions, setTransactions] = useState<TransactionResponse[]>([])
  const [total, setTotal] = useState(0)
  const [page, setPage] = useState(1)
  const [loading, setLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('')
  const [typeFilter, setTypeFilter] = useState('')

  const PAGE_SIZE = 20

  useEffect(() => {
    setLoading(true)
    http.get<TransactionListResponse>(`/transactions/?page=${page}&page_size=${PAGE_SIZE}`)
      .then(r => {
        const all = r.data.transactions ?? r.data.items ?? []
        setTransactions(all)
        setTotal(r.data.total)
      })
      .catch(() => setTransactions([]))
      .finally(() => setLoading(false))
  }, [page])

  // Client-side filtering (backend doesn't have filter params for transactions)
  const filtered = transactions.filter(t => {
    const matchSearch = !search ||
      (t.recipient_name ?? '').toLowerCase().includes(search.toLowerCase()) ||
      (t.recipient_account ?? '').toLowerCase().includes(search.toLowerCase()) ||
      t.id.toLowerCase().includes(search.toLowerCase())
    const matchStatus = !statusFilter || t.status === statusFilter
    const matchType   = !typeFilter   || t.transaction_type === typeFilter
    return matchSearch && matchStatus && matchType
  })

  const totalPages = Math.ceil(total / PAGE_SIZE)

  return (
    <AppShell>
      {/* Vault banner */}
      <div className="flex items-center gap-2 bg-[#0D2010] border-b border-emerald-900/40 px-6 py-2.5">
        <svg className="w-3.5 h-3.5 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
        </svg>
        <span className="text-emerald-400 text-[10px] font-bold tracking-widest uppercase">
          GabbyBank Connection Active • AES-256 Encrypted
        </span>
      </div>

      <div className="p-6 max-w-[1200px] mx-auto" style={{ fontFamily: "'DM Sans', sans-serif" }}>

        {/* Header */}
        <div className="flex items-start justify-between mb-6">
          <div>
            <h1 className="text-[#0A0F0A] text-2xl font-bold" style={{ fontFamily: "'Playfair Display', serif" }}>
              Transaction History
            </h1>
            <p className="text-[#888] text-sm mt-1">
              {total} total transactions · real-time fraud screening applied 
            </p>
          </div>
          <Link
            to="/transactions/new"
            className="flex items-center gap-2 px-4 py-2.5 bg-[#0A0F0A] text-white text-xs font-bold tracking-widest uppercase rounded-lg hover:bg-[#1c2a1c] transition-all"
          >
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
            </svg>
            New Transaction
          </Link>
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-3 mb-5">
          {/* Search */}
          <div className="relative flex-1 max-w-xs">
            <svg className="w-4 h-4 absolute left-3 top-1/2 -translate-y-1/2 text-[#aaa]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
            </svg>
            <input
              type="text"
              placeholder="Search transactions..."
              value={search}
              onChange={e => setSearch(e.target.value)}
              className="w-full pl-9 pr-4 py-2 bg-white border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm placeholder-[#aaa] focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/30 focus:border-[#1a4a25] transition-all"
            />
          </div>

          {/* Type filter */}
          <select
            value={typeFilter}
            onChange={e => setTypeFilter(e.target.value)}
            className="px-3 py-2 bg-white border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/30 transition-all"
          >
            {TYPE_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>

          {/* Status filter */}
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-3 py-2 bg-white border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/30 transition-all"
          >
            {STATUS_OPTIONS.map(o => <option key={o.value} value={o.value}>{o.label}</option>)}
          </select>
        </div>

        {/* Table */}
        <div className="bg-white rounded-xl border border-black/5 overflow-hidden">

          {/* Table header */}
          <div className="grid grid-cols-[2fr_1fr_1fr_1fr_1fr] px-6 py-3 border-b border-[#F0F0EC] bg-[#FAFAF8]">
            {['Recipient / Sender', 'Type', 'Ref · Date', 'Amount', 'Status'].map(h => (
              <p key={h} className="text-[#aaa] text-[10px] font-bold tracking-widest uppercase">{h}</p>
            ))}
          </div>

          {/* Rows */}
          {loading ? (
            <div className="flex items-center justify-center py-16 text-[#aaa] text-sm">
              <svg className="animate-spin w-5 h-5 mr-2 text-[#1a4a25]" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              Loading transactions…
            </div>
          ) : filtered.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16 gap-3">
              <svg className="w-10 h-10 text-[#ddd]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              <p className="text-[#aaa] text-sm">No transactions found</p>
              <Link to="/transactions/new" className="text-[#1a4a25] text-sm font-medium hover:underline">
                Create your first transaction →
              </Link>
            </div>
          ) : (
            filtered.map((txn, i) => (
              <div
                key={txn.id}
                onClick={() => navigate(`/transactions/${txn.id}`)}
                className={`grid grid-cols-[2fr_1fr_1fr_1fr_1fr] px-6 py-4 items-center
                  cursor-pointer border-b border-[#F8F8F5] last:border-0 transition-all
                  hover:bg-[#FAFAF8]
                  ${txn.status === 'blocked' ? 'bg-red-50/60 hover:bg-red-50' : ''}
                  ${txn.status === 'flagged' ? 'bg-amber-50/40 hover:bg-amber-50/60' : ''}`}
              >
                {/* Recipient */}
                <div className="flex items-center gap-3">
                  <Avatar name={txn.recipient_name ?? txn.transaction_type} index={i} />
                  <div>
                    <p className={`text-sm font-medium ${txn.status === 'blocked' ? 'text-red-700' : 'text-[#0A0F0A]'}`}>
                      {txn.recipient_name ?? txn.transaction_type.charAt(0).toUpperCase() + txn.transaction_type.slice(1)}
                    </p>
                    {txn.recipient_account && (
                      <p className="text-[#aaa] text-xs font-mono">{txn.recipient_account}</p>
                    )}
                  </div>
                </div>

                {/* Type badge */}
                <TypeBadge type={txn.transaction_type} />

                {/* Ref + date */}
                <div>
                  <p className={`text-xs font-mono ${txn.status === 'blocked' ? 'text-red-400' : 'text-[#aaa]'}`}>
                    TXN_{txn.id.slice(0, 8).toUpperCase()}
                  </p>
                  <p className="text-[#bbb] text-xs mt-0.5">
                    {new Date(txn.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                  </p>
                </div>

                {/* Amount */}
                <p className={`text-sm font-semibold tabular-nums ${
                  txn.transaction_type === 'deposit' ? 'text-emerald-600' :
                  txn.status === 'blocked' ? 'text-red-600' : 'text-[#0A0F0A]'
                }`}>
                  {txn.transaction_type === 'deposit' ? '+' : '−'}$
                  {parseFloat(txn.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                </p>

                {/* Status badge */}
                <StatusBadge status={txn.status} />
              </div>
            ))
          )}
        </div>

        {/* Pagination */}
        {totalPages > 1 && (
          <div className="flex items-center justify-between mt-4">
            <p className="text-[#888] text-xs">
              Page {page} of {totalPages} · {total} transactions
            </p>
            <div className="flex items-center gap-2">
              <button
                onClick={() => setPage(p => Math.max(1, p - 1))}
                disabled={page === 1}
                className="px-3 py-1.5 text-xs font-medium border border-[#E0E0DC] rounded-lg disabled:opacity-40 hover:bg-[#F8F8F5] transition-all"
              >
                ← Previous
              </button>
              <button
                onClick={() => setPage(p => Math.min(totalPages, p + 1))}
                disabled={page === totalPages}
                className="px-3 py-1.5 text-xs font-medium border border-[#E0E0DC] rounded-lg disabled:opacity-40 hover:bg-[#F8F8F5] transition-all"
              >
                Next →
              </button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}