import { ConfidenceChip } from '../../components/SeverityChip'
import { TriangleAlert } from 'lucide-react'

type ExtractedScalar = { value: unknown; confidence: number; legible: boolean }

function isScalarField(v: unknown): v is ExtractedScalar {
  return (
    typeof v === 'object' &&
    v !== null &&
    'confidence' in v &&
    'legible' in v &&
    typeof (v as Record<string, unknown>).confidence === 'number'
  )
}

function humanize(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase())
}

/** Renders whatever `Document.extracted` holds (Phase 3's per-field
 * {value, confidence, legible} envelope for scalars; plain arrays for
 * row-level tables like weekly earnings / payment history) without assuming
 * a fixed schema per doc type -- new extraction fields show up automatically. */
export function ExtractedFieldsTable({
  extracted,
  citedFields = new Set<string>(),
}: {
  extracted: Record<string, unknown> | null
  citedFields?: Set<string>
}) {
  if (!extracted) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">No extraction data available.</p>
  }

  const scalarEntries = Object.entries(extracted).filter(([, v]) => isScalarField(v))
  const arrayEntries = Object.entries(extracted).filter(([, v]) => Array.isArray(v) && v.length > 0)
  const boolEntries = Object.entries(extracted).filter(([, v]) => typeof v === 'boolean')

  return (
    <div className="space-y-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs uppercase text-slate-500 dark:text-slate-400">
            <th className="py-1 pr-2">Field</th>
            <th className="py-1 pr-2">Value</th>
            <th className="py-1">Confidence</th>
          </tr>
        </thead>
        <tbody>
          {scalarEntries.map(([key, raw]) => {
            const v = raw as ExtractedScalar
            const cited = citedFields.has(key)
            return (
              <tr
                key={key}
                className={`border-t border-slate-100 dark:border-slate-800 ${cited ? 'bg-amber-50 dark:bg-amber-950/40' : ''}`}
              >
                <td className="py-1.5 pr-2 text-slate-600 dark:text-slate-400 flex items-center gap-1">
                  {humanize(key)}
                  {cited && <TriangleAlert size={12} className="text-amber-600" aria-label="cited by a fraud finding" />}
                </td>
                <td className="py-1.5 pr-2 font-medium">
                  {v.value === null || v.value === undefined ? (
                    <span className="text-slate-400 italic">not legible</span>
                  ) : (
                    String(v.value)
                  )}
                </td>
                <td className="py-1.5">
                  <ConfidenceChip confidence={v.confidence} />
                </td>
              </tr>
            )
          })}
          {boolEntries.map(([key, v]) => (
            <tr key={key} className="border-t border-slate-100 dark:border-slate-800">
              <td className="py-1.5 pr-2 text-slate-600 dark:text-slate-400">{humanize(key)}</td>
              <td colSpan={2} className="py-1.5 font-medium">
                {String(v)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>

      {arrayEntries.map(([key, rows]) => (
        <details key={key} className="rounded border border-slate-200 dark:border-slate-800">
          <summary className="cursor-pointer px-3 py-1.5 text-xs font-medium text-slate-600 dark:text-slate-400">
            {humanize(key)} ({(rows as unknown[]).length} rows)
          </summary>
          <div className="overflow-x-auto px-3 pb-2">
            <table className="w-full text-xs">
              <thead>
                <tr className="text-left text-slate-500">
                  {Object.keys((rows as Record<string, unknown>[])[0]).map((col) => (
                    <th key={col} className="py-1 pr-2">
                      {humanize(col)}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {(rows as Record<string, unknown>[]).map((row, i) => (
                  <tr key={i} className="border-t border-slate-100 dark:border-slate-800">
                    {Object.values(row).map((val, j) => (
                      <td key={j} className="py-1 pr-2">
                        {String(val)}
                      </td>
                    ))}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      ))}
    </div>
  )
}
