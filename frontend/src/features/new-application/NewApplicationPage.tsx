import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { UploadCloud, FileCheck2, X } from 'lucide-react'
import { api, ApiError } from '../../api/client'
import { ErrorBlock } from '../../components/Feedback'
import type { DocType } from '../../api/types'

const UPLOAD_SLOTS: Array<{
  key: DocType
  label: string
  accept: string
  hint: string
}> = [
  {
    key: 'GIG_PAYOUT',
    label: 'Gig-platform payout screenshot',
    accept: '.png,.jpg,.jpeg',
    hint: 'PNG or JPG',
  },
  {
    key: 'UTILITY_BILL',
    label: 'Utility bill',
    accept: '.pdf,.png,.jpg,.jpeg',
    hint: 'PDF, PNG, or JPG',
  },
  {
    key: 'BANK_STATEMENT',
    label: 'Bank / UPI statement (CSV)',
    accept: '.csv',
    hint: 'CSV',
  },
]

export function NewApplicationPage() {
  const navigate = useNavigate()
  const [fullName, setFullName] = useState('')
  const [phone, setPhone] = useState('')
  const [pan, setPan] = useState('')
  const [aadhaar, setAadhaar] = useState('')
  const [declaredAddress, setDeclaredAddress] = useState('')
  const [statedVocation, setStatedVocation] = useState('')
  const [requestedLine, setRequestedLine] = useState('25000')
  const [consent, setConsent] = useState(false)
  const [files, setFiles] = useState<Partial<Record<DocType, File>>>({})
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  const {
    data: consentMeta,
    isLoading: consentLoading,
    error: consentError,
  } = useQuery({
    queryKey: ['consent-meta'],
    queryFn: api.getConsentMeta,
    staleTime: 1000 * 60 * 60,
  })

  const panValid = /^[A-Z]{5}[0-9]{4}[A-Z]$/.test(pan.toUpperCase())
  const phoneValid = /^[6-9]\d{9}$/.test(phone)
  const aadhaarValid = /^\d{12}$/.test(aadhaar)
  const hasAnyDoc = Object.values(files).some(Boolean)
  const canSubmit =
    fullName.trim().length > 1 &&
    phoneValid &&
    panValid &&
    aadhaarValid &&
    consent &&
    hasAnyDoc &&
    Boolean(consentMeta?.version)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    if (!canSubmit) {
      setError(
        'Please complete all required fields, accept consent, and attach at least one document.',
      )
      return
    }
    setSubmitting(true)
    try {
      const form = new FormData()
      form.set(
        'kyc',
        JSON.stringify({
          full_name: fullName,
          phone,
          pan: pan.toUpperCase(),
          aadhaar,
          declared_address: declaredAddress || null,
          stated_vocation: statedVocation || null,
          requested_line_inr: Number(requestedLine),
          consent_accepted: consent,
          consent_given: consent,
          consent_text_version: consentMeta?.version ?? '',
        }),
      )
      for (const slot of UPLOAD_SLOTS) {
        const f = files[slot.key]
        if (f) form.set(slot.key.toLowerCase(), f)
      }
      const res = await api.createApplication(form)
      navigate(`/applications/${res.id}`)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : 'Failed to submit application.',
      )
      setSubmitting(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto space-y-6">
      <h1 className="text-lg font-semibold">New application</h1>
      {/* noValidate: the component's own validation (canSubmit/handleSubmit) is the single
          source of truth for error messaging -- otherwise the browser's native constraint
          validation on the `required` fields (especially the consent checkbox) silently
          blocks submission before our consistently-styled inline errors ever render. */}
      <form onSubmit={handleSubmit} noValidate className="space-y-6">
        <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-4">
          <h2 className="font-medium text-slate-800 dark:text-slate-200">
            Applicant details (KYC)
          </h2>
          <div className="grid sm:grid-cols-2 gap-4">
            <Field id="full-name" label="Full name" required>
              <input
                id="full-name"
                required
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                className="input"
              />
            </Field>
            <Field
              id="phone"
              label="Phone"
              required
              error={
                phone && !phoneValid
                  ? '10-digit Indian mobile number'
                  : undefined
              }
            >
              <input
                id="phone"
                required
                value={phone}
                onChange={(e) => setPhone(e.target.value)}
                className="input"
                placeholder="9XXXXXXXXX"
              />
            </Field>
            <Field
              id="pan"
              label="PAN"
              required
              error={pan && !panValid ? 'Format: ABCDE1234F' : undefined}
            >
              <input
                id="pan"
                required
                value={pan}
                onChange={(e) => setPan(e.target.value.toUpperCase())}
                className="input uppercase"
                placeholder="ABCDE1234F"
              />
            </Field>
            <Field
              id="aadhaar"
              label="Aadhaar"
              required
              error={aadhaar && !aadhaarValid ? '12 digits' : undefined}
            >
              <input
                id="aadhaar"
                required
                value={aadhaar}
                onChange={(e) => setAadhaar(e.target.value)}
                className="input"
                placeholder="12-digit number"
              />
            </Field>
            <Field id="stated-vocation" label="Stated vocation">
              <input
                id="stated-vocation"
                value={statedVocation}
                onChange={(e) => setStatedVocation(e.target.value)}
                className="input"
                placeholder="e.g. Ride-hailing driver"
              />
            </Field>
            <Field
              id="requested-line"
              label="Requested credit line (₹)"
              required
            >
              <input
                id="requested-line"
                required
                type="number"
                min={1}
                value={requestedLine}
                onChange={(e) => setRequestedLine(e.target.value)}
                className="input"
              />
            </Field>
            <Field id="declared-address" label="Declared address" full>
              <textarea
                id="declared-address"
                value={declaredAddress}
                onChange={(e) => setDeclaredAddress(e.target.value)}
                className="input"
                rows={2}
              />
            </Field>
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5 space-y-4">
          <h2 className="font-medium text-slate-800 dark:text-slate-200">
            Documents
          </h2>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            Attach at least one. More documents produce a more complete,
            higher-confidence assessment.
          </p>
          <div className="grid sm:grid-cols-3 gap-3">
            {UPLOAD_SLOTS.map((slot) => (
              <UploadZone
                key={slot.key}
                slot={slot}
                file={files[slot.key]}
                onChange={(f) =>
                  setFiles((prev) => ({ ...prev, [slot.key]: f }))
                }
              />
            ))}
          </div>
        </section>

        <section className="rounded-lg border border-slate-200 dark:border-slate-800 bg-white dark:bg-slate-900 p-5">
          <label className="flex items-start gap-3 text-sm">
            <input
              type="checkbox"
              required
              disabled={consentLoading || !consentMeta}
              checked={consent}
              onChange={(e) => setConsent(e.target.checked)}
              className="mt-0.5 h-4 w-4"
            />
            <span className="text-slate-700 dark:text-slate-300">
              <span className="font-medium">
                I have read and agree to the consent statement
              </span>
              {consentLoading && (
                <span className="text-slate-400">
                  {' '}
                  (loading consent terms…)
                </span>
              )}
              {consentError && (
                <span className="text-red-500">
                  {' '}
                  (failed to load consent terms)
                </span>
              )}
              {consentMeta && (
                <>
                  {' '}
                  (version {consentMeta.version}):{' '}
                  <span className="text-slate-500 dark:text-slate-400 whitespace-pre-line">
                    {consentMeta.text}
                  </span>
                </>
              )}
            </span>
          </label>
        </section>

        {error && <ErrorBlock message={error} />}

        <button
          type="submit"
          disabled={submitting}
          className="w-full sm:w-auto rounded-md bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 px-5 py-2.5 text-sm font-semibold hover:opacity-90 disabled:opacity-50"
        >
          {submitting ? 'Submitting…' : 'Submit application'}
        </button>
      </form>
    </div>
  )
}

