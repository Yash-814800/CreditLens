import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  LabelList,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import type { ScoreBreakdown, ScoreFactor } from '../../api/types'

export interface FactorChartRow {
  name: string
  points: number
  label: string
  reasonCode: string
}

/** Pure mapping from a ScoreBreakdown to Recharts data -- exported so a unit
 * test can assert on the mapping without rendering an SVG (Phase 7's
 * required "factor chart data mapping" test). A synthetic "Base" row is
 * prepended so the chart reads as base -> each factor's +/- points -> total,
 * matching the spec's "diverging bar ... from base score through each
 * factor" description (a true stacked waterfall would obscure which single
 * factor moved the score the most, which is the more useful underwriter
 * question here). */
export function mapFactorsToChartData(breakdown: ScoreBreakdown): FactorChartRow[] {
  const base: FactorChartRow = {
    name: 'Base',
    points: breakdown.base,
    label: `${breakdown.base} pts: starting base`,
    reasonCode: '',
  }
  const factors: FactorChartRow[] = breakdown.factors.map((f: ScoreFactor) => ({
    name: humanizeFactorName(f.name),
    points: f.points,
    label: `${f.points >= 0 ? '+' : ''}${f.points} pts: ${f.bin_label}`,
    reasonCode: f.reason_code,
  }))
  return [base, ...factors]
}

function humanizeFactorName(name: string): string {
  return name.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

interface CustomLabelProps {
  x?: number
  y?: number
  width?: number
  height?: number
  value?: number
}

function PointsLabel(props: CustomLabelProps) {
  const { x = 0, y = 0, width = 0, height = 0, value } = props
  if (value === undefined || value === null) return null
  const num = Number(value)
  const text = `${num > 0 ? '+' : ''}${num} pts`
  const isNegative = num < 0
  const textX = isNegative ? x - 6 : x + width + 6
  const textAnchor = isNegative ? 'end' : 'start'

  return (
    <text
      x={textX}
      y={y + height / 2 + 4}
      textAnchor={textAnchor}
      fontSize={11}
      fontWeight={600}
      className="fill-slate-700 dark:fill-slate-300"
    >
      {text}
    </text>
  )
}

function CustomTooltip({ active, payload }: { active?: boolean; payload?: Array<{ payload: FactorChartRow }> }) {
  if (!active || !payload || !payload.length) return null
  const row = payload[0].payload
  return (
    <div className="rounded-md border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-2.5 shadow-md text-xs space-y-1">
      <div className="font-semibold text-slate-800 dark:text-slate-200">{row.name}</div>
      <div className="text-slate-600 dark:text-slate-400">{row.label}</div>
      {row.reasonCode && (
        <div className="inline-block rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 font-mono text-[10px] text-slate-600 dark:text-slate-300">
          Reason code: {row.reasonCode}
        </div>
      )}
    </div>
  )
}

export function FactorBreakdownChart({ breakdown }: { breakdown: ScoreBreakdown }) {
  const data = mapFactorsToChartData(breakdown)
  const chartHeight = 40 + data.length * 36

  return (
    <div data-testid="factor-breakdown-chart" className="space-y-3 w-full min-w-0">
      <div style={{ height: chartHeight, width: '100%', minWidth: 280 }}>
        <ResponsiveContainer width="100%" height="100%" minWidth={280}>
          <BarChart
            layout="vertical"
            data={data}
            margin={{ top: 8, right: 60, left: 8, bottom: 8 }}
          >
            <CartesianGrid horizontal={false} stroke="currentColor" className="text-slate-200 dark:text-slate-800" />
            <XAxis type="number" hide />
            <YAxis
              type="category"
              dataKey="name"
              width={170}
              tick={{ fontSize: 11 }}
              stroke="currentColor"
              className="text-slate-600 dark:text-slate-400"
            />
            <Tooltip content={<CustomTooltip />} />
            <ReferenceLine x={0} stroke="currentColor" className="text-slate-400 dark:text-slate-600" />
            <Bar dataKey="points" radius={3}>
              {data.map((row) => (
                <Cell key={row.name} fill={row.name === 'Base' ? '#64748b' : row.points >= 0 ? '#059669' : '#dc2626'} />
              ))}
              <LabelList dataKey="points" content={<PointsLabel />} />
            </Bar>
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="rounded-md border border-slate-200 dark:border-slate-800 p-2.5 bg-slate-50/70 dark:bg-slate-900/60 text-xs">
        <span className="text-slate-500 dark:text-slate-400">Score derivation: </span>
        <span className="font-medium text-slate-700 dark:text-slate-300">
          {breakdown.base} base {data.slice(1).reduce((s, r) => s + r.points, 0) >= 0 ? '+' : ''}
          {data.slice(1).reduce((s, r) => s + r.points, 0)} ={' '}
        </span>
        <strong className="text-slate-900 dark:text-slate-100 text-sm">{breakdown.total}</strong>
        <span className="text-slate-500 dark:text-slate-400"> / 100 ({breakdown.version})</span>
      </div>

      <div className="space-y-1.5">
        <h4 className="text-xs font-semibold uppercase tracking-wide text-slate-500 dark:text-slate-400">
          Factor Details & Explanations
        </h4>
        <div className="space-y-1">
          {data.map((row) => (
            <div
              key={row.name}
              className="flex items-start justify-between gap-2 rounded border border-slate-200 dark:border-slate-800/80 bg-white dark:bg-slate-900 px-3 py-2 text-xs"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-2">
                  <span className="font-semibold text-slate-800 dark:text-slate-200">{row.name}</span>
                  {row.reasonCode && (
                    <span className="rounded bg-slate-100 dark:bg-slate-800 px-1.5 py-0.5 text-[10px] font-mono text-slate-600 dark:text-slate-300">
                      {row.reasonCode}
                    </span>
                  )}
                </div>
                <div className="text-slate-600 dark:text-slate-400 text-xs mt-0.5 leading-relaxed">
                  {row.name === 'Base' ? 'Starting baseline before alternative-data signals' : row.label.replace(/^([+-]?\d+ pts:\s*)/, '')}
                </div>
              </div>
              <span
                className={`font-semibold tabular-nums shrink-0 text-xs px-2 py-0.5 rounded ${
                  row.name === 'Base'
                    ? 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300'
                    : row.points > 0
                      ? 'bg-emerald-50 text-emerald-700 dark:bg-emerald-950 dark:text-emerald-300'
                      : row.points < 0
                        ? 'bg-rose-50 text-rose-700 dark:bg-rose-950 dark:text-rose-300'
                        : 'bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400'
                }`}
              >
                {row.points > 0 ? `+${row.points}` : row.points} pts
              </span>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}
