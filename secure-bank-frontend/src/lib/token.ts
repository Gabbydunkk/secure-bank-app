// src/lib/token.ts
// Tokens are stored in module-level variables — in-memory only.
//
// Why not localStorage?
//   Any XSS attack can read localStorage and steal tokens silently.
//   In-memory tokens die when the tab closes and are never accessible
//   to injected scripts. For a banking app this is non-negotiable.
//
// Trade-off:
//   The user is logged out when they close the tab. This is acceptable
//   and expected behaviour for financial applications.
//   On page refresh within the same tab, the http.ts interceptor
//   catches the 401 and attempts a silent refresh using the refresh token.
//   If you want persistence across tabs, store ONLY the refresh token
//   in an httpOnly cookie (requires backend support) — never the access token.

let _accessToken: string | null = null
let _refreshToken: string | null = null

export const tokenStore = {
  getAccessToken(): string | null {
    return _accessToken
  },

  getRefreshToken(): string | null {
    return _refreshToken
  },

  setTokens(accessToken: string, refreshToken: string): void {
    _accessToken = accessToken
    _refreshToken = refreshToken
  },

  clearTokens(): void {
    _accessToken = null
    _refreshToken = null
  },

  hasTokens(): boolean {
    return _accessToken !== null && _refreshToken !== null
  },
}