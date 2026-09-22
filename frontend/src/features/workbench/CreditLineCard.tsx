import type { ApplicationDetail } from '../../api/types'

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

export function CreditLineCard({ application }: { application: ApplicationDetail }) {
  const tier = application.decision?.tier
  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">Credit line</h3>
      <div className="grid grid-cols-2 gap-3 text-sm">
        <div>
          <div className="text-xs text-slate-500 dark:text-slate-400">Requested</div>
          <div className="font-semibold tabular-nums">{inr.format(application.requested_line_inr)}</div>
        </div>
        <div>
          <div className="text-xs text-slate-500 dark:text-slate-400">Eligible</div>
          <div className="font-semibold tabular-nums">
            {application.eligible_line_inr != null ? inr.format(application.eligible_line_inr) : '—'}
          </div>
        </div>
        {tier && (
          <div className="col-span-2">
            <span className="inline-block rounded-full bg-slate-100 dark:bg-slate-800 px-2.5 py-1 text-xs font-medium text-slate-700 dark:text-slate-300">
              Tier: {tier}
            </span>
          </div>
        )}
      </div>
    </div>
  )
}
