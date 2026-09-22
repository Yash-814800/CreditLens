import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { ScoreGauge } from './ScoreGauge'

describe('ScoreGauge', () => {
  it('renders score number and upright semicircle track', () => {
    render(<ScoreGauge score={58} label="Score / 100" />)

    expect(screen.getByTestId('score-gauge')).toBeInTheDocument()
    expect(screen.getByText('58')).toBeInTheDocument()
    expect(screen.getByText('Score / 100')).toBeInTheDocument()

    const paths = screen.getByTestId('score-gauge').querySelectorAll('path')
    expect(paths).toHaveLength(2)

    // Both the background track and colored progress track use the upright arc
    const track = paths[0]
    const progress = paths[1]
    expect(track.getAttribute('d')).toBe('M 8 50 A 42 42 0 0 1 92 50')
    expect(progress.getAttribute('d')).toBe('M 8 50 A 42 42 0 0 1 92 50')

    // Radius 42 -> arcLength = 42 * PI ~= 131.947
    const arcLength = 42 * Math.PI
    expect(Number(progress.getAttribute('stroke-dasharray'))).toBeCloseTo(arcLength, 2)

    // Score 58 -> 58% complete -> offset = arcLength * (1 - 0.58)
    const expectedOffset = arcLength * (1 - 0.58)
    expect(Number(progress.getAttribute('stroke-dashoffset'))).toBeCloseTo(expectedOffset, 2)
  })

  it('renders placeholder dash when score is null', () => {
    render(<ScoreGauge score={null} label="Score / 100" />)
    expect(screen.getByText('—')).toBeInTheDocument()
    const paths = screen.getByTestId('score-gauge').querySelectorAll('path')
    expect(paths).toHaveLength(1) // only background track
  })
})

