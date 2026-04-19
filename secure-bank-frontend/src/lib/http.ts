// src/lib/http.ts
// Central HTTP client. Every API call in the app goes through this instance.
// Never call fetch() or axios.create() directly from components or service files.
//
// What this handles automatically:
//   1. Attaches Authorization: Bearer <token> to every request
//   2. Attaches X-Device-Fingerprint header (fraud scoring)
//   3. On 401: silently refreshes tokens and retries the original request
//   4. If refresh fails: clears tokens and dispatches auth:logout event
//   5. If multiple requests 401 simultaneously: only one refresh call is made
//      (mutex pattern) — all other requests queue and retry with the new token

import axios, {
    type AxiosInstance,
    type AxiosError,
    type InternalAxiosRequestConfig,
  } from 'axios'
  import { tokenStore } from './token'
  import { getDeviceFingerprint } from './fingerprint'
  import { getLocationContext } from './location'
  
  const BASE_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1'
  
  // ── Refresh mutex ─────────────────────────────────────────────────────────
  // Prevents a burst of 401 responses (e.g. from parallel page-load requests)
  // from triggering multiple simultaneous refresh calls.
  //
  // Pattern:
  //   First 401 → sets isRefreshing=true, starts refresh, queues subscribers
  //   Subsequent 401s → immediately join the queue
  //   On refresh success → all queued requests get the new token and retry
  //   On refresh failure → all queued requests reject; logout dispatched
  
  let isRefreshing = false
  let refreshQueue: Array<{
    resolve: (token: string) => void
    reject: (err: unknown) => void
  }> = []
  
  function enqueueRefreshSubscriber(): Promise<string> {
    return new Promise((resolve, reject) => {
      refreshQueue.push({ resolve, reject })
    })
  }
  
  function resolveRefreshQueue(newToken: string): void {
    refreshQueue.forEach(({ resolve }) => resolve(newToken))
    refreshQueue = []
  }
  
  function rejectRefreshQueue(err: unknown): void {
    refreshQueue.forEach(({ reject }) => reject(err))
    refreshQueue = []
  }
  
  // ── Axios instance ────────────────────────────────────────────────────────
  
  export const http: AxiosInstance = axios.create({
    baseURL: BASE_URL,
    headers: { 'Content-Type': 'application/json' },
  })
  
  // ── Request interceptor ───────────────────────────────────────────────────
  
  http.interceptors.request.use(async (config: InternalAxiosRequestConfig) => {
    // Attach access token if present
    const token = tokenStore.getAccessToken()
    if (token) {
      config.headers.Authorization = `Bearer ${token}`
    }
  
    // Attach device fingerprint — fraud engine reads this on every request.
    // getDeviceFingerprint() is async but cached after the first call.
    try {
      const fp = await getDeviceFingerprint()
      config.headers['X-Device-Fingerprint'] = fp
    } catch {
      // Fingerprint failure is non-fatal — request still proceeds
    }
  
    // Attach coarse location context used by backend fraud scoring.
    // No GPS prompt: derived from browser locale/timezone.
    try {
      const location = await getLocationContext()
      if (location.country) config.headers['X-Location-Country'] = location.country
      if (location.city) config.headers['X-Location-City'] = location.city
    } catch {
      // Location resolution failure is non-fatal - request still proceeds
    }

    return config
  })
  
  // ── Response interceptor ──────────────────────────────────────────────────
  
  // Extend the config type to track retry state
  type RetryConfig = InternalAxiosRequestConfig & { _retry?: boolean }
  
  http.interceptors.response.use(
    response => response,
    async (error: AxiosError) => {
      const config = error.config as RetryConfig | undefined
  
      // Only intercept 401s on requests that have a config (i.e. not network errors)
      // and haven't already been retried. Skip the refresh endpoint itself to avoid
      // an infinite loop if the refresh token is also invalid.
      const isTokenExpired = error.response?.status === 401
      const canRetry = config && !config._retry
      const isRefreshCall = config?.url?.includes('/auth/refresh')
      const isLoginCall = config?.url?.includes('/auth/login')
  
      if (!isTokenExpired || !canRetry || isRefreshCall || isLoginCall) {
        return Promise.reject(error)
      }
  
      if (isRefreshing) {
        // Another request already kicked off a refresh.
        // Wait for it to complete, then retry this request with the new token.
        try {
          const newToken = await enqueueRefreshSubscriber()
          config.headers.Authorization = `Bearer ${newToken}`
          return http(config)
        } catch {
          return Promise.reject(error)
        }
      }
  
      // This request is the first to 401 — take ownership of the refresh.
      config._retry = true
      isRefreshing = true
  
      try {
        const refreshToken = tokenStore.getRefreshToken()
        if (!refreshToken) throw new Error('No refresh token available')
  
        // POST /auth/refresh returns a new Token pair
        const { data } = await axios.post<{
          access_token: string
          refresh_token: string
        }>(`${BASE_URL}/auth/refresh`, {
          refresh_token: refreshToken,
        })
  
        tokenStore.setTokens(data.access_token, data.refresh_token)
        resolveRefreshQueue(data.access_token)
  
        // Retry the original request with the new token
        config.headers.Authorization = `Bearer ${data.access_token}`
        return http(config)
      } catch (refreshError) {
        // Refresh failed — session is truly dead.
        rejectRefreshQueue(refreshError)
        tokenStore.clearTokens()
        // Signal AuthContext to clear state and redirect to login.
        // Using a CustomEvent decouples http.ts from React — no circular imports.
        window.dispatchEvent(new CustomEvent('auth:session-expired'))
        return Promise.reject(error)
      } finally {
        isRefreshing = false
      }
    }
  )
