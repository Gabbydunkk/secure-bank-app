// src/App.tsx
// Wires together the AuthProvider, router, and all route guards.
// This is what your full routing tree will look like once all phases are built.
// Start with the Phase 1 routes (login, register, dashboard shell) and add the rest.

import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './contexts/AuthContext'
import { RequireAuth } from './components/guards/RequireAuth'

// ── Page imports (build these in Phase 2 onwards) ─────────────────────────
// Uncomment each as you build it.

// Phase 2 — Auth
import { LoginPage } from './pages/auth/LoginPage'
import { RegisterPage } from './pages/auth/RegisterPage'
import { MfaVerifyPage } from './pages/auth/MfaVerifyPage'
import { MfaSetupPage }    from './pages/auth/MfaSetupPage'
import { ForgotAccessPage } from './pages/auth/ForgotAccessPage'
// import { MfaConfirmPage }  from './pages/auth/MfaConfirmPage'

// Phase 3 — User views
import { DashboardPage }       from './pages/dashboard/DashboardPage'
import { TransactionsPage }    from './pages/transactions/TransactionsPage'
import { TransactionDetailPage }   from './pages/transactions/TransactionDetailPage'
import { NewTransactionPage }  from './pages/transactions/NewTransactionPage'
// import { FraudAlertsPage }     from './pages/fraud/FraudAlertsPage'
// import { FraudAlertDetail }    from './pages/fraud/FraudAlertDetail'
// import { AuditLogPage }        from './pages/audit/AuditLogPage'
// import { AccountSettingsPage } from './pages/account/AccountSettingsPage'
// import { DevicesPage }         from './pages/account/DevicesPage'

// Phase 4 — Analyst views (require role="analyst")
import { FraudWorkspacePage }   from './pages/analyst/FraudWorkspacePage'
import { AnalystToolsPage }     from './pages/analyst/AnalystToolsPage'

// Phase 5 — Admin views (require role="admin")
import { AdminControlCenterPage } from './pages/admin/AdminControlCenterPage'
import { AdminUserDetailPage }    from './pages/admin/AdminUserDetailPage'

// ── Placeholder pages — delete as you build real ones ─────────────────────

function Placeholder({ name }: { name: string }) {
  return (
    <div style={{ padding: 32 }}>
      <h2>{name}</h2>
      <p style={{ color: '#888' }}>Not yet built.</p>
    </div>
  )
}

// ── App ───────────────────────────────────────────────────────────────────

export default function App() {
  return (
    <BrowserRouter>
      {/*
        AuthProvider wraps everything so every page can call useAuth().
        It runs the hydration check (GET /auth/me) immediately on mount.
        While hydrating, RequireAuth renders a loading screen — no flicker.
      */}
      <AuthProvider>
        <Routes>
          {/* ── Public routes (no auth required) ──────────────────────── */}
          <Route path="/login"    element={<LoginPage />} />
          <Route path="/register" element={<RegisterPage />} />
          <Route path="/forgot-access" element={<ForgotAccessPage />} />
          {/*
            /mfa/verify is public — the mfa_token in the request body IS the
            credential. Do not wrap this in RequireAuth.
          */}
          <Route path="/mfa/verify" element={<MfaVerifyPage />} />
          <Route
            path="/mfa/setup"
            element={
              <RequireAuth>
                <MfaSetupPage />
             </RequireAuth>
            }
          />

          {/* ── User routes (authenticated, any role) ─────────────────── */}
          <Route
            path="/dashboard"
            element={
              <RequireAuth>
                <DashboardPage />
              </RequireAuth>
            }
          />
          <Route
            path="/transactions"
            element={
              <RequireAuth>
                <TransactionsPage />
              </RequireAuth>
            }
          />
          <Route
            path="/transactions/new"
            element={
              <RequireAuth>
                <NewTransactionPage />
              </RequireAuth>
            }
          />
          <Route
            path="/transactions/:id"
            element={
              <RequireAuth>
                <TransactionDetailPage />
              </RequireAuth>
            }
          />
          <Route
            path="/fraud/alerts"
            element={
              <RequireAuth>
                <Placeholder name="Fraud Alerts (own)" />
              </RequireAuth>
            }
          />
          <Route
            path="/audit"
            element={
              <RequireAuth>
                <Placeholder name="Audit Log" />
              </RequireAuth>
            }
          />
          <Route
            path="/settings"
            element={
              <RequireAuth>
                <Placeholder name="Account Settings" />
              </RequireAuth>
            }
          />
          <Route
            path="/settings/devices"
            element={
              <RequireAuth>
                <Placeholder name="Devices" />
              </RequireAuth>
            }
          />

          {/* ── Analyst routes (role >= analyst) ──────────────────────── */}
          <Route
            path="/analyst/fraud"
            element={
              <RequireAuth role="analyst">
                <FraudWorkspacePage />
              </RequireAuth>
            }
          />
          <Route
            path="/analyst/tools"
            element={
              <RequireAuth role="analyst">
                <AnalystToolsPage />
              </RequireAuth>
            }
          />

          {/* ── Admin routes (role = admin only) ──────────────────────── */}
          <Route
            path="/admin/users"
            element={
              <RequireAuth role="admin">
                <AdminControlCenterPage />
              </RequireAuth>
            }
          />
          <Route
            path="/admin/users/:id"
            element={
              <RequireAuth role="admin">
                <AdminUserDetailPage />
              </RequireAuth>
            }
          />
          <Route
            path="/admin/system"
            element={
              <RequireAuth role="admin">
                <AdminControlCenterPage />
              </RequireAuth>
            }
          />

          {/* ── Fallbacks ─────────────────────────────────────────────── */}
          <Route
            path="/unauthorized"
            element={<Placeholder name="403 — Insufficient permissions" />}
          />
          <Route path="/" element={<Navigate to="/dashboard" replace />} />
          <Route path="*" element={<Placeholder name="404 — Page not found" />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}
