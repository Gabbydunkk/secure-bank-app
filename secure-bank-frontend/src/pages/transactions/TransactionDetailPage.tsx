// src/pages/transactions/TransactionDetailPage.tsx
// Transaction detail — matches the Stitch "Forensic Unit" design.
//
// API calls:
//   GET  /api/v1/transactions/:id          → transaction data (all roles)
//   GET  /api/v1/fraud/alerts/?status=open  → find linked alert for escalation
//   POST /api/v1/transactions/:id/process   → Authorize & Clear (analyst+)
//   POST /api/v1/transactions/:id/block     → Freeze & Flag (analyst+)
//   PATCH /api/v1/fraud/alerts/:id/status   → Escalate to Compliance (analyst+)
//
// The risk gauge SVG is hand-drawn using a circular arc path — no library needed.
// Colour thresholds: 0-39 green, 40-69 amber (ELEVATED CONCERN), 70+ red (CRITICAL)

import { useEffect, useState } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { AppShell } from '../../components/layout/AppShell'
import { useAuth } from '../../contexts/AuthContext'
import { http } from '../../lib/http'
import type { TransactionResponse, FraudAlertListResponse, FraudAlertResponse } from '../../types/api'

// ── Risk gauge SVG ────────────────────────────────────────────────────────
// Renders a semicircle arc gauge (like a speedometer).
// Score 0-100 maps to 0-180 degrees of the arc.

function RiskGauge({ score }: { score: number }) {
  const clamped = Math.min(100, Math.max(0, score))
  // Arc geometry
  const cx = 80, cy = 80, r = 60
  const startAngle = -180   // leftmost point
  const angleRange = 180    // sweep to rightmost
  const endDeg = startAngle + (clamped / 100) * angleRange

  function polar(deg: number, radius: number) {
    const rad = (deg * Math.PI) / 180
    return { x: cx + radius * Math.cos(rad), y: cy + radius * Math.sin(rad) }
  }

  const start = polar(startAngle, r)
  const end   = polar(endDeg, r)
  const large = endDeg - startAngle > 180 ? 1 : 0

  const trackEnd = polar(0, r)  // full track is 180 degrees

  const colour = clamped >= 70 ? '#EF4444' : clamped >= 40 ? '#F59E0B' : '#10B981'
  const label  = clamped >= 70 ? 'CRITICAL'          : clamped >= 40 ? 'ELEVATED CONCERN' : 'LOW RISK'
  const labelC = clamped >= 70 ? 'text-red-600'      : clamped >= 40 ? 'text-amber-500'   : 'text-emerald-600'

  return (
    <div className="flex flex-col items-center">
      <svg width="160" height="100" viewBox="0 0 160 100">
        {/* Track (grey) */}
        <path
          d={`M ${polar(-180, r).x} ${polar(-180, r).y} A ${r} ${r} 0 0 1 ${trackEnd.x} ${trackEnd.y}`}
          fill="none" stroke="#E8E8E4" strokeWidth="12" strokeLinecap="round"
        />
        {/* Filled arc */}
        {clamped > 0 && (
          <path
            d={`M ${start.x} ${start.y} A ${r} ${r} 0 ${large} 1 ${end.x} ${end.y}`}
            fill="none" stroke={colour} strokeWidth="12" strokeLinecap="round"
          />
        )}
        {/* Score text */}
        <text x={cx} y={cy - 4} textAnchor="middle" fontSize="24" fontWeight="bold" fill="#0A0F0A" fontFamily="'Playfair Display', serif">
          {clamped}
        </text>
        <text x={cx} y={cy + 14} textAnchor="middle" fontSize="11" fill="#aaa">
          / 100
        </text>
      </svg>
      <p className={`text-[10px] font-bold tracking-widest uppercase mt-1 ${labelC}`}>
        {label}
      </p>
    </div>
  )
}

