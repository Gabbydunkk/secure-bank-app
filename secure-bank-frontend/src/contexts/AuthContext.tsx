// src/contexts/AuthContext.tsx
// Global authentication state for the entire application.
//
// Responsibilities:
//   - Hydrate session on app startup (GET /auth/me)
//   - Handle the full login flow including the 202 MFA pending path
//   - Expose login(), verifyMfa(), logout() to any component
//   - Provide hasRole() for permission checks (respects role hierarchy)
//   - Listen for auth:session-expired events from the HTTP interceptor
//
// Role hierarchy (mirrors backend _SCOPE_RANK):
//   admin (3) > analyst (2) > user (1)
//   hasRole('analyst') returns true for admin users — admin satisfies all lower roles.

import React, {
    createContext,
    useCallback,
    useContext,
    useEffect,
    useReducer,
  } from 'react'
  import { http } from '../lib/http'
  import { tokenStore } from '../lib/token'
  import type {
    LoginResponse,
    UserResponse,
    UserRole,
  } from '../types/api'
  
  // ── State shape ───────────────────────────────────────────────────────────
  
  interface AuthState {
    user: UserResponse | null
    isAuthenticated: boolean
    /** True while the app is checking for an existing session on startup */
    isLoading: boolean
    /**
     * Set when POST /auth/login returns 202 (MFA required).
     * Cleared after verifyMfa() succeeds or the user logs out.
     */
    mfaPending: {
      mfaToken: string
      email: string
      userId: string
    } | null
    /**
     * True when the fraud engine flagged the login but still allowed it.
     * The UI should show a soft security warning to the user.
     */
    riskFlagged: boolean
  }
  
  const initialState: AuthState = {
    user: null,
    isAuthenticated: false,
    isLoading: true,
    mfaPending: null,
    riskFlagged: false,
  }
  
  // ── Actions ───────────────────────────────────────────────────────────────
  
  type AuthAction =
    | { type: 'HYDRATE_SUCCESS'; payload: UserResponse }
    | { type: 'HYDRATE_FAIL' }
    | { type: 'LOGIN_SUCCESS'; payload: { user: UserResponse; riskFlagged: boolean } }
    | { type: 'MFA_REQUIRED'; payload: { mfaToken: string; email: string; userId: string } }
    | { type: 'MFA_COMPLETE'; payload: { user: UserResponse; riskFlagged: boolean } }
    | { type: 'LOGOUT' }
    | { type: 'UPDATE_USER'; payload: UserResponse }
  
  function authReducer(state: AuthState, action: AuthAction): AuthState {
    switch (action.type) {
      case 'HYDRATE_SUCCESS':
        return { ...state, user: action.payload, isAuthenticated: true, isLoading: false }
  
      case 'HYDRATE_FAIL':
        return { ...state, isLoading: false }
  
      case 'LOGIN_SUCCESS':
        return {
          ...state,
          user: action.payload.user,
          isAuthenticated: true,
          riskFlagged: action.payload.riskFlagged,
          mfaPending: null,
        }
  
      case 'MFA_REQUIRED':
        return { ...state, mfaPending: action.payload }
  
      case 'MFA_COMPLETE':
        return {
          ...state,
          user: action.payload.user,
          isAuthenticated: true,
          riskFlagged: action.payload.riskFlagged,
          mfaPending: null,
        }
  
      case 'LOGOUT':
        return { ...initialState, isLoading: false }
  
      case 'UPDATE_USER':
        return { ...state, user: action.payload }
  
      default:
        return state
    }
  }
  
  // ── Context value ─────────────────────────────────────────────────────────
  
export type LoginResult =
  | 'success'       // full login, tokens issued
  | 'success_flagged' // full login, tokens issued, unusual activity flagged
  | 'mfa_required'  // password correct, MFA code still needed
  | 'blocked'       // fraud engine hard-blocked, or account suspended
    | 'locked'        // account temporarily locked
    | 'invalid'       // wrong password
    | 'error'         // unexpected error
  
