import { OutcomeBadge } from '../../components/OutcomeBadge'
import { SeverityChip } from '../../components/SeverityChip'
import { ScoreGauge } from './ScoreGauge'
import { CreditLineCard } from './CreditLineCard'
import { FactorBreakdownChart } from './FactorBreakdownChart'
import { FraudFlagsList } from './FraudFlagsList'
import { PrecedentPanel } from './PrecedentPanel'
import { RecourseCard } from './RecourseCard'
import { ExplainabilityPanel } from './ExplainabilityPanel'
import { GuardrailPanel } from './GuardrailPanel'
import { OverridePanel } from './OverridePanel'
import type { ApplicationDetail } from '../../api/types'

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4">
      <h3 className="text-sm font-semibold text-slate-700 dark:text-slate-300 mb-3">{title}</h3>
      {children}
    </section>
  )
}

/** RIGHT panel of the workbench (Phase 7 spec): every decision-facing signal
 * an underwriter needs, in the order the spec lists them. */
export function DecisionConsole({ application }: { application: ApplicationDetail }) {
  return (
    <div className="space-y-4">
      <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 flex flex-wrap items-center gap-4">
        <OutcomeBadge outcome={application.final_outcome ?? application.outcome} size="lg" />
        <ScoreGauge score={application.score} label="Score / 100" />
        {application.fraud_report && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-slate-500 dark:text-slate-400">Fraud severity</span>
            <SeverityChip severity={application.fraud_severity} />
          </div>
        )}
        <span className="text-xs text-slate-500 dark:text-slate-400 ml-auto">
          Data completeness: {Math.round((application.data_completeness ?? 0) * 100)}%
        </span>
      </section>

      <CreditLineCard application={application} />

      {application.score_breakdown && (
        <Section title="Weighted factor breakdown">
          <FactorBreakdownChart breakdown={application.score_breakdown} />
        </Section>
      )}

      {application.fraud_report && (
        <Section title="Fraud & document-integrity flags">
          <FraudFlagsList findings={application.fraud_report.findings} trustScore={application.fraud_report.trust_score} />
        </Section>
      )}

      {application.precedents && (
        <Section title="Historical precedents (pgvector)">
          <PrecedentPanel panel={application.precedents} />
        </Section>
      )}

      {application.recourse.length > 0 && (
        <Section title="Counterfactual recourse">
          <RecourseCard recourse={application.recourse} />
        </Section>
      )}

      {application.decision && (
        <Section title="Explainability & adverse action">
          <ExplainabilityPanel decision={application.decision} summary={application.summary} notice={application.notice} />
        </Section>
      )}

      {application.sanitization_report && (
        <Section title="Responsible-AI guardrail">
          <GuardrailPanel report={application.sanitization_report} />
        </Section>
      )}

      <Section title="Underwriter decision">
        <OverridePanel application={application} />
      </Section>
    </div>
  )
}