// ── Status badge ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: string }) {
  const map: Record<string, string> = {
    completed:  'bg-emerald-50 text-emerald-700 border-emerald-200',
    pending:    'bg-amber-50   text-amber-700   border-amber-200',
    processing: 'bg-blue-50    text-blue-700    border-blue-200',
    failed:     'bg-red-50     text-red-700     border-red-200',
    blocked:    'bg-red-100    text-red-800     border-red-300',
    flagged:    'bg-orange-50  text-orange-700  border-orange-200',
  }
  const label: Record<string, string> = {
    pending:    'Pending Review',
    flagged:    'Flagged for Review',
    completed:  'Completed',
    failed:     'Failed',
    blocked:    'Blocked',
    processing: 'Processing',
  }
  return (
    <span className={`inline-flex items-center gap-1.5 px-3 py-1 rounded-full text-[10px] font-bold tracking-widest uppercase border ${map[status] ?? 'bg-gray-50 text-gray-600 border-gray-200'}`}>
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
      {label[status] ?? status}
    </span>
  )
}

// ── Forensic breakdown row ────────────────────────────────────────────────

function ForensicRow({ label, sub, badge, badgeStyle }: {
  label: string; sub: string; badge: string; badgeStyle: string
}) {
  return (
    <div className="flex items-start justify-between py-3 border-b border-[#F0F0EC] last:border-0">
      <div>
        <p className="text-[#0A0F0A] text-xs font-bold tracking-widest uppercase">{label}</p>
        <p className="text-[#888] text-xs mt-0.5 font-mono">{sub}</p>
      </div>
      <span className={`text-[10px] font-bold tracking-widest uppercase flex items-center gap-1 ${badgeStyle}`}>
        <span className="w-1.5 h-1.5 rounded-full bg-current" />
        {badge}
      </span>
    </div>
  )
}

// ── Timeline event ────────────────────────────────────────────────────────

function TimelineEvent({ time, title, desc, dotColour, last }: {
  time: string; title: string; desc: string; dotColour: string; last?: boolean
}) {
  return (
    <div className="flex gap-4">
      <div className="flex flex-col items-center">
        <div className={`w-3 h-3 rounded-full shrink-0 border-2 border-white ${dotColour} shadow-sm`} />
        {!last && <div className="w-px flex-1 bg-[#E0E0DC] mt-1" />}
      </div>
      <div className="pb-5">
        <p className="text-[#0A0F0A] text-xs font-bold font-mono tracking-wider">{time} — {title}</p>
        <p className="text-[#888] text-xs mt-0.5 leading-relaxed">{desc}</p>
      </div>
    </div>
  )
}

// ── Build timeline from transaction data ──────────────────────────────────

function buildTimeline(txn: TransactionResponse) {
  const events = []

  events.push({
    time: new Date(txn.created_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }),
    title: 'TRANSFER INITIATED',
    desc: `${txn.transaction_type.charAt(0).toUpperCase() + txn.transaction_type.slice(1)} request submitted via SecureBank API`,
    dotColour: 'bg-emerald-500',
  })

  if (txn.fraud_check_status === 'approved') {
    events.push({
      time: new Date(new Date(txn.created_at).getTime() + 2000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }),
      title: 'FRAUD SCAN PASSED',
      desc: `Risk score ${txn.risk_score ?? 0}/100 — approved by fraud detection engine`,
      dotColour: 'bg-emerald-500',
    })
  } else if (txn.fraud_check_status === 'flagged') {
    events.push({
      time: new Date(new Date(txn.created_at).getTime() + 2000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }),
      title: 'FRAUD SCAN WARNING',
      desc: `Heuristic engine flagged anomaly. Risk score ${txn.risk_score ?? 0}/100 exceeded threshold.`,
      dotColour: 'bg-amber-500',
    })
  } else if (txn.fraud_check_status === 'blocked') {
    events.push({
      time: new Date(new Date(txn.created_at).getTime() + 2000).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }),
      title: 'FRAUD SCAN BLOCKED',
      desc: `Transaction blocked. Risk score ${txn.risk_score ?? 0}/100 exceeded block threshold.`,
      dotColour: 'bg-red-500',
    })
  }

  if (txn.processed_at) {
    events.push({
      time: new Date(txn.processed_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }),
      title: 'PROCESSING INITIATED',
      desc: 'Transaction entered processing pipeline',
      dotColour: 'bg-blue-500',
    })
  }

  if (txn.completed_at) {
    events.push({
      time: new Date(txn.completed_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false }),
      title: 'TRANSACTION COMPLETED',
      desc: 'Funds transferred successfully. Ledger updated.',
      dotColour: 'bg-emerald-500',
    })
  }

  if (txn.status === 'pending' || txn.status === 'flagged') {
    events.push({
      time: '—',
      title: 'AWAITING ' + (txn.status === 'flagged' ? 'ANALYST' : 'PROCESSING'),
      desc: txn.status === 'flagged'
        ? 'Manual intervention required for high-risk transaction clearance.'
        : 'Transaction queued for processing.',
      dotColour: 'bg-gray-300',
    })
  }

  return events
}

