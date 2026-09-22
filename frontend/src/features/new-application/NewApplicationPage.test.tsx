import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { NewApplicationPage } from './NewApplicationPage'

function renderPage() {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  })
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter>
        <NewApplicationPage />
      </MemoryRouter>
    </QueryClientProvider>,
  )
}

async function fillRequiredFields(user: ReturnType<typeof userEvent.setup>) {
  await user.type(screen.getByLabelText(/full name/i), 'Aarav Mehta')
  await user.type(screen.getByLabelText(/^phone/i), '9876543210')
  await user.type(screen.getByLabelText(/^pan/i), 'ABCDE1234F')
  await user.type(screen.getByLabelText(/^aadhaar/i), '123412341234')
  const file = new File(['dummy'], 'bill.pdf', { type: 'application/pdf' })
  await user.upload(screen.getByLabelText(/utility bill/i), file)
}

describe('NewApplicationPage consent gating', () => {
  beforeEach(() => {
    vi.stubGlobal(
      'fetch',
      vi.fn((url: string) => {
        if (typeof url === 'string' && url.includes('/v1/meta/consent')) {
          return Promise.resolve({
            ok: true,
            status: 200,
            json: () =>
              Promise.resolve({
                text: 'Consent terms for testing purposes',
                version: 'v1',
                sha256: 'mock-sha256',
              }),
          } as Response)
        }
        return Promise.resolve({
          ok: true,
          status: 202,
          json: () => Promise.resolve({ id: 'new-app-id' }),
        } as Response)
      }),
    )
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('blocks submission with an explanatory error when consent is not given', async () => {
    renderPage()
    const user = userEvent.setup()
    await fillRequiredFields(user)
    // Wait for consent to load
    await screen.findByText(/Consent terms for testing purposes/)
    // consent checkbox intentionally left unchecked
    await user.click(
      screen.getByRole('button', { name: /submit application/i }),
    )

    expect(await screen.findByText(/accept consent/i)).toBeInTheDocument()
    // Only meta/consent was called, no POST /applications
    expect(fetch).not.toHaveBeenCalledWith(
      '/api/v1/applications',
      expect.anything(),
    )
  })

  it('submits once every required field, a document, and consent are all provided', async () => {
    renderPage()
    const user = userEvent.setup()
    await fillRequiredFields(user)
    await screen.findByText(/Consent terms for testing purposes/)
    await user.click(
      screen.getByRole('checkbox', { name: /consent statement/i }),
    )
    await user.click(
      screen.getByRole('button', { name: /submit application/i }),
    )

    expect(await screen.findByText(/submitting/i)).toBeInTheDocument()
    expect(fetch).toHaveBeenCalledWith(
      '/api/v1/applications',
      expect.objectContaining({ method: 'POST' }),
    )
  })
})
