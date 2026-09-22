import type { ReactNode } from 'react'
import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from './AuthContext'
import type { Role } from '../api/types'

/** Route guard. `roles` omitted = any authenticated user; otherwise the
 * current role must be in the allowlist (RBAC matrix from CLAUDE.md --
 * underwriter has no audit-log access at all, for example). */
export function RequireAuth({ children, roles }: { children: ReactNode; roles?: Role[] }) {
  const { isAuthenticated, role } = useAuth()
  const location = useLocation()

  if (!isAuthenticated) {
    return <Navigate to="/login" state={{ from: location }} replace />
  }
  if (roles && (role === null || !roles.includes(role))) {
    return (
      <div className="p-8 text-center text-slate-600 dark:text-slate-300">
        <p className="text-lg font-semibold">Access restricted</p>
        <p className="text-sm mt-1">
          Your role ({role}) doesn&apos;t have permission to view this page.
        </p>
      </div>
    )
  }
  return <>{children}</>
}
