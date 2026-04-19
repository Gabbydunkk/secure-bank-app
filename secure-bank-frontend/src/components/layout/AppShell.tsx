// src/components/layout/AppShell.tsx
// The authenticated layout wrapper used by every page after login.
// Sidebar nav is role-aware — items with requiredRole only render for
// users whose role satisfies that requirement (via hasRole()).
//
// Sidebar:    dark #0A0F0A, 200px fixed left
// Topbar:     white, shows account chip + user name + role badge
// Content:    everything to the right of the sidebar, below the topbar

import { Link, useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../../contexts/AuthContext'
import type { UserRole } from '../../types/api'

// ── Nav item definition ───────────────────────────────────────────────────

interface NavItem {
  label: string
  href: string
  requiredRole: UserRole | null   // null = visible to everyone
  icon: React.ReactNode
}

// ── SVG icons (inline, no external library needed) ───────────────────────

const Icons = {
  grid: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M4 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2V6zM14 6a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2V6zM4 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2H6a2 2 0 01-2-2v-2zM14 16a2 2 0 012-2h2a2 2 0 012 2v2a2 2 0 01-2 2h-2a2 2 0 01-2-2v-2z" />
    </svg>
  ),
  transactions: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 7h12m0 0l-4-4m4 4l-4 4m0 6H4m0 0l4 4m-4-4l4-4" />
    </svg>
  ),
  shield: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
    </svg>
  ),
  fraud: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
    </svg>
  ),
  analyst: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
    </svg>
  ),
  users: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" />
    </svg>
  ),
  system: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
    </svg>
  ),
  settings: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 6V4m0 2a2 2 0 100 4m0-4a2 2 0 110 4m-6 8a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4m6 6v10m6-2a2 2 0 100-4m0 4a2 2 0 110-4m0 4v2m0-6V4" />
    </svg>
  ),
  support: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8.228 9c.549-1.165 2.03-2 3.772-2 2.21 0 4 1.343 4 3 0 1.4-1.278 2.575-3.006 2.907-.542.104-.994.54-.994 1.093m0 3h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
    </svg>
  ),
  signout: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" />
    </svg>
  ),
  bell: (
    <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
    </svg>
  ),
  plus: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
    </svg>
  ),
  audit: (
    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
    </svg>
  ),
}

// ── Nav config — requiredRole: null = everyone, 'analyst' = analyst+admin, 'admin' = admin only
const NAV_ITEMS: NavItem[] = [
  { label: 'Dashboard',        href: '/dashboard',       requiredRole: null,       icon: Icons.grid },
  { label: 'Transactions',     href: '/transactions',    requiredRole: null,       icon: Icons.transactions },
  { label: 'Security',         href: '/settings',        requiredRole: null,       icon: Icons.shield },
  { label: 'Fraud Workspace',  href: '/analyst/fraud',   requiredRole: 'analyst',  icon: Icons.fraud },
  { label: 'Analyst Tools',    href: '/analyst/tools',   requiredRole: 'analyst',  icon: Icons.analyst },
  { label: 'User Management',  href: '/admin/users',     requiredRole: 'admin',    icon: Icons.users },
  { label: 'System Controls',  href: '/admin/system',    requiredRole: 'admin',    icon: Icons.system },
  { label: 'Settings',         href: '/settings',        requiredRole: null,       icon: Icons.settings },
]

// ── Role badge label ──────────────────────────────────────────────────────

function roleBadge(role: string): string {
  if (role === 'admin')   return 'Lvl 4 Auth'
  if (role === 'analyst') return 'Fraud Ops'
  return 'Member'
}

// ── User initials avatar ──────────────────────────────────────────────────

function initials(firstName: string, lastName: string): string {
  return `${firstName[0] ?? ''}${lastName[0] ?? ''}`.toUpperCase()
}

// ── AppShell ──────────────────────────────────────────────────────────────

interface AppShellProps {
  children: React.ReactNode
  /** Optional topbar title shown in the content area header */
  title?: string
}

