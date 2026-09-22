import { describe, expect, it } from 'vitest'
import { parseCsvStatement } from './csvParser'

describe('parseCsvStatement', () => {
  it('parses bank statement CSV with key-value metadata and transactions table', () => {
    const csv = `
account_holder,Aarav Mehta
account_number_masked,XXXXXXXX4137
bank,Demo Sahakari Bank
period_from,2026-03-18
period_to,2026-09-14

date,narration,ref,debit,credit,balance
2026-03-18,ATM CASH WDL,671069,94.35,,9405.65
2026-03-20,UPI/ZIPRIDEPARTNER PAYOUT/671071,671071,,5687.51,14931.95
`
    const parsed = parseCsvStatement(csv)
    expect(parsed.metadata).toHaveLength(5)
    expect(parsed.metadata[0]).toEqual({ key: 'Account Holder', value: 'Aarav Mehta' })
    expect(parsed.headers).toEqual(['date', 'narration', 'ref', 'debit', 'credit', 'balance'])
    expect(parsed.rows).toHaveLength(2)
    expect(parsed.rows[0]).toEqual(['2026-03-18', 'ATM CASH WDL', '671069', '94.35', '', '9405.65'])
    expect(parsed.rows[1]).toEqual(['2026-03-20', 'UPI/ZIPRIDEPARTNER PAYOUT/671071', '671071', '', '5687.51', '14931.95'])
  })

  it('handles standard flat CSV with table headers on line 1', () => {
    const csv = `Date,Description,Amount\n2026-01-01,Payment,100.00`
    const parsed = parseCsvStatement(csv)
    expect(parsed.headers).toEqual(['Date', 'Description', 'Amount'])
    expect(parsed.rows).toHaveLength(1)
    expect(parsed.rows[0]).toEqual(['2026-01-01', 'Payment', '100.00'])
  })
})
