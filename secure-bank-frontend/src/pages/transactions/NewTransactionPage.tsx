// src/pages/transactions/NewTransactionPage.tsx
// New Transaction form — matches Stitch design precisely.
//
// API flow:
//   POST /api/v1/transactions/           → creates transaction
//   Response 201 status=pending          → success, go to /transactions/:id
//   Response 201 status=flagged          → flagged by fraud engine, show warning
//   Response 403 TransactionBlockedError → blocked, show block state
//   Response 422                         → validation error, show inline
//
// The Fraud Risk Indicator in the summary panel is calculated locally
// from the amount entered — it updates live as the user types, giving
// immediate feedback before submission. The real fraud score comes back
// in the API response and is shown post-submission.

import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { AppShell } from '../../components/layout/AppShell'
import { http } from '../../lib/http'
import type { TransactionCreate, TransactionResponse } from '../../types/api'

type TxnType = 'transfer' | 'payment' | 'withdrawal' | 'deposit'

interface FormState {
  type: TxnType
  amount: string
  currency: string
  recipientAccount: string
  recipientName: string
  description: string
}

// ── Live fraud risk estimate (client-side, before submission) ─────────────
// Based purely on amount — gives the user live feedback.
// The backend's real fraud engine considers many more signals.
function estimateRisk(amount: string): { level: 'LOW' | 'MEDIUM' | 'HIGH'; colour: string; dot: string } {
  const n = parseFloat(amount) || 0
  if (n >= 10000) return { level: 'HIGH',   colour: 'text-red-600',    dot: 'bg-red-500' }
  if (n >= 1000)  return { level: 'MEDIUM', colour: 'text-amber-600',  dot: 'bg-amber-500' }
  return             { level: 'LOW',    colour: 'text-emerald-600', dot: 'bg-emerald-500' }
}

// ── Result state after submission ─────────────────────────────────────────
type SubmitResult =
  | { state: 'idle' }
  | { state: 'submitting' }
  | { state: 'success'; txn: TransactionResponse }
  | { state: 'flagged'; txn: TransactionResponse }
  | { state: 'blocked'; message: string }
  | { state: 'error'; message: string }

// ── Page ──────────────────────────────────────────────────────────────────

