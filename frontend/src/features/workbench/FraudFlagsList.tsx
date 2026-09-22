import { ShieldAlert, ShieldCheck, ShieldQuestion, ShieldX } from 'lucide-react'
import type { Finding, FraudSeverity } from '../../api/types'

const ICONS: Record<FraudSeverity, typeof ShieldCheck> = {
  NONE: ShieldCheck,
  LOW: ShieldQuestion,
  MEDIUM: ShieldAlert,
  HIGH: ShieldX,
}
const TONE: Record<FraudSeverity, string> = {
  NONE: 'text-slate-400',
  LOW: 'text-sky-600 dark:text-sky-400',
  MEDIUM: 'text-amber-600 dark:text-amber-400',
  HIGH: 'text-red-600 dark:text-red-400',
}

export function FraudFlagsList({ findings, trustScore }: { findings: Finding[]; trustScore: number }) {
  if (findings.length === 0) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">No fraud findings recorded.</p>
  }
  return (
    <div className="space-y-2">
      <p className="text-xs text-slate-500 dark:text-slate-400">Document-integrity trust score: {trustScore}/100</p>
      <ul className="space-y-2">
        {findings.map((f, i) => {
          const sev = (f.severity as FraudSeverity) ?? 'NONE'
          const Icon = ICONS[sev] ?? ShieldCheck
          return (
            <li
              key={i}
              className="flex items-start gap-2 rounded-md border border-slate-200 dark:border-slate-800 p-2.5 text-sm"
            >
              <Icon size={16} className={`mt-0.5 shrink-0 ${TONE[sev]}`} aria-hidden="true" />
              <div>
                <p className="font-medium text-slate-800 dark:text-slate-200">
                  {f.check_name.replace(/_/g, ' ')}{' '}
                  <span className="font-normal text-slate-500 dark:text-slate-400">({sev})</span>
                </p>
                <p className="text-slate-600 dark:text-slate-400">{f.message}</p>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