export function AppShell({ children }: AppShellProps) {
  const location  = useLocation()
  const navigate  = useNavigate()
  const { user, hasRole, logout } = useAuth()
  const visibleNav = NAV_ITEMS.filter(item =>
    item.requiredRole === null || hasRole(item.requiredRole)
  )

  async function handleSignOut() {
    await logout()
    navigate('/login', { replace: true })
  }

  const userInitials = user
    ? initials(user.first_name, user.last_name)
    : '?'

  return (
    <div className="flex h-screen bg-[#F2F2EF] overflow-hidden" style={{ fontFamily: "'DM Sans', sans-serif" }}>

      {/* ── Sidebar ─────────────────────────────────────────────────── */}
      <aside className="w-[200px] shrink-0 bg-[#0A0F0A] flex flex-col h-full z-30">

        {/* Logo */}
        <div className="px-5 pt-6 pb-5 border-b border-white/5">
          <p
            className="text-white text-base font-semibold leading-tight"
            style={{ fontFamily: "'Playfair Display', serif" }}
          >
            The GabbyBank
          </p>
          <p className="text-white/25 text-[9px] tracking-widest uppercase mt-0.5">
            {user?.role === 'admin' ? 'Precision Finance' : user?.role === 'analyst' ? 'Fraud Operations' : 'Personal Finance'}
          </p>
        </div>

        {/* Nav items */}
        <nav className="flex-1 px-3 py-4 space-y-0.5 overflow-y-auto">
          {visibleNav.map(item => {
            const active = location.pathname === item.href ||
              (item.href !== '/dashboard' && location.pathname.startsWith(item.href))
            return (
              <Link
                key={item.href + item.label}
                to={item.href}
                className={`flex items-center gap-3 px-3 py-2.5 rounded-lg text-sm transition-all duration-150 group
                  ${active
                    ? 'bg-white/8 text-white border-l-2 border-emerald-500 pl-[10px]'
                    : 'text-white/40 hover:text-white/80 hover:bg-white/5'
                  }`}
              >
                <span className={active ? 'text-emerald-400' : 'text-white/30 group-hover:text-white/60'}>
                  {item.icon}
                </span>
                <span className={`text-xs font-medium tracking-wide ${active ? 'text-white' : ''}`}>
                  {item.label}
                </span>
              </Link>
            )
          })}
        </nav>

        {/* Bottom section */}
        <div className="px-3 pb-4 space-y-1 border-t border-white/5 pt-3">
          {/* NEW TRANSACTION — primary CTA */}
          <Link
            to="/transactions/new"
            className="flex items-center justify-center gap-2 w-full py-2.5 px-3
                       bg-white text-[#0A0F0A] text-xs font-semibold rounded-lg
                       hover:bg-white/90 transition-all mb-3"
          >
            {Icons.plus}
            New Transaction
          </Link>

          <button className="flex items-center gap-3 px-3 py-2 w-full rounded-lg text-white/30 hover:text-white/60 hover:bg-white/5 transition-all">
            <span>{Icons.support}</span>
            <span className="text-xs font-medium">Support</span>
          </button>
          <button
            onClick={handleSignOut}
            className="flex items-center gap-3 px-3 py-2 w-full rounded-lg text-white/30 hover:text-red-400 hover:bg-red-500/5 transition-all"
          >
            <span>{Icons.signout}</span>
            <span className="text-xs font-medium">Sign Out</span>
          </button>
        </div>
      </aside>

      {/* ── Main area ────────────────────────────────────────────────── */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">

        {/* ── Topbar ─────────────────────────────────────────────────── */}
        <header className="h-14 bg-white border-b border-black/5 flex items-center px-6 gap-4 shrink-0 z-20">

          {/* Account chip */}
          <div className="flex items-center gap-2 bg-[#F2F2EF] border border-[#E0E0DC] rounded-full px-3 py-1.5 text-xs font-medium text-[#333]">
            <svg className="w-3.5 h-3.5 text-[#888]" fill="currentColor" viewBox="0 0 24 24">
              <path d="M4 4h16a2 2 0 012 2v12a2 2 0 01-2 2H4a2 2 0 01-2-2V6a2 2 0 012-2z" />
            </svg>
            <span className="text-[#555]">
              {user?.role === 'admin' ? 'INSTITUTIONAL' : 'STANDARD SAVINGS'} ···· 8829
            </span>
          </div>

          {/* Tab pills */}
          <div className="flex items-center gap-1">
            {['Portfolio', 'Activity', 'Reports'].map((tab, i) => (
              <button
                key={tab}
                className={`px-3 py-1.5 text-xs font-medium rounded-full transition-all ${
                  i === 0
                    ? 'text-[#0A0F0A] border-b-2 border-[#0A0F0A] rounded-none'
                    : 'text-[#888] hover:text-[#333]'
                }`}
              >
                {tab}
              </button>
            ))}
          </div>

          {/* Spacer */}
          <div className="flex-1" />

          {/* Bell */}
          <button className="relative p-2 text-[#888] hover:text-[#333] transition-colors">
            {Icons.bell}
            {/* Notification dot */}
            <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 rounded-full bg-red-500" />
          </button>

          {/* User info */}
          <div className="flex items-center gap-3">
            <div className="text-right">
              <p className="text-[#0A0F0A] text-xs font-semibold leading-tight">
                {user ? `${user.first_name} ${user.last_name}` : 'Loading…'}
              </p>
              <p className="text-[#888] text-[10px] tracking-wider uppercase">
                {user ? roleBadge(user.role) : ''}
              </p>
            </div>
            <div className="w-9 h-9 rounded-full bg-[#0A0F0A] flex items-center justify-center">
              <span className="text-white text-xs font-bold">{userInitials}</span>
            </div>
          </div>
        </header>

        {/* ── Page content ───────────────────────────────────────────── */}
        <main className="flex-1 overflow-y-auto">
          {children}
        </main>
      </div>
    </div>
  )
}
