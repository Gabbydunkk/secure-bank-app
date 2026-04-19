// src/components/guards/RequireAuth.tsx
// Protects routes from unauthenticated or unauthorised access.
//
// Usage:
//
//   // Require authentication only:
//   <Route path="/dashboard" element={<RequireAuth><Dashboard /></RequireAuth>} />
//
//   // Require analyst or admin role:
//   <Route path="/fraud" element={<RequireAuth role="analyst"><FraudQueue /></RequireAuth>} />
//
//   // Require admin only:
//   <Route path="/admin" element={<RequireAuth role="admin"><AdminPanel /></RequireAuth>} />
//
// Behaviour:
//   isLoading → renders the LoadingScreen (prevents flash of login redirect)
//   not authenticated → redirects to /login, preserving the intended destination
//     in location.state so the login page can redirect back after success
//   authenticated but wrong role → redirects to /unauthorized (403 page)
//   authenticated and authorised → renders children

import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import type { UserRole } from '../../types/api'

interface RequireAuthProps {
  children: React.ReactNode
  /**
   * Required role(s). If omitted, only authentication is checked.
   * Respects the role hierarchy from AuthContext.hasRole():
   *   role="analyst" allows both analyst AND admin users.
   *   role="admin" allows only admin users.
   */
  role?: UserRole | UserRole[]
}

export function RequireAuth({ children, role }: RequireAuthProps) {
  const { isAuthenticated, isLoading, hasRole } = useAuth()
  const location = useLocation()

  // Still hydrating session from stored tokens — show nothing to prevent
  // a flash redirect to /login that immediately reverses.
  if (isLoading) {
    return <LoadingScreen />
  }

  // Not authenticated → send to login, remembering where they were going.
  // The login page reads location.state.from to redirect back on success.
  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }

  // Authenticated but lacking the required role → 403 page.
  if (role !== undefined && !hasRole(role)) {
    return <Navigate to="/unauthorized" replace />
  }

  return <>{children}</>
}

// ── Loading screen ────────────────────────────────────────────────────────
// Replace this with your actual design system spinner.

function LoadingScreen() {
  return (
    <div
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        height: '100vh',
        fontSize: 14,
        color: 'var(--color-text-secondary, #666)',
      }}
    >
      Loading…
    </div>
  )
}