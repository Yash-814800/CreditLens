import { useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ChevronDown, RefreshCw } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import { OutcomeBadge } from '../../components/OutcomeBadge'
import { SeverityChip } from '../../components/SeverityChip'
import { LoadingBlock, EmptyState, ErrorBlock } from '../../components/Feedback'
import { useAuth } from '../../auth/AuthContext'
import { DemoPersonaMenu } from './DemoPersonaMenu'
import type { ApplicationSummary, Outcome } from '../../api/types'

const STAGE_LABEL: Record<string, string> = {
  UPLOADED: 'Uploaded',
  EXTRACTING: 'Extracting documents',
  FRAUD_CHECK: 'Checking document integrity',
  SANITIZING: 'Applying guardrails',
  SCORING: 'Scoring',
  PRECEDENT_MATCH: 'Matching precedents',
  DECIDING: 'Deciding',
  SUMMARIZING: 'Summarizing',
  COMPLETE: 'Complete',
  FAILED: 'Failed',
}

const inr = new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 })

export function ApplicationsQueuePage() {
  const { role } = useAuth()
  const navigate = useNavigate()
  const [outcomeFilter, setOutcomeFilter] = useState<Outcome | 'ALL'>('ALL')
  const { data, isLoading, isError, error, refetch, isFetching } = useQuery({
    queryKey: ['applications'],
    queryFn: () => api.listApplications(1, 50),
    refetchInterval: 5000,
  })

  const items = data?.items.filter((a) => outcomeFilter === 'ALL' || a.outcome === outcomeFilter) ?? []

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-lg font-semibold">Applications queue</h1>
        <div className="flex items-center gap-2">
          <FilterSelect value={outcomeFilter} onChange={setOutcomeFilter} />
          <button
            onClick={() => refetch()}
            className="flex items-center gap-1.5 rounded-md border border-slate-300 dark:border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
          >
            <RefreshCw size={14} className={isFetching ? 'animate-spin' : ''} aria-hidden="true" />
            Refresh
          </button>
          {(role === 'underwriter' || role === 'admin') && <DemoPersonaMenu />}
          <Link
            to="/applications/new"
            className="rounded-md bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 px-3 py-1.5 text-sm font-semibold hover:opacity-90"
          >
            New application
          </Link>
        </div>
      </div>

      {isLoading && <LoadingBlock label="Loading applications…" />}
      {isError && <ErrorBlock message={error instanceof ApiError ? error.message : 'Failed to load applications.'} />}
      {!isLoading && !isError && items.length === 0 && (
        <EmptyState title="No applications yet" hint="Submit a new application or load a demo persona to get started." />
      )}

      {!isLoading && items.length > 0 && (
        <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
          <table className="w-full text-sm">
            <thead className="bg-slate-50 dark:bg-slate-800/60 text-left text-xs uppercase tracking-wide text-slate-500 dark:text-slate-400">
              <tr>
                <th className="px-4 py-2.5">Applicant</th>
                <th className="px-4 py-2.5">Requested</th>
                <th className="px-4 py-2.5">Eligible</th>
                <th className="px-4 py-2.5">Outcome</th>
                <th className="px-4 py-2.5">Score</th>
                <th className="px-4 py-2.5">Fraud</th>
                <th className="px-4 py-2.5">Stage</th>
                <th className="px-4 py-2.5">Submitted</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
              {items.map((a: ApplicationSummary) => (
                <tr
                  key={a.id}
                  className="hover:bg-slate-50 dark:hover:bg-slate-800/40 cursor-pointer"
                  onClick={() => navigate(`/applications/${a.id}`)}
                >
                  <td className="px-4 py-2.5">
                    <Link
                      to={`/applications/${a.id}`}
                      className="font-medium text-slate-900 dark:text-slate-100 hover:underline"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {a.applicant_reference}
                    </Link>
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{inr.format(a.requested_line_inr)}</td>
                  <td className="px-4 py-2.5 tabular-nums">
                    {a.eligible_line_inr != null ? inr.format(a.eligible_line_inr) : '—'}
                  </td>
                  <td className="px-4 py-2.5">
                    <OutcomeBadge outcome={a.final_outcome ?? a.outcome} size="sm" />
                  </td>
                  <td className="px-4 py-2.5 tabular-nums">{a.score ?? '—'}</td>
                  <td className="px-4 py-2.5">
                    <SeverityChip severity={a.fraud_severity} />
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                    {STAGE_LABEL[a.stage] ?? a.stage}
                  </td>
                  <td className="px-4 py-2.5 text-slate-500 dark:text-slate-400">
                    {new Date(a.created_at).toLocaleString()}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

function FilterSelect({
  value,
  onChange,
}: {
  value: Outcome | 'ALL'
  onChange: (v: Outcome | 'ALL') => void
}) {
  return (
    <div className="relative">
      <select
        value={value}
        onChange={(e) => onChange(e.target.value as Outcome | 'ALL')}
        aria-label="Filter by outcome"
        className="appearance-none rounded-md border border-slate-300 dark:border-slate-700 dark:bg-slate-800 pl-3 pr-8 py-1.5 text-sm"
      >
        <option value="ALL">All outcomes</option>
        <option value="APPROVE">Approve</option>
        <option value="REFER">Refer</option>
        <option value="DECLINE">Decline</option>
      </select>
      <ChevronDown size={14} className="pointer-events-none absolute right-2 top-1/2 -translate-y-1/2 text-slate-400" />
    </div>
  )
}
