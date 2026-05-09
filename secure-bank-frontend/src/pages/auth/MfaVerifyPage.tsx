import { useEffect, useRef, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import { SecurityBar } from './LoginPage'
import { DemoControlPanel } from '../../components/demo/DemoControlPanel'

// MFA_PENDING_EXPIRE_MINUTES is 5 in your backend config — 300 seconds
const SESSION_SECONDS = 300

export function MfaVerifyPage() {
  const navigate = useNavigate()
  const { mfaPending, isAuthenticated, verifyMfa } = useAuth()
  const [digits, setDigits] = useState<string[]>(Array(6).fill(''))
  const [isBackupMode, setIsBackupMode] = useState(false)
  const [backupCode, setBackupCode] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const [secondsLeft, setSecondsLeft] = useState(SESSION_SECONDS)
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])

  // Redirect if no pending MFA session
  useEffect(() => {
    // After successful verification, mfaPending is cleared and the user is authenticated.
    // In that case, do NOT send them back to /login.
    if (mfaPending) return
    if (isAuthenticated) {
      navigate('/dashboard', { replace: true })
      return
    }
    navigate('/login', { replace: true })
  }, [mfaPending, isAuthenticated, navigate])

  // Auto-focus first digit box
  useEffect(() => {
    inputRefs.current[0]?.focus()
  }, [])

  // Countdown timer — matches "CODE EXPIRES IN 0:59" from Stitch
  useEffect(() => {
    if (secondsLeft <= 0) return
    const id = setInterval(() => setSecondsLeft(s => s - 1), 1000)
    return () => clearInterval(id)
  }, [secondsLeft])

  const minutes = Math.floor(secondsLeft / 60)
  const secs = secondsLeft % 60
  const timerLabel = `${minutes}:${secs.toString().padStart(2, '0')}`
  const timerExpired = secondsLeft <= 0

  function handleDigitChange(index: number, value: string) {
    const digit = value.replace(/\D/g, '').slice(-1)
    const next = [...digits]
    next[index] = digit
    setDigits(next)
    setError(null)
    if (digit && index < 5) inputRefs.current[index + 1]?.focus()
    if (digit && index === 5 && next.every(d => d !== '')) submitCode(next.join(''))
  }

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace') {
      if (digits[index]) {
        const next = [...digits]; next[index] = ''; setDigits(next)
      } else if (index > 0) {
        const next = [...digits]; next[index - 1] = ''; setDigits(next)
        inputRefs.current[index - 1]?.focus()
      }
    }
    if (e.key === 'ArrowLeft' && index > 0) inputRefs.current[index - 1]?.focus()
    if (e.key === 'ArrowRight' && index < 5) inputRefs.current[index + 1]?.focus()
  }

  function handlePaste(e: React.ClipboardEvent) {
    e.preventDefault()
    const pasted = e.clipboardData.getData('text').replace(/\D/g, '').slice(0, 6)
    if (pasted.length === 6) {
      setDigits(pasted.split(''))
      inputRefs.current[5]?.focus()
      submitCode(pasted)
    }
  }

  async function submitCode(code: string) {
    setError(null)
    setSubmitting(true)
    try {
      const result = await verifyMfa(code)
      if (result === 'success') { navigate('/dashboard', { replace: true }); return }
      if (result === 'expired') {
        setError('Your verification session has expired. Please sign in again to start a new session.')
        return
      }
      if (result === 'wrong_code') {
        setError('Incorrect code. Please check your authenticator app and try again.')
        setDigits(Array(6).fill(''))
        inputRefs.current[0]?.focus()
        return
      }
      if (result === 'rate_limited') {
        setError('Too many attempts. Please wait 5 minutes, then sign in again.')
        return
      }
      setError('Verification unavailable. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  async function handleDigitSubmit(e: React.FormEvent) {
    e.preventDefault()
    const code = digits.join('')
    if (code.length < 6) { setError('Please enter all 6 digits.'); return }
    await submitCode(code)
  }

  async function handleBackupSubmit(e: React.FormEvent) {
    e.preventDefault()
    await submitCode(backupCode.trim().toUpperCase())
  }

  return (
    <div className="min-h-screen bg-[#F2F2EF]" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <SecurityBar rightText="Encryption: AES-256" />

      <div className="min-h-screen flex pt-10">

        {/* ── Left dark panel ──────────────────────────────────────────── */}
        <div className="hidden lg:flex lg:w-[52%] bg-[#0A0F0A] flex-col justify-between p-14 relative overflow-hidden">
          <div
            className="absolute inset-0 opacity-20"
            style={{ background: 'radial-gradient(ellipse at 20% 70%, #1a4a25 0%, transparent 55%)' }}
          />

          {/* Logo */}
          <div className="relative z-10 flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-white/8 border border-white/10 flex items-center justify-center">
              <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
              </svg>
            </div>
            <span className="text-white text-base font-semibold">GabbyBank</span>
          </div>

          {/* Main content */}
          <div className="relative z-10 space-y-6">
            <div>
              <p className="text-white/30 text-[10px] font-bold tracking-widest uppercase mb-4">
                Identity Verification Protocol V.4.2
              </p>
              <h1
                className="text-white text-6xl font-bold leading-[1.05] tracking-tight"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                Two-Factor<br />Authentication
              </h1>
            </div>

            <p className="text-white/40 text-base leading-relaxed max-w-sm">
              Secure your session. Verify your identity to access your account.
            </p>

            {/* Timer display on left panel */}
            <div className="border border-white/8 rounded-xl p-5 bg-white/[0.025]">
              <p className="text-white/25 text-[10px] font-bold tracking-widest uppercase mb-2">
                Session Window
              </p>
              <p className={`text-4xl font-bold tracking-tight ${timerExpired ? 'text-red-400' : 'text-emerald-400'}`}>
                {timerExpired ? 'EXPIRED' : timerLabel}
              </p>
              <p className="text-white/25 text-sm mt-1">
                {timerExpired
                  ? 'Please return to login and try again.'
                  : 'Time remaining to enter your code'}
              </p>
            </div>

            {/* Protocol version */}
            <div className="flex items-center gap-3 pt-4">
              <div className="h-px flex-1 bg-white/10" />
              <p className="text-white/20 text-[10px] tracking-widest uppercase">
                Identity Verification Protocol V.4.2
              </p>
            </div>
          </div>

          {/* Bottom */}
          <div className="relative z-10 flex items-center justify-between">
            <p className="text-white/15 text-[10px] tracking-widest uppercase">
              © {new Date().getFullYear()} GabbyBank
            </p>
            <div className="flex items-center gap-1.5 bg-emerald-500/8 border border-emerald-500/15 rounded-full px-3 py-1">
              <div className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse" />
              <span className="text-emerald-400 text-[10px] tracking-widest uppercase font-semibold">Security Status: Protected</span>
            </div>
          </div>
        </div>

        {/* ── Right form panel ─────────────────────────────────────────── */}
        <div className="flex-1 flex items-center justify-center px-8 sm:px-14 bg-[#F2F2EF]">
          <div className="w-full max-w-[400px]">

            {/* Security status pill — top right (matches Stitch) */}
            <div className="hidden lg:flex justify-end mb-6">
              <div className="flex items-center gap-1.5 bg-white border border-[#E0E0DC] rounded-full px-3 py-1.5 shadow-sm">
                <div className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                <span className="text-[#333] text-[10px] font-semibold tracking-widest uppercase">
                  Security Status: Protected
                </span>
              </div>
            </div>

            {/* Card */}
            <div className="bg-white rounded-2xl shadow-sm border border-black/5 p-8">
              <h2
                className="text-[#0A0F0A] text-2xl mb-1"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                Verify Your Identity
              </h2>
              <p className="text-[#777] text-sm mb-6">
                Enter the 6-digit code from your authenticator app.
              </p>

              {/* Error */}
              {error && (
                <div className="mb-5 flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-lg">
                  <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center shrink-0">
                    <span className="text-white text-xs font-bold leading-none">!</span>
                  </div>
                  <p className="text-red-700 text-sm">{error}</p>
                </div>
              )}

              {!isBackupMode ? (
                <form onSubmit={handleDigitSubmit} className="space-y-5">
                  {/* 6-box OTP input */}
                  <div className="flex gap-2 justify-center" onPaste={handlePaste}>
                    {digits.map((digit, i) => (
                      <input
                        key={i}
                        ref={el => { inputRefs.current[i] = el }}
                        type="text"
                        inputMode="numeric"
                        maxLength={1}
                        value={digit}
                        onChange={e => handleDigitChange(i, e.target.value)}
                        onKeyDown={e => handleKeyDown(i, e)}
                        disabled={submitting || timerExpired}
                        className="w-11 h-14 text-center text-xl font-semibold
                                   bg-[#F8F8F5] border-2 border-[#E0E0DC] rounded-xl text-[#0A0F0A]
                                   focus:outline-none focus:border-[#1a4a25] focus:bg-white
                                   disabled:opacity-40 transition-all caret-transparent"
                        aria-label={`Digit ${i + 1}`}
                      />
                    ))}
                  </div>

                  {/* Timer + Resend row — directly from Stitch */}
                  <div className="flex items-center justify-between">
                    <div className="flex items-center gap-1.5">
                      <svg className="w-3.5 h-3.5 text-[#aaa]" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                      </svg>
                      <span className={`text-xs font-semibold tracking-wider uppercase ${
                        timerExpired ? 'text-red-500' :
                        secondsLeft < 60 ? 'text-amber-600' : 'text-[#888]'
                      }`}>
                        Code expires in {timerLabel}
                      </span>
                    </div>
                    <button
                      type="button"
                      onClick={() => { setSecondsLeft(SESSION_SECONDS); setDigits(Array(6).fill('')); setError(null) }}
                      className="text-[10px] text-[#1a4a25] hover:text-emerald-700 font-bold tracking-widest uppercase transition-colors"
                    >
                      Resend Code
                    </button>
                  </div>

                  <button
                    type="submit"
                    disabled={submitting || digits.some(d => !d) || timerExpired}
                    className="w-full py-3.5 bg-[#0A0F0A] hover:bg-[#1c2a1c] disabled:bg-[#ccc]
                               text-white text-sm font-medium rounded-lg
                               transition-all flex items-center justify-center gap-2"
                  >
                    {submitting ? (
                      <>
                        <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Verifying…
                      </>
                    ) : (
                      'Verify Identity →'
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => { setIsBackupMode(true); setError(null) }}
                    className="w-full text-center text-[#888] hover:text-[#444] text-sm transition-colors"
                  >
                    Use a backup recovery key
                  </button>
                </form>
              ) : (
                <form onSubmit={handleBackupSubmit} className="space-y-4">
                  <div className="space-y-1.5">
                    <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase">
                      Backup Recovery Key
                    </label>
                    <input
                      type="text"
                      value={backupCode}
                      onChange={e => setBackupCode(e.target.value)}
                      autoFocus
                      required
                      placeholder="XXXX-XXXX"
                      className="w-full px-4 py-3 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg
                                 text-[#0A0F0A] text-sm placeholder-[#aaa] tracking-widest
                                 focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/40 focus:border-[#1a4a25] transition-all"
                    />
                    <p className="text-[#aaa] text-xs">Single-use backup code. Format: XXXX-XXXX</p>
                  </div>

                  <button
                    type="submit"
                    disabled={submitting || !backupCode.trim()}
                    className="w-full py-3.5 bg-[#0A0F0A] hover:bg-[#1c2a1c] disabled:bg-[#ccc]
                               text-white text-sm font-medium rounded-lg transition-all"
                  >
                    {submitting ? 'Verifying…' : 'Verify Recovery Key →'}
                  </button>

                  <button
                    type="button"
                    onClick={() => { setIsBackupMode(false); setError(null) }}
                    className="w-full text-center text-[#888] hover:text-[#444] text-sm transition-colors"
                  >
                    ← Back to authenticator app
                  </button>
                </form>
              )}
            </div>

            {/* Footer links — matches Stitch */}
            <div className="mt-6 flex items-center justify-center gap-6">
              <button className="text-[#888] text-xs hover:text-[#444] tracking-wider uppercase transition-colors">
                Security Center
              </button>
              <button className="text-[#888] text-xs hover:text-[#444] tracking-wider uppercase transition-colors">
                Support
              </button>
              <Link to="/login" className="text-[#1a4a25] text-xs hover:text-emerald-700 tracking-wider uppercase font-semibold transition-colors">
                Back to Login
              </Link>
            </div>
          </div>
        </div>
      </div>

      {/* Bottom bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-[#0A0F0A] border-t border-white/5 px-8 py-2.5 flex items-center justify-between">
        <p className="text-white/20 text-[10px] tracking-widest uppercase">SecureBank · Institutional Grade</p>
        <div className="flex items-center gap-3">
          <svg className="w-3 h-3 text-emerald-500" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
          </svg>
          <span className="text-emerald-500/60 text-[10px] tracking-widest uppercase">End-to-End Encrypted</span>
        </div>
      </div>
      <DemoControlPanel compact />
    </div>
  )
}
