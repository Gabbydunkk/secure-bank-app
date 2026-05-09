import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { AppShell } from '../../components/layout/AppShell'
import { http } from '../../lib/http'
import type { AuditLogListResponse, AuditLogResponse } from '../../types/api'

export function AuditTrailPage() {
  const [logs, setLogs] = useState<AuditLogResponse[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [actionFilter, setActionFilter] = useState('')

  async function loadLogs() {
    setLoading(true)
    setError(null)
    try {
      const query = actionFilter.trim()
        ? `/audit/logs/?page=1&page_size=50&action=${encodeURIComponent(actionFilter.trim())}`
        : '/audit/logs/?page=1&page_size=50'
      const res = await http.get<AuditLogListResponse>(query)
      setLogs(res.data.logs ?? res.data.items ?? [])
    } catch (err: unknown) {
      const maybe = err as { response?: { status?: number; data?: { detail?: string } } }
      const status = maybe.response?.status
      const detail = maybe.response?.data?.detail
      setError(
        status
          ? `Unable to load audit logs at this time (HTTP ${status}${detail ? `: ${detail}` : ''}).`
          : 'Unable to load audit logs at this time.'
      )
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadLogs()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <AppShell>
      <div className="p-6 max-w-[1300px] mx-auto" style={{ fontFamily: "'DM Sans', sans-serif" }}>
        <div className="mb-5">
          <h1 className="text-[#0A0F0A] text-3xl font-bold" style={{ fontFamily: "'Playfair Display', serif" }}>
            Audit Trail
          </h1>
          <p className="text-[#777] text-sm mt-1">
            Immutable activity record for authentication and transaction operations.
          </p>
        </div>

        <div className="bg-white rounded-xl border border-black/5 overflow-hidden">
          <div className="flex items-center gap-3 px-5 py-4 border-b border-[#F0F0EC]">
            <input
              value={actionFilter}
              onChange={e => setActionFilter(e.target.value)}
              placeholder="Filter by action (e.g. transaction, login, fraud)"
              className="flex-1 max-w-md px-3 py-2 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg text-sm text-[#0A0F0A] focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/20"
            />
            <button
              type="button"
              onClick={loadLogs}
              className="px-4 py-2 bg-[#0A0F0A] text-white text-xs font-semibold rounded-lg hover:bg-[#1c2a1c]"
            >
              Refresh
            </button>
          </div>

          {loading && <p className="px-5 py-6 text-sm text-[#777]">Loading audit log entries...</p>}
          {error && <p className="px-5 py-6 text-sm text-red-700">{error}</p>}
          {!loading && !error && logs.length === 0 && (
            <p className="px-5 py-6 text-sm text-[#777]">No audit records found for this filter.</p>
          )}

          {!loading && !error && logs.length > 0 && (
            <div>
              <div className="grid grid-cols-[180px_180px_1fr_120px] px-5 py-3 bg-[#FAFAF8] border-b border-[#F0F0EC]">
                <span className="text-[10px] font-bold tracking-widest uppercase text-[#777]">Time</span>
                <span className="text-[10px] font-bold tracking-widest uppercase text-[#777]">Action</span>
                <span className="text-[10px] font-bold tracking-widest uppercase text-[#777]">Context</span>
                <span className="text-[10px] font-bold tracking-widest uppercase text-[#777]">Result</span>
              </div>

              {logs.map(log => {
                const isTxn = log.entity_type === 'transaction' && !!log.entity_id
                return (
                  <div key={log.id} className="grid grid-cols-[180px_180px_1fr_120px] px-5 py-3 border-b border-[#F8F8F5] last:border-0 items-center">
                    <span className="text-xs text-[#555]">
                      {new Date(log.created_at).toLocaleString()}
                    </span>
                    <span className="text-xs font-semibold text-[#0A0F0A]">{log.action}</span>
                    <div className="text-xs text-[#666]">
                      <p>
                        {log.entity_type ?? 'event'} {isTxn ? (
                          <Link to={`/transactions/${log.entity_id}`} className="text-[#1a4a25] hover:underline">
                            {String(log.entity_id).slice(0, 8)}...
                          </Link>
                        ) : (
                          log.entity_id ? `${String(log.entity_id).slice(0, 8)}...` : 'n/a'
                        )}
                      </p>
                      <p className="text-[#999]">IP: {log.ip_address ?? 'n/a'}</p>
                    </div>
                    <span className={`text-xs font-semibold ${log.success ? 'text-emerald-700' : 'text-red-700'}`}>
                      {log.success ? 'Success' : 'Failed'}
                    </span>
                  </div>
                )
              })}
            </div>
          )}
        </div>
      </div>
    </AppShell>
  )
}
