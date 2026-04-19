import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { http } from '../../lib/http'
import type { UserResponse } from '../../types/api'
import { SecurityBar } from './LoginPage'
import { useAuth } from '../../contexts/AuthContext'

type RegisterForm = {
  email: string
  username: string
  firstName: string
  lastName: string
  password: string
  dateOfBirth: string
}

function getPasswordStrength(pw: string): { score: number; label: string; colour: string } {
  if (!pw) return { score: 0, label: '', colour: '' }
  let s = 0
  if (pw.length >= 12) s++
  if (/[A-Z]/.test(pw)) s++
  if (/[a-z]/.test(pw)) s++
  if (/[0-9]/.test(pw)) s++
  if (/[!@#$%^&*(),.?":{}|<>]/.test(pw)) s++
  if (s <= 2) return { score: s, label: 'Weak', colour: 'bg-red-400' }
  if (s === 3) return { score: s, label: 'Fair', colour: 'bg-amber-400' }
  if (s === 4) return { score: s, label: 'Robust', colour: 'bg-blue-400' }
  return { score: s, label: 'Robust', colour: 'bg-emerald-500' }
}

export function RegisterPage() {
  const navigate = useNavigate()
  const { login } = useAuth()
  const [form, setForm] = useState<RegisterForm>({
    email: '', username: '', firstName: '', lastName: '', password: '', dateOfBirth: '',
  })
  const [showPassword, setShowPassword] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)
  const strength = getPasswordStrength(form.password)

  function field(key: keyof RegisterForm) {
    return {
      value: form[key],
      onChange: (e: React.ChangeEvent<HTMLInputElement>) =>
        setForm(v => ({ ...v, [key]: e.target.value })),
    }
  }

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      const response = await http.post<UserResponse | { detail: unknown }>(
        '/auth/register',
        {
          email: form.email.trim(),
          username: form.username.trim(),
          first_name: form.firstName.trim(),
          last_name: form.lastName.trim(),
          password: form.password,
          ...(form.dateOfBirth ? { date_of_birth: form.dateOfBirth } : {}),
        },
        { validateStatus: s => s < 500 }
      )

      if (response.status === 201 || response.status === 200) {
        await login({
          email: form.email.trim(),
          password: form.password,
        })
        navigate('/mfa/setup', { replace: true })
        return
      }

      // Fixed: handles both 409 string AND 422 validation array
      const detail = (response.data as { detail?: unknown }).detail
      if (Array.isArray(detail)) {
        const first = (detail as { msg: string }[])[0]
        setError((first?.msg ?? 'Please check your inputs.').replace(/^Value error,\s*/i, ''))
      } else if (typeof detail === 'string') {
        setError(detail)
      } else {
        setError('Unable to establish your account right now. Please try again.')
      }
    } catch {
      setError('Unable to establish your account right now. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  const inputClass = `w-full px-4 py-3 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg text-[#0A0F0A] text-sm placeholder-[#aaa]
    focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/40 focus:border-[#1a4a25] transition-all`

  const labelClass = 'block text-[#333] text-[10px] font-bold tracking-widest uppercase mb-1.5'

  return (
    <div className="min-h-screen bg-[#F2F2EF]" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <SecurityBar rightText="AES-256 Bit Encryption Enabled" />

      <div className="min-h-screen flex pt-10">

        {/* ── Left dark panel ──────────────────────────────────────────── */}
        <div className="hidden lg:flex lg:w-[42%] bg-[#0A0F0A] flex-col justify-between p-14 relative overflow-hidden">
          <div
            className="absolute inset-0"
            style={{ background: 'radial-gradient(ellipse at 20% 80%, #1a3a20 0%, transparent 60%)' }}
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
              <div className="flex items-center gap-1 bg-emerald-500/8 border border-emerald-500/15 rounded-full px-2 py-0.5">
                <div className="w-1 h-1 rounded-full bg-emerald-400" />
                <span className="text-emerald-400 text-[9px] tracking-widest uppercase font-bold">Protected Banking</span>
              </div>
            </div>
          </div>

          {/* Headline */}
          <div className="relative z-10 space-y-8">
            <div>
              <p className="text-white/25 text-[10px] font-bold tracking-widest uppercase mb-4">
                Standard Banking Experience
              </p>
              <h1
                className="text-white text-5xl font-bold leading-[1.05] tracking-tight"
                style={{ fontFamily: "'Playfair Display', serif" }}
              >
                Architectural<br />Precision in<br />Finance.
              </h1>
            </div>

            <p className="text-white/35 text-sm leading-relaxed">
              Join the standard banking experience with GabbyBank.
            </p>

            {/* Stats row — directly from Stitch screen 2 */}
            <div className="flex gap-8">
              {[
                { value: '4.8T', label: 'Assets Verified' },
                { value: '100%', label: 'Uptime Audit' },
              ].map(({ value, label }) => (
                <div key={label}>
                  <p className="text-white text-4xl font-bold tracking-tight">{value}</p>
                  <p className="text-white/25 text-[10px] tracking-widest uppercase mt-1">{label}</p>
                </div>
              ))}
            </div>

            {/* Compliance badges — from Stitch */}
            <div className="flex flex-wrap gap-2">
              {['ISO 27001', 'SOC II Compliant', 'FDIC Insured'].map(badge => (
                <div
                  key={badge}
                  className="flex items-center gap-1.5 bg-white/5 border border-white/8 rounded-full px-3 py-1.5"
                >
                  <svg className="w-3 h-3 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                  </svg>
                  <span className="text-white/40 text-[10px] tracking-wider uppercase font-semibold">{badge}</span>
                </div>
              ))}
            </div>
          </div>

          <p className="relative z-10 text-white/15 text-[10px] tracking-widest uppercase">
            © {new Date().getFullYear()} GabbyBank · Member FDIC · Equal Housing Lender
          </p>
        </div>

        {/* ── Right form panel ─────────────────────────────────────────── */}
        <div className="flex-1 flex items-start justify-center px-8 sm:px-12 bg-[#F2F2EF] py-10 overflow-y-auto">
          <div className="w-full max-w-[520px]">

            {/* Mobile logo */}
            <div className="lg:hidden mb-8 flex items-center gap-2">
              <div className="w-8 h-8 rounded bg-[#0A0F0A] flex items-center justify-center">
                <svg className="w-4 h-4 text-emerald-400" fill="currentColor" viewBox="0 0 24 24">
                  <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                </svg>
              </div>
              <span className="text-[#0A0F0A] font-semibold">GabbyBank</span>
            </div>

            <h2
              className="text-[#0A0F0A] text-3xl mb-1"
              style={{ fontFamily: "'Playfair Display', serif" }}
            >
              Create your account
            </h2>
            <p className="text-[#777] text-sm mb-6">
              Enter your account profile to begin the registration process.
            </p>

            {/* Error */}
            {error && (
              <div className="mb-5 flex gap-3 p-4 bg-red-50 border-l-4 border-red-500 rounded-r-lg">
                <div className="w-5 h-5 rounded-full bg-red-500 flex items-center justify-center shrink-0 mt-0.5">
                  <span className="text-white text-xs font-bold leading-none">!</span>
                </div>
                <div>
                  <p className="text-red-800 text-sm font-semibold">Registration Error</p>
                  <p className="text-red-700 text-xs mt-0.5">{error}</p>
                </div>
              </div>
            )}

            <form onSubmit={onSubmit} className="space-y-4">
              {/* Name row */}
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className={labelClass} htmlFor="firstName">Legal First Name</label>
                  <input id="firstName" type="text" autoComplete="given-name" required placeholder="Baby" {...field('firstName')} className={inputClass} />
                </div>
                <div>
                  <label className={labelClass} htmlFor="lastName">Legal Last Name</label>
                  <input id="lastName" type="text" autoComplete="family-name" required placeholder="Basquiat" {...field('lastName')} className={inputClass} />
                </div>
              </div>

              {/* Email */}
              <div>
                <label className={labelClass} htmlFor="email">Email Address</label>
                <input id="email" type="email" autoComplete="email" required placeholder="name@email.com" {...field('email')} className={inputClass} />
              </div>

              {/* Username */}
              <div>
                <label className={labelClass} htmlFor="username">Username</label>
                <input id="username" type="text" autoComplete="username" required minLength={3} placeholder="babybasquiat" {...field('username')} className={inputClass} />
              </div>

              {/* Date of birth */}
              <div>
                <label className={labelClass} htmlFor="dob">
                  Date of Birth{' '}
                  <span className="text-[#aaa] normal-case font-normal tracking-normal text-xs">(must be 18+)</span>
                </label>
                <input
                  id="dob"
                  type="date"
                  {...field('dateOfBirth')}
                  max={new Date(new Date().setFullYear(new Date().getFullYear() - 18)).toISOString().split('T')[0]}
                  className={inputClass}
                />
              </div>

              {/* Password */}
              <div>
                <label className={labelClass} htmlFor="password">Access Password</label>
                <div className="relative">
                  <input
                    id="password"
                    type={showPassword ? 'text' : 'password'}
                    autoComplete="new-password"
                    required
                    minLength={12}
                    placeholder="Min. 12 characters"
                    {...field('password')}
                    className={`${inputClass} pr-11`}
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

                {/* Strength bar — "Security strength: Robust" style from Stitch */}
                {form.password && (
                  <div className="mt-2 space-y-1">
                    <div className="flex gap-1">
                      {[1, 2, 3, 4, 5].map(i => (
                        <div key={i} className={`h-1 flex-1 rounded-full transition-all duration-300 ${i <= strength.score ? strength.colour : 'bg-[#E0E0DC]'}`} />
                      ))}
                    </div>
                    {strength.label && (
                      <p className={`text-xs font-semibold ${
                        strength.score <= 2 ? 'text-red-500' :
                        strength.score === 3 ? 'text-amber-600' :
                        'text-emerald-600'
                      }`}>
                        Security strength: {strength.label}
                      </p>
                    )}
                  </div>
                )}
              </div>

              {/* Submit — "Establish Account" from Stitch */}
              <button
                type="submit"
                disabled={submitting}
                className="w-full py-3.5 px-4 bg-[#0A0F0A] hover:bg-[#1c2a1c] disabled:bg-[#aaa]
                           text-white text-sm font-medium rounded-lg mt-2
                           transition-all flex items-center justify-center gap-2"
              >
                {submitting ? (
                  <>
                    <svg className="animate-spin w-4 h-4" fill="none" viewBox="0 0 24 24">
                      <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                      <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                    </svg>
                    Establishing Account…
                  </>
                ) : (
                  'Establish Account'
                )}
              </button>

              {/* Terms line — from Stitch */}
              <p className="text-center text-[#aaa] text-xs leading-relaxed">
                By establishing an account, you agree to our{' '}
                <span className="text-[#0A0F0A] font-medium underline underline-offset-2 cursor-pointer">
                  Master Service Agreement
                </span>{' '}
                and{' '}
                <span className="text-[#0A0F0A] font-medium underline underline-offset-2 cursor-pointer">
                  Privacy Protocol
                </span>.
              </p>
            </form>

            {/* Compliance badges — bottom of form, from Stitch */}
            <div className="flex items-center justify-center gap-5 mt-6 pt-5 border-t border-[#E0E0DC]">
              {['ISO 27001', 'SOC II Compliant', 'FDIC Insured'].map(badge => (
                <div key={badge} className="flex items-center gap-1">
                  <svg className="w-3 h-3 text-[#888]" fill="currentColor" viewBox="0 0 24 24">
                    <path d="M12 1L3 5v6c0 5.55 3.84 10.74 9 12 5.16-1.26 9-6.45 9-12V5l-9-4z" />
                  </svg>
                  <span className="text-[#888] text-[10px] tracking-wider uppercase">{badge}</span>
                </div>
              ))}
            </div>

            <p className="mt-4 text-center text-[#888] text-sm">
              Already registered?{' '}
              <Link to="/login" className="text-[#1a4a25] hover:text-emerald-700 font-medium transition-colors">
                Sign in to your account
              </Link>
            </p>

            {/* Footer */}
            <p className="mt-4 text-center text-[#bbb] text-[11px]">
              © {new Date().getFullYear()} GabbyBank Financial Group · Member FDIC · Equal Housing Lender
            </p>
          </div>
        </div>
      </div>
    </div>
  )
}
