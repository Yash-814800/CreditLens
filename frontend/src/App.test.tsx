import { render, screen, waitFor } from '@testing-library/react'
import { afterEach, describe, expect, it, vi } from 'vitest'
import App from './App'

/** Smoke test for the routed cockpit shell (Phase 7 replaced the Phase 0
 * healthz placeholder App.tsx with the real router). Feature-specific
 * behaviour (login flow, workbench panels, etc.) has its own test files next
 * to the component. */
describe('App', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('redirects an unauthenticated visitor to the login page', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByRole('heading', { name: 'CreditLens' })).toBeInTheDocument()
      expect(screen.getByLabelText('Email')).toBeInTheDocument()
    })
  })

  it('always shows the synthetic-data banner', async () => {
    render(<App />)
    await waitFor(() => {
      expect(screen.getByText(/SYNTHETIC DATA: DEMO ONLY/)).toBeInTheDocument()
    })
  })
})
