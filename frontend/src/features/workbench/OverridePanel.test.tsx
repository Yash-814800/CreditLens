import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../../auth/AuthContext'
import { OverridePanel } from './OverridePanel'
import type { ApplicationDetail } from '../../api/types'

const baseApplication = {
  id: 'app-1',
  applicant_reference: 'APP-0001',
  applicant_name: 'Test Applicant',
  requested_line_inr: 25000,
  eligible_line_inr: 25000,
  status: 'DECIDED',
  stage: 'COMPLETE',
  error_code: null,
  outcome: 'APPROVE',
  final_outcome: null,
  overridden_by: null,
  override_reason: null,
  score: 90,
  fraud_severity: 'LOW',
  data_completeness: 1,
  scorecard_version: 'v1',
  policy_version: 'v1',
  created_at: new Date().toISOString(),
  completed_at: new Date().toISOString(),
  documents: [],
  fraud_report: null,
  sanitization_report: null,
  score_breakdown: null,
  decision: null,
  precedents: null,
  recourse: [],
  summary: null,
  notice: null,
} as unknown as ApplicationDetail

function renderPanel(role: 'underwriter' | 'auditor' = 'underwriter') {
  sessionStorage.setItem('creditlens_role', role)
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <MemoryRouter>
      <QueryClientProvider client={queryClient}>
        <AuthProvider>
          <OverridePanel application={baseApplication} />
        </AuthProvider>
      </QueryClientProvider>
    </MemoryRouter>,
  )
}

describe('OverridePanel', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn())
  })
  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('disables submit until a reason of at least 5 characters is entered', async () => {
    renderPanel('underwriter')
    const user = userEvent.setup()
    const submit = screen.getByRole('button', { name: /confirm decision/i })
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText(/reason/i), 'ok')
    expect(submit).toBeDisabled()

    await user.type(screen.getByLabelText(/reason/i), 'ay this really is a good reason')
    expect(submit).toBeEnabled()
  })

  it('relabels the button and marks the reason required when overriding to a different outcome', async () => {
    renderPanel('underwriter')
    const user = userEvent.setup()
    await user.selectOptions(screen.getByLabelText('Outcome'), 'DECLINE')
    expect(screen.getByRole('button', { name: /override decision/i })).toBeInTheDocument()
    expect(screen.getByLabelText(/reason/i)).toBeRequired()
  })

  it('hides the override form entirely for the auditor role', () => {
    renderPanel('auditor')
    expect(screen.queryByLabelText(/reason/i)).not.toBeInTheDocument()
  })
})
