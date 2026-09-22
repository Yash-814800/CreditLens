import { TrendingUp } from 'lucide-react'
import type { RecourseAction } from '../../api/types'

export function RecourseCard({ recourse }: { recourse: RecourseAction[] }) {
  const actionable = recourse.filter((r) => r.actionable)
  if (actionable.length === 0) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">No recourse path available.</p>
  }
  return (
    <ul className="space-y-2">
      {actionable.map((r, i) => (
        <li
          key={i}
          className="flex items-start gap-2 rounded-md border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-800/40 p-2.5 text-sm"
        >
          <TrendingUp size={16} className="mt-0.5 shrink-0 text-emerald-600 dark:text-emerald-400" aria-hidden="true" />
          <div>
            <p className="text-slate-800 dark:text-slate-200">{r.text}</p>
            <p className="text-xs text-slate-500 dark:text-slate-400 mt-0.5">
              +{r.points_gain} pts → score {r.resulting_score}
              {r.horizon_days ? ` · over ~${Math.round(r.horizon_days / 30)} month(s)` : ''}
            </p>
          </div>
        </li>
      ))}
    </ul>
  )
}
