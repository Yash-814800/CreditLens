import { CircleCheck, CircleX, TriangleAlert, HelpCircle } from 'lucide-react'
import type { Outcome } from '../api/types'

const CONFIG: Record<
  Outcome,
  { label: string; icon: typeof CircleCheck; className: string }
> = {
  APPROVE: {
    label: 'Approve',
    icon: CircleCheck,
    className: 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300',
  },
  REFER: {
    label: 'Refer for review',
    icon: TriangleAlert,
    className: 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300',
  },
  DECLINE: {
    label: 'Decline',
    icon: CircleX,
    className: 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300',
  },
}

/** Never relies on color alone (CLAUDE.md/Phase 7 design rule): every badge
 * pairs a distinct icon with an explicit text label. */
export function OutcomeBadge({ outcome, size = 'md' }: { outcome: Outcome | string | null; size?: 'sm' | 'md' | 'lg' }) {
  const cfg = CONFIG[outcome as Outcome]
  const sizeClass = size === 'lg' ? 'text-base px-3 py-1.5 gap-2' : size === 'sm' ? 'text-xs px-2 py-0.5 gap-1' : 'text-sm px-2.5 py-1 gap-1.5'
  const iconSize = size === 'lg' ? 20 : size === 'sm' ? 12 : 14

  if (!cfg) {
    return (
      <span
        className={`inline-flex items-center rounded-full font-medium bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300 ${sizeClass}`}
        data-testid="outcome-badge"
      >
        <HelpCircle size={iconSize} aria-hidden="true" />
        Pending
      </span>
    )
  }
  const Icon = cfg.icon
  return (
    <span
      className={`inline-flex items-center rounded-full font-semibold ${cfg.className} ${sizeClass}`}
      data-testid="outcome-badge"
      data-outcome={outcome}
    >
      <Icon size={iconSize} aria-hidden="true" />
      {cfg.label}
    </span>
  )
}
