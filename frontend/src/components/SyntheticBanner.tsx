import { FlaskConical } from 'lucide-react'

/** Persistent, unmissable reminder that every applicant/document/history row
 * in this system is synthetic (CLAUDE.md rule 4: "Synthetic data is labelled
 * synthetic everywhere"). Rendered once in the app shell so no screen can
 * accidentally omit it. */
export function SyntheticBanner() {
  return (
    <div className="bg-amber-500 text-amber-950 text-xs sm:text-sm font-medium px-3 py-1.5 flex items-center justify-center gap-2 text-center">
      <FlaskConical size={14} className="shrink-0" aria-hidden="true" />
      <span>SYNTHETIC DATA: DEMO ONLY — no real applicants, documents, or credit decisions</span>
    </div>
  )
}
