import { useQuery } from '@tanstack/react-query'
import { api, ApiError } from '../../api/client'
import { LoadingBlock, ErrorBlock } from '../../components/Feedback'

interface Bin {
  upper_bound: number | null
  points: number
  label: string
}
interface Factor {
  label: string
  direction: string
  max_up: number
  max_down: number
  reason_code_on_penalty: string
  bins: Bin[]
}
interface ScorecardConfig {
  version: string
  base: number
  factors: Record<string, Factor>
}
interface PolicyConfig {
  version: string
  score_tiers: { approve_min: number; refer_min: number }
  completeness_gate: { min_data_completeness: number; min_extraction_confidence: number }
}

/** "How this scorecard works" transparency page (Phase 7 spec), rendered
 * directly from GET /meta/scorecard -- the live scorecard_v1.yaml/policy_v1.yaml
 * config, not a hand-written description that could drift from the real
 * thresholds (CLAUDE.md rule 3: no black-box decisioning). */
export function ScorecardPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['scorecard-meta'],
    queryFn: api.getScorecardMeta,
  })

  if (isLoading) return <LoadingBlock label="Loading scorecard configuration…" />
  if (isError || !data) {
    return <ErrorBlock message={error instanceof ApiError ? error.message : 'Failed to load scorecard metadata.'} />
  }

  const scorecard = data.scorecard as unknown as ScorecardConfig
  const policy = data.policy as unknown as PolicyConfig

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <div>
        <h1 className="text-lg font-semibold">How this scorecard works</h1>
        <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
          CreditLens never uses a black-box model to decide. Every application's score is computed by this exact,
          versioned, additive rule table — scorecard {scorecard.version}, policy {policy.version}.
        </p>
      </div>

      <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
        <p className="text-sm">
          <strong>score = clamp(base + sum of each factor's points, 0, 100)</strong>, base ={' '}
          <strong>{scorecard.base}</strong>. A missing factor (its source document wasn't submitted) contributes 0
          points — never a penalty — and instead lowers <em>data completeness</em>.
        </p>
      </section>

      <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
        <h2 className="text-sm font-semibold mb-2">Outcome tiers</h2>
        <ul className="text-sm space-y-1 text-slate-600 dark:text-slate-400">
          <li>
            Score <strong>≥ {policy.score_tiers.approve_min}</strong> → APPROVE
          </li>
          <li>
            Score <strong>{policy.score_tiers.refer_min}–{policy.score_tiers.approve_min - 1}</strong> → REFER
          </li>
          <li>
            Score <strong>&lt; {policy.score_tiers.refer_min}</strong> → DECLINE
          </li>
        </ul>
        <p className="text-xs text-slate-500 dark:text-slate-400 mt-2">
          Hard rules (a HIGH fraud finding, an identity mismatch, an incomplete file, or a suspected prompt-injection
          flag) are evaluated first and can cap or override the tier — see the underwriter workbench's "rules fired"
          trace on any application for exactly which rules applied.
        </p>
      </section>

      <section className="space-y-3">
        <h2 className="text-sm font-semibold">Scoring factors</h2>
        {Object.entries(scorecard.factors).map(([key, factor]) => (
          <details key={key} className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
            <summary className="cursor-pointer font-medium text-sm">
              {factor.label} <span className="text-slate-400 font-normal">(+{factor.max_up} / {factor.max_down} pts)</span>
            </summary>
            <table className="w-full text-xs mt-3">
              <thead className="text-left text-slate-500 dark:text-slate-400">
                <tr>
                  <th className="py-1 pr-2">Band</th>
                  <th className="py-1">Points</th>
                </tr>
              </thead>
              <tbody>
                {factor.bins.map((b, i) => (
                  <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
                    <td className="py-1 pr-2">{b.label}</td>
                    <td className={`py-1 font-semibold ${b.points >= 0 ? 'text-emerald-700 dark:text-emerald-400' : 'text-red-700 dark:text-red-400'}`}>
                      {b.points >= 0 ? '+' : ''}
                      {b.points}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
            <p className="text-xs text-slate-400 mt-2">If declined, cited as reason code {factor.reason_code_on_penalty}.</p>
          </details>
        ))}
      </section>
    </div>
  )
}
