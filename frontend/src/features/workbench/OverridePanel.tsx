import { useState } from 'react'
import { useMutation, useQueryClient } from '@tanstack/react-query'
import { PenSquare } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import { useAuth } from '../../auth/AuthContext'
import { OutcomeBadge } from '../../components/OutcomeBadge'
import type { ApplicationDetail, Outcome } from '../../api/types'

const OUTCOMES: Outcome[] = ['APPROVE', 'REFER', 'DECLINE']

/** Underwriter override: confirm the system outcome, or override it with a
 * mandatory reason (CLAUDE.md: human-in-the-loop override, mandatory reason,
 * written to the audit log). Shows system vs. final outcome once one is
 * recorded. Read-only (no form) for auditor role, matching the backend's own
 * `_write_roles` gate. */
export function OverridePanel({ application }: { application: ApplicationDetail }) {
  const { role } = useAuth()
  const queryClient = useQueryClient()
  const canOverride = role === 'underwriter' || role === 'admin'
  const [outcome, setOutcome] = useState<Outcome>((application.outcome as Outcome) ?? 'REFER')
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)

  const mutation = useMutation({
    mutationFn: () => api.overrideDecision(application.id, outcome, reason.trim()),
    onSuccess: () => {
      setReason('')
      setError(null)
      queryClient.invalidateQueries({ queryKey: ['application', application.id] })
    },
    onError: (err) => setError(err instanceof ApiError ? err.message : 'Failed to record override.'),
  })

  const alreadyOverridden = application.overridden_by !== null
  const reasonTooShort = reason.trim().length < 5
  const sameAsSystem = outcome === application.outcome

  return (
    <div className="space-y-3">
      <div className="flex items-center gap-4 text-sm">
        <div>
          <div className="text-xs text-slate-500 dark:text-slate-400">System decision</div>
          <OutcomeBadge outcome={application.outcome} size="sm" />
        </div>
        {application.final_outcome && application.final_outcome !== application.outcome && (
          <div>
            <div className="text-xs text-slate-500 dark:text-slate-400">Final (overridden)</div>
            <OutcomeBadge outcome={application.final_outcome} size="sm" />
          </div>
        )}
      </div>

      {alreadyOverridden && (
        <p className="text-xs text-slate-500 dark:text-slate-400 italic">
          Reason on file: "{application.override_reason}"
        </p>
      )}

      {canOverride && (
        <form
          onSubmit={(e) => {
            e.preventDefault()
            if (reasonTooShort) {
              setError('An override reason of at least 5 characters is required.')
              return
            }
            mutation.mutate()
          }}
          className="space-y-2 rounded-md border border-slate-200 dark:border-slate-800 p-3"
        >
          <div className="flex items-center gap-2">
            <label htmlFor="override-outcome" className="text-xs font-medium text-slate-600 dark:text-slate-400">
              Outcome
            </label>
            <select
              id="override-outcome"
              value={outcome}
              onChange={(e) => setOutcome(e.target.value as Outcome)}
              className="input w-auto py-1"
            >
              {OUTCOMES.map((o) => (
                <option key={o} value={o}>
                  {o}
                </option>
              ))}
            </select>
          </div>
          <label htmlFor="override-reason" className="text-xs font-medium text-slate-600 dark:text-slate-400 block">
            Reason {!sameAsSystem && <span className="text-red-600">*</span>}
          </label>
          <textarea
            id="override-reason"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            rows={2}
            className="input"
            placeholder="Required: explain why this decision is being confirmed or overridden"
            required={!sameAsSystem}
          />
          {error && (
            <p role="alert" className="text-xs text-red-600 dark:text-red-400">
              {error}
            </p>
          )}
          <button
            type="submit"
            disabled={mutation.isPending || reasonTooShort}
            className="flex items-center gap-1.5 rounded-md bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 px-3 py-1.5 text-xs font-semibold disabled:opacity-50"
          >
            <PenSquare size={13} aria-hidden="true" />
            {sameAsSystem ? 'Confirm decision' : 'Override decision'}
          </button>
        </form>
      )}
    </div>
  )
}