// ── Main page ─────────────────────────────────────────────────────────────

type ActionState = 'idle' | 'loading' | 'done'

export function TransactionDetailPage() {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { hasRole } = useAuth()

  const [txn, setTxn]     = useState<TransactionResponse | null>(null)
  const [alert, setAlert] = useState<FraudAlertResponse | null>(null)
  const [loading, setLoading]   = useState(true)
  const [error, setError]       = useState<string | null>(null)

  const [processState, setProcessState]   = useState<ActionState>('idle')
  const [blockState, setBlockState]       = useState<ActionState>('idle')
  const [escalateState, setEscalateState] = useState<ActionState>('idle')
  const [actionError, setActionError]     = useState<string | null>(null)

  // Fetch transaction
  useEffect(() => {
    if (!id) return
    setLoading(true)
    http.get<TransactionResponse>(`/transactions/${id}`)
      .then(r => setTxn(r.data))
      .catch(async () => {
        if (!hasRole('analyst')) {
          setError('Transaction not found or you do not have permission to view it.')
          return
        }
        try {
          const fallback = await http.get<TransactionResponse>(`/transactions/review-item/${id}`)
          setTxn(fallback.data)
        } catch {
          setError('Transaction not found or you do not have permission to view it.')
        }
      })
      .finally(() => setLoading(false))
  }, [id, hasRole])

  // Fetch linked fraud alert (if any) for escalation
  useEffect(() => {
    if (!txn || !hasRole('analyst')) return
    http.get<FraudAlertListResponse>('/fraud/alerts/?status=open')
      .then(r => {
        const linked = (r.data.alerts ?? r.data.items ?? []).find(a => a.transaction_id === txn.id)
        if (linked) setAlert(linked)
      })
      .catch(() => {})
  }, [txn, hasRole])

  // ── Actions ─────────────────────────────────────────────────────────────

  async function handleProcess() {
    if (!txn || processState === 'loading') return
    setProcessState('loading'); setActionError(null)
    try {
      // Analyst/Admin one-click flow for flagged transactions:
      // clear flag -> process -> completed.
      if (isAnalyst && txn.status === 'flagged') {
        const clearRes = await http.post<TransactionResponse>(
          `/transactions/${txn.id}/clear`,
          { reason: 'Cleared by analyst via Action Console' },
          { validateStatus: s => s < 500 }
        )
        if (clearRes.status >= 400) {
          const detail = (clearRes.data as unknown as { detail?: string }).detail
          setActionError(detail ?? 'Unable to clear flagged transaction.')
          setProcessState('idle')
          return
        }
      }

      const processUrl = isAnalyst
        ? `/transactions/review-item/${txn.id}/process`
        : `/transactions/${txn.id}/process`
      const r = await http.post<TransactionResponse>(processUrl, {}, { validateStatus: s => s < 500 })
      if (r.status >= 400) {
        const detail = (r.data as unknown as { detail?: string }).detail
        setActionError(detail ?? 'Unable to process transaction.')
        setProcessState('idle')
        return
      }
      setTxn(r.data)
      setProcessState('done')
    } catch {
      setActionError('Unable to process transaction. Please try again.')
      setProcessState('idle')
    }
  }

  async function handleBlock() {
    if (!txn || blockState === 'loading') return
    setBlockState('loading'); setActionError(null)
    try {
      const r = await http.post<TransactionResponse>(
        `/transactions/${txn.id}/block`,
        { reason: 'Manually blocked by analyst via Action Console' },
        { validateStatus: s => s < 500 }
      )
      if (r.status >= 400) {
        const detail = (r.data as unknown as { detail?: string }).detail
        setActionError(detail ?? 'Unable to block transaction.')
        setBlockState('idle')
        return
      }
      setTxn(r.data)
      setBlockState('done')
    } catch {
      setActionError('Unable to block transaction. Please try again.')
      setBlockState('idle')
    }
  }

  async function handleEscalate() {
    if (!alert || escalateState === 'loading') return
    setEscalateState('loading'); setActionError(null)
    try {
      await http.patch(
        `/fraud/alerts/${alert.id}/status`,
        { status: 'investigating', resolution_notes: 'Escalated to compliance by analyst via Action Console' },
        { validateStatus: s => s < 500 }
      )
      setEscalateState('done')
    } catch {
      setActionError('Unable to escalate. Please try again.')
      setEscalateState('idle')
    }
  }

  // ── Forensic breakdown logic ─────────────────────────────────────────────

  function forensicRows(t: TransactionResponse, linkedAlert: FraudAlertResponse | null) {
    const extra = t as TransactionResponse & {
      device_fingerprint?: string
      location_country?: string
      location_city?: string
    }
    const score = t.risk_score ?? 0
    const ruleKeys = Object.keys(linkedAlert?.triggered_rules ?? {})
    const hasUnknownDeviceRule = ruleKeys.includes('unknown_device')
    const hasVelocityRule = ruleKeys.includes('high_velocity_attempts')
    const hasLocationRule = ruleKeys.includes('location_anomaly')
    const hasFp = !!extra.device_fingerprint

    return [
      {
        label: 'Device Fingerprint',
        sub: extra.device_fingerprint ? `ID: ${extra.device_fingerprint.slice(0, 16)}…` : 'Not captured',
        badge: hasUnknownDeviceRule ? 'Anomalous' : hasFp ? 'Captured' : 'Unknown',
        badgeStyle: hasUnknownDeviceRule ? 'text-red-600' : hasFp ? 'text-emerald-600' : 'text-red-600',
      },
      {
        label: 'Geolocation',
        sub: extra.location_country
          ? `${extra.location_city ? extra.location_city + ', ' : ''}${extra.location_country}`
          : 'IP: Not captured',
        badge: hasLocationRule ? 'Anomalous' : extra.location_country ? 'Captured' : 'Unknown',
        badgeStyle: hasLocationRule ? 'text-red-600' : extra.location_country ? 'text-emerald-600' : 'text-amber-500',
      },
      {
        label: 'Velocity Check',
        sub: hasVelocityRule ? 'Multiple attempts/rate burst detected by ruleset' : `Risk score context: ${score}/100`,
        badge: hasVelocityRule ? 'Triggered' : score >= 70 ? 'High' : score >= 40 ? 'Elevated' : 'Normal',
        badgeStyle: hasVelocityRule ? 'text-red-600' : score >= 70 ? 'text-red-600' : score >= 40 ? 'text-amber-500' : 'text-emerald-600',
      },
      {
        label: 'Fraud Check Status',
        sub: t.fraud_check_status,
        badge: t.fraud_check_status === 'approved' ? 'Cleared' : t.fraud_check_status === 'blocked' ? 'Blocked' : 'Review',
        badgeStyle: t.fraud_check_status === 'approved' ? 'text-emerald-600' : t.fraud_check_status === 'blocked' ? 'text-red-600' : 'text-amber-500',
      },
    ]
  }

  const isAnalyst = hasRole('analyst')
  const timeline  = txn ? buildTimeline(txn) : []

  // ── Render ────────────────────────────────────────────────────────────────

  return (
    <AppShell>
      {/* Vault banner */}
      <div className="flex items-center gap-2 bg-[#0D2010] border-b border-emerald-900/40 px-6 py-2.5">
        <svg className="w-3.5 h-3.5 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
        </svg>
        <span className="text-emerald-400 text-[10px] font-bold tracking-widest uppercase">
          Vault Connection Active • End-to-End Encryption Verified
        </span>
      </div>

      {/* Breadcrumb + action buttons — from Stitch topbar */}
      <div className="flex items-center justify-between px-6 py-3 border-b border-[#F0F0EC] bg-white">
        <div className="flex items-center gap-2 text-xs text-[#888]">
          <Link to="/transactions" className="hover:text-[#0A0F0A] transition-colors uppercase tracking-wider font-medium">
            Transactions
          </Link>
          <span>›</span>
          <span className="uppercase tracking-wider font-medium text-[#555]">
            {txn?.transaction_type ?? '…'}
          </span>
          <span>›</span>
          <span className="font-mono text-[#0A0F0A] font-semibold">
            TXN-{id?.slice(0, 8).toUpperCase() ?? '…'}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <button className="flex items-center gap-1.5 px-3 py-1.5 border border-[#E0E0DC] rounded-lg text-[#555] text-xs font-medium hover:bg-[#F8F8F5] transition-all">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
            </svg>
            Export PDF Ledger
          </button>
          <Link to="/audit" className="flex items-center gap-1.5 px-3 py-1.5 border border-[#E0E0DC] rounded-lg text-[#555] text-xs font-medium hover:bg-[#F8F8F5] transition-all">
            <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
            </svg>
            Audit Logs
          </Link>
        </div>
      </div>

      {/* Main content */}
      <div className="p-6 max-w-[1200px] mx-auto" style={{ fontFamily: "'DM Sans', sans-serif" }}>

        {/* ── Loading ──────────────────────────────────────────────── */}
        {loading && (
          <div className="flex items-center justify-center py-20 text-[#aaa] text-sm gap-2">
            <svg className="animate-spin w-5 h-5 text-[#1a4a25]" fill="none" viewBox="0 0 24 24">
              <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
              <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
            </svg>
            Loading transaction…
          </div>
        )}

        {/* ── Error ────────────────────────────────────────────────── */}
        {error && (
          <div className="flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-xl">
            <p className="text-red-700 text-sm">{error}</p>
          </div>
        )}

        {/* ── Action error ─────────────────────────────────────────── */}
        {actionError && (
          <div className="mb-4 flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-xl">
            <p className="text-red-700 text-sm">{actionError}</p>
          </div>
        )}

        {/* ── Detail layout ─────────────────────────────────────────── */}
        {txn && (
          <div className="flex gap-5">

            {/* Left column */}
            <div className="flex-1 min-w-0 space-y-4">

              {/* Hero card — TRANSACTION VALUE + status */}
              <div className="bg-white rounded-xl border border-black/5 p-6">
                <div className="flex items-start justify-between mb-4">
                  <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase">
                    Transaction Value
                  </p>
                  <StatusBadge status={txn.status} />
                </div>
                <div className="flex items-end gap-1 mb-2">
                  <span
                    className="text-[#0A0F0A] text-5xl font-bold tracking-tight"
                    style={{ fontFamily: "'Playfair Display', serif" }}
                  >
                    ${parseFloat(txn.amount).toLocaleString('en-US', { minimumFractionDigits: 2 })}
                  </span>
                  <span className="text-[#888] text-sm mb-1.5 ml-1">{txn.currency}</span>
                </div>
                <p className="text-[#aaa] text-xs font-mono">
                  ID: TXN_{txn.id.toUpperCase()}
                </p>
              </div>

              {/* Origin / Destination — 2 col from Stitch */}
              <div className="bg-white rounded-xl border border-black/5 p-6">
                <div className="grid grid-cols-2 gap-6 mb-6">
                  <div>
                    <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">
                      Origin Sender
                    </p>
                    <p className="text-[#0A0F0A] text-sm font-semibold">SecureBank Account</p>
                    <p className="text-[#aaa] text-xs mt-0.5 font-mono">···· 8829</p>
                  </div>
                  <div>
                    <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">
                      Destination Recipient
                    </p>
                    <p className="text-[#0A0F0A] text-sm font-semibold">
                      {txn.recipient_name ?? '—'}
                    </p>
                    {txn.recipient_account && (
                      <p className="text-[#aaa] text-xs mt-0.5 font-mono">{txn.recipient_account}</p>
                    )}
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-6 pt-5 border-t border-[#F0F0EC]">
                  <div>
                    <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">
                      Transaction Type
                    </p>
                    <p className="text-[#0A0F0A] text-sm font-semibold capitalize">
                      {txn.transaction_type} · {txn.description ?? 'No description'}
                    </p>
                  </div>
                  <div>
                    <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">
                      Execution Timestamp
                    </p>
                    <p className="text-[#0A0F0A] text-sm font-semibold">
                      {new Date(txn.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}
                    </p>
                    <p className="text-[#aaa] text-xs mt-0.5 font-mono">
                      {new Date(txn.created_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit', hour12: false })} UTC
                    </p>
                  </div>
                </div>
              </div>

              {/* EXECUTION TRACEABILITY timeline — from Stitch */}
              <div className="bg-white rounded-xl border border-black/5 p-6">
                <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-5">
                  Execution Traceability
                </p>
                <div className="space-y-0">
                  {timeline.map((e, i) => (
                    <TimelineEvent
                      key={i}
                      time={e.time}
                      title={e.title}
                      desc={e.desc}
                      dotColour={e.dotColour}
                      last={i === timeline.length - 1}
                    />
                  ))}
                </div>
              </div>
            </div>

            {/* Right column */}
            <div className="w-[300px] shrink-0 space-y-4">

              {/* PROPRIETARY RISK INDEX gauge — from Stitch */}
              <div className="bg-white rounded-xl border border-black/5 p-6">
                <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-4">
                  Proprietary Risk Index
                </p>
                <RiskGauge score={txn.risk_score ?? 0} />
              </div>

              {/* FORENSIC AUDIT BREAKDOWN — from Stitch */}
              <div className="bg-white rounded-xl border border-black/5 p-5">
                <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">
                  Forensic Audit Breakdown
                </p>
                <div>
                  {forensicRows(txn, alert).map(row => (
                    <ForensicRow key={row.label} {...row} />
                  ))}
                </div>
              </div>

              {/* ANALYST ACTION CONSOLE — dark panel, analyst/admin only */}
              {isAnalyst && (
                <div className="bg-[#0A0F0A] rounded-xl p-5 space-y-3">
                  <p className="text-white/40 text-[10px] font-bold tracking-widest uppercase">
                    Analyst Action Console
                  </p>

                  {/* Authorize & Clear Transfer */}
                  <button
                    onClick={handleProcess}
                    disabled={processState === 'loading' || processState === 'done' || txn.status === 'completed' || txn.status === 'blocked' || txn.status === 'failed'}
                    className="w-full flex items-center justify-between px-4 py-3 bg-emerald-600 hover:bg-emerald-700 disabled:bg-emerald-900 disabled:text-emerald-700 text-white rounded-lg transition-all"
                  >
                    <span className="text-[10px] font-bold tracking-widest uppercase">
                      {processState === 'done' ? '✓ Authorized' : processState === 'loading' ? 'Processing…' : 'Authorize & Clear Transfer'}
                    </span>
                    {processState !== 'done' && processState !== 'loading' && (
                      <svg className="w-4 h-4 opacity-70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M14 5l7 7m0 0l-7 7m7-7H3" />
                      </svg>
                    )}
                  </button>

                  {/* Escalate to Compliance */}
                  <button
                    onClick={handleEscalate}
                    disabled={escalateState === 'loading' || escalateState === 'done' || !alert}
                    className="w-full flex items-center justify-between px-4 py-3 bg-amber-500 hover:bg-amber-600 disabled:bg-amber-900 disabled:text-amber-700 text-white rounded-lg transition-all"
                  >
                    <span className="text-[10px] font-bold tracking-widest uppercase">
                      {escalateState === 'done' ? '✓ Escalated' : escalateState === 'loading' ? 'Escalating…' : !alert ? 'No Alert to Escalate' : 'Escalate to Compliance'}
                    </span>
                    {escalateState !== 'done' && escalateState !== 'loading' && alert && (
                      <span className="w-5 h-5 rounded bg-amber-400 flex items-center justify-center text-amber-900 text-xs font-black">!</span>
                    )}
                  </button>

                  {/* Freeze Assets & Flag Account */}
                  <button
                    onClick={handleBlock}
                    disabled={blockState === 'loading' || blockState === 'done' || txn.status === 'blocked' || txn.status === 'completed'}
                    className="w-full flex items-center justify-between px-4 py-3 bg-red-600 hover:bg-red-700 disabled:bg-red-950 disabled:text-red-800 text-white rounded-lg transition-all"
                  >
                    <span className="text-[10px] font-bold tracking-widest uppercase">
                      {blockState === 'done' ? '✓ Blocked' : txn.status === 'blocked' ? 'Already Blocked' : blockState === 'loading' ? 'Blocking…' : 'Freeze Assets & Flag Account'}
                    </span>
                    {blockState !== 'done' && blockState !== 'loading' && txn.status !== 'blocked' && (
                      <svg className="w-4 h-4 opacity-70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                      </svg>
                    )}
                  </button>

                  {/* Clearance note — from Stitch */}
                  <p className="text-white/20 text-[9px] tracking-wider uppercase pt-1 leading-relaxed border-t border-white/5">
                    Clearance Level: Senior Auditor Req.<br />
                    All actions logged under SEC-OP compliance.
                  </p>
                </div>
              )}

              {/* Regular user — process button if pending */}
              {!isAnalyst && (txn.status === 'pending') && (
                <div className="bg-white rounded-xl border border-black/5 p-5">
                  <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-3">
                    Transaction Actions
                  </p>
                  <button
                    onClick={handleProcess}
                    disabled={processState === 'loading' || processState === 'done'}
                    className="w-full py-3 bg-[#0A0F0A] hover:bg-[#1c2a1c] disabled:bg-[#ccc] text-white text-sm font-medium rounded-lg transition-all flex items-center justify-center gap-2"
                  >
                    {processState === 'loading' ? (
                      <><svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24"><circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/><path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>Processing…</>
                    ) : processState === 'done' ? '✓ Submitted for Processing' : 'Process Transaction'}
                  </button>
                </div>
              )}

              {/* Back button */}
              <button
                onClick={() => navigate('/transactions')}
                className="w-full py-2.5 border border-[#E0E0DC] rounded-xl text-[#555] text-sm font-medium hover:bg-white transition-all"
              >
                ← Back to Transactions
              </button>
            </div>
          </div>
        )}
      </div>
    </AppShell>
  )
}
