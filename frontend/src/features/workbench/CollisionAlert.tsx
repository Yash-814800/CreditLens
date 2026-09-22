import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TriangleAlert, Network } from 'lucide-react'
import { api, fetchAuthedBlobUrl } from '../../api/client'
import type { Finding } from '../../api/types'

/** Red/amber banner for a HIGH/MEDIUM pHash collision finding on this
 * document, with a real side-by-side image comparison against the matching
 * other-applicant document (Phase 7 spec) -- both documents are fetched
 * through the same authenticated `/documents/{id}/file` endpoint an
 * underwriter can already reach for any application, using the
 * `other_application_id`/`other_document_id` evidence fields the fraud
 * service records for exactly this purpose. */
export function CollisionAlert({ applicationId, finding }: { applicationId: string; finding: Finding }) {
  const ev = finding.evidence as Record<string, unknown>
  const otherApplicant = typeof ev.other_applicant_id === 'string' ? ev.other_applicant_id : null
  const otherApplicationId = typeof ev.other_application_id === 'string' ? ev.other_application_id : null
  const otherDocumentId = typeof ev.other_document_id === 'string' ? ev.other_document_id : null
  const hamming = typeof ev.hamming_distance === 'number' ? ev.hamming_distance : null
  const shaMatch = Boolean(ev.sha256_match)
  const nameCorroborated = Boolean(ev.name_corroborated)
  const identifierCorroborated = Boolean(ev.identifier_corroborated)
  const isHigh = finding.severity === 'HIGH'

  const [thisFileUrl, setThisFileUrl] = useState<string | null>(null)
  const [otherFileUrl, setOtherFileUrl] = useState<string | null>(null)

  useEffect(() => {
    if (!finding.document_id) return
    let revoked = false
    let url: string | null = null
    fetchAuthedBlobUrl(api.documentFileUrl(applicationId, finding.document_id))
      .then((u) => {
        if (revoked) {
          URL.revokeObjectURL(u)
          return
        }
        url = u
        setThisFileUrl(u)
      })
      .catch(() => {
        /* stats above still stand even if the thumbnail can't load */
      })
    return () => {
      revoked = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [applicationId, finding.document_id])

  useEffect(() => {
    if (!otherApplicationId || !otherDocumentId) return
    let revoked = false
    let url: string | null = null
    fetchAuthedBlobUrl(api.documentFileUrl(otherApplicationId, otherDocumentId))
      .then((u) => {
        if (revoked) {
          URL.revokeObjectURL(u)
          return
        }
        url = u
        setOtherFileUrl(u)
      })
      .catch(() => {
        /* the other document may be unreachable (e.g. deleted); the stats above still stand */
      })
    return () => {
      revoked = true
      if (url) URL.revokeObjectURL(url)
    }
  }, [otherApplicationId, otherDocumentId])

  return (
    <div
      role="alert"
      data-testid="collision-alert"
      className={`rounded-lg border p-4 space-y-3 ${
        isHigh
          ? 'border-red-300 bg-red-50 dark:border-red-900 dark:bg-red-950'
          : 'border-amber-300 bg-amber-50 dark:border-amber-900 dark:bg-amber-950'
      }`}
    >
      <div className="flex items-start gap-2">
        <TriangleAlert
          size={20}
          className={isHigh ? 'text-red-700 dark:text-red-400' : 'text-amber-700 dark:text-amber-400'}
          aria-hidden="true"
        />
        <div className="flex-1">
          <p className={`font-semibold ${isHigh ? 'text-red-800 dark:text-red-300' : 'text-amber-800 dark:text-amber-300'}`}>
            {isHigh ? 'Document reuse detected (high confidence)' : 'Possible document reuse'}
          </p>
          <p className="text-sm mt-0.5 text-slate-700 dark:text-slate-300">{finding.message}</p>
        </div>
      </div>

      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2 text-xs">
        <Stat label="Other applicant" value={otherApplicant ? `${otherApplicant.slice(0, 8)}…` : '—'} />
        <Stat label="Hamming distance" value={hamming !== null ? `${hamming} / 256 bits` : '—'} />
        <Stat label="Exact byte match" value={shaMatch ? 'Yes' : 'No'} />
        <Stat
          label="Corroborated by"
          value={[nameCorroborated && 'name', identifierCorroborated && 'ID field'].filter(Boolean).join(', ') || 'none'}
        />
      </div>

      {otherDocumentId && (
        <div>
          <p className="text-xs font-medium text-slate-600 dark:text-slate-400 mb-1">
            Side-by-side comparison (this document vs. the other applicant's document)
          </p>
          <div className="grid grid-cols-2 gap-2">
            <div className="rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 p-1">
              <p className="text-[10px] text-slate-500 text-center mb-1">This application</p>
              <div className="h-32 overflow-hidden flex items-center justify-center">
                {thisFileUrl ? (
                  <img src={thisFileUrl} alt="This application's document" className="max-h-32 object-contain" />
                ) : (
                  <span className="text-xs text-slate-400">Loading…</span>
                )}
              </div>
            </div>
            <div className="rounded border border-slate-300 dark:border-slate-700 bg-white dark:bg-slate-950 p-1">
              <p className="text-[10px] text-slate-500 text-center mb-1">
                Other applicant {otherApplicant ? `(${otherApplicant.slice(0, 8)}…)` : ''}
              </p>
              <div className="h-32 overflow-hidden flex items-center justify-center">
                {otherFileUrl ? (
                  <img src={otherFileUrl} alt="Colliding document from the other applicant" className="max-h-32 object-contain" />
                ) : (
                  <span className="text-xs text-slate-400">Loading…</span>
                )}
              </div>
            </div>
          </div>
        </div>
      )}

      <Link
        to="/syndicate"
        className="inline-flex items-center gap-1.5 text-sm font-medium text-slate-900 dark:text-slate-100 hover:underline"
      >
        <Network size={14} aria-hidden="true" /> Open syndicate graph
      </Link>
    </div>
  )
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded bg-white/70 dark:bg-black/20 px-2 py-1.5">
      <div className="text-slate-500 dark:text-slate-400">{label}</div>
      <div className="font-semibold text-slate-800 dark:text-slate-200">{value}</div>
    </div>
  )
}
