import { describe, expect, it } from 'vitest'
import { mapFactorsToChartData } from './FactorBreakdownChart'
import type { ScoreBreakdown } from '../../api/types'

const breakdown: ScoreBreakdown = {
  version: 'v1',
  base: 15,
  total: 63,
  data_completeness: 1,
  factors: [
    {
      name: 'utility_tenure_months',
      value: 12,
      bin_label: '12+ months of established utility history',
      points: 25,
      max_up: 25,
      max_down: -10,
      direction: 'higher_is_better',
      reason_code: 'RC01',
    },
    {
      name: 'weekly_inflow_cv',
      value: 0.9,
      bin_label: 'Extreme cash-inflow variability (CV >= 0.80)',
      points: -30,
      max_up: 15,
      max_down: -30,
      direction: 'lower_is_better',
      reason_code: 'RC03',
    },
  ],
}

describe('mapFactorsToChartData', () => {
  it('prepends a Base row and maps every factor to a labelled +/- points row', () => {
    const rows = mapFactorsToChartData(breakdown)

    expect(rows).toHaveLength(3)
    expect(rows[0]).toEqual({ name: 'Base', points: 15, label: '15 pts: starting base', reasonCode: '' })
    expect(rows[1].name).toBe('Utility Tenure Months')
    expect(rows[1].points).toBe(25)
    expect(rows[1].label).toBe('+25 pts: 12+ months of established utility history')
    expect(rows[1].reasonCode).toBe('RC01')
    expect(rows[2].points).toBe(-30)
    expect(rows[2].label).toBe('-30 pts: Extreme cash-inflow variability (CV >= 0.80)')
  })
})
