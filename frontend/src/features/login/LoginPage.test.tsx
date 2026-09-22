import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { AuthProvider } from '../../auth/AuthContext'
import { LoginPage } from './LoginPage'

function renderLogin() {
  return render(
    <MemoryRouter initialEntries={['/login']}>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/applications" element={<div>Applications queue</div>} />
        </Routes>
      </AuthProvider>
    </MemoryRouter>,
  )
}

describe('LoginPage', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('logs in and navigates to the applications queue on success', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: () => Promise.resolve({ access_token: 'tok123', token_type: 'bearer', role: 'underwriter' }),
      }),
    )
    renderLogin()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Email'), 'underwriter@creditlens.demo')
    await user.type(screen.getByLabelText('Password'), 'correct-password')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByText('Applications queue')).toBeInTheDocument()
    })
    expect(sessionStorage.getItem('creditlens_token')).toBe('tok123')
  })

  it('shows an error and stays on the page when login fails', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue({
        ok: false,
        status: 401,
        json: () => Promise.resolve({ detail: 'Invalid email or password.' }),
      }),
    )
    renderLogin()
    const user = userEvent.setup()

    await user.type(screen.getByLabelText('Email'), 'underwriter@creditlens.demo')
    await user.type(screen.getByLabelText('Password'), 'wrong-password')
    await user.click(screen.getByRole('button', { name: /sign in/i }))

    await waitFor(() => {
      expect(screen.getByRole('alert')).toHaveTextContent('Invalid email or password.')
    })
    expect(sessionStorage.getItem('creditlens_token')).toBeNull()
  })
})
