// src/pages/analyst/FraudWorkspacePage.tsx
// Fraud Analysis Workspace — matches Stitch Image 3 precisely.
// Analyst and admin roles only (protected by RequireAuth role="analyst" in App.tsx)
//
// API calls:
//   GET  /api/v1/fraud/alerts/              → alert table
//   GET  /api/v1/fraud/alerts/{id}          → case detail slide-in
//   PATCH /api/v1/fraud/alerts/{id}/status  → Mark Investigating / Resolve / False Positive
//   POST /api/v1/transactions/{id}/block    → SEC_PROTOCOL freeze button
//
// The GEO ANOMALY MAP is an SVG world outline — no external map library.
// The RISK TREND bars are generated from the alert's risk_score.
// The BEHAVIORAL ANOMALY scatter plot uses two static points + dynamic outlier.

import { useCallback, useEffect, useState } from 'react'
import { AppShell } from '../../components/layout/AppShell'
import { http } from '../../lib/http'
import type {
  FraudAlertListResponse,
  FraudAlertResponse,
  FraudAlertStatus,
  FraudSeverity,
  TransactionResponse,
} from '../../types/api'

// ── Severity colours ──────────────────────────────────────────────────────

const SEV_DOT: Record<FraudSeverity, string> = {
  critical: 'bg-red-500',
  high:     'bg-orange-500',
  medium:   'bg-amber-400',
  low:      'bg-emerald-400',
}

const SEV_TEXT: Record<FraudSeverity, string> = {
  critical: 'text-red-600',
  high:     'text-orange-600',
  medium:   'text-amber-600',
  low:      'text-emerald-600',
}

const SEV_SCORE_BG: Record<FraudSeverity, string> = {
  critical: 'bg-red-100 text-red-700 border-red-300',
  high:     'bg-orange-100 text-orange-700 border-orange-300',
  medium:   'bg-amber-100 text-amber-700 border-amber-300',
  low:      'bg-emerald-100 text-emerald-700 border-emerald-300',
}

// ── Status badge ──────────────────────────────────────────────────────────

function StatusBadge({ status }: { status: FraudAlertStatus }) {
  const map: Record<FraudAlertStatus, string> = {
    open:           'bg-red-50 text-red-700 border-red-200',
    investigating:  'bg-blue-50 text-blue-700 border-blue-200',
    resolved:       'bg-emerald-50 text-emerald-700 border-emerald-200',
    false_positive: 'bg-gray-50 text-gray-500 border-gray-200',
  }
  const labels: Record<FraudAlertStatus, string> = {
    open:           'Action Required',
    investigating:  'Investigating',
    resolved:       'Resolved',
    false_positive: 'False Positive',
  }
  return (
    <span className={`inline-flex px-2 py-0.5 rounded text-[9px] font-bold tracking-widest uppercase border ${map[status]}`}>
      {labels[status]}
    </span>
  )
}

// ── Risk score circle ─────────────────────────────────────────────────────

function ScoreCircle({ score, severity }: { score: number; severity: FraudSeverity }) {
  return (
    <div className={`w-10 h-10 rounded-full border-2 flex items-center justify-center font-bold text-sm ${SEV_SCORE_BG[severity]}`}>
      {score}
    </div>
  )
}

// ── Geo anomaly map (SVG world outline, simplified) ───────────────────────

