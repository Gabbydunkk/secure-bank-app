import { useState } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { DemoControlPanel } from '../../components/demo/DemoControlPanel'

type LoginForm = {
  emailOrUsername: string
  password: string
}

// ── Shared security status bar — import this in all three auth pages ──────
export function SecurityBar({ rightText }: { rightText?: string }) {
  return (
    <div className="fixed top-0 left-0 right-0 z-50 bg-[#0D1F12] border-b border-[#1a3a20] px-6 py-2.5 flex items-center justify-between">
      <div className="flex items-center gap-2">
        <svg className="w-3.5 h-3.5 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
          <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
        </svg>
        <span className="text-emerald-400 text-[10px] font-semibold tracking-widest uppercase">
          GabbyBank Vault Active
        </span>
        <span className="text-emerald-900 text-[10px] tracking-widest uppercase hidden sm:inline">
          · AES-256 Encryption Enabled
        </span>
      </div>
      {rightText && (
        <span className="text-emerald-900 text-[10px] tracking-widest uppercase hidden md:inline">
          {rightText}
        </span>
      )}
    </div>
  )
}

export function LoginPage() {
  const navigate = useNavigate()
  const location = useLocation()
  const { login } = useAuth()
  const [form, setForm] = useState<LoginForm>({ emailOrUsername: '', password: '' })
  const [error, setError] = useState<string | null>(null)
  const [riskWarning, setRiskWarning] = useState(false)
  const [showPassword, setShowPassword] = useState(false)
  const [submitting, setSubmitting] = useState(false)

  const redirectPath =
    (location.state as { from?: { pathname?: string } } | null)?.from?.pathname ?? '/dashboard'

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setRiskWarning(false)
    setSubmitting(true)
    try {
      const raw = form.emailOrUsername.trim()
      const result = await login({
        email: raw.includes('@') ? raw : undefined,
        username: raw.includes('@') ? undefined : raw,
        password: form.password,
      })

      if (result === 'success') {
        navigate(redirectPath, { replace: true })
        return
      }
      if (result === 'success_flagged') {
        window.alert('We noticed unusual activity. Please review your recent transactions.')
        navigate(redirectPath, { replace: true })
        return
      }
      if (result === 'mfa_required') {
        navigate('/mfa/verify', { replace: true })
        return
      }
      if (result === 'locked') {
        setError('Account temporarily locked after too many failed attempts. Please wait 15 minutes before trying again.')
        return
      }
      if (result === 'blocked') {
        setError('Authentication blocked by security policy. Please contact support if you believe this is an error.')
        return
      }
      if (result === 'invalid') {
        setError('Invalid credentials. Please check your email and access password.')
        return
      }
      setError('Authentication service unavailable. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F2F2EF]" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <SecurityBar rightText="GabbyBank Financial Systems" /> 

      <div className="min-h-screen flex pt-10">

        {/* ── Left brand panel ─────────────────────────────────────────── */}
        <div className="hidden lg:flex lg:w-[55%] bg-[#0A0F0A] flex-col justify-between p-14 relative overflow-hidden">
          <div
            className="absolute inset-0 opacity-25"
            style={{ background: 'radial-gradient(ellipse at 25% 65%, #1a4a25 0%, transparent 55%)' }}
          />

          {/* Logo */}
          <div className="relative z-10 flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-white/8 border border-white/10 flex items-center justify-center">
              <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
              </svg>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-white text-base font-semibold">GabbyBank</span>
              <span className="text-white/20 text-[10px] tracking-widest uppercase border border-white/10 rounded px-1.5 py-0.5">
                Institutional
              </span>
            </div>
          </div>

          {/* Headline */}
          <div className="relative z-10 space-y-8">
            <div className="space-y-4">
              <p className="text-white/30 text-[10px] font-semibold tracking-widest uppercase">
                Precision Security · Multi-Layer Fraud Detection
              </p>
              <h1
                className="text-white text-6xl font-bold leading-[1.05] tracking-tight"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                Banking with<br />Baby Basquiat.
              </h1>
            </div>

            <p className="text-white/40 text-base leading-relaxed max-w-sm">
              Institutional-grade fraud detection and multi-layer security protecting every transaction, every time.
            </p>

            {/* Protocol card */}
            <div className="border border-white/8 rounded-xl p-5 bg-white/[0.025]">
              <div className="flex items-start gap-4 mb-4">
                <div className="w-9 h-9 rounded-lg bg-emerald-500/10 border border-emerald-500/15 flex items-center justify-center shrink-0">
                  <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                  </svg>
                </div>
                <div>
                  <p className="text-white text-[10px] font-bold tracking-widest uppercase mb-0.5">Fraud Detection Protocol</p>
                  <p className="text-white/35 text-sm">Real-time risk scoring on every login and transaction</p>
                </div>
              </div>
              <p className="text-white/25 text-sm italic leading-relaxed border-t border-white/5 pt-4">
                "The architecture is built on the premise of a safe and secure banking experience for all."
              </p>
            </div>

            {/* Stats row */}
            <div className="flex gap-10">
              {[
                { value: '99.9%', label: 'Uptime SLA' },
                { value: 'AES-256', label: 'Encryption' },
                { value: '<50ms', label: 'Fraud check' },
              ].map(({ value, label }) => (
                <div key={label}>
                  <p className="text-white text-2xl font-bold tracking-tight">{value}</p>
                  <p className="text-white/25 text-[10px] tracking-widest uppercase mt-1">{label}</p>
                </div>
              ))}
            </div>
          </div>

          {/* Bottom bar */}
          <div className="relative z-10 flex items-center justify-between">
            <p className="text-white/15 text-[10px] tracking-widest uppercase">
              © {new Date().getFullYear()} GabbyBank. All rights reserved.
            </p>
            <div className="flex items-center gap-1.5 bg-emerald-500/8 border border-emerald-500/15 rounded-full px-3 py-1.5">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-emerald-400 text-[10px] tracking-widest uppercase font-semibold">
                Security Status: Protected
              </span>
            </div>
          </div>
        </div>

        {/* ── Right form panel ─────────────────────────────────────────── */}
        <div className="flex-1 flex items-center justify-center px-8 sm:px-14 bg-[#F2F2EF]">
          <div className="w-full max-w-[420px]">

            {/* Mobile logo */}
            <div className="lg:hidden mb-8 flex items-center gap-2">
              <div className="w-8 h-8 rounded bg-[#0A0F0A] flex items-center justify-center">
                <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                </svg>
              </div>
              <span className="text-[#0A0F0A] font-semibold">GabbyBank</span>
            </div>

            {/* Form card */}
            <div className="bg-white rounded-2xl shadow-sm border border-black/5 p-8">
              <h2
                className="text-[#0A0F0A] text-2xl mb-1"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                GabbyBank Login
              </h2>
              <p className="text-[#777] text-sm mb-6">Enter your credentials to access your account.</p>

              {/* Risk warning */}
              {riskWarning && (
                <div className="mb-5 flex gap-3 p-4 bg-amber-50 border-l-4 border-amber-400 rounded-r-lg">
                  <span className="text-amber-500 shrink-0">⚠</span>
                  <div>
                    <p className="text-amber-800 text-sm font-semibold">Unusual activity detected</p>
                    <p className="text-amber-700 text-xs mt-0.5">
                      This login differs from your usual pattern. Please review your recent account activity.
                    </p>
                  </div>
                </div>
              )}

              {/* Error — red left-border style from Stitch */}
              {error && (
                <div className="mb-5 flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-lg">
                  <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center shrink-0 mt-0.5">
                    <span className="text-white text-xs font-bold leading-none">!</span>
                  </div>
                  <div>
                    <p className="text-red-800 text-sm font-semibold">Authentication Failed</p>
                    <p className="text-red-700 text-xs mt-0.5">{error}</p>
                  </div>
                </div>
              )}

              <form onSubmit={onSubmit} className="space-y-4">

                {/* Email — ALL CAPS label */}
                <div className="space-y-1.5">
                  <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase" htmlFor="identity">
                    Enter Your Email Address
                  </label>
                  <div className="relative">
                    <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[#aaa]">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M3 8l7.89 5.26a2 2 0 002.22 0L21 8M5 19h14a2 2 0 002-2V7a2 2 0 00-2-2H5a2 2 0 00-2 2v10a2 2 0 002 2z" />
                      </svg>
                    </div>
                    <input
                      id="identity"
                      type="text"
                      value={form.emailOrUsername}
                      onChange={e => setForm(v => ({ ...v, emailOrUsername: e.target.value }))}
                      autoComplete="username"
                      autoFocus
                      required
                      placeholder="name@email.com"
                      className="w-full pl-10 pr-4 py-3 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm placeholder-[#aaa]
                                 focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/40 focus:border-[#1a4a25] transition-all"
                    />
                  </div>
                </div>

                {/* Password — ALL CAPS label */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase" htmlFor="password">
                      Access Password
                    </label>
                    <Link
                      to="/forgot-access"
                      className="text-[10px] text-[#1a4a25] hover:text-emerald-700 font-semibold tracking-wider uppercase transition-colors"
                    >
                      Forgot Access?
                    </Link>
                  </div>
                  <div className="relative">
                    <div className="absolute left-3 top-1/2 -translate-y-1/2 text-[#aaa]">
                      <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" />
                      </svg>
                    </div>
                    <input
                      id="password"
                      type={showPassword ? 'text' : 'password'}
                      value={form.password}
                      onChange={e => setForm(v => ({ ...v, password: e.target.value }))}
                      autoComplete="current-password"
                      required
                      placeholder="••••••••••••"
                      className="w-full pl-10 pr-11 py-3 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm placeholder-[#aaa]
                                 focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/40 focus:border-[#1a4a25] transition-all"
                    />
                    <button
                      type="button"
                      onClick={() => setShowPassword(v => !v)}
                      className="absolute right-3 top-1/2 -translate-y-1/2 text-[#aaa] hover:text-[#555] transition-colors"
                    >
                      {showPassword ? (
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M13.875 18.825A10.05 10.05 0 0112 19c-4.478 0-8.268-2.943-9.543-7a9.97 9.97 0 011.563-3.029m5.858.908a3 3 0 114.243 4.243M9.878 9.878l4.242 4.242M9.88 9.88l-3.29-3.29m7.532 7.532l3.29 3.29M3 3l3.59 3.59m0 0A9.953 9.953 0 0112 5c4.478 0 8.268 2.943 9.543 7a10.025 10.025 0 01-4.132 4.411m0 0L21 21" />
                        </svg>
                      ) : (
                        <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M2.458 12C3.732 7.943 7.523 5 12 5c4.478 0 8.268 2.943 9.542 7-1.274 4.057-5.064 7-9.542 7-4.477 0-8.268-2.943-9.542-7z" />
                        </svg>
                      )}
                    </button>
                  </div>
                </div>

                {/* Submit button — "Authenticate Identity" from Stitch */}
                <button
                  type="submit"
                  disabled={submitting}
                  className="w-full py-3.5 px-4 bg-[#0A0F0A] hover:bg-[#1c2a1c] disabled:bg-[#aaa]
                             text-white text-sm font-medium rounded-lg mt-2
                             transition-all flex items-center justify-center gap-2
                             focus:outline-none focus:ring-2 focus:ring-[#0A0F0A] focus:ring-offset-2"
                >
                  {submitting ? (
                    <>
                      <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                        <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                        <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                      </svg>
                      Authenticating…
                    </>
                  ) : (
                    'Authenticate Identity →'
                  )}
                </button>
              </form>

              <p className="mt-5 text-center text-[#aaa] text-xs">
                Forgot administrative access?
              </p>
            </div>

            <p className="mt-4 text-center text-[#888] text-sm">
              New to GabbyBank?{' '}
              <Link to="/register" className="text-[#1a4a25] hover:text-emerald-700 font-medium transition-colors">
                Open an account
              </Link>
            </p>
          </div>
        </div>
      </div>

      {/* Bottom status bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-[#0A0F0A] border-t border-white/5 px-8 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="text-white/25 text-[10px] font-semibold tracking-widest uppercase">GabbyBank</span>
          <span className="text-white/10 mx-1">·</span>
          <span className="text-white/15 text-[10px] tracking-widest uppercase">Institutional Grade</span>
        </div>
        <div className="flex items-center gap-3">
          <div className="flex items-center gap-1.5 bg-emerald-500/8 border border-emerald-500/15 rounded-full px-3 py-1">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span className="text-emerald-400 text-[10px] tracking-widest uppercase font-semibold">Security Status: Protected</span>
          </div>
          <span className="text-white/15 text-[10px]">© {new Date().getFullYear()} GabbyBank</span>
        </div>
      </div>
      <DemoControlPanel compact />
    </div>
  )
}
