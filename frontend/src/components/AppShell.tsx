import type { ReactNode } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { LayoutList, Network, ScrollText, BookOpen, LogOut, Plus } from 'lucide-react'
import { useAuth } from '../auth/AuthContext'
import { SyntheticBanner } from './SyntheticBanner'

import { ThemeToggle } from './ThemeToggle'

const navItemClass = ({ isActive }: { isActive: boolean }) =>
  `flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium transition-colors ${
    isActive
      ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
      : 'text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800'
  }`

export function AppShell({ children }: { children: ReactNode }) {
  const { role, email, logout } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="min-h-screen flex flex-col bg-slate-50 dark:bg-slate-950 text-slate-900 dark:text-slate-100">
      <SyntheticBanner />
      <header className="border-b border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        <div className="mx-auto max-w-[1600px] px-4 py-2 flex items-center gap-4 flex-wrap">
          <span className="font-bold text-lg tracking-tight">CreditLens</span>
          <nav className="flex items-center gap-1 flex-wrap" aria-label="Main">
            <NavLink to="/applications" className={navItemClass}>
              <LayoutList size={16} aria-hidden="true" /> Applications
            </NavLink>
            <NavLink to="/applications/new" className={navItemClass}>
              <Plus size={16} aria-hidden="true" /> New application
            </NavLink>
            <NavLink to="/syndicate" className={navItemClass}>
              <Network size={16} aria-hidden="true" /> Syndicate graph
            </NavLink>
            {(role === 'auditor' || role === 'admin') && (
              <NavLink to="/audit" className={navItemClass}>
                <ScrollText size={16} aria-hidden="true" /> Audit log
              </NavLink>
            )}
            <NavLink to="/scorecard" className={navItemClass}>
              <BookOpen size={16} aria-hidden="true" /> How scoring works
            </NavLink>
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            <span className="text-slate-500 dark:text-slate-400 hidden sm:inline">
              {email} · <span className="font-medium">{role}</span>
            </span>
            <ThemeToggle />
            <button
              onClick={() => {
                logout()
                navigate('/login')
              }}
              className="flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-slate-600 hover:bg-slate-100 dark:text-slate-300 dark:hover:bg-slate-800"
            >
              <LogOut size={16} aria-hidden="true" /> Log out
            </button>
          </div>
        </div>
      </header>
      <main className="flex-1 mx-auto w-full max-w-[1600px] p-4">{children}</main>
    </div>
  )
}
