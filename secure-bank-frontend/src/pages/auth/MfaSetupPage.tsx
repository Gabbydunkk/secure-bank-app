// src/pages/auth/MfaSetupPage.tsx
// Design steals from Stitch:
//   ✓ Amber numbered step circles (1 SCAN · 2 SAVE · 3 CONFIRM) with active/dim states
//   ✓ "MFA IMPLEMENTATION" ALL CAPS label above heading
//   ✓ QR code in its own bordered card, separated from backup codes
//   ✓ Keyboard icon + "MANUAL ENTRY" link below QR
//   ✓ "BACKUP RECOVERY KEYS" + "COPY ALL" as a header row above the grid
//   ✓ Blue info bar at the bottom of backup codes card
//   ✓ Our checkbox safety gate (not in Stitch but kept — good UX)
//   ✓ Our 3-phase state machine (loading → scan → confirm)
//
// Requires: npm install qrcode.react

import { useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { QRCodeSVG } from 'qrcode.react'
import { http } from '../../lib/http'
import { useAuth } from '../../contexts/AuthContext'
import type { MFASetupResponse } from '../../types/api'
import { SecurityBar } from './LoginPage'

// ── Step indicator data ───────────────────────────────────────────────────

const STEPS = [
  { n: 1, key: 'SCAN',    label: 'SCAN',    desc: 'Link your authenticator app by scanning the secure QR signature.' },
  { n: 2, key: 'SAVE',    label: 'SAVE',    desc: 'Secure your emergency recovery keys in a safe offline location.' },
  { n: 3, key: 'CONFIRM', label: 'CONFIRM', desc: 'Validate your device with a time-sensitive authorisation token.' },
]

type Phase = 'loading' | 'error' | 'scan' | 'confirm' | 'activating'

interface ScanState { phase: 'scan'; data: MFASetupResponse; codesConfirmed: boolean }
interface ConfirmState { phase: 'confirm' | 'activating'; data: MFASetupResponse }
interface ErrorState { phase: 'error'; message: string }
interface LoadingState { phase: 'loading' }

type SetupState = LoadingState | ErrorState | ScanState | ConfirmState
const MFA_SETUP_CACHE_KEY = 'mfa_setup_payload_v1'

// Which step number is "active" given the current phase
function activeStep(phase: Phase): number {
  if (phase === 'loading' || phase === 'error') return 1
  if (phase === 'scan') return 1       // still on step 1 until they move to confirm
  if (phase === 'confirm' || phase === 'activating') return 3
  return 1
}

// ── Step circle component ─────────────────────────────────────────────────

function StepCircle({ n, label, desc, active, done }: {
  n: number; label: string; desc: string; active: boolean; done: boolean
}) {
  return (
    <div className="flex gap-4 items-start">
      {/* Amber numbered circle — amber when active/done, dimmed when future */}
      <div
        className={`w-9 h-9 rounded-full flex items-center justify-center shrink-0 mt-0.5
                    border transition-all duration-300
                    ${active || done
                      ? 'bg-amber-500/20 border-amber-500/40'
                      : 'bg-white/5 border-white/10'}`}
      >
        <span className={`text-sm font-bold transition-colors duration-300 ${
          active || done ? 'text-amber-400' : 'text-white/25'
        }`}>
          {n}
        </span>
      </div>

      <div>
        <p className={`text-[10px] font-bold tracking-widest uppercase transition-colors duration-300 ${
          active || done ? 'text-white' : 'text-white/25'
        }`}>
          {label}
        </p>
        <p className={`text-sm mt-0.5 leading-relaxed transition-colors duration-300 ${
          active || done ? 'text-white/50' : 'text-white/15'
        }`}>
          {desc}
        </p>
      </div>
    </div>
  )
}

// ── Main component ────────────────────────────────────────────────────────

export function MfaSetupPage() {
  const navigate = useNavigate()
  const { updateUser } = useAuth()
  const [state, setState] = useState<SetupState>({ phase: 'loading' })
  const [digits, setDigits] = useState<string[]>(Array(6).fill(''))
  const [confirmError, setConfirmError] = useState<string | null>(null)
  const [showManualEntry, setShowManualEntry] = useState(false)
  const [copiedAll, setCopiedAll] = useState(false)
  const inputRefs = useRef<(HTMLInputElement | null)[]>([])

  // Call POST /auth/mfa/setup on mount
  useEffect(() => {
    const cached = sessionStorage.getItem(MFA_SETUP_CACHE_KEY)
    if (cached) {
      try {
        const data = JSON.parse(cached) as MFASetupResponse
        setState({ phase: 'scan', data, codesConfirmed: false })
        return
      } catch {
        sessionStorage.removeItem(MFA_SETUP_CACHE_KEY)
      }
    }

    let cancelled = false
    async function setup() {
      try {
        const { data } = await http.post<MFASetupResponse>('/auth/mfa/setup')
        if (cancelled) return
        sessionStorage.setItem(MFA_SETUP_CACHE_KEY, JSON.stringify(data))
        setState({ phase: 'scan', data, codesConfirmed: false })
      } catch {
        if (cancelled) return
        setState({ phase: 'error', message: 'Failed to initialise MFA setup. Please try again.' })
      }
    }
    setup()
    return () => {
      cancelled = true
    }
  }, [])

  // Auto-focus first digit box when entering confirm phase
  useEffect(() => {
    if (state.phase === 'confirm') {
      setTimeout(() => inputRefs.current[0]?.focus(), 100)
    }
  }, [state.phase])

  // ── OTP input handlers ──────────────────────────────────────────────────

  function handleDigitChange(index: number, value: string) {
    const digit = value.replace(/\D/g, '').slice(-1)
    const next = [...digits]; next[index] = digit; setDigits(next)
    setConfirmError(null)
    if (digit && index < 5) inputRefs.current[index + 1]?.focus()
    if (digit && index === 5 && next.every(d => d !== '')) confirmCode(next.join(''))
  }

  function handleKeyDown(index: number, e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Backspace') {
      if (digits[index]) { const n = [...digits]; n[index] = ''; setDigits(n) }
      else if (index > 0) {
        const n = [...digits]; n[index - 1] = ''; setDigits(n)
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
      confirmCode(pasted)
    }
  }

  // ── Copy all backup codes ───────────────────────────────────────────────

  function copyAll(codes: string[]) {
    navigator.clipboard.writeText(codes.join('\n')).then(() => {
      setCopiedAll(true)
      setTimeout(() => setCopiedAll(false), 2500)
    })
  }

  // ── Confirm code ────────────────────────────────────────────────────────

  async function confirmCode(code: string) {
    const currentData = (state as ConfirmState).data || (state as ScanState).data
    if (!currentData) return
    setState({ phase: 'activating', data: currentData })
    setConfirmError(null)

    try {
      await http.post('/auth/mfa/confirm', { code })
      sessionStorage.removeItem(MFA_SETUP_CACHE_KEY)
      const { data: freshUser } = await http.get('/auth/me')
      updateUser(freshUser)
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setDigits(Array(6).fill(''))
      // Keep the same secret so the previously scanned authenticator entry stays valid.
      // Rotating setup here would invalidate the QR just scanned by the user.
      setState({ phase: 'confirm', data: currentData })
      setTimeout(() => inputRefs.current[0]?.focus(), 100)
      if (typeof err === 'object' && err !== null && 'response' in err) {
        const e = err as { response: { data: { detail?: string } } }
        setConfirmError(e.response?.data?.detail ?? 'Invalid code. Please try again.')
      } else {
        setConfirmError('Invalid code. Please try again.')
      }
    }
  }

  async function handleConfirmSubmit(e: React.FormEvent) {
    e.preventDefault()
    const code = digits.join('')
    if (code.length < 6) { setConfirmError('Please enter all 6 digits.'); return }
    await confirmCode(code)
  }

  const currentPhase = state.phase as Phase
  const step = activeStep(currentPhase)

  // ── Render ───────────────────────────────────────────────────────────────

  return (
    <div className="min-h-screen bg-[#F2F2EF]" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <SecurityBar rightText="MFA Onboarding · AES-256" />

      <div className="min-h-screen flex pt-10">

        {/* ── Left brand panel ───────────────────────────────────────── */}
        <div className="hidden lg:flex lg:w-[44%] bg-[#0A0F0A] flex-col justify-between p-14 relative overflow-hidden">
          <div
            className="absolute inset-0 opacity-20"
            style={{ background: 'radial-gradient(ellipse at 25% 65%, #1a4a25 0%, transparent 55%)' }}
          />

          {/* Logo */}
          <div className="relative z-10 flex items-center gap-3">
            <div className="w-8 h-8 rounded bg-white/8 border border-white/10 flex items-center justify-center">
              <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
                <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
              </svg>
            </div>
            <span className="text-white text-base font-semibold">GabbyBank</span>
            <span className="text-white/20 text-[10px] tracking-widest uppercase border border-white/10 rounded px-1.5 py-0.5">
              Standard Banking
            </span>
          </div>

          {/* Security status badge — from Stitch */}
          <div className="relative z-10 flex items-center gap-1.5 bg-emerald-500/10 border border-emerald-500/20 rounded-full px-3 py-1.5 w-fit mt-6">
            <div className="w-1.5 h-1.5 rounded-full bg-emerald-400" />
            <span className="text-emerald-400 text-[10px] font-bold tracking-widest uppercase">
              Security Status: Protected
            </span>
          </div>

          {/* Headline */}
          <div className="relative z-10 space-y-8">
            <div>
              <h1
                className="text-white text-6xl font-bold leading-tight"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                GabbyBank<br />
                <span className="text-white/30">Standard Banking</span>
              </h1>
            </div>

            <p className="text-white/45 text-base leading-relaxed max-w-sm">
              Our precision security architecture ensures your assets are shielded by industry-leading multi-factor protocols.
            </p>

            {/* Step indicators — amber circles, active/dim states */}
            <div className="space-y-6 pt-2">
              {STEPS.map(({ n, label, desc }) => (
                <StepCircle
                  key={n}
                  n={n}
                  label={label}
                  desc={desc}
                  active={step === n}
                  done={step > n}
                />
              ))}
            </div>
          </div>

          <p className="relative z-10 text-white/15 text-[10px] tracking-widest uppercase">
            © {new Date().getFullYear()} GabbyBank · All rights reserved
          </p>
        </div>

        {/* ── Right content panel ─────────────────────────────────────── */}
        <div className="flex-1 flex items-start justify-center px-8 sm:px-14 bg-[#F2F2EF] overflow-y-auto py-12">
          <div className="w-full max-w-[520px] space-y-5">

            {/* Section label + heading — "MFA IMPLEMENTATION" style from Stitch */}
            <div>
              <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-2">
                MFA Setup
              </p>
              <h2
                className="text-[#0A0F0A] text-3xl"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                {state.phase === 'confirm' || state.phase === 'activating'
                  ? 'Confirm your device'
                  : 'Authenticator Setup'}
              </h2>
            </div>

            {/* ── Loading ─────────────────────────────────────────────── */}
            {state.phase === 'loading' && (
              <div className="bg-white rounded-2xl border border-black/5 p-12 flex flex-col items-center gap-4">
                <svg className="animate-spin w-8 h-8 text-[#1a4a25]" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
                <p className="text-[#888] text-sm">Generating your secure QR signature…</p>
              </div>
            )}

            {/* ── Error ───────────────────────────────────────────────── */}
            {state.phase === 'error' && (
              <div className="bg-white rounded-2xl border border-black/5 p-8 space-y-4">
                <div className="flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-lg">
                  <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center shrink-0">
                    <span className="text-white text-xs font-bold">!</span>
                  </div>
                  <p className="text-red-700 text-sm">{state.message}</p>
                </div>
                <button
                  onClick={() => { setState({ phase: 'loading' }); window.location.reload() }}
                  className="w-full py-3 bg-[#0A0F0A] text-white text-sm font-medium rounded-lg hover:bg-[#1c2a1c] transition-all"
                >
                  Try again
                </button>
              </div>
            )}

            {/* ── Scan phase ──────────────────────────────────────────── */}
            {state.phase === 'scan' && (
              <>
                {/* Card 1: QR code — separate card, as in Stitch */}
                <div className="bg-white rounded-2xl border border-black/5 p-8">

                  {/* QR centred in padded bordered box */}
                  <div className="flex justify-center mb-5">
                    <div className="p-5 bg-white border-2 border-[#E8E8E4] rounded-2xl inline-block shadow-sm">
                      <QRCodeSVG
                        value={state.data.provisioning_uri}
                        size={180}
                        level="H"
                        includeMargin={false}
                      />
                    </div>
                  </div>

                  <p className="text-center text-[#666] text-sm mb-4">
                    Scan using Google Authenticator, Duo, or Okta.
                  </p>

                  {/* "MANUAL ENTRY" with keyboard icon — from Stitch */}
                  <button
                    type="button"
                    onClick={() => setShowManualEntry(v => !v)}
                    className="flex items-center gap-2 mx-auto text-[#555] hover:text-[#0A0F0A] transition-colors group"
                  >
                    <svg className="w-4 h-4 text-[#888] group-hover:text-[#555] transition-colors" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 17V7m0 10a2 2 0 01-2 2H5a2 2 0 01-2-2V7a2 2 0 012-2h2a2 2 0 012 2m0 10a2 2 0 002 2h2a2 2 0 002-2M9 7a2 2 0 012-2h2a2 2 0 012 2m0 10V7m0 10a2 2 0 002 2h2a2 2 0 002-2V7a2 2 0 00-2-2h-2a2 2 0 00-2 2" />
                    </svg>
                    <span className="text-[10px] font-bold tracking-widest uppercase">
                      Manual Entry
                    </span>
                  </button>

                  {showManualEntry && (
                    <div className="mt-4 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg px-4 py-3">
                      <p className="text-[#888] text-[10px] font-bold tracking-widest uppercase mb-1">
                        Secret Key
                      </p>
                      <p className="text-[#0A0F0A] font-mono text-sm tracking-widest break-all select-all">
                        {state.data.secret}
                      </p>
                    </div>
                  )}
                </div>

                {/* Card 2: Backup recovery keys — separate card, as in Stitch */}
                <div className="bg-white rounded-2xl border border-black/5 overflow-hidden">
                  <div className="px-8 pt-7 pb-5">

                    {/* Header row: "BACKUP RECOVERY KEYS" + "COPY ALL" — directly from Stitch */}
                    <div className="flex items-center justify-between mb-4">
                      <p className="text-[#0A0F0A] text-[10px] font-bold tracking-widest uppercase">
                        Backup Recovery Keys
                      </p>
                      <button
                        type="button"
                        onClick={() => copyAll(state.data.backup_codes)}
                        className={`text-[10px] font-bold tracking-widest uppercase transition-colors ${
                          copiedAll ? 'text-emerald-600' : 'text-[#555] hover:text-[#0A0F0A]'
                        }`}
                      >
                        {copiedAll ? '✓ Copied' : 'Copy All'}
                      </button>
                    </div>

                    {/* 2-column backup code grid */}
                    <div className="grid grid-cols-2 gap-2 mb-5">
                      {state.data.backup_codes.map((code, i) => (
                        <div
                          key={i}
                          className="bg-[#F2F2EF] border border-[#E0E0DC] rounded-lg px-4 py-2.5 font-mono text-sm text-center text-[#0A0F0A] tracking-widest"
                        >
                          {code}
                        </div>
                      ))}
                    </div>

                    {/* Checkbox safety gate — our addition, not in Stitch but kept */}
                    <label className="flex items-start gap-3 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={state.codesConfirmed}
                        onChange={e => setState(s =>
                          s.phase === 'scan' ? { ...s, codesConfirmed: e.target.checked } : s
                        )}
                        className="mt-0.5 w-4 h-4 rounded border-[#E0E0DC] accent-[#1a4a25]"
                      />
                      <span className="text-[#666] text-sm">
                        I have saved my backup codes in a secure location
                      </span>
                    </label>
                  </div>

                  {/* Blue info bar — from Stitch */}
                  <div className="flex gap-3 px-6 py-4 bg-blue-50 border-t border-blue-100">
                    <div className="w-5 h-5 rounded-full bg-blue-500 flex items-center justify-center shrink-0 mt-0.5">
                      <svg className="w-3 h-3 text-white" fill="currentColor" viewBox="0 0 24 24">
                        <path fillRule="evenodd" d="M18 10a8 8 0 11-16 0 8 8 0 0116 0zm-7-4a1 1 0 11-2 0 1 1 0 012 0zM9 9a1 1 0 000 2v3a1 1 0 001 1h1a1 1 0 100-2v-3a1 1 0 00-1-1H9z" clipRule="evenodd" />
                      </svg>
                    </div>
                    <p className="text-blue-700 text-sm leading-relaxed">
                      Store these keys in a physically secure location. They are required if you ever lose access to your authenticator app.
                    </p>
                  </div>
                </div>

                {/* Continue button */}
                <button
                  type="button"
                  disabled={!state.codesConfirmed}
                  onClick={() => {
                    if (state.phase === 'scan') {
                      setState({ phase: 'confirm', data: state.data })
                    }
                  }}
                  className="w-full py-3.5 bg-[#0A0F0A] hover:bg-[#1c2a1c] disabled:bg-[#ccc]
                             text-white text-sm font-medium rounded-xl transition-all
                             focus:outline-none focus:ring-2 focus:ring-[#0A0F0A] focus:ring-offset-2"
                >
                  I've scanned the QR code — Continue →
                </button>
              </>
            )}

            {/* ── Confirm phase ────────────────────────────────────────── */}
            {(state.phase === 'confirm' || state.phase === 'activating') && (
              <div className="bg-white rounded-2xl border border-black/5 p-8">

                {/* Shield icon */}
                <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-[#0A0F0A] mx-auto mb-6">
                  <svg className="w-6 h-6 text-amber-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                  </svg>
                </div>

                <p className="text-[#666] text-sm text-center mb-6">
                  Enter the 6-digit code from your authenticator app to activate MFA.
                </p>

                {/* Error */}
                {confirmError && (
                  <div className="mb-5 flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-lg">
                    <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center shrink-0">
                      <span className="text-white text-xs font-bold">!</span>
                    </div>
                    <p className="text-red-700 text-sm">{confirmError}</p>
                  </div>
                )}

                <form onSubmit={handleConfirmSubmit} className="space-y-5">
                  {/* 6-box OTP */}
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
                        disabled={state.phase === 'activating'}
                        className="w-11 h-14 text-center text-xl font-semibold
                                   bg-[#F8F8F5] border-2 border-[#E0E0DC] rounded-xl text-[#0A0F0A]
                                   focus:outline-none focus:border-amber-500 focus:bg-white
                                   disabled:opacity-50 transition-all caret-transparent"
                        aria-label={`Digit ${i + 1}`}
                      />
                    ))}
                  </div>

                  <button
                    type="submit"
                    disabled={state.phase === 'activating' || digits.some(d => !d)}
                    className="w-full py-3.5 bg-[#0A0F0A] hover:bg-[#1c2a1c] disabled:bg-[#ccc]
                               text-white text-sm font-medium rounded-lg
                               transition-all flex items-center justify-center gap-2
                               focus:outline-none focus:ring-2 focus:ring-[#0A0F0A] focus:ring-offset-2"
                  >
                    {state.phase === 'activating' ? (
                      <>
                        <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                        </svg>
                        Activating MFA…
                      </>
                    ) : (
                      'Activate MFA & Enter Dashboard →'
                    )}
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      if (state.phase === 'confirm') {
                        setState({ phase: 'scan', data: state.data, codesConfirmed: true })
                        setDigits(Array(6).fill(''))
                        setConfirmError(null)
                      }
                    }}
                    className="w-full text-center text-[#888] hover:text-[#444] text-sm transition-colors"
                  >
                    ← Back to QR code
                  </button>
                </form>
              </div>
            )}

          </div>
        </div>
      </div>

      {/* Bottom status bar */}
      <div className="fixed bottom-0 left-0 right-0 bg-[#0A0F0A] border-t border-white/5 px-8 py-2.5 flex items-center justify-between">
        <p className="text-white/20 text-[10px] tracking-widest uppercase">SecureBank · Institutional Grade</p>
        <div className="flex items-center gap-1.5">
          <svg className="w-3 h-3 text-emerald-500" fill="currentColor" viewBox="0 0 24 24">
            <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
          </svg>
          <span className="text-emerald-500/50 text-[10px] tracking-widest uppercase">End-to-End Encrypted</span>
        </div>
      </div>
    </div>
  )
}
