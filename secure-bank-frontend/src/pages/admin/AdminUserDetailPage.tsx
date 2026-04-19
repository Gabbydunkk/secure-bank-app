import { useCallback, useEffect, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import { AppShell } from '../../components/layout/AppShell'
import { http } from '../../lib/http'
import type {
  AccountStatus,
  AuditLogListResponse,
  AuditLogResponse,
  UserResponse,
  UserRole,
} from '../../types/api'

function apiErrorMessage(err: unknown, fallback: string): string {
  if (typeof err === 'object' && err !== null && 'response' in err) {
    const e = err as { response?: { status?: number; data?: { detail?: unknown } } }
    const detail = e.response?.data?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail) && detail.length > 0) {
      const first = detail[0] as { msg?: string }
      if (first?.msg) return first.msg
    }
    if (e.response?.status) return `${fallback} (HTTP ${e.response.status})`
  }
  return fallback
}

export function AdminUserDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [user, setUser] = useState<UserResponse | null>(null)
  const [logs, setLogs] = useState<AuditLogResponse[]>([])
  const [logsError, setLogsError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [statusVal, setStatusVal] = useState<AccountStatus>('active')
  const [roleVal, setRoleVal] = useState<UserRole>('user')
  const [busy, setBusy] = useState(false)

  const load = useCallback(async () => {
    if (!id) return
    setLoading(true)
    setError(null)
    setLogsError(null)
    try {
      const u = await http.get<UserResponse>(`/admin/users/${id}`)
      setUser(u.data)
      setStatusVal(u.data.account_status)
      setRoleVal(u.data.role)
      try {
        const a = await http.get<AuditLogListResponse>(`/admin/users/${id}/audit-logs?page=1&page_size=20`)
        setLogs(a.data.logs ?? a.data.items ?? [])
      } catch (err) {
        setLogs([])
        setLogsError(apiErrorMessage(err, 'Unable to load audit logs for this user.'))
      }
    } catch (err) {
      setError(apiErrorMessage(err, 'Unable to load user detail.'))
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => { void load() }, [load])

  async function saveStatus() {
    if (!id) return
    setBusy(true)
    setError(null)
    try {
      await http.patch(`/admin/users/${id}/status`, { status: statusVal })
      await load()
    } catch (err) {
      setError(apiErrorMessage(err, 'Failed to update status.'))
    } finally {
      setBusy(false)
    }
  }

  async function saveRole() {
    if (!id) return
    setBusy(true)
    setError(null)
    try {
      await http.patch(`/admin/users/${id}/role`, { role: roleVal })
      await load()
    } catch (err) {
      setError(apiErrorMessage(err, 'Failed to update role.'))
    } finally {
      setBusy(false)
    }
  }

  async function forceLogout() {
    if (!id) return
    setBusy(true)
    setError(null)
    try {
      await http.delete(`/admin/users/${id}/sessions`)
      await load()
    } catch (err) {
      setError(apiErrorMessage(err, 'Failed to invalidate sessions.'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <AppShell>
      <div className="p-6 max-w-[1200px] mx-auto" style={{ fontFamily: "'DM Sans', sans-serif" }}>
        <div className="mb-5 flex items-center justify-between">
          <div>
            <h1 className="text-[#0A0F0A] text-3xl font-bold" style={{ fontFamily: "'Playfair Display', serif" }}>
              User Detail
            </h1>
            <p className="text-[#777] text-sm mt-1">Admin controls and audit timeline for this account.</p>
          </div>
          <Link to="/admin/users" className="px-4 py-2 border border-[#E0E0DC] rounded-lg text-sm text-[#555] hover:bg-white">
            Back to Users
          </Link>
        </div>

        {error && <div className="mb-4 p-3 bg-red-50 border border-red-200 rounded text-red-700 text-sm">{error}</div>}

        {loading ? (
          <div className="p-6 text-[#888] text-sm">Loading user…</div>
        ) : user ? (
          <div className="grid grid-cols-3 gap-5">
            <div className="col-span-1 space-y-4">
              <div className="bg-white border border-black/5 rounded-xl p-5">
                <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">Identity</p>
                <p className="text-[#0A0F0A] font-semibold">{user.first_name} {user.last_name}</p>
                <p className="text-[#666] text-sm mt-1">{user.email}</p>
                <p className="text-[#aaa] text-xs mt-2 font-mono">{user.id}</p>
              </div>

              <div className="bg-white border border-black/5 rounded-xl p-5 space-y-4">
                <div>
                  <label className="block text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">Account Status</label>
                  <select value={statusVal} onChange={e => setStatusVal(e.target.value as AccountStatus)} className="w-full px-3 py-2 border border-[#E0E0DC] rounded-lg text-sm">
                    <option value="active">active</option>
                    <option value="suspended">suspended</option>
                    <option value="locked">locked</option>
                    <option value="closed">closed</option>
                  </select>
                  <button onClick={saveStatus} disabled={busy} className="mt-2 w-full py-2 bg-[#0A0F0A] text-white rounded-lg text-xs font-semibold disabled:opacity-50">
                    Update Status
                  </button>
                </div>

                <div>
                  <label className="block text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">Role</label>
                  <select value={roleVal} onChange={e => setRoleVal(e.target.value as UserRole)} className="w-full px-3 py-2 border border-[#E0E0DC] rounded-lg text-sm">
                    <option value="user">user</option>
                    <option value="analyst">analyst</option>
                    <option value="admin">admin</option>
                  </select>
                  <button onClick={saveRole} disabled={busy} className="mt-2 w-full py-2 bg-[#0A0F0A] text-white rounded-lg text-xs font-semibold disabled:opacity-50">
                    Update Role
                  </button>
                </div>

                <button onClick={forceLogout} disabled={busy} className="w-full py-2 bg-red-600 text-white rounded-lg text-xs font-semibold disabled:opacity-50">
                  Force Logout Sessions
                </button>
              </div>
            </div>

            <div className="col-span-2 bg-white border border-black/5 rounded-xl p-5">
              <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-4">Audit Trail</p>
              {logsError && (
                <div className="mb-3 p-2.5 bg-amber-50 border border-amber-200 rounded text-amber-700 text-xs">
                  {logsError}
                </div>
              )}
              {logs.length === 0 ? (
                <p className="text-[#999] text-sm">No audit events found.</p>
              ) : (
                <div className="space-y-3 max-h-[540px] overflow-y-auto pr-1">
                  {logs.map(log => (
                    <div key={log.id} className="pb-3 border-b border-[#F2F2EF] last:border-0">
                      <p className="text-[#0A0F0A] text-xs font-semibold">{log.action}</p>
                      <p className="text-[#888] text-xs mt-0.5">
                        {new Date(log.created_at).toLocaleString()} {log.success ? '· success' : '· failed'}
                      </p>
                      {log.error_message && <p className="text-red-600 text-xs mt-1">{log.error_message}</p>}
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        ) : null}
      </div>
    </AppShell>
  )
}