export type MfaResult = 'success' | 'wrong_code' | 'expired' | 'rate_limited' | 'error'
  
  interface AuthContextValue extends AuthState {
    login(credentials: {
      email?: string
      username?: string
      password: string
    }): Promise<LoginResult>
    verifyMfa(code: string): Promise<MfaResult>
    logout(): Promise<void>
    updateUser(user: UserResponse): void
    /**
     * Returns true if the current user's role satisfies the required role.
     * Respects hierarchy: admin passes analyst check, analyst passes user check.
     *
     * @example
     *   hasRole('analyst')   // true for analyst AND admin
     *   hasRole('admin')     // true only for admin
     *   hasRole(['analyst', 'admin'])  // equivalent to hasRole('analyst')
     */
    hasRole(role: UserRole | UserRole[]): boolean
  }
  
  const AuthContext = createContext<AuthContextValue | null>(null)
  
  // ── Role hierarchy ────────────────────────────────────────────────────────
  
  const ROLE_RANK: Record<UserRole, number> = {
    user: 1,
    analyst: 2,
    admin: 3,
  }
  
  // ── Provider ──────────────────────────────────────────────────────────────
  
  export function AuthProvider({ children }: { children: React.ReactNode }) {
    const [state, dispatch] = useReducer(authReducer, initialState)
  
    // On app startup: attempt to re-hydrate session from stored tokens.
    // If tokens are absent or the GET /auth/me call fails (e.g. both tokens
    // are expired), we clear state and show the login page.
    useEffect(() => {
      async function hydrate() {
        if (!tokenStore.hasTokens()) {
          dispatch({ type: 'HYDRATE_FAIL' })
          return
        }
        try {
          const { data } = await http.get<UserResponse>('/auth/me')
          dispatch({ type: 'HYDRATE_SUCCESS', payload: data })
        } catch {
          tokenStore.clearTokens()
          dispatch({ type: 'HYDRATE_FAIL' })
        }
      }
      hydrate()
    }, [])
  
    // Listen for forced logout dispatched by the HTTP interceptor when
    // both the access token AND refresh token are invalid.
    useEffect(() => {
      function handleSessionExpired() {
        dispatch({ type: 'LOGOUT' })
        // Navigation to /login is handled by RequireAuth — no need to call
        // navigate() here, which would create a coupling to React Router.
      }
      window.addEventListener('auth:session-expired', handleSessionExpired)
      return () => window.removeEventListener('auth:session-expired', handleSessionExpired)
    }, [])
  
    const login = useCallback(
      async (credentials: {
        email?: string
        username?: string
        password: string
      }): Promise<LoginResult> => {
        try {
          // validateStatus: handle 4xx ourselves instead of throwing
          const response = await http.post<LoginResponse>(
            '/auth/login',
            credentials,
            { validateStatus: status => status < 500 }
          )
  
          // 202 — password correct, MFA code still required
          if (response.status === 202) {
            const body = response.data
            dispatch({
              type: 'MFA_REQUIRED',
              payload: {
                mfaToken: body.mfa_token!,
                email: body.email,
                userId: body.user_id,
              },
            })
            return 'mfa_required'
          }
  
          // 403 — fraud block or account suspended/locked/closed
          if (response.status === 403) return 'blocked'
  
          // 401 — distinguish locked vs invalid credentials
          if (response.status === 401) {
            const detail: string =
              typeof response.data === 'object' &&
              'detail' in response.data
                ? String((response.data as { detail: string }).detail)
                : ''
            return detail.toLowerCase().includes('locked') ? 'locked' : 'invalid'
          }
  
          // 200 — full success
          const { tokens, risk_flagged } = response.data
          if (!tokens) return 'error'
  
          tokenStore.setTokens(tokens.access_token, tokens.refresh_token)
  
          // Fetch full user profile (includes role — needed for route guards)
          const { data: user } = await http.get<UserResponse>('/auth/me')
          dispatch({ type: 'LOGIN_SUCCESS', payload: { user, riskFlagged: risk_flagged } })
          return risk_flagged ? 'success_flagged' : 'success'
        } catch {
          return 'error'
        }
      },
      []
    )
  
    const verifyMfa = useCallback(
      async (code: string): Promise<MfaResult> => {
        if (!state.mfaPending) return 'error'

        try {
          const response = await http.post<LoginResponse>(
            '/auth/mfa/verify',
            // Note: /auth/mfa/verify is PUBLIC — do NOT add Authorization header.
            // The mfa_token in the body IS the credential.
            // The http interceptor adds Authorization only if tokenStore has a token,
            // which it won't at this point (user hasn't fully logged in yet).
            {
              mfa_token: state.mfaPending.mfaToken,
              code,
            },
            { validateStatus: status => status < 500 }
          )

          const detail =
            typeof response.data === 'object' &&
            response.data !== null &&
            'detail' in response.data
              ? String((response.data as { detail: unknown }).detail)
              : ''

          if (response.status === 429) return 'rate_limited'
          if (response.status === 401) return 'expired'
          if (response.status === 400) {
            // Backend may return 400 for invalid code or account-state issues.
            // If detail suggests token/session expiry, treat as expired UX flow.
            if (detail.toLowerCase().includes('expired') || detail.toLowerCase().includes('session')) {
              return 'expired'
            }
            // If backend indicates an MFA config/decryption issue, don't lie to the user
            // with "wrong code" — treat as unexpected error.
            if (
              detail.toLowerCase().includes('mfa configuration error') ||
              detail.toLowerCase().includes('unable to read') ||
              detail.toLowerCase().includes('decrypt')
            ) {
              return 'error'
            }
            return 'wrong_code'
          }

          const { data } = response
          if (data.tokens == null) {
            // 400 or unexpected shape
            return 'wrong_code'
          }
  
          tokenStore.setTokens(data.tokens.access_token, data.tokens.refresh_token)
          const { data: user } = await http.get<UserResponse>('/auth/me')
          dispatch({
            type: 'MFA_COMPLETE',
            payload: { user, riskFlagged: data.risk_flagged },
          })
          return 'success'
        } catch {
          return 'error'
        }
      },
      [state.mfaPending]
    )
  
    const logout = useCallback(async () => {
      try {
        // Best-effort — if the server is unreachable we still clear local state
        await http.post('/auth/logout')
      } finally {
        tokenStore.clearTokens()
        dispatch({ type: 'LOGOUT' })
      }
    }, [])
  
    const updateUser = useCallback((user: UserResponse) => {
      dispatch({ type: 'UPDATE_USER', payload: user })
    }, [])
  
    const hasRole = useCallback(
      (role: UserRole | UserRole[]): boolean => {
        if (!state.user) return false
        const required = Array.isArray(role) ? role : [role]
        const userRank = ROLE_RANK[state.user.role]
        // User satisfies the check if their rank >= the minimum required rank
        const minRequired = Math.min(...required.map(r => ROLE_RANK[r]))
        return userRank >= minRequired
      },
      [state.user]
    )
  
    return (
      <AuthContext.Provider
        value={{ ...state, login, verifyMfa, logout, updateUser, hasRole }}
      >
        {children}
      </AuthContext.Provider>
    )
  }
  
  // ── Hook ──────────────────────────────────────────────────────────────────
  
  export function useAuth(): AuthContextValue {
    const ctx = useContext(AuthContext)
    if (ctx === null) {
      throw new Error('useAuth must be used inside <AuthProvider>')
    }
    return ctx
  }
