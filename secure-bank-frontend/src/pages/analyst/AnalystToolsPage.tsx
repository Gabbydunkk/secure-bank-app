import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AppShell } from '../../components/layout/AppShell'
import { http } from '../../lib/http'
import type { TransactionListResponse, TransactionResponse, TransactionStatus } from '../../types/api'

function statusClass(status: TransactionStatus): string {
  if (status === 'blocked') return 'bg-red-100 text-red-700 border-red-200'
  if (status === 'flagged') return 'bg-amber-100 text-amber-700 border-amber-200'
  if (status === 'completed') return 'bg-emerald-100 text-emerald-700 border-emerald-200'
  if (status === 'processing') return 'bg-blue-100 text-blue-700 border-blue-200'
  if (status === 'failed') return 'bg-red-50 text-red-600 border-red-100'
  return 'bg-gray-100 text-gray-600 border-gray-200'
}

export function AnalystToolsPage() {
  const [rows, setRows] = useState<TransactionResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [statusFilter, setStatusFilter] = useState<string>('flagged')
  const [minRisk, setMinRisk] = useState<number>(40)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const load = useCallback(() => {
    setLoading(true)
    setError(null)
    const params = new URLSearchParams({ page: '1', page_size: '50' })
    if (statusFilter) params.append('status', statusFilter)
    if (minRisk > 0) params.append('min_risk_score', String(minRisk))

    http.get<TransactionListResponse>(`/transactions/review?${params}`)
      .then(r => setRows(r.data.items ?? r.data.transactions ?? []))
      .catch(() => setError('Unable to load review transactions.'))
      .finally(() => setLoading(false))
  }, [statusFilter, minRisk])

  useEffect(() => { load() }, [load])

  async function quickAuthorize(txn: TransactionResponse) {
    setBusyId(txn.id)
    setError(null)
    try {
      if (txn.status === 'flagged' || txn.status === 'blocked') {
        await http.post(`/transactions/${txn.id}/clear`, { reason: 'Analyst quick-clear from review board' })
      }
      await http.post(`/transactions/review-item/${txn.id}/process`, {})
      load()
    } catch {
      setError('Unable to authorize/process this transaction.')
    } finally {
      setBusyId(null)
    }
  }

  async function quickBlock(txnId: string) {
    setBusyId(txnId)
    setError(null)
    try {
      await http.post(`/transactions/${txnId}/block`, { reason: 'Analyst quick-block from review board' })
      load()
    } catch {
      setError('Unable to block this transaction.')
    } finally {
      setBusyId(null)
    }
  }

  return (
    <AppShell>
      <div className="p-6 max-w-[1300px] mx-auto" style={{ fontFamily: "'DM Sans', sans-serif" }}>
        <div className="mb-5 flex items-start justify-between gap-4">
          <div>
            <h1 className="text-[#0A0F0A] text-3xl font-bold" style={{ fontFamily: "'Playfair Display', serif" }}>
              Analyst Tools
            </h1>
            <p className="text-[#777] text-sm mt-1">Global transaction triage and manual risk operations.</p>
          </div>
          <button
            onClick={load}
            className="px-4 py-2 bg-[#0A0F0A] text-white text-xs font-semibold rounded-lg hover:bg-[#1c2a1c] transition-all"
          >
            Refresh
          </button>
        </div>

        <div className="mb-4 flex items-center gap-3">
          <select
            value={statusFilter}
            onChange={e => setStatusFilter(e.target.value)}
            className="px-3 py-2 bg-white border border-[#E0E0DC] rounded-lg text-sm"
          >
            <option value="">All Statuses</option>
            <option value="flagged">Flagged</option>
            <option value="blocked">Blocked</option>
            <option value="pending">Pending</option>
            <option value="processing">Processing</option>
            <option value="failed">Failed</option>
            <option value="completed">Completed</option>
          </select>
          <input
            type="number"
            min={0}
            max={100}
            value={minRisk}
            onChange={e => setMinRisk(Number(e.target.value || 0))}
            className="w-40 px-3 py-2 bg-white border border-[#E0E0DC] rounded-lg text-sm"
            placeholder="Min risk score"
          />
          <span className="text-xs text-[#888]">Tip: set min risk to 40+ for anomaly triage.</span>
        </div>

        {error && (
          <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded-lg text-red-700 text-sm">{error}</div>
        )}

        <div className="bg-white border border-black/5 rounded-xl overflow-hidden">
          <div className="grid grid-cols-[140px_110px_90px_1fr_220px] px-5 py-3 bg-[#FAFAF8] border-b border-[#F0F0EC]">
            <p className="text-[10px] text-[#888] font-bold tracking-widest uppercase">Transaction</p>
            <p className="text-[10px] text-[#888] font-bold tracking-widest uppercase">Status</p>
            <p className="text-[10px] text-[#888] font-bold tracking-widest uppercase">Risk</p>
            <p className="text-[10px] text-[#888] font-bold tracking-widest uppercase">Signals</p>
            <p className="text-[10px] text-[#888] font-bold tracking-widest uppercase">Actions</p>
          </div>

          {loading ? (
            <div className="p-8 text-[#888] text-sm">Loading review queue…</div>
          ) : rows.length === 0 ? (
            <div className="p-8 text-[#888] text-sm">No transactions match current filters.</div>
          ) : (
            rows.map(txn => (
              <div key={txn.id} className="grid grid-cols-[140px_110px_90px_1fr_220px] px-5 py-4 border-b border-[#F8F8F5] items-center last:border-0">
                <div>
                  <Link to={`/transactions/${txn.id}`} className="text-[#0A0F0A] text-xs font-mono font-semibold hover:underline">
                    TXN-{txn.id.slice(0, 8).toUpperCase()}
                  </Link>
                  <p className="text-[#999] text-[11px] mt-0.5">{txn.transaction_type.toUpperCase()}</p>
                </div>

                <div>
                  <span className={`inline-flex px-2 py-0.5 rounded border text-[10px] font-bold tracking-widest uppercase ${statusClass(txn.status)}`}>
                    {txn.status}
                  </span>
                </div>

                <div className={`text-sm font-bold ${(txn.risk_score ?? 0) >= 70 ? 'text-red-600' : (txn.risk_score ?? 0) >= 40 ? 'text-amber-600' : 'text-emerald-600'}`}>
                  {txn.risk_score ?? 0}
                </div>

                <div>
                  <p className="text-xs text-[#555]">Fraud: {txn.fraud_check_status}</p>
                  <p className="text-[11px] text-[#888] font-mono">
                    {txn.device_fingerprint ? `DFP:${txn.device_fingerprint.slice(0, 10)}…` : 'DFP: none'} · {txn.location_country ?? 'LOC: none'}
                  </p>
                </div>

                <div className="flex items-center gap-2">
                  <button
                    onClick={() => quickAuthorize(txn)}
                    disabled={busyId === txn.id || txn.status === 'completed' || txn.status === 'processing'}
                    className="px-2.5 py-1.5 bg-emerald-600 text-white text-[10px] font-bold tracking-widest uppercase rounded hover:bg-emerald-700 disabled:opacity-50"
                  >
                    Authorize
                  </button>
                  <button
                    onClick={() => quickBlock(txn.id)}
                    disabled={busyId === txn.id || txn.status === 'blocked' || txn.status === 'completed'}
                    className="px-2.5 py-1.5 bg-red-600 text-white text-[10px] font-bold tracking-widest uppercase rounded hover:bg-red-700 disabled:opacity-50"
                  >
                    Block
                  </button>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </AppShell>
  )
}