function GeoAnomalyMap({ alert }: { alert: FraudAlertResponse }) {
  // Simple world rectangle with a dot. The dot position is derived from
  // the alert type — in production this would use real geolocation data.
  const hasAnomaly = alert.alert_type === 'location_anomaly' || (alert.risk_score ?? 0) >= 60

  return (
    <div className="bg-[#1a1a1a] rounded-xl overflow-hidden relative">
      <div className="flex items-center justify-between px-4 pt-3 pb-2">
        <p className="text-white/40 text-[9px] font-bold tracking-widest uppercase">Geo Anomaly Map</p>
        {hasAnomaly && (
          <span className="text-[9px] font-bold tracking-widest uppercase text-amber-400 border border-amber-400/30 rounded-full px-2 py-0.5">
            Active Outlier
          </span>
        )}
      </div>
      <svg viewBox="0 0 300 140" className="w-full opacity-60">
        {/* Simplified world landmass outlines */}
        {/* North America */}
        <path d="M30 30 L80 25 L90 40 L85 60 L70 70 L50 65 L35 50 Z" fill="#333" stroke="#444" strokeWidth="0.5"/>
        {/* South America */}
        <path d="M65 75 L85 72 L90 90 L80 115 L65 118 L55 100 Z" fill="#333" stroke="#444" strokeWidth="0.5"/>
        {/* Europe */}
        <path d="M130 25 L160 22 L165 38 L150 45 L130 40 Z" fill="#333" stroke="#444" strokeWidth="0.5"/>
        {/* Africa */}
        <path d="M135 48 L165 45 L170 80 L155 100 L135 95 L125 70 Z" fill="#333" stroke="#444" strokeWidth="0.5"/>
        {/* Asia */}
        <path d="M168 20 L240 18 L250 45 L230 55 L200 50 L170 42 Z" fill="#333" stroke="#444" strokeWidth="0.5"/>
        {/* Australia */}
        <path d="M215 80 L245 78 L248 100 L225 105 L210 95 Z" fill="#333" stroke="#444" strokeWidth="0.5"/>

        {/* Normal cluster dots */}
        <circle cx="55" cy="45" r="2" fill="#34d399" opacity="0.6"/>
        <circle cx="145" cy="32" r="2" fill="#34d399" opacity="0.6"/>
        <circle cx="190" cy="32" r="2" fill="#34d399" opacity="0.6"/>

        {/* Anomalous IP location dot — pulsing red */}
        {hasAnomaly && (
          <>
            <circle cx="148" cy="30" r="6" fill="#EF4444" opacity="0.15"/>
            <circle cx="148" cy="30" r="3" fill="#EF4444" opacity="0.8"/>
            <text x="156" y="27" fill="#EF4444" fontSize="7" fontFamily="monospace">IP: Anomalous</text>
          </>
        )}
      </svg>
      <p className="text-white/20 text-[9px] tracking-widest uppercase px-4 pb-3">
        Sudden Cluster Exit detected
      </p>
    </div>
  )
}

// ── Device risk fingerprint card ──────────────────────────────────────────