export function NewTransactionPage() {
  const navigate = useNavigate()
  const [form, setForm] = useState<FormState>({
    type: 'transfer',
    amount: '',
    currency: 'USD',
    recipientAccount: '',
    recipientName: '',
    description: '',
  })
  const [result, setResult] = useState<SubmitResult>({ state: 'idle' })
  const [sessionTime] = useState(() => {
    const now = new Date()
    return `${now.getHours()}:${String(now.getMinutes()).padStart(2, '0')}`
  })

  const risk = estimateRisk(form.amount)
  const amountNum = parseFloat(form.amount) || 0
  const needsRecipient = form.type === 'transfer' || form.type === 'payment'

  // Auto-navigate to transaction detail on success after a short delay
  useEffect(() => {
    if (result.state === 'success') {
      const timer = setTimeout(() => {
        navigate(`/transactions/${(result as { state: 'success'; txn: TransactionResponse }).txn.id}`)
      }, 1500)
      return () => clearTimeout(timer)
    }
  }, [result, navigate])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (result.state === 'submitting') return
    setResult({ state: 'submitting' })

    const payload: TransactionCreate = {
      transaction_type: form.type,
      amount: form.amount,
      currency: form.currency,
      ...(form.recipientAccount ? { recipient_account: form.recipientAccount } : {}),
      ...(form.recipientName    ? { recipient_name: form.recipientName }    : {}),
      ...(form.description      ? { description: form.description }          : {}),
    }

    try {
      const response = await http.post<TransactionResponse>(
        '/transactions/',
        payload,
        { validateStatus: s => s < 500 }
      )

      if (response.status === 403) {
        const detail =
          (response.data as unknown as { detail?: string })?.detail?.toLowerCase() ?? ''
        if (detail.includes('insufficient permissions') || detail.includes('transfer_authorized')) {
          setResult({
            state: 'error',
            message: 'Your current account role is not permitted to create transactions.',
          })
          return
        }
        setResult({
          state: 'blocked',
          message: 'This transaction was blocked by our security systems. It has been flagged for compliance review.',
        })
        return
      }

      if (response.status === 422) {
        const detail = (response.data as unknown as { detail: unknown }).detail
        const msg = Array.isArray(detail)
          ? (detail as { msg: string }[])[0]?.msg ?? 'Validation error'
          : String(detail ?? 'Validation error')
        setResult({ state: 'error', message: msg })
        return
      }

      const txn = response.data as TransactionResponse

      if (txn.status === 'flagged') {
        setResult({ state: 'flagged', txn })
        return
      }

      setResult({ state: 'success', txn })
    } catch {
      setResult({ state: 'error', message: 'Unable to submit transaction. Please try again.' })
    }
  }

  return (
    <AppShell>
      {/* Vault banner — from Stitch */}
      <div className="flex items-center gap-2 bg-[#0D2010] border-b border-emerald-900/40 px-6 py-2.5">
        <svg className="w-3.5 h-3.5 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
        </svg>
        <span className="text-emerald-400 text-[10px] font-bold tracking-widest uppercase">
          GabbyBank Connection Active • AES-256 Encrypted
        </span>
      </div>

      <div className="p-6 max-w-[1100px] mx-auto" style={{ fontFamily: "'DM Sans', sans-serif" }}>

        {/* Heading */}
        <div className="mb-8">
          <h1 className="text-[#0A0F0A] text-3xl font-bold" style={{ fontFamily: "'Playfair Display', serif" }}>
            New Transaction
          </h1>
          <p className="text-[#777] text-sm mt-1">
           Standard Banking Transactions. Real-time fraud screening and liquidity verification.
          </p>
        </div>

        {/* ── Success state ─────────────────────────────────────────── */}
        {result.state === 'success' && (
          <div className="mb-6 flex gap-3 p-4 bg-emerald-50 border border-emerald-200 rounded-xl">
            <div className="w-8 h-8 rounded-full bg-emerald-500 flex items-center justify-center shrink-0">
              <svg className="w-4 h-4 text-white" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
              </svg>
            </div>
            <div>
              <p className="text-emerald-800 text-sm font-semibold">Transaction submitted successfully</p>
              <p className="text-emerald-700 text-xs mt-0.5">
                Risk score: {result.txn.risk_score ?? 0}/100 · Redirecting to transaction detail…
              </p>
            </div>
          </div>
        )}

        {/* ── Flagged state ─────────────────────────────────────────── */}
        {result.state === 'flagged' && (
          <div className="mb-6 flex gap-3 p-4 bg-amber-50 border border-amber-200 rounded-xl">
            <span className="text-amber-500 text-lg shrink-0">⚠</span>
            <div>
              <p className="text-amber-800 text-sm font-semibold">Transaction flagged for review</p>
              <p className="text-amber-700 text-xs mt-0.5">
                Risk score {result.txn.risk_score}/100 — our fraud engine has flagged this transaction for manual review before processing. You will be notified when it is cleared.
              </p>
              <button
                onClick={() => navigate(`/transactions/${result.txn.id}`)}
                className="mt-2 text-xs font-bold text-amber-700 hover:text-amber-900 underline underline-offset-2"
              >
                View transaction detail →
              </button>
            </div>
          </div>
        )}

        {/* ── Blocked state ─────────────────────────────────────────── */}
        {result.state === 'blocked' && (
          <div className="mb-6 flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-xl">
            <div className="w-6 h-6 rounded-full bg-red-500 flex items-center justify-center shrink-0 mt-0.5">
              <span className="text-white text-xs font-bold">!</span>
            </div>
            <div>
              <p className="text-red-800 text-sm font-semibold">Transaction Blocked by Security Systems</p>
              <p className="text-red-700 text-xs mt-0.5">{result.message}</p>
              <button onClick={() => setResult({ state: 'idle' })} className="mt-2 text-xs font-bold text-red-700 hover:text-red-900 underline underline-offset-2">
                Create a different transaction →
              </button>
            </div>
          </div>
        )}

        {/* ── Error state ───────────────────────────────────────────── */}
        {result.state === 'error' && (
          <div className="mb-6 flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-xl">
            <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center shrink-0">
              <span className="text-white text-xs font-bold">!</span>
            </div>
            <p className="text-red-700 text-sm">{result.message}</p>
          </div>
        )}

        {/* ── Form + Summary ────────────────────────────────────────── */}
        <form onSubmit={handleSubmit}>
          <div className="flex gap-6 items-start">

            {/* Left: form fields */}
            <div className="flex-1 space-y-6">

              {/* TRANSACTION TYPE — button group from Stitch */}
              <div>
                <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase mb-3">
                  Transaction Type
                </label>
                <div className="flex gap-2">
                  {(['transfer', 'payment', 'withdrawal', 'deposit'] as TxnType[]).map(t => (
                    <button
                      key={t}
                      type="button"
                      onClick={() => setForm(f => ({ ...f, type: t }))}
                      className={`px-4 py-2.5 rounded-lg text-sm font-medium transition-all capitalize
                        ${form.type === t
                          ? 'bg-[#0A0F0A] text-white'
                          : 'bg-white border border-[#E0E0DC] text-[#555] hover:border-[#0A0F0A] hover:text-[#0A0F0A]'
                        }`}
                    >
                      {t.charAt(0).toUpperCase() + t.slice(1)}
                    </button>
                  ))}
                </div>
              </div>

              {/* AMOUNT — with USD prefix inside input, from Stitch */}
              <div>
                <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase mb-2">
                  Amount
                </label>
                <div className="flex items-center bg-white border border-[#E0E0DC] rounded-lg overflow-hidden focus-within:ring-2 focus-within:ring-[#1a4a25]/30 focus-within:border-[#1a4a25] transition-all">
                  <span className="px-4 py-3 text-[#888] text-sm font-semibold border-r border-[#E0E0DC] bg-[#F8F8F5]">
                    USD
                  </span>
                  <input
                    type="number"
                    min="0.01"
                    step="0.01"
                    value={form.amount}
                    onChange={e => setForm(f => ({ ...f, amount: e.target.value }))}
                    placeholder="0.00"
                    required
                    className="flex-1 px-4 py-3 text-[#0A0F0A] text-lg font-semibold placeholder-[#ccc] focus:outline-none bg-transparent"
                  />
                </div>
              </div>

              {/* RECIPIENT ACCOUNT + RECIPIENT NAME — side by side, from Stitch */}
              {needsRecipient && (
                <div className="grid grid-cols-2 gap-4">
                  <div>
                    <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase mb-2">
                      Recipient Account
                    </label>
                    <input
                      type="text"
                      value={form.recipientAccount}
                      onChange={e => setForm(f => ({ ...f, recipientAccount: e.target.value }))}
                      placeholder="#### #### #### ####"
                      required={needsRecipient}
                      className="w-full px-4 py-3 bg-white border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm placeholder-[#ccc] font-mono focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/30 focus:border-[#1a4a25] transition-all"
                    />
                  </div>
                  <div>
                    <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase mb-2">
                      Recipient Name
                    </label>
                    <input
                      type="text"
                      value={form.recipientName}
                      onChange={e => setForm(f => ({ ...f, recipientName: e.target.value }))}
                      placeholder="Full Legal Name or Entity"
                      required={needsRecipient}
                      className="w-full px-4 py-3 bg-white border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm placeholder-[#ccc] focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/30 focus:border-[#1a4a25] transition-all"
                    />
                  </div>
                </div>
              )}

              {/* DESCRIPTION */}
              <div>
                <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase mb-2">
                  Description
                </label>
                <textarea
                  value={form.description}
                  onChange={e => setForm(f => ({ ...f, description: e.target.value }))}
                  placeholder="Reference note for the transaction..."
                  rows={3}
                  className="w-full px-4 py-3 bg-white border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm placeholder-[#ccc] focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/30 focus:border-[#1a4a25] transition-all resize-none"
                />
              </div>
            </div>

            {/* Right: TRANSACTION SUMMARY panel — from Stitch */}
            <div className="w-[300px] shrink-0 space-y-4">
              <div className="bg-[#F8F8F6] border border-[#E8E8E4] rounded-xl p-6 space-y-5">
                <p className="text-[#0A0F0A] text-[10px] font-bold tracking-widest uppercase">
                  Transaction Summary
                </p>

                {/* Total amount */}
                <div className="flex items-start justify-between">
                  <span className="text-[#888] text-sm">Total Amount (USD)</span>
                  <span className="text-[#0A0F0A] text-2xl font-bold tracking-tight">
                    {amountNum.toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </span>
                </div>

                {/* Fraud Risk Indicator — live, from Stitch */}
                <div className="flex items-center justify-between py-3 border-t border-[#E8E8E4]">
                  <span className="text-[#888] text-sm">Fraud Risk Indicator</span>
                  <div className="flex items-center gap-1.5">
                    <div className={`w-2 h-2 rounded-full ${risk.dot}`} />
                    <span className={`text-sm font-bold ${risk.colour}`}>{risk.level} RISK</span>
                  </div>
                </div>

                {/* Processing speed */}
                <div className="flex items-center justify-between py-3 border-t border-[#E8E8E4]">
                  <span className="text-[#888] text-sm">Processing Speed</span>
                  <span className="text-[#0A0F0A] text-sm font-semibold">Priority (T+0)</span>
                </div>

                {/* Entity Verification card — from Stitch */}
                <div className="flex gap-3 p-3 bg-white border border-[#E8E8E4] rounded-xl">
                  <div className="w-8 h-8 rounded-lg bg-emerald-50 border border-emerald-100 flex items-center justify-center shrink-0">
                    <svg className="w-4 h-4 text-emerald-600" fill="currentColor" viewBox="0 0 24 24">
                      <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                    </svg>
                  </div>
                  <div>
                    <p className="text-[#0A0F0A] text-xs font-semibold">Account Verification</p>
                    <p className="text-[#888] text-xs mt-0.5 leading-relaxed">
                      {form.recipientName
                        ? `${form.recipientName} — pending verification`
                        : 'Recipient will be verified before processing'}
                    </p>
                  </div>
                </div>

                {/* Confirm button — from Stitch */}
                <button
                  type="submit"
                  disabled={result.state === 'submitting' || result.state === 'success'}
                  className="w-full py-3.5 bg-[#0A0F0A] hover:bg-[#1c2a1c] disabled:bg-[#ccc]
                             text-white text-sm font-semibold rounded-xl
                             transition-all flex items-center justify-center gap-2"
                >
                  {result.state === 'submitting' ? (
                    <>
                      <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Processing…
                    </>
                  ) : result.state === 'success' ? (
                    '✓ Transaction Submitted'
                  ) : (
                    'Confirm Transaction'
                  )}
                </button>

                {/* Authorised signature note — from Stitch */}
                <p className="text-[#aaa] text-xs text-center">
                  ⓘ Authorized signature required on next step
                </p>
              </div>

              {/* INSTITUTIONAL CONTEXT card — from Stitch */}
              <div className="bg-[#F8F8F6] border border-[#E8E8E4] rounded-xl p-5">
                <p className="text-[#0A0F0A] text-[10px] font-bold tracking-widest uppercase mb-4">
                  Standard Banking Context
                </p>
                <div className="flex items-start justify-between">
                  <div>
                    <p className="text-[#888] text-xs">Available Liquidity</p>
                    <p className="text-[#0A0F0A] text-base font-bold tracking-tight mt-0.5">$12,450,280.00</p>
                  </div>
                  <div className="text-right">
                    <p className="text-[#888] text-xs">Daily Limit</p>
                    <p className="text-[#0A0F0A] text-base font-bold tracking-tight mt-0.5">$50,000.00</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </form>

        {/* Footer security bar — from Stitch */}
        <div className="flex items-start justify-between mt-8 pt-5 border-t border-[#E8E8E4]">
          <div className="flex gap-2">
            <svg className="w-4 h-4 text-[#888] shrink-0 mt-0.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
            </svg>
            <p className="text-[#888] text-xs max-w-lg leading-relaxed">
              All transactions are screened by our fraud detection engine before processing. Unauthorized activity will be flagged and reported immediately to the Compliance department.
            </p>
          </div>
          <div className="flex items-center gap-2 shrink-0 ml-4">
            <div className="px-3 py-1.5 bg-[#F2F2EF] border border-[#E0E0DC] rounded-lg">
              <p className="text-[#555] text-[10px] font-bold tracking-wider uppercase">Secure Session: {sessionTime}</p>
            </div>
          </div>
        </div>
      </div>
    </AppShell>
  )
}
