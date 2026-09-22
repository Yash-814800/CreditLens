/** Simple 0-100 semicircle score gauge (plain SVG, no chart library --
 * Recharts is reserved for the factor-breakdown chart per the Phase 7 spec).
 * Color band always ships with the numeric value printed in the center, so
 * the gauge never relies on color alone. */
export function ScoreGauge({ score, label }: { score: number | null; label: string }) {
  const value = score ?? 0
  const pct = Math.max(0, Math.min(100, value)) / 100
  const radius = 42
  const cx = 50
  const cy = 50
  const arcLength = Math.PI * radius
  const strokeOffset = arcLength * (1 - pct)
  const tone = value >= 70 ? '#059669' : value >= 45 ? '#d97706' : '#dc2626'

  return (
    <div className="flex flex-col items-center" data-testid="score-gauge">
      <svg viewBox="0 0 100 58" className="w-32 h-auto">
        <path
          d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
          fill="none"
          stroke="currentColor"
          className="text-slate-200 dark:text-slate-700"
          strokeWidth={8}
          strokeLinecap="round"
        />
        {score !== null && value > 0 && (
          <path
            d={`M ${cx - radius} ${cy} A ${radius} ${radius} 0 0 1 ${cx + radius} ${cy}`}
            fill="none"
            stroke={tone}
            strokeWidth={8}
            strokeLinecap="round"
            strokeDasharray={arcLength}
            strokeDashoffset={strokeOffset}
          />
        )}
        <text x={cx} y={cy - 4} textAnchor="middle" className="fill-slate-900 dark:fill-slate-100" fontSize={20} fontWeight={700}>
          {score ?? '—'}
        </text>
      </svg>
      <span className="text-xs font-medium text-slate-500 dark:text-slate-400 -mt-1">{label}</span>
    </div>
  )
}
