/** Thin typed fetch wrapper. Centralises auth-header injection, 401 handling,
 * and RFC 7807 problem-detail parsing so no feature module talks to `fetch`
 * directly (CLAUDE.md: consistent error model, no leaked stack traces to the
 * user -- the backend already sends {title, detail, status}; we just surface
 * `detail` and let the caller decide how to render it). */
import type {
  ApplicationDetail,
  ApplicationListResponse,
  AuditLogListResponse,
  ConsentMeta,
  DemoPersonaInfo,
  FraudGraphResponse,
  LoginRequest,
  LoginResponse,
  MeResponse,
  ScorecardMeta,
  VerifyChainResponse,
} from './types'

const TOKEN_KEY = 'creditlens_token'
const ROLE_KEY = 'creditlens_role'

/** sessionStorage, not localStorage: the token dies with the tab. This trades
 * "logged in across tabs/reloads-of-a-closed-browser" for "an XSS payload
 * that outlives this tab can't replay the token later" -- documented as a
 * deliberate tradeoff, not an oversight, in docs/threat_model.md. */
export const tokenStore = {
  get: (): string | null => sessionStorage.getItem(TOKEN_KEY),
  getRole: (): string | null => sessionStorage.getItem(ROLE_KEY),
  set: (token: string, role: string) => {
    sessionStorage.setItem(TOKEN_KEY, token)
    sessionStorage.setItem(ROLE_KEY, role)
  },
  clear: () => {
    sessionStorage.removeItem(TOKEN_KEY)
    sessionStorage.removeItem(ROLE_KEY)
  },
}

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
    this.name = 'ApiError'
  }
}

let onUnauthorized: (() => void) | null = null
/** Wired once from AuthProvider so a 401 from anywhere redirects to /login
 * without every call site needing to know about routing. */
export function registerUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const token = tokenStore.get()
  const headers = new Headers(init.headers)
  if (token) headers.set('Authorization', `Bearer ${token}`)
  if (
    init.body &&
    !(init.body instanceof FormData) &&
    !headers.has('Content-Type')
  ) {
    headers.set('Content-Type', 'application/json')
  }

  const res = await fetch(`/api${path}`, { ...init, headers })

  // A 401 only means "your session expired" when we actually sent a token --
  // a 401 on an unauthenticated call (e.g. a wrong-password /auth/login
  // attempt) is a normal request failure and must fall through to the
  // generic error-detail handling below instead of masking the backend's
  // real "invalid email or password" message.
  if (res.status === 401 && token) {
    tokenStore.clear()
    onUnauthorized?.()
    throw new ApiError(401, 'Session expired. Please log in again.')
  }

  if (!res.ok) {
    let detail = `Request failed (${res.status})`
    try {
      const body = (await res.json()) as { detail?: unknown; title?: string }
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) {
        // FastAPI 422 validation errors: [{loc, msg, type}, ...]
        detail = body.detail
          .map(
            (e: { loc?: unknown[]; msg?: string }) =>
              e.msg ?? JSON.stringify(e),
          )
          .join('; ')
      } else if (body.title) detail = body.title
    } catch {
      // non-JSON error body; keep the generic message
    }
    throw new ApiError(res.status, detail)
  }

  if (res.status === 202 || res.status === 204) {
    return (await res.json().catch(() => ({}))) as T
  }
  return (await res.json()) as T
}

export const api = {
  login: (body: LoginRequest) =>
    request<LoginResponse>('/v1/auth/login', {
      method: 'POST',
      body: JSON.stringify(body),
    }),
  me: () => request<MeResponse>('/v1/auth/me'),

  listApplications: (page = 1, pageSize = 20) =>
    request<ApplicationListResponse>(
      `/v1/applications?page=${page}&page_size=${pageSize}`,
    ),
  getApplication: (id: string) =>
    request<ApplicationDetail>(`/v1/applications/${id}`),
  createApplication: (form: FormData) =>
    request<{ id: string }>('/v1/applications', { method: 'POST', body: form }),
  overrideDecision: (id: string, outcome: string, reason: string) =>
    request<{ id: string; system_outcome: string; final_outcome: string }>(
      `/v1/applications/${id}/override`,
      { method: 'POST', body: JSON.stringify({ outcome, reason }) },
    ),
  documentFileUrl: (applicationId: string, documentId: string) =>
    `/api/v1/applications/${applicationId}/documents/${documentId}/file`,
  documentOverlayUrl: (applicationId: string, documentId: string) =>
    `/api/v1/applications/${applicationId}/documents/${documentId}/overlay`,

  getScorecardMeta: () => request<ScorecardMeta>('/v1/meta/scorecard'),
  getConsentMeta: () => request<ConsentMeta>('/v1/meta/consent'),
  getFraudGraph: () => request<FraudGraphResponse>('/v1/fraud/graph'),

  listAuditLog: (
    page = 1,
    pageSize = 50,
    filters?: { event_type?: string },
  ) => {
    const params = new URLSearchParams({
      page: String(page),
      page_size: String(pageSize),
    })
    if (filters?.event_type) params.set('event_type', filters.event_type)
    return request<AuditLogListResponse>(`/v1/audit?${params.toString()}`)
  },
  verifyAuditChain: () => request<VerifyChainResponse>('/v1/audit/verify'),

  listDemoPersonas: () => request<DemoPersonaInfo[]>('/v1/demo/personas'),
  submitDemoPersona: (personaId: string) =>
    request<{ id: string; persona_id: string }>(
      `/v1/demo/personas/${personaId}/submit`,
      {
        method: 'POST',
      },
    ),
}

/** Attaches the bearer token to a plain <img>/<a> URL for endpoints that
 * can't send an Authorization header (document viewer). We fetch as a blob
 * and hand back an object URL instead of trying to smuggle the token into
 * the URL itself. */
export async function fetchAuthedBlobUrl(path: string): Promise<string> {
  const token = tokenStore.get()
  const headers = new Headers()
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const res = await fetch(path, { headers })
  if (!res.ok)
    throw new ApiError(res.status, `Failed to load file (${res.status})`)
  const blob = await res.blob()
  return URL.createObjectURL(blob)
}
