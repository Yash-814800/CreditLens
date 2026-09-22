import { Check, LoaderCircle, CircleX } from 'lucide-react'

const STAGES = [
  ['EXTRACTING', 'Extracting'],
  ['FRAUD_CHECK', 'Fraud check'],
  ['SANITIZING', 'Sanitizing'],
  ['SCORING', 'Scoring'],
  ['PRECEDENT_MATCH', 'Precedents'],
  ['DECIDING', 'Deciding'],
  ['SUMMARIZING', 'Summarizing'],
  ['COMPLETE', 'Complete'],
] as const

export function StageStepper({ stage, errorCode }: { stage: string; errorCode?: string | null }) {
  if (stage === 'FAILED') {
    return (
      <div className="flex items-center gap-2 rounded-lg border border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950 p-4 text-red-800 dark:text-red-300">
        <CircleX size={20} aria-hidden="true" />
        <div>
          <p className="font-semibold">Processing failed</p>
          {errorCode && <p className="text-sm opacity-80">Error code: {errorCode}</p>}
        </div>
      </div>
    )
  }

  const currentIdx = STAGES.findIndex(([key]) => key === stage)

  return (
    <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
      <p className="text-sm font-medium text-slate-700 dark:text-slate-300 mb-4">
        Processing application…
      </p>
      <ol className="flex flex-wrap gap-x-1 gap-y-3">
        {STAGES.map(([key, label], i) => {
          const done = currentIdx > i || stage === 'COMPLETE'
          const active = currentIdx === i && stage !== 'COMPLETE'
          return (
            <li key={key} className="flex items-center gap-1.5">
              <span
                className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold shrink-0 ${
                  done
                    ? 'bg-emerald-600 text-white'
                    : active
                      ? 'bg-slate-900 text-white dark:bg-slate-100 dark:text-slate-900'
                      : 'bg-slate-200 text-slate-500 dark:bg-slate-800 dark:text-slate-400'
                }`}
              >
                {done ? <Check size={13} /> : active ? <LoaderCircle size={13} className="animate-spin" /> : i + 1}
              </span>
              <span className={`text-xs ${active ? 'font-semibold' : 'text-slate-500 dark:text-slate-400'}`}>
                {label}
              </span>
              {i < STAGES.length - 1 && <span className="mx-1 h-px w-4 bg-slate-300 dark:bg-slate-700" />}
            </li>
          )
        })}
      </ol>
    </div>
  )
}
