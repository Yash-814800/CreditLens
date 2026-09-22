import { CheckCircle2, XCircle } from 'lucide-react'
import type { PrecedentPanel as PrecedentPanelType } from '../../api/types'

const pct = (v: number) => `${(v * 100).toFixed(1)}%`

/** Matched pgvector precedents + the two-signal "agrees / disagrees with
 * scorecard" indicator (Phase 6's policy already computed the agreement;
 * this panel only renders it). */
export function PrecedentPanel({ panel }: { panel: PrecedentPanelType }) {
  return (
    <div className="space-y-3">
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <Stat label="Peer default rate" value={pct(panel.peer_default_rate)} />
        <Stat label="Similarity-weighted" value={pct(panel.peer_default_rate_weighted)} />
        <Stat label="95% CI" value={`${pct(panel.ci_lower)} – ${pct(panel.ci_upper)}`} />
        <Stat label="Sample size" value={String(panel.sample_size)} />
      </div>

      {panel.agrees_with_scorecard !== null && (
        <div
          className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium ${
            panel.agrees_with_scorecard
              ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
              : 'bg-amber-50 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
          }`}
        >
          {panel.agrees_with_scorecard ? (
            <CheckCircle2 size={16} aria-hidden="true" />
          ) : (
            <XCircle size={16} aria-hidden="true" />
          )}
          Precedents {panel.agrees_with_scorecard ? 'agree' : 'disagree'} with the scorecard
        </div>
      )}

      <details>
        <summary className="cursor-pointer text-xs font-medium text-slate-500 dark:text-slate-400">
          {panel.matches.length} matched historical profiles
        </summary>
        <div className="overflow-x-auto mt-2">
          <table className="w-full text-xs">
            <thead className="text-left text-slate-500 dark:text-slate-400">
              <tr>
                <th className="py-1 pr-2">Rank</th>
                <th className="py-1 pr-2">Similarity</th>
                <th className="py-1 pr-2">Cohort</th>
                <th className="py-1">Defaulted</th>
              </tr>
            </thead>
            <tbody>
              {panel.matches.slice(0, 10).map((m) => (
                <tr key={m.historical_id} className="border-t border-slate-100 dark:border-slate-800">
                  <td className="py-1 pr-2">{m.rank}</td>
                  <td className="py-1 pr-2">{pct(m.similarity)}</td>
                  <td className="py-1 pr-2">{m.cohort ?? '—'}</td>
                  <td className="py-1">{m.defaulted ? 'Yes' : 'No'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-slate-50 dark:bg-slate-800/60 px-2 py-1.5">
      <div className="text-slate-500 dark:text-slate-400">{label}</div>
      <div className="font-semibold text-slate-800 dark:text-slate-200">{value}</div>
    </div>
  )
}