function Field({
  id,
  label,
  required,
  error,
  full,
  children,
}: {
  id: string
  label: string
  required?: boolean
  error?: string
  full?: boolean
  children: React.ReactNode
}) {
  return (
    <div className={`space-y-1 ${full ? 'sm:col-span-2' : ''}`}>
      <label
        htmlFor={id}
        className="text-sm font-medium text-slate-700 dark:text-slate-300"
      >
        {label} {required && <span className="text-red-600">*</span>}
      </label>
      {children}
      {error && <p className="text-xs text-red-600">{error}</p>}
    </div>
  )
}

function UploadZone({
  slot,
  file,
  onChange,
}: {
  slot: { key: DocType; label: string; accept: string; hint: string }
  file?: File
  onChange: (f: File | undefined) => void
}) {
  const inputId = `upload-${slot.key}`
  return (
    <div className="relative rounded-lg border-2 border-dashed border-slate-300 dark:border-slate-700 p-4 text-center hover:border-slate-400">
      <input
        id={inputId}
        type="file"
        accept={slot.accept}
        className="absolute inset-0 opacity-0 cursor-pointer"
        onChange={(e) => onChange(e.target.files?.[0])}
        aria-label={slot.label}
      />
      {file ? (
        <div className="flex flex-col items-center gap-1 text-emerald-700 dark:text-emerald-400">
          <FileCheck2 size={22} aria-hidden="true" />
          <span className="text-xs font-medium truncate max-w-full">
            {file.name}
          </span>
          <button
            type="button"
            onClick={(e) => {
              e.preventDefault()
              onChange(undefined)
            }}
            className="relative z-10 mt-1 flex items-center gap-1 text-xs text-slate-500 hover:text-red-600"
          >
            <X size={12} /> remove
          </button>
        </div>
      ) : (
        <div className="flex flex-col items-center gap-1 text-slate-500 dark:text-slate-400">
          <UploadCloud size={22} aria-hidden="true" />
          <span className="text-xs font-medium">{slot.label}</span>
          <span className="text-[11px]">{slot.hint}</span>
        </div>
      )}
    </div>
  )
}
