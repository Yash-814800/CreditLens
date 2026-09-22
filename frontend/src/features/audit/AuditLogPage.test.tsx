import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { AuditLogPage } from './AuditLogPage'

const listResponse = {
  items: [
    {
      id: 1,
      ts: '2026-09-21T10:00:00Z',
      event_type: 'DECISION_MADE',
      application_id: 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
      applicant_id: null,
      actor: 'system',
      payload: { outcome: 'APPROVE', score: 91 },
    },
  ],
  total: 1,
  page: 1,
  page_size: 25,
}

function renderPage() {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={queryClient}>
      <AuditLogPage />
    </QueryClientProvider>,
  )
}

describe('AuditLogPage', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({ ok: true, status: 200, json: () => Promise.resolve(listResponse) }),
    )
  })
  afterEach(() => vi.unstubAllGlobals())

  it('renders one row per audit entry with an expandable JSON payload', async () => {
    renderPage()
    const table = await screen.findByTestId('audit-table')
    expect(table).toHaveTextContent('DECISION_MADE')
    expect(table).toHaveTextContent('system')
    expect(screen.queryByText(/"outcome": "APPROVE"/)).not.toBeInTheDocument()

    const user = userEvent.setup()
    const { getByText } = within(table)
    await user.click(getByText('DECISION_MADE'))
    expect(await screen.findByText(/"outcome": "APPROVE"/)).toBeInTheDocument()
  })

  it('calls the verify-chain endpoint and shows the result', async () => {
    renderPage()
    await screen.findByTestId('audit-table')
    vi.mocked(fetch).mockResolvedValueOnce({
      ok: true,
      status: 200,
      json: () => Promise.resolve({ valid: true, first_broken_id: null, checked: 42 }),
    } as Response)

    const user = userEvent.setup()
    await user.click(screen.getByRole('button', { name: /verify chain/i }))

    await waitFor(() => {
      expect(screen.getByRole('status')).toHaveTextContent('Hash chain verified')
    })
  })
})
