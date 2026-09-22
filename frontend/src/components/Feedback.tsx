import type { ReactNode } from 'react'
import { Inbox, LoaderCircle } from 'lucide-react'

export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-slate-200 dark:bg-slate-800 ${className}`} />
}

export function LoadingBlock({ label = 'Loading…' }: { label?: string }) {
  return (
    <div className="flex items-center justify-center gap-2 p-8 text-slate-500 dark:text-slate-400">
      <LoaderCircle className="animate-spin" size={18} aria-hidden="true" />
      <span className="text-sm">{label}</span>
    </div>
  )
}

export function EmptyState({ title, hint, icon }: { title: string; hint?: string; icon?: ReactNode }) {
  return (
    <div className="flex flex-col items-center gap-2 p-10 text-center text-slate-500 dark:text-slate-400">
      {icon ?? <Inbox size={28} aria-hidden="true" />}
      <p className="font-medium text-slate-700 dark:text-slate-200">{title}</p>
      {hint && <p className="text-sm">{hint}</p>}
    </div>
  )
}

export function ErrorBlock({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
    >
      {message}
    </div>
  )
}
