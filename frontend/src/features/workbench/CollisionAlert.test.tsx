import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CollisionAlert } from './CollisionAlert'
import type { Finding } from '../../api/types'

const highFinding: Finding = {
  check_name: 'phash_collision',
  severity: 'HIGH',
  penalty_points: 40,
  message: 'This document is a near-duplicate or byte-identical copy of a document already on file for a DIFFERENT applicant.',
  document_id: 'cccccccc-dddd-eeee-ffff-000000000000',
  evidence: {
    other_applicant_id: '11111111-2222-3333-4444-555555555555',
    other_application_id: '66666666-7777-8888-9999-aaaaaaaaaaaa',
    other_document_id: 'bbbbbbbb-cccc-dddd-eeee-ffffffffffff',
    hamming_distance: 2,
    sha256_match: false,
    name_corroborated: true,
    identifier_corroborated: false,
  },
}

describe('CollisionAlert', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ ok: true, blob: () => Promise.resolve(new Blob()) }))
    URL.createObjectURL = vi.fn(() => 'blob:mock-url')
    URL.revokeObjectURL = vi.fn()
  })
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('renders severity, hamming distance, corroboration, and a link to the syndicate graph', async () => {
    render(
      <MemoryRouter>
        <CollisionAlert applicationId="app-1" finding={highFinding} />
      </MemoryRouter>,
    )

    const alert = screen.getByTestId('collision-alert')
    expect(alert).toHaveTextContent('Document reuse detected (high confidence)')
    expect(alert).toHaveTextContent('2 / 256 bits')
    expect(alert).toHaveTextContent('name')
    expect(screen.getByRole('link', { name: /open syndicate graph/i })).toHaveAttribute('href', '/syndicate')

    await waitFor(() => {
      expect(screen.getByAltText('Colliding document from the other applicant')).toBeInTheDocument()
    })
  })

  it('renders the amber, non-alarming style for a MEDIUM uncorroborated match', () => {
    const medium: Finding = { ...highFinding, severity: 'MEDIUM', evidence: { ...highFinding.evidence, name_corroborated: false } }
    render(
      <MemoryRouter>
        <CollisionAlert applicationId="app-1" finding={medium} />
      </MemoryRouter>,
    )
    expect(screen.getByTestId('collision-alert')).toHaveTextContent('Possible document reuse')
  })
})
