import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { http } from '../../lib/http'
import { SecurityBar } from './LoginPage'

type Step = 'request' | 'reset'

type ForgotAccessResponse = {
  message: string
  reset_token?: string | null
}

export function ForgotAccessPage() {
  const navigate = useNavigate()
  const [step, setStep] = useState<Step>('request')
  const [email, setEmail] = useState('')
  const [resetToken, setResetToken] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [info, setInfo] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function requestReset(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    setInfo(null)
    try {
      const { data } = await http.post<ForgotAccessResponse>(
        '/auth/forgot-access',
        { email },
        { validateStatus: s => s < 500 }
      )
      setInfo(data.message)
      if (data.reset_token) {
        setResetToken(data.reset_token)
        setStep('reset')
      }
    } catch {
      setError('Unable to process request right now. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  async function resetAccess(e: React.FormEvent) {
    e.preventDefault()
    setSubmitting(true)
    setError(null)
    setInfo(null)

    if (newPassword !== confirmPassword) {
      setSubmitting(false)
      setError('Passwords do not match.')
      return
    }

    try {
      const response = await http.post(
        '/auth/reset-access',
        {
          reset_token: resetToken.trim(),
          new_password: newPassword,
        },
        { validateStatus: s => s < 500 }
      )
      if (response.status >= 400) {
        const detail = (response.data as { detail?: unknown }).detail
        setError(typeof detail === 'string' ? detail : 'Reset failed. Check token and password requirements.')
        return
      }
      setInfo('Access password reset successfully. Please log in.')
      setTimeout(() => navigate('/login', { replace: true }), 900)
    } catch {
      setError('Unable to reset access right now. Please try again.')
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <div className="min-h-screen bg-[#F2F2EF]" style={{ fontFamily: "'DM Sans', sans-serif" }}>
      <SecurityBar rightText="Secure Account Recovery" />
      <div className="min-h-screen flex items-center justify-center px-6 pt-10">
        <div className="w-full max-w-[480px] bg-white rounded-2xl shadow-sm border border-black/5 p-8">
          <h2 className="text-[#0A0F0A] text-2xl mb-1" style={{ fontFamily: "'Playfair Display', serif" }}>
            Forgot Access
          </h2>
          <p className="text-[#777] text-sm mb-6">
            {step === 'request'
              ? 'Enter your account email to start access recovery.'
              : 'Enter reset token and choose a new access password.'}
          </p>

          {info && (
            <div className="mb-5 p-3 bg-emerald-50 border border-emerald-200 rounded text-sm text-emerald-700">
              {info}
            </div>
          )}
          {error && (
            <div className="mb-5 p-3 bg-red-50 border border-red-200 rounded text-sm text-red-700">
              {error}
            </div>
          )}

          {step === 'request' ? (
            <form onSubmit={requestReset} className="space-y-4">
              <div className="space-y-1.5">
                <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase">
                  Account Email
                </label>
                <input
                  type="email"
                  value={email}
                  onChange={e => setEmail(e.target.value)}
                  required
                  className="w-full px-4 py-3 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/40"
                />
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full py-3.5 bg-[#0A0F0A] text-white rounded-lg disabled:opacity-60"
              >
                {submitting ? 'Submitting...' : 'Request Reset'}
              </button>
              <button
                type="button"
                onClick={() => setStep('reset')}
                className="w-full py-2 text-[#1a4a25] text-xs font-semibold tracking-wider uppercase"
              >
                I Already Have A Reset Token
              </button>
            </form>
          ) : (
            <form onSubmit={resetAccess} className="space-y-4">
              <div className="space-y-1.5">
                <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase">
                  Reset Token
                </label>
                <textarea
                  value={resetToken}
                  onChange={e => setResetToken(e.target.value)}
                  required
                  rows={3}
                  className="w-full px-4 py-3 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg text-xs font-mono focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/40"
                />
              </div>
              <div className="space-y-1.5">
                <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase">
                  New Password
                </label>
                <input
                  type="password"
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                  required
                  minLength={12}
                  className="w-full px-4 py-3 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/40"
                />
              </div>
              <div className="space-y-1.5">
                <label className="block text-[#333] text-[10px] font-bold tracking-widest uppercase">
                  Confirm New Password
                </label>
                <input
                  type="password"
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                  required
                  minLength={12}
                  className="w-full px-4 py-3 bg-[#F8F8F5] border border-[#E0E0DC] rounded-lg text-sm focus:outline-none focus:ring-2 focus:ring-[#1a4a25]/40"
                />
              </div>
              <button
                type="submit"
                disabled={submitting}
                className="w-full py-3.5 bg-[#0A0F0A] text-white rounded-lg disabled:opacity-60"
              >
                {submitting ? 'Resetting...' : 'Reset Access Password'}
              </button>
              <button
                type="button"
                onClick={() => setStep('request')}
                className="w-full py-2 text-[#1a4a25] text-xs font-semibold tracking-wider uppercase"
              >
                Back To Request Step
              </button>
            </form>
          )}

          <div className="mt-6 text-center">
            <Link to="/login" className="text-xs text-[#666] hover:text-[#0A0F0A]">
              Return to login
            </Link>
          </div>
        </div>
      </div>
    </div>
  )
}

