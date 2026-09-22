import { useState } from 'react'
import { DocumentViewer } from './DocumentViewer'
import { ExtractedFieldsTable } from './ExtractedFieldsTable'
import { CollisionAlert } from './CollisionAlert'
import type { DocumentSummary, Finding, FraudSeverity } from '../../api/types'

const DOC_LABEL: Record<string, string> = {
  GIG_PAYOUT: 'Gig payout',
  UTILITY_BILL: 'Utility bill',
  BANK_STATEMENT: 'Bank statement',
}

const SEVERITY_RANK: Record<FraudSeverity, number> = { NONE: 0, LOW: 1, MEDIUM: 2, HIGH: 3 }

function worstSeverity(findings: Finding[]): FraudSeverity {
  return findings.reduce<FraudSeverity>(
    (worst, f) => (SEVERITY_RANK[f.severity as FraudSeverity] > SEVERITY_RANK[worst] ? (f.severity as FraudSeverity) : worst),
    'NONE',
  )
}

/** The tab an underwriter should see FIRST is whichever document carries the
 * most severe fraud finding (e.g. a pHash collision) -- not simply
 * `documents[0]`. A real Playwright run of the P05->P06 collision demo found
 * this: P06's HIGH collision finding is attached to its UTILITY_BILL, but
 * `documents` from the API happened to list BANK_STATEMENT first, so the
 * collision alert silently never appeared unless the underwriter manually
 * clicked the right tab. */
function pickDefaultDocumentId(documents: DocumentSummary[], findings: Finding[]): string | undefined {
  let best: DocumentSummary | undefined
  let bestRank = -1
  for (const doc of documents) {
    const rank = SEVERITY_RANK[worstSeverity(findings.filter((f) => f.document_id === doc.id))]
    if (rank > bestRank) {
      best = doc
      bestRank = rank
    }
  }
  return (bestRank > 0 ? best : documents[0])?.id
}

function citedFieldsFor(findings: Finding[], extracted: Record<string, unknown> | null): Set<string> {
  if (!extracted) return new Set()
  const keys = new Set(Object.keys(extracted))
  const cited = new Set<string>()
  for (const f of findings) {
    const ev = (f.evidence ?? {}) as Record<string, unknown>
    for (const v of Object.values(ev)) {
      if (typeof v === 'string' && keys.has(v)) cited.add(v)
    }
    if (typeof ev.field === 'string' && keys.has(ev.field)) cited.add(ev.field)
  }
  return cited
}

/** LEFT panel of the workbench (Phase 7 spec): one tab per uploaded
 * document, each with the viewer + tamper-radar overlay, per-check status
 * chips, a pHash collision alert when relevant, and the extracted-fields
 * table with fraud-cited fields highlighted. */
export function DocumentIntake({
  applicationId,
  documents,
  findings,
}: {
  applicationId: string
  documents: DocumentSummary[]
  findings: Finding[]
}) {
  const [activeId, setActiveId] = useState(() => pickDefaultDocumentId(documents, findings))
  const active = documents.find((d) => d.id === activeId) ?? documents[0]
  if (!active) return <p className="text-sm text-slate-500 dark:text-slate-400">No documents uploaded.</p>

  const docFindings = findings.filter((f) => f.document_id === active.id)
  const byCheck = new Map<string, Finding[]>()
  for (const f of docFindings) {
    byCheck.set(f.check_name, [...(byCheck.get(f.check_name) ?? []), f])
  }
  const collision = docFindings.find(
    (f) => f.check_name === 'phash_collision' && (f.severity === 'HIGH' || f.severity === 'MEDIUM'),
  )

  return (
    <div className="space-y-3">
      <div className="flex gap-1 border-b border-slate-200 dark:border-slate-800" role="tablist">
        {documents.map((d) => (
          <button
            key={d.id}
            role="tab"
            aria-selected={d.id === active.id}
            onClick={() => setActiveId(d.id)}
            className={`px-3 py-2 text-sm font-medium border-b-2 -mb-px ${
              d.id === active.id
                ? 'border-slate-900 dark:border-slate-100 text-slate-900 dark:text-slate-100'
                : 'border-transparent text-slate-500 hover:text-slate-700 dark:hover:text-slate-300'
            }`}
          >
            {DOC_LABEL[d.doc_type] ?? d.doc_type}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap gap-1.5">
        {[...byCheck.entries()].map(([check, fs]) => {
          const sev = worstSeverity(fs)
          const tone =
            sev === 'HIGH'
              ? 'bg-red-100 text-red-800 dark:bg-red-950 dark:text-red-300'
              : sev === 'MEDIUM'
                ? 'bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-300'
                : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-300'
          return (
            <span key={check} className={`rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>
              {check.replace(/_/g, ' ')}: {sev}
            </span>
          )
        })}
      </div>

      {collision && <CollisionAlert applicationId={applicationId} finding={collision} />}

      {/* key={active.id} forces a clean remount per document tab, so DocumentViewer's
          fileUrl/overlayUrl state resets naturally instead of needing a manual reset
          inside its effect (which the set-state-in-effect lint rule correctly flags as
          a cascading-render anti-pattern). */}
      <DocumentViewer key={active.id} applicationId={applicationId} document={active} />

      <ExtractedFieldsTable extracted={active.extracted} citedFields={citedFieldsFor(docFindings, active.extracted)} />
    </div>
  )
}
