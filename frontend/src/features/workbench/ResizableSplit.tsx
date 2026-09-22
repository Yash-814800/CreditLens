import { useEffect, useRef, useState, type ReactNode } from 'react'

const DESKTOP_QUERY = '(min-width: 1024px)'

function useIsDesktop(): boolean {
  const [isDesktop, setIsDesktop] = useState(
    () => typeof window !== 'undefined' && window.matchMedia(DESKTOP_QUERY).matches,
  )
  useEffect(() => {
    const mq = window.matchMedia(DESKTOP_QUERY)
    const handler = () => setIsDesktop(mq.matches)
    mq.addEventListener('change', handler)
    return () => mq.removeEventListener('change', handler)
  }, [])
  return isDesktop
}

/** Two resizable panels at >=1024px (Phase 7: "two panels, resizable
 * divider"), stacking to a single column below that (Phase 7: "usable at
 * 1024px"). Renders `left`/`right` exactly ONCE -- an earlier version
 * rendered a second, CSS-hidden copy of both panels for the mobile
 * fallback, which silently double-mounted every child (duplicate document
 * fetches, duplicate `data-testid`s breaking every workbench query, found
 * via a real Playwright run). The resize handle is desktop-only; below
 * 1024px the panels simply stack via `flex-col`, no duplicate DOM. */
export function ResizableSplit({ left, right }: { left: ReactNode; right: ReactNode }) {
  const [leftPct, setLeftPct] = useState(50)
  const containerRef = useRef<HTMLDivElement>(null)
  const dragging = useRef(false)
  const isDesktop = useIsDesktop()

  function onPointerDown(e: React.PointerEvent) {
    dragging.current = true
    ;(e.target as Element).setPointerCapture(e.pointerId)
  }
  function onPointerMove(e: React.PointerEvent) {
    if (!dragging.current || !containerRef.current) return
    const rect = containerRef.current.getBoundingClientRect()
    const pct = ((e.clientX - rect.left) / rect.width) * 100
    setLeftPct(Math.min(72, Math.max(28, pct)))
  }
  function onPointerUp() {
    dragging.current = false
  }

  return (
    <div ref={containerRef} className="flex flex-col lg:flex-row w-full min-h-[70vh]" data-testid="workbench-split">
      <div style={isDesktop ? { width: `${leftPct}%` } : undefined} className="min-w-0 lg:pr-2">
        {left}
      </div>
      <div
        role="separator"
        aria-orientation="vertical"
        aria-label="Resize panels"
        tabIndex={0}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onKeyDown={(e) => {
          if (e.key === 'ArrowLeft') setLeftPct((p) => Math.max(28, p - 3))
          if (e.key === 'ArrowRight') setLeftPct((p) => Math.min(72, p + 3))
        }}
        className="hidden lg:block w-1.5 mx-1 shrink-0 cursor-col-resize rounded bg-slate-200 dark:bg-slate-800 hover:bg-slate-400 dark:hover:bg-slate-600"
      />
      <div style={isDesktop ? { width: `${100 - leftPct}%` } : undefined} className="min-w-0 lg:pl-2 mt-4 lg:mt-0">
        {right}
      </div>
    </div>
  )
}
