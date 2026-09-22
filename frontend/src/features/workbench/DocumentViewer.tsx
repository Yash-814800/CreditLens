import { useEffect, useMemo, useState } from 'react'
import { ZoomIn, ZoomOut, Layers, Download, Search } from 'lucide-react'
import { api, fetchAuthedBlobUrl, tokenStore } from '../../api/client'
import { LoadingBlock } from '../../components/Feedback'
import type { DocumentSummary } from '../../api/types'

import { parseCsvStatement, type ParsedCsvStatement } from './csvParser'

function BankStatementTableView({
  fileUrl,
  parsed,
}: {
  fileUrl: string | null
  parsed: ParsedCsvStatement
}) {
  const [filter, setFilter] = useState('')

  const filteredRows = useMemo(() => {
    if (!filter.trim()) return parsed.rows
    const q = filter.toLowerCase()
    return parsed.rows.filter((row) => row.some((cell) => cell.toLowerCase().includes(q)))
  }, [parsed.rows, filter])

  const headersLower = parsed.headers.map((h) => h.toLowerCase())
  const debitIdx = headersLower.findIndex((h) => h.includes('debit') || h.includes('withdrawal'))
  const creditIdx = headersLower.findIndex((h) => h.includes('credit') || h.includes('deposit'))
  const balanceIdx = headersLower.findIndex((h) => h.includes('balance'))

  return (
    <div className="space-y-3" data-testid="bank-statement-viewer">
      {parsed.metadata.length > 0 && (
        <div className="flex flex-wrap gap-2 p-2.5 rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-900 text-xs">
          {parsed.metadata.map((m) => (
            <div key={m.key} className="rounded bg-white dark:bg-slate-800 px-2 py-1 border border-slate-200 dark:border-slate-700/60">
              <span className="text-slate-500 dark:text-slate-400 font-medium">{m.key}: </span>
              <span className="text-slate-800 dark:text-slate-200 font-semibold">{m.value}</span>
            </div>
          ))}
        </div>
      )}

      <div className="flex items-center justify-between gap-2 flex-wrap">
        <div className="flex items-center gap-2">
          <div className="relative">
            <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-slate-400" />
            <input
              type="text"
              placeholder="Filter narration, date, or amount..."
              value={filter}
              onChange={(e) => setFilter(e.target.value)}
              className="pl-8 pr-3 py-1 text-xs rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-900 text-slate-800 dark:text-slate-200 placeholder:text-slate-400 w-60 focus:outline-none focus:ring-1 focus:ring-slate-400"
            />
          </div>
          <span className="text-xs text-slate-500 dark:text-slate-400">
            {filteredRows.length} of {parsed.rows.length} transactions
          </span>
        </div>

        {fileUrl && (
          <a
            href={fileUrl}
            download="bank_statement.csv"
            className="inline-flex items-center gap-1.5 rounded border border-slate-300 dark:border-slate-700 px-2.5 py-1 text-xs font-medium text-slate-700 dark:text-slate-300 hover:bg-slate-100 dark:hover:bg-slate-800 transition-colors"
          >
            <Download size={13} /> Download CSV
          </a>
        )}
      </div>

      <div className="relative overflow-auto rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 max-h-[55vh]">
        <table className="w-full text-xs text-left border-collapse">
          <thead className="sticky top-0 bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-300 z-10 shadow-sm">
            <tr>
              {parsed.headers.map((h, i) => {
                const isNumeric = i === debitIdx || i === creditIdx || i === balanceIdx
                return (
                  <th
                    key={i}
                    className={`py-2 px-3 font-semibold uppercase tracking-wider text-[11px] ${
                      isNumeric ? 'text-right' : 'text-left'
                    }`}
                  >
                    {h.replace(/_/g, ' ')}
                  </th>
                )
              })}
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
            {filteredRows.length === 0 ? (
              <tr>
                <td colSpan={parsed.headers.length || 1} className="text-center py-6 text-slate-500">
                  No transactions match &ldquo;{filter}&rdquo;
                </td>
              </tr>
            ) : (
              filteredRows.map((row, rIdx) => (
                <tr
                  key={rIdx}
                  className="hover:bg-slate-50 dark:hover:bg-slate-800/60 transition-colors odd:bg-white dark:odd:bg-slate-900 even:bg-slate-50/40 dark:even:bg-slate-800/30"
                >
                  {row.map((cell, cIdx) => {
                    const isDebit = cIdx === debitIdx
                    const isCredit = cIdx === creditIdx
                    const isBalance = cIdx === balanceIdx
                    const isNumeric = isDebit || isCredit || isBalance
                    const isDate = cIdx === 0

                    let cellStyle = 'py-2 px-3 text-slate-700 dark:text-slate-300'
                    if (isDate) {
                      cellStyle = 'py-2 px-3 font-mono text-slate-600 dark:text-slate-400 whitespace-nowrap'
                    } else if (isDebit && cell) {
                      cellStyle = 'py-2 px-3 font-mono text-right text-rose-600 dark:text-rose-400 font-medium'
                    } else if (isCredit && cell) {
                      cellStyle = 'py-2 px-3 font-mono text-right text-emerald-600 dark:text-emerald-400 font-semibold'
                    } else if (isBalance && cell) {
                      cellStyle = 'py-2 px-3 font-mono text-right text-slate-900 dark:text-slate-100 font-semibold'
                    } else if (isNumeric) {
                      cellStyle = 'py-2 px-3 font-mono text-right text-slate-400'
                    }

                    return (
                      <td key={cIdx} className={cellStyle}>
                        {cell ? (isNumeric && !cell.startsWith('₹') ? `₹${cell}` : cell) : '—'}
                      </td>
                    )
                  })}
                </tr>
              ))
            )}
          </tbody>
        </table>
      </div>
    </div>
  )
}

