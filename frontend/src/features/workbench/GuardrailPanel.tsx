import { ShieldOff } from 'lucide-react'
import type { SanitizationReport } from '../../api/types'

/** Responsible-AI guardrail panel: exactly which fields the allowlist
 * sanitizer removed before scoring (CLAUDE.md rule 7 -- protected attributes
 * never reach the scorer), rendered verbatim from the backend's own report. */
export function GuardrailPanel({ report }: { report: SanitizationReport }) {
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500 dark:text-slate-400">
        {report.allowed.length} feature(s) reached the scorer. {report.removed.length} field(s) were stripped before
        scoring:
      </p>
      <ul className="space-y-1.5">
        {report.removed.map((r, i) => (
          <li key={i} className="flex items-start gap-2 text-xs text-slate-600 dark:text-slate-400">
            <ShieldOff size={13} className="mt-0.5 shrink-0 text-slate-400" aria-hidden="true" />
            <span>
              <strong className="font-medium text-slate-700 dark:text-slate-300">{r.field}</strong> — {r.reason}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}
