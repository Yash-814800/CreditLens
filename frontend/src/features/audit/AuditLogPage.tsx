import { Fragment, useState } from 'react'
import { useMutation, useQuery } from '@tanstack/react-query'
import { ChevronDown, ChevronRight, ShieldCheck, ShieldX } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import { LoadingBlock, ErrorBlock, EmptyState } from '../../components/Feedback'

const EVENT_TYPES = [
  'APPLICATION_SUBMITTED',
  'DOCUMENT_EXTRACTED',
  'FRAUD_CHECKED',
  'GUARDRAIL_APPLIED',
  'SCORED',
  'PRECEDENTS_MATCHED',
  'DECISION_MADE',
  'SUMMARY_GENERATED',
  'NOTICE_GENERATED',
  'DECISION_OVERRIDDEN',
  'LOGIN',
]

const PAGE_SIZE = 25

/** Auditor/admin-only audit log view (RBAC-gated at the route level in
 * App.tsx): filterable, paginated, expandable-JSON table + the hash-chain
 * "Verify chain" action (Phase 1/6's audit service). */
export function AuditLogPage() {
  const [eventType, setEventType] = useState('')
  const [page, setPage] = useState(1)
  const [expanded, setExpanded] = useState<number | null>(null)

  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['audit-log', page, eventType],
    queryFn: () => api.listAuditLog(page, PAGE_SIZE, eventType ? { event_type: eventType } : undefined),
  })

  const verify = useMutation({ mutationFn: api.verifyAuditChain })

  const totalPages = data ? Math.max(1, Math.ceil(data.total / PAGE_SIZE)) : 1

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-lg font-semibold">Audit log</h1>
        <div className="flex items-center gap-2">
          <select
            value={eventType}
            onChange={(e) => {
              setEventType(e.target.value)
              setPage(1)
            }}
            aria-label="Filter by event type"
            className="input w-auto"
          >
            <option value="">All event types</option>
            {EVENT_TYPES.map((t) => (
              <option key={t} value={t}>
                {t}
              </option>
            ))}
          </select>
          <button
            onClick={() => verify.mutate()}
            disabled={verify.isPending}
            className="flex items-center gap-1.5 rounded-md border border-slate-300 dark:border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800 disabled:opacity-60"
          >
            <ShieldCheck size={14} aria-hidden="true" />
            {verify.isPending ? 'Verifying…' : 'Verify chain'}
          </button>
        </div>
      </div>

      {verify.data && (
        <div
          role="status"
          className={`flex items-center gap-2 rounded-md px-3 py-2 text-sm font-medium ${
            verify.data.valid
              ? 'bg-emerald-50 text-emerald-800 dark:bg-emerald-950 dark:text-emerald-300'
              : 'bg-red-50 text-red-800 dark:bg-red-950 dark:text-red-300'
          }`}
        >
          {verify.data.valid ? <ShieldCheck size={16} /> : <ShieldX size={16} />}
          {verify.data.valid
            ? 'Hash chain verified — no tampering detected.'
            : `Chain broken at row ${verify.data.first_broken_id ?? '?'}.`}
        </div>
      )}

      {isLoading && <LoadingBlock label="Loading audit log…" />}
      {isError && <ErrorBlock message={error instanceof ApiError ? error.message : 'Failed to load the audit log.'} />}
      {data && data.items.length === 0 && <EmptyState title="No audit events match this filter" />}

      {data && data.items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
          <table className="w-full text-sm" data-testid="audit-table">
            <thead className="bg-slate-50 dark:bg-slate-800/60 text-left text-xs uppercase text-slate-500 dark:text-slate-400">
              <tr>
                <th className="px-3 py-2 w-6"></th>
                <th className="px-3 py-2">Timestamp</th>
                <th className="px-3 py-2">Event</th>
                <th className="px-3 py-2">Application / Applicant</th>
                <th className="px-3 py-2">Actor</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {data.items.map((entry) => (
                <Fragment key={entry.id}>
                  <tr
                    className="cursor-pointer hover:bg-slate-50 dark:hover:bg-slate-800/40"
                    onClick={() => setExpanded(expanded === entry.id ? null : entry.id)}
                  >
                    <td className="px-3 py-2 text-slate-400">
                      {expanded === entry.id ? <ChevronDown size={14} /> : <ChevronRight size={14} />}
                    </td>
                    <td className="px-3 py-2 text-slate-500 dark:text-slate-400">
                      {new Date(entry.ts).toLocaleString()}
                    </td>
                    <td className="px-3 py-2 font-medium">{entry.event_type}</td>
                    <td className="px-3 py-2 font-mono text-xs text-slate-500">
                      {(entry.application_id ?? entry.applicant_id ?? '—').toString().slice(0, 8)}
                    </td>
                    <td className="px-3 py-2">{entry.actor}</td>
                  </tr>
                  {expanded === entry.id && (
                    <tr>
                      <td colSpan={5} className="px-3 pb-3">
                        <pre className="rounded bg-slate-50 dark:bg-slate-950 border border-slate-200 dark:border-slate-800 p-3 text-xs overflow-x-auto">
                          {JSON.stringify(entry.payload, null, 2)}
                        </pre>
                      </td>
                    </tr>
                  )}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {data && totalPages > 1 && (
        <div className="flex items-center justify-center gap-3 text-sm">
          <button
            onClick={() => setPage((p) => Math.max(1, p - 1))}
            disabled={page <= 1}
            className="rounded border border-slate-300 dark:border-slate-700 px-2 py-1 disabled:opacity-40"
          >
            Previous
          </button>
          <span className="text-slate-500 dark:text-slate-400">
            Page {page} of {totalPages}
          </span>
          <button
            onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            disabled={page >= totalPages}
            className="rounded border border-slate-300 dark:border-slate-700 px-2 py-1 disabled:opacity-40"
          >
            Next
          </button>
        </div>
      )}
    </div>
  )
}
