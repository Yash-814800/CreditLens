import { ShieldCheck, ShieldAlert, ShieldQuestion, ShieldX } from 'lucide-react'
import type { FraudSeverity } from '../api/types'

const CONFIG: Record<FraudSeverity, { icon: typeof ShieldCheck; className: string }> = {
  NONE: { icon: ShieldCheck, className: 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300' },
  LOW: { icon: ShieldQuestion, className: 'bg-sky-100 text-sky-800 dark:bg-sky-950 dark:text-sky-300' },
  MEDIUM: { icon: ShieldAlert, className: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300' },
  HIGH: { icon: ShieldX, className: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300' },
}

export function SeverityChip({ severity }: { severity: FraudSeverity | string | null }) {
  const cfg = CONFIG[(severity ?? 'NONE') as FraudSeverity] ?? CONFIG.NONE
  const Icon = cfg.icon
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-semibold ${cfg.className}`}
      data-testid="severity-chip"
    >
      <Icon size={12} aria-hidden="true" />
      {severity ?? 'NONE'}
    </span>
  )
}

export function ConfidenceChip({ confidence }: { confidence: number | null | undefined }) {
  if (confidence === null || confidence === undefined) {
    return <span className="text-xs text-slate-400">n/a</span>
  }
  const pct = Math.round(confidence * 100)
  const tone =
    pct >= 80
      ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
      : pct >= 50
        ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
        : 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300'
  return (
    <span className={`inline-block rounded px-1.5 py-0.5 text-xs font-medium ${tone}`}>{pct}%</span>
  )
}
