import { BadgeCheck, FileText, Printer } from 'lucide-react'
import type { AdverseActionNotice, Decision, SummaryResult } from '../../api/types'

/** Explainable-AI & adverse-action panel: reason codes, the grounded LLM
 * summary with its grounding-verified badge (Phase 6's grounding verifier
 * result surfaced, not re-derived here), and a printable notice. */
export function ExplainabilityPanel({
  decision,
  summary,
  notice,
}: {
  decision: Decision
  summary: SummaryResult | null
  notice: AdverseActionNotice | null
}) {
  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 mb-1.5">
          Principal reason codes
        </h4>
        <div className="flex flex-wrap gap-1.5">
          {decision.reason_codes.map((code) => (
            <span
              key={code}
              className="rounded-full bg-slate-100 dark:bg-slate-800 px-2 py-0.5 text-xs font-mono text-slate-700 dark:text-slate-300"
            >
              {code}
            </span>
          ))}
        </div>
      </div>

      {summary && (
        <div>
          <div className="flex items-center gap-2 mb-1.5">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
              Underwriter summary
            </h4>
            <span
              data-testid="grounding-badge"
              className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${
                summary.verified
                  ? 'bg-emerald-100 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
                  : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
              }`}
            >
              <BadgeCheck size={12} aria-hidden="true" />
              {summary.verified ? 'Grounding verified ✓' : 'Not verified'}
            </span>
            <span className="text-xs text-slate-400">
              {summary.source === 'llm' ? summary.model : 'template fallback'} · {summary.prompt_version}
            </span>
          </div>
          <p className="text-sm text-slate-700 dark:text-slate-300 leading-relaxed">{summary.text}</p>
        </div>
      )}

      {notice && (
        <div className="print:block">
          <div className="flex items-center justify-between mb-1.5">
            <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400 flex items-center gap-1.5">
              <FileText size={14} aria-hidden="true" /> Adverse action notice
            </h4>
            <button
              onClick={() => window.print()}
              className="flex items-center gap-1.5 rounded border border-slate-300 dark:border-slate-700 px-2 py-1 text-xs hover:bg-slate-100 dark:hover:bg-slate-800 print:hidden"
            >
              <Printer size={12} aria-hidden="true" /> Print / Save as PDF
            </button>
          </div>
          <div className="rounded-md border border-slate-200 dark:border-slate-800 p-3 text-xs space-y-2 bg-white dark:bg-slate-950">
            <p>
              <strong>Decision:</strong> {notice.decision} · {notice.applicant_reference} ·{' '}
              {new Date(notice.generated_at).toLocaleDateString()}
            </p>
            <p>{notice.basis_statement}</p>
            {notice.what_you_can_do && notice.what_you_can_do.length > 0 && (
              <div>
                <strong>What you can do:</strong>
                <ul className="list-disc pl-5">
                  {notice.what_you_can_do.map((line, i) => (
                    <li key={i}>{line}</li>
                  ))}
                </ul>
              </div>
            )}
            <p className="text-slate-500 dark:text-slate-400">{notice.appeal_contact_placeholder}</p>
            <p className="text-slate-500 dark:text-slate-400 italic">{notice.non_discrimination_statement}</p>
          </div>
        </div>
      )}
    </div>
  )
}
