import { useQuery } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, ApiError } from '../../api/client'
import { LoadingBlock, ErrorBlock, EmptyState } from '../../components/Feedback'
import type { FraudGraphResponse } from '../../api/types'

const mask = (id: string) => `${id.slice(0, 8)}…`

/** Syndicate graph: nodes = applicants, edges = shared/reused documents
 * (Phase 7 spec). A simple circular-layout SVG graph, since the spec
 * explicitly allows "a clean grouped list" as a fallback -- this renders
 * both: the SVG for a visual read, and a table underneath for exact
 * evidence values a table communicates better than a diagram. */
export function SyndicateGraphPage() {
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['fraud-graph'],
    queryFn: api.getFraudGraph,
  })
  const [hovered, setHovered] = useState<string | null>(null)

  const nodes = useMemo(() => {
    if (!data) return []
    const ids = new Set<string>()
    for (const e of data.edges) {
      ids.add(e.applicant_a)
      ids.add(e.applicant_b)
    }
    return [...ids]
  }, [data])

  if (isLoading) return <LoadingBlock label="Loading syndicate graph…" />
  if (isError || !data) {
    return <ErrorBlock message={error instanceof ApiError ? error.message : 'Failed to load the fraud graph.'} />
  }
  if (data.edges.length === 0) {
    return <EmptyState title="No document-reuse edges recorded" hint="No pHash collisions have been detected across applicants yet." />
  }

  const size = 420
  const cx = size / 2
  const cy = size / 2
  const r = size / 2 - 48
  const positions = new Map(
    nodes.map((id, i) => {
      const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2
      return [id, { x: cx + r * Math.cos(angle), y: cy + r * Math.sin(angle) }] as const
    }),
  )

  return (
    <div className="space-y-4">
      <h1 className="text-lg font-semibold">Syndicate graph</h1>
      <p className="text-sm text-slate-500 dark:text-slate-400">
        Applicants connected by a shared or reused document. Red edges are corroborated (a matching identity
        signal under a different identity); grey edges are uncorroborated template similarity.
      </p>
      <div className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-4 flex justify-center overflow-x-auto">
        <svg viewBox={`0 0 ${size} ${size}`} width={size} height={size} role="img" aria-label="Syndicate graph">
          {data.edges.map((e, i) => {
            const a = positions.get(e.applicant_a)
            const b = positions.get(e.applicant_b)
            if (!a || !b) return null
            const isHovered = hovered === e.applicant_a || hovered === e.applicant_b
            return (
              <line
                key={i}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                stroke={e.corroborated ? '#dc2626' : '#94a3b8'}
                strokeWidth={isHovered ? 3 : e.corroborated ? 2 : 1}
                opacity={hovered && !isHovered ? 0.2 : 1}
              >
                <title>
                  {e.doc_type} · Hamming {e.hamming_distance} · {e.sha256_match ? 'byte-identical' : 'near-duplicate'} ·{' '}
                  {e.corroborated ? 'corroborated' : 'uncorroborated'}
                </title>
              </line>
            )
          })}
          {nodes.map((id) => {
            const p = positions.get(id)!
            return (
              <g
                key={id}
                onMouseEnter={() => setHovered(id)}
                onMouseLeave={() => setHovered(null)}
                className="cursor-pointer"
              >
                <circle cx={p.x} cy={p.y} r={10} fill="#0f172a" className="dark:fill-slate-100" />
                <text x={p.x} y={p.y - 14} textAnchor="middle" fontSize={10} className="fill-slate-600 dark:fill-slate-300">
                  {mask(id)}
                </text>
              </g>
            )
          })}
        </svg>
      </div>

      <div className="overflow-x-auto rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900">
        <table className="w-full text-sm">
          <thead className="bg-slate-50 dark:bg-slate-800/60 text-left text-xs uppercase text-slate-500 dark:text-slate-400">
            <tr>
              <th className="px-3 py-2">Applicant A</th>
              <th className="px-3 py-2">Applicant B</th>
              <th className="px-3 py-2">Doc type</th>
              <th className="px-3 py-2">Hamming</th>
              <th className="px-3 py-2">SHA match</th>
              <th className="px-3 py-2">Corroborated</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {data.edges.map((e: FraudGraphResponse['edges'][number], i) => (
              <tr key={i}>
                <td className="px-3 py-2 font-mono text-xs">{mask(e.applicant_a)}</td>
                <td className="px-3 py-2 font-mono text-xs">{mask(e.applicant_b)}</td>
                <td className="px-3 py-2">{e.doc_type}</td>
                <td className="px-3 py-2 tabular-nums">{e.hamming_distance}</td>
                <td className="px-3 py-2">{e.sha256_match ? 'Yes' : 'No'}</td>
                <td className="px-3 py-2">{e.corroborated ? 'Yes' : 'No'}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}
