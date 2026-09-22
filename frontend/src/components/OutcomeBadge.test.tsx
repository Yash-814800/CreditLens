import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { OutcomeBadge } from './OutcomeBadge'

describe('OutcomeBadge', () => {
  it('pairs a distinct icon with a text label for every outcome, never color alone', () => {
    const { rerender } = render(<OutcomeBadge outcome="APPROVE" />)
    let badge = screen.getByTestId('outcome-badge')
    expect(badge).toHaveTextContent('Approve')
    expect(badge.querySelector('svg')).toBeInTheDocument()

    rerender(<OutcomeBadge outcome="REFER" />)
    badge = screen.getByTestId('outcome-badge')
    expect(badge).toHaveTextContent('Refer for review')
    expect(badge.querySelector('svg')).toBeInTheDocument()

    rerender(<OutcomeBadge outcome="DECLINE" />)
    badge = screen.getByTestId('outcome-badge')
    expect(badge).toHaveTextContent('Decline')
    expect(badge.querySelector('svg')).toBeInTheDocument()
  })

  it('falls back to a Pending state for a null/unknown outcome', () => {
    render(<OutcomeBadge outcome={null} />)
    expect(screen.getByTestId('outcome-badge')).toHaveTextContent('Pending')
  })
})