/** Zoomable file viewer with an optional tamper-radar heatmap overlay
 * (opacity-sliderable) per the Phase 7 spec. Both the file and the overlay
 * are authenticated endpoints, so we fetch them as blobs rather than
 * pointing an <img> at the URL directly (no Authorization header on <img>). */
export function DocumentViewer({
  applicationId,
  document,
}: {
  applicationId: string
  document: DocumentSummary
}) {
  const [fileUrl, setFileUrl] = useState<string | null>(null)
  const [overlayUrl, setOverlayUrl] = useState<string | null>(null)
  const [parsedCsv, setParsedCsv] = useState<ParsedCsvStatement | null>(null)
  const [zoom, setZoom] = useState(1)
  const [showOverlay, setShowOverlay] = useState(false)
  const [opacity, setOpacity] = useState(0.6)
  const hasOverlay = Boolean((document.forensic as { heatmap_storage_key?: string } | null)?.heatmap_storage_key)
  const isPdf = document.mime === 'application/pdf'
  const isCsv = document.mime === 'text/csv'

  useEffect(() => {
    const revoke: string[] = []
    const token = tokenStore.get()
    const headers = new Headers()
    if (token) headers.set('Authorization', `Bearer ${token}`)

    fetch(api.documentFileUrl(applicationId, document.id), { headers })
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.blob()
      })
      .then(async (blob) => {
        const url = URL.createObjectURL(blob)
        revoke.push(url)
        setFileUrl(url)
        if (isCsv) {
          const text = await blob.text()
          setParsedCsv(parseCsvStatement(text))
        }
      })
      .catch((err) => {
        console.error('Failed to load document file:', err)
      })

    if (hasOverlay) {
      fetchAuthedBlobUrl(api.documentOverlayUrl(applicationId, document.id)).then((url) => {
        revoke.push(url)
        setOverlayUrl(url)
      })
    }
    return () => revoke.forEach((u) => URL.revokeObjectURL(u))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [applicationId, document.id])

  if (isCsv) {
    if (!parsedCsv) return <LoadingBlock label="Loading bank statement…" />
    return <BankStatementTableView fileUrl={fileUrl} parsed={parsedCsv} />
  }

  return (
    <div className="space-y-2">
      <div className="flex items-center gap-2 flex-wrap">
        <button
          onClick={() => setZoom((z) => Math.max(0.5, z - 0.25))}
          className="rounded border border-slate-300 dark:border-slate-700 p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
          aria-label="Zoom out"
        >
          <ZoomOut size={14} />
        </button>
        <span className="text-xs tabular-nums w-10 text-center">{Math.round(zoom * 100)}%</span>
        <button
          onClick={() => setZoom((z) => Math.min(3, z + 0.25))}
          className="rounded border border-slate-300 dark:border-slate-700 p-1.5 hover:bg-slate-100 dark:hover:bg-slate-800"
          aria-label="Zoom in"
        >
          <ZoomIn size={14} />
        </button>
        {hasOverlay && (
          <>
            <button
              onClick={() => setShowOverlay((v) => !v)}
              aria-pressed={showOverlay}
              className={`ml-2 flex items-center gap-1.5 rounded border px-2 py-1 text-xs font-medium ${
                showOverlay
                  ? 'border-purple-400 bg-purple-100 text-purple-800 dark:bg-purple-950 dark:text-purple-300'
                  : 'border-slate-300 dark:border-slate-700'
              }`}
            >
              <Layers size={12} /> Tamper radar
            </button>
            {showOverlay && (
              <label className="flex items-center gap-1.5 text-xs text-slate-500">
                Opacity
                <input
                  type="range"
                  min={0.1}
                  max={1}
                  step={0.1}
                  value={opacity}
                  onChange={(e) => setOpacity(Number(e.target.value))}
                  aria-label="Overlay opacity"
                />
              </label>
            )}
          </>
        )}
      </div>

      <div className="relative overflow-auto rounded-lg border border-slate-200 dark:border-slate-800 bg-slate-100 dark:bg-slate-950 max-h-[60vh]">
        {!fileUrl && <LoadingBlock label="Loading document…" />}
        {fileUrl && isPdf && (
          <iframe title={document.doc_type} src={fileUrl} className="w-full h-[60vh]" />
        )}
        {fileUrl && !isPdf && (
          <div className="relative inline-block" style={{ transform: `scale(${zoom})`, transformOrigin: 'top left' }}>
            <img src={fileUrl} alt={`${document.doc_type} document`} className="block max-w-none" />
            {showOverlay && overlayUrl && (
              <img
                src={overlayUrl}
                alt="Tamper radar heatmap overlay"
                className="absolute inset-0 pointer-events-none"
                style={{ opacity }}
              />
            )}
          </div>
        )}
      </div>
    </div>
  )
}