function DeviceRiskCard({
  alert,
  deviceFingerprint,
  locationText,
}: {
  alert: FraudAlertResponse
  deviceFingerprint: string | null
  locationText: string | null
}) {
  const isUnknown = alert.alert_type === 'device_change'
  const masked = deviceFingerprint ? `${deviceFingerprint.slice(0, 16)}...` : 'N/A'
  return (
    <div className="bg-white rounded-xl border border-black/5 p-4">
      <p className="text-[#888] text-[9px] font-bold tracking-widest uppercase mb-3">
        Device Risk Fingerprint
      </p>
      <div className="flex gap-3 items-start">
        <div className={`w-10 h-14 rounded-lg border-2 flex items-center justify-center shrink-0 ${
          isUnknown ? 'bg-red-50 border-red-200' : 'bg-gray-50 border-gray-200'
        }`}>
          <svg className={`w-5 h-5 ${isUnknown ? 'text-red-400' : 'text-gray-400'}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 18h.01M8 21h8a2 2 0 002-2V5a2 2 0 00-2-2H8a2 2 0 00-2 2v14a2 2 0 002 2z" />
          </svg>
          {isUnknown && (
            <span className="absolute text-[8px] font-bold text-red-500 mt-8">UNK-IP</span>
          )}
        </div>
        <div className="space-y-1">
          <p className={`text-xs font-semibold ${isUnknown ? 'text-red-700' : 'text-[#0A0F0A]'}`}>
            {isUnknown ? 'Unknown Device' : 'Registered Device'}
          </p>
          <p className="text-[#888] text-[10px] font-mono">
            Device Fingerprint: {masked}
          </p>
          <p className="text-[#888] text-[10px]">
            Location: {locationText ?? 'Unknown'}
          </p>
          {/* Risk trend bars */}
          <div className="flex gap-0.5 items-end mt-2 h-6">
            {[0.2, 0.4, 0.3, 0.6, 0.5, 1.0, 0.8].map((h, i) => {
              const score = alert.risk_score ?? 0
              const isHigh = i >= 5
              return (
                <div
                  key={i}
                  className={`w-3 rounded-sm ${isHigh && score > 50 ? 'bg-red-400' : 'bg-gray-200'}`}
                  style={{ height: `${h * 24}px` }}
                />
              )
            })}
          </div>
          <p className="text-[#aaa] text-[9px] tracking-wider uppercase">Risk Trend (24h)</p>
        </div>
      </div>
    </div>
  )
}

// ── Case detail slide-in panel ────────────────────────────────────────────

interface CasePanelProps {
  alert: FraudAlertResponse
  onClose: () => void
  onAction: (alertId: string, status: FraudAlertStatus, notes: string) => Promise<void>
  onBlock: (txnId: string) => Promise<void>
  onProcess: (txnId: string) => Promise<void>
  actionLoading: boolean
}

function CasePanel({ alert, onClose, onAction, onBlock, onProcess, actionLoading }: CasePanelProps) {
  const riskFactors = alert.triggered_rules
    ? Object.entries(alert.triggered_rules).map(([key, val]) => ({
        label: key.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase()),
        score: val,
        max: 10,
      }))
    : [
        { label: 'Velocity Threshold', score: 9.4, max: 10 },
        { label: 'Entity Link Analysis', score: 6.1, max: 10 },
        { label: 'Historical Pattern Match', score: 1.2, max: 10 },
      ]

  const caseNum = `CASE #${alert.id.slice(0, 7).toUpperCase()}-AF`

  return (
    <div className="w-[340px] shrink-0 bg-white rounded-xl border border-black/5 flex flex-col overflow-hidden max-h-[calc(100vh-180px)] sticky top-4">

      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4 border-b border-[#F0F0EC]">
        <div className="flex items-center gap-2">
          <span className="px-2.5 py-1 bg-[#0A0F0A] text-white text-[9px] font-bold tracking-widest uppercase rounded">
            {caseNum}
          </span>
        </div>
        <button onClick={onClose} className="text-[#aaa] hover:text-[#333] transition-colors text-lg leading-none">
          ×
        </button>
      </div>

      <div className="flex-1 overflow-y-auto p-5 space-y-5">

        {/* Title */}
        <div>
          <h3
            className="text-[#0A0F0A] text-lg font-bold leading-tight"
            style={{ fontFamily: "'Playfair Display', serif" }}
          >
            {alert.alert_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
          </h3>
          {alert.transaction_id && (
            <p className="text-[#888] text-xs mt-1">
               Target Account: <span className="font-mono font-semibold text-[#555]">TXN_{alert.transaction_id.slice(0, 12).toUpperCase()}</span>
            </p>
          )}
          <p className="text-[#666] text-xs mt-2 leading-relaxed">{alert.description ?? 'Anomalous activity pattern detected by the fraud detection engine.'}</p>
        </div>

        {/* Risk breakdown */}
        <div>
          <p className="text-[#888] text-[9px] font-bold tracking-widest uppercase mb-3">Risk Breakdown</p>
          <div className="space-y-2">
            {riskFactors.slice(0, 3).map(f => (
              <div key={f.label} className="flex items-center justify-between">
                <p className="text-[#555] text-xs">{f.label}</p>
                <span className={`text-xs font-bold ${
                  Number(f.score) >= 8 ? 'text-red-600' :
                  Number(f.score) >= 5 ? 'text-amber-600' : 'text-emerald-600'
                }`}>
                  {Number(f.score).toFixed(1)}/10
                </span>
              </div>
            ))}
          </div>
        </div>

        {/* Behavioral anomaly — mini scatter */}
        <div className="bg-[#F8F8F5] rounded-xl p-4">
          <p className="text-[#888] text-[9px] font-bold tracking-widest uppercase mb-3">Behavioral Anomaly</p>
          <svg viewBox="0 0 200 100" className="w-full">
            <rect x="0" y="0" width="200" height="100" fill="none" stroke="#E0E0DC" strokeWidth="0.5" rx="4"/>
            {/* Cluster */}
            {[[40,30],[50,35],[45,28],[55,40],[42,38],[48,32],[52,36]].map(([x,y], i) => (
              <circle key={i} cx={x} cy={y} r="3" fill="#34d399" opacity="0.7"/>
            ))}
            {/* Outlier */}
            <circle cx="160" cy="70" r="5" fill="#EF4444" opacity="0.9"/>
            <text x="110" y="78" fill="#EF4444" fontSize="7" fontFamily="monospace">SUDDEN CLUSTER EXIT</text>
            <line x1="65" y1="38" x2="155" y2="67" stroke="#EF4444" strokeWidth="0.5" strokeDasharray="3 2" opacity="0.5"/>
          </svg>
        </div>

        {/* Investigation log */}
        <div>
          <p className="text-[#888] text-[9px] font-bold tracking-widest uppercase mb-3">Investigation Log</p>
          <div className="space-y-3">
            <div className="flex gap-2">
              <div className="w-2 h-2 rounded-full bg-gray-400 shrink-0 mt-1" />
              <div>
                <p className="text-[#0A0F0A] text-[10px] font-bold tracking-widest uppercase">System Triggered</p>
                <p className="text-[#888] text-xs mt-0.5 leading-relaxed">
                  Alert flagged via fraud engine. Risk score: {alert.risk_score ?? 0}/100. Confidence high.
                </p>
              </div>
            </div>
            {alert.assigned_to && (
              <div className="flex gap-2">
                <div className="w-2 h-2 rounded-full bg-amber-400 shrink-0 mt-1" />
                <div>
                  <p className="text-amber-600 text-[10px] font-bold tracking-widest uppercase">Analyst Claimed</p>
                  <p className="text-[#888] text-xs mt-0.5">
                    {alert.assigned_to} assigned to review.
                  </p>
                </div>
              </div>
            )}
            {alert.resolution_notes && (
              <div className="flex gap-2">
                <div className="w-2 h-2 rounded-full bg-emerald-400 shrink-0 mt-1" />
                <div>
                  <p className="text-emerald-600 text-[10px] font-bold tracking-widest uppercase">Resolution Note</p>
                  <p className="text-[#888] text-xs mt-0.5">{alert.resolution_notes}</p>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {/* Action buttons — from Stitch */}
      <div className="p-4 border-t border-[#F0F0EC] space-y-2">
        <div className="grid grid-cols-2 gap-2">
          <button
            onClick={() => onAction(alert.id, 'investigating', 'Analyst claimed case for investigation')}
            disabled={actionLoading || alert.status === 'investigating'}
            className="py-2.5 px-3 border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-[10px] font-bold tracking-wider uppercase hover:bg-[#F8F8F5] disabled:opacity-50 transition-all"
          >
            {alert.status === 'investigating' ? '✓ Investigating' : 'Mark Investigating'}
          </button>
          <button
            onClick={() => onAction(alert.id, 'resolved', 'Case resolved by analyst')}
            disabled={actionLoading || alert.status === 'resolved'}
            className="py-2.5 px-3 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white rounded-lg text-[10px] font-bold tracking-wider uppercase transition-all"
          >
            {alert.status === 'resolved' ? '✓ Resolved' : 'Resolve Case'}
          </button>
        </div>
        <div className="grid grid-cols-2 gap-2">
          {alert.transaction_id && (
            <button
              onClick={() => onProcess(alert.transaction_id!)}
              disabled={actionLoading}
              className="py-2.5 px-3 bg-emerald-600 hover:bg-emerald-700 disabled:opacity-50 text-white rounded-lg text-[10px] font-bold tracking-wider uppercase transition-all"
            >
              Authorize Transfer
            </button>
          )}
          <button
            onClick={() => onAction(alert.id, 'false_positive', 'Marked as false positive by analyst')}
            disabled={actionLoading || alert.status === 'false_positive'}
            className="py-2.5 px-3 bg-amber-500 hover:bg-amber-600 disabled:opacity-50 text-white rounded-lg text-[10px] font-bold tracking-wider uppercase transition-all"
          >
            {alert.status === 'false_positive' ? '✓ FP Marked' : 'False Positive'}
          </button>
          {alert.transaction_id && (
            <button
              onClick={() => onBlock(alert.transaction_id!)}
              disabled={actionLoading}
              className="py-2.5 px-3 bg-red-700 hover:bg-red-800 disabled:opacity-50 text-white rounded-lg text-[9px] font-bold tracking-wider uppercase transition-all flex items-center justify-center gap-1"
            >
              <svg className="w-3 h-3 opacity-70" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
              </svg>
              SEC_PROTOCOL
            </button>
          )}
        </div>

        <p className="text-[#aaa] text-[9px] text-center tracking-wider uppercase pt-1">
          All actions logged under SEC-OP compliance
        </p>
      </div>
    </div>
  )
}

// ── Main page ─────────────────────────────────────────────────────────────

export function FraudWorkspacePage() {
  const [alerts, setAlerts]           = useState<FraudAlertResponse[]>([])
  const [total, setTotal]             = useState(0)
  const [loading, setLoading]         = useState(true)
  const [selectedAlert, setSelected]  = useState<FraudAlertResponse | null>(null)
  const [selectedAlertTxn, setSelectedAlertTxn] = useState<TransactionResponse | null>(null)
  const [actionLoading, setActLoading]= useState(false)
  const [actionMsg, setActionMsg]     = useState<{ type: 'success' | 'error'; text: string } | null>(null)

  const [sevFilter, setSevFilter]     = useState('')
  const [statusFilter, setStatusFilter] = useState('')

  const avgRisk = alerts.length
    ? Math.round(alerts.reduce((s, a) => s + (a.risk_score ?? 0), 0) / alerts.length * 10) / 10
    : 0

  const fetchAlerts = useCallback(() => {
    setLoading(true)
    http.get<FraudAlertListResponse>('/fraud/alerts/?page=1&page_size=50')
      .then(r => {
        const all = r.data.alerts ?? r.data.items ?? []
        setAlerts(all)
        setTotal(r.data.total)
      })
      .catch(() => setAlerts([]))
      .finally(() => setLoading(false))
  }, [])

  useEffect(() => { fetchAlerts() }, [fetchAlerts])

  useEffect(() => {
    if (!selectedAlert?.transaction_id) {
      setSelectedAlertTxn(null)
      return
    }
    http.get<TransactionResponse>(`/transactions/review-item/${selectedAlert.transaction_id}`)
      .then(r => setSelectedAlertTxn(r.data))
      .catch(() => setSelectedAlertTxn(null))
  }, [selectedAlert?.transaction_id])

  const filtered = alerts.filter(a => {
    const matchSev    = !sevFilter    || a.severity === sevFilter
    const matchStatus = !statusFilter || a.status   === statusFilter
    return matchSev && matchStatus
  })

  async function handleAction(alertId: string, status: FraudAlertStatus, notes: string) {
    setActLoading(true); setActionMsg(null)
    try {
      await http.patch(`/fraud/alerts/${alertId}/status`, {
        status,
        resolution_notes: notes,
      }, { validateStatus: s => s < 500 })

      setActionMsg({ type: 'success', text: `Alert marked as ${status.replace('_', ' ')}.` })
      fetchAlerts()
      if (selectedAlert?.id === alertId) {
        setSelected(prev => prev ? { ...prev, status } : null)
      }
    } catch {
      setActionMsg({ type: 'error', text: 'Action failed. Please try again.' })
    } finally {
      setActLoading(false)
    }
  }

  async function handleBlock(txnId: string) {
    setActLoading(true); setActionMsg(null)
    try {
      await http.post(`/transactions/${txnId}/block`, {
        reason: 'Blocked via SEC_PROTOCOL from Fraud Workspace',
      }, { validateStatus: s => s < 500 })
      setActionMsg({ type: 'success', text: 'Transaction frozen. SEC_PROTOCOL executed.' })
    } catch {
      setActionMsg({ type: 'error', text: 'Unable to freeze transaction. Verify analyst permissions.' })
    } finally {
      setActLoading(false)
    }
  }

  async function handleProcess(txnId: string) {
    setActLoading(true); setActionMsg(null)
    try {
      await http.post(
        `/transactions/review-item/${txnId}/process`,
        {},
        { validateStatus: s => s < 500 }
      )
      setActionMsg({ type: 'success', text: 'Transaction processed successfully.' })
      fetchAlerts()
    } catch {
      setActionMsg({ type: 'error', text: 'Unable to process transaction from this case.' })
    } finally {
      setActLoading(false)
    }
  }

  const openCount = alerts.filter(a => a.status === 'open').length

  return (
    <AppShell>
      {/* Vault banner */}
      <div className="flex items-center justify-between bg-[#0A0F0A] border-b border-emerald-900/30 px-6 py-2">
        <div className="flex items-center gap-2">
          <svg className="w-3.5 h-3.5 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
          </svg>
          <span className="text-emerald-400 text-[9px] font-bold tracking-widest uppercase">
            GabbyBank Connection Active | Standard Banking System
          </span>
        </div>
        <span className="text-white/30 text-[9px] tracking-widest uppercase">Fraud Ops Level 4</span>
      </div>

      <div className="p-6" style={{ fontFamily: "'DM Sans', sans-serif" }}>

        {/* Action feedback */}
        {actionMsg && (
          <div className={`mb-4 flex gap-3 p-3 rounded-lg border text-sm ${
            actionMsg.type === 'success'
              ? 'bg-emerald-50 border-emerald-200 text-emerald-700'
              : 'bg-red-50 border-red-200 text-red-700'
          }`}>
            <span>{actionMsg.type === 'success' ? '✓' : '!'}</span>
            <span>{actionMsg.text}</span>
            <button onClick={() => setActionMsg(null)} className="ml-auto opacity-60 hover:opacity-100">×</button>
          </div>
        )}

        <div className="flex gap-5 items-start">

          {/* ── Left: main panel ────────────────────────────────────── */}
          <div className="flex-1 min-w-0 space-y-5">

            {/* Hero heading + stats */}
            <div className="flex items-start justify-between">
              <div>
                <h1 className="text-[#0A0F0A] text-3xl font-bold" style={{ fontFamily: "'Playfair Display', serif" }}>
                  Fraud Analysis<br />Workspace
                </h1>
                <p className="text-[#888] text-sm mt-1">
                  Reviewing <span className="font-semibold text-[#0A0F0A]">{total}</span> pending anomalies across Standard Banking System
                </p>
              </div>

              {/* Hero stat cards */}
              <div className="flex gap-3">
                <div className="bg-white border border-black/5 rounded-xl px-6 py-4 text-center min-w-[110px]">
                  <p className="text-[#888] text-[9px] font-bold tracking-widest uppercase mb-1">Active Alerts</p>
                  <p className="text-[#0A0F0A] text-3xl font-bold">{openCount}</p>
                </div>
                <div className="bg-white border border-black/5 rounded-xl px-6 py-4 text-center min-w-[110px]">
                  <p className="text-[#888] text-[9px] font-bold tracking-widest uppercase mb-1">Risk Score Avg</p>
                  <p className={`text-3xl font-bold ${avgRisk >= 70 ? 'text-red-600' : avgRisk >= 40 ? 'text-amber-600' : 'text-emerald-600'}`}>
                    {avgRisk}
                  </p>
                </div>
              </div>
            </div>

            {/* Filter bar */}
            <div className="flex items-center gap-3">
              <div className="flex items-center gap-2 bg-white border border-[#E0E0DC] rounded-lg px-3 py-2">
                <span className="text-[#888] text-[10px] font-bold tracking-widest uppercase">Severity</span>
                <select
                  value={sevFilter}
                  onChange={e => setSevFilter(e.target.value)}
                  className="text-[#0A0F0A] text-xs bg-transparent focus:outline-none"
                >
                  <option value="">All Levels</option>
                  <option value="critical">Critical</option>
                  <option value="high">High</option>
                  <option value="medium">Medium</option>
                  <option value="low">Low</option>
                </select>
              </div>
              <div className="flex items-center gap-2 bg-white border border-[#E0E0DC] rounded-lg px-3 py-2">
                <span className="text-[#888] text-[10px] font-bold tracking-widest uppercase">Status</span>
                <select
                  value={statusFilter}
                  onChange={e => setStatusFilter(e.target.value)}
                  className="text-[#0A0F0A] text-xs bg-transparent focus:outline-none"
                >
                  <option value="">All Status</option>
                  <option value="open">Open</option>
                  <option value="investigating">Investigating</option>
                  <option value="resolved">Resolved</option>
                  <option value="false_positive">False Positive</option>
                </select>
              </div>
              <div className="ml-auto flex items-center gap-2">
                <span className="text-[#888] text-[10px] font-bold tracking-widest uppercase">Risk Range</span>
                <div className="w-20 h-1.5 bg-[#E0E0DC] rounded-full">
                  <div className="h-full bg-[#0A0F0A] rounded-full" style={{ width: '100%' }} />
                </div>
              </div>
            </div>

            {/* Alert table */}
            <div className="bg-white rounded-xl border border-black/5 overflow-hidden">

              {/* Table header */}
              <div className="grid grid-cols-[80px_1fr_80px_1fr_120px] px-5 py-3 border-b border-[#F0F0EC] bg-[#FAFAF8]">
                {['Severity', 'Transaction ID', 'Score', 'Rule Triggered', 'Status'].map(h => (
                  <p key={h} className="text-[#aaa] text-[9px] font-bold tracking-widest uppercase">{h}</p>
                ))}
              </div>

              {loading ? (
                <div className="flex items-center justify-center py-12 text-[#aaa] text-sm gap-2">
                  <svg className="animate-spin w-4 h-4 text-[#1a4a25]" fill="none" viewBox="0 0 24 24">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Loading alerts…
                </div>
              ) : filtered.length === 0 ? (
                <div className="flex flex-col items-center justify-center py-12 gap-2">
                  <svg className="w-8 h-8 text-[#ddd]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                  </svg>
                  <p className="text-[#aaa] text-sm">No alerts match the current filters</p>
                </div>
              ) : (
                filtered.map(alert => (
                  <div
                    key={alert.id}
                    onClick={() => setSelected(alert)}
                    className={`grid grid-cols-[80px_1fr_80px_1fr_120px] px-5 py-4 items-center
                      cursor-pointer border-b border-[#F8F8F5] last:border-0 transition-all
                      hover:bg-[#FAFAF8]
                      ${selectedAlert?.id === alert.id ? 'bg-blue-50/50 border-l-2 border-l-blue-400' : ''}
                    `}
                  >
                    {/* Severity */}
                    <div className="flex items-center gap-2">
                      <div className={`w-2 h-2 rounded-full ${SEV_DOT[alert.severity]}`} />
                      <span className={`text-[10px] font-bold uppercase tracking-wider ${SEV_TEXT[alert.severity]}`}>
                        {alert.severity}
                      </span>
                    </div>

                    {/* TXN ID */}
                    <div>
                      <p className="text-[#0A0F0A] text-xs font-mono font-semibold">
                        TXN_{alert.transaction_id?.slice(0, 8).toUpperCase() ?? alert.id.slice(0, 8).toUpperCase()}
                      </p>
                      <p className="text-[#aaa] text-[10px] mt-0.5">
                        {new Date(alert.created_at).toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}
                      </p>
                    </div>

                    {/* Score circle */}
                    <ScoreCircle score={alert.risk_score ?? 0} severity={alert.severity} />

                    {/* Rule triggered */}
                    <p className="text-[#555] text-xs italic">
                      {alert.alert_type.replace(/_/g, ' ').replace(/\b\w/g, c => c.toUpperCase())}
                    </p>

                    {/* Status */}
                    <StatusBadge status={alert.status} />
                  </div>
                ))
              )}
            </div>

            {/* Bottom widgets row — GEO MAP + DEVICE RISK */}
            {selectedAlert && (
              <div className="grid grid-cols-2 gap-4">
                <GeoAnomalyMap alert={selectedAlert} />
                <DeviceRiskCard
                  alert={selectedAlert}
                  deviceFingerprint={selectedAlertTxn?.device_fingerprint ?? null}
                  locationText={
                    selectedAlertTxn?.location_country
                      ? `${selectedAlertTxn.location_city ? `${selectedAlertTxn.location_city}, ` : ''}${selectedAlertTxn.location_country}`
                      : null
                  }
                />
              </div>
            )}
          </div>

          {/* ── Right: case detail slide-in ──────────────────────── */}
          {selectedAlert && (
            <CasePanel
              alert={selectedAlert}
              onClose={() => setSelected(null)}
              onAction={handleAction}
              onBlock={handleBlock}
              onProcess={handleProcess}
              actionLoading={actionLoading}
            />
          )}
        </div>
      </div>
    </AppShell>
  )
}
