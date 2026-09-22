/** Domain types re-exported from the generated OpenAPI schema (src/api/schema.d.ts)
 * so the rest of the app never hand-duplicates a backend shape -- if a Pydantic
 * model changes, `npm run gen:api` regenerates schema.d.ts and every consumer
 * here fails to typecheck until it's updated, instead of silently drifting. */
import type { components } from './schema.d.ts'

type Schemas = components['schemas']

export type ApplicationSummary = Schemas['ApplicationSummary']
export type ApplicationListResponse = Schemas['ApplicationListResponse']
export type ApplicationDetail = Schemas['ApplicationDetail']
export type DocumentSummary = Schemas['DocumentSummary']
export type FraudReport = Schemas['FraudReport']
export type Finding = Schemas['Finding']
export type DocumentRadar = Schemas['DocumentRadar']
export type GraphEdge = Schemas['GraphEdge']
export type SanitizationReport = Schemas['SanitizationReport']
export type RemovedField = Schemas['RemovedField']
export type ScoreBreakdown = Schemas['ScoreBreakdown']
export type ScoreFactor = Schemas['ScoreFactor']
export type Decision = Schemas['Decision']
export type RecourseAction = Schemas['RecourseAction']
export type PrecedentPanel = Schemas['PrecedentPanel']
export type PrecedentMatchOut = Schemas['PrecedentMatchOut']
export type SummaryResult = Schemas['SummaryResult']
export type AdverseActionNotice = Schemas['AdverseActionNotice']
export type AuditLogEntry = Schemas['AuditLogEntry']
export type AuditLogListResponse = Schemas['AuditLogListResponse']
export type VerifyChainResponse = Schemas['VerifyChainResponse']
export type DemoPersonaInfo = Schemas['DemoPersonaInfo']
export type LoginRequest = Schemas['LoginRequest']
export type LoginResponse = Schemas['LoginResponse']
export type MeResponse = Schemas['MeResponse']
export type OverrideRequest = Schemas['OverrideRequest']

export type Outcome = 'APPROVE' | 'REFER' | 'DECLINE'
export type FraudSeverity = 'NONE' | 'LOW' | 'MEDIUM' | 'HIGH'
export type Role = 'underwriter' | 'auditor' | 'admin'
export type DocType = 'GIG_PAYOUT' | 'UTILITY_BILL' | 'BANK_STATEMENT'

export interface ScorecardMeta {
  scorecard: Record<string, unknown>
  policy: Record<string, unknown>
}

export interface ConsentMeta {
  text: string
  version: string
  sha256: string
}

export interface FraudGraphResponse {
  edges: Array<{
    applicant_a: string
    applicant_b: string
    doc_type: string
    hamming_distance: number | null
    sha256_match: boolean
    severity: string
    corroborated: boolean
  }>
}
