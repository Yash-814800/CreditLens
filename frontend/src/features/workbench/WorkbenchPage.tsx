import { useQuery } from '@tanstack/react-query'
import { useParams } from 'react-router-dom'
import { api, ApiError } from '../../api/client'
import { LoadingBlock, ErrorBlock } from '../../components/Feedback'
import { StageStepper } from './StageStepper'
import { ResizableSplit } from './ResizableSplit'
import { DocumentIntake } from './DocumentIntake'
import { DecisionConsole } from './DecisionConsole'

const TERMINAL_STAGES = new Set(['COMPLETE', 'FAILED'])

/** The core two-panel underwriter workbench (Phase 7). Polls while the
 * pipeline is still running (Phase 6's `stage` field), then renders the full
 * document-intake + decision-console split once it reaches a terminal
 * stage. */
export function WorkbenchPage() {
  const { id } = useParams<{ id: string }>()
  const { data, isLoading, isError, error } = useQuery({
    queryKey: ['application', id],
    queryFn: () => api.getApplication(id!),
    enabled: Boolean(id),
    refetchInterval: (query) => (TERMINAL_STAGES.has(query.state.data?.stage ?? '') ? false : 1500),
  })

  if (isLoading) return <LoadingBlock label="Loading application…" />
  if (isError || !data) {
    return <ErrorBlock message={error instanceof ApiError ? error.message : 'Failed to load application.'} />
  }

  if (!TERMINAL_STAGES.has(data.stage)) {
    return (
      <div className="max-w-xl mx-auto space-y-4">
        <h1 className="text-lg font-semibold">{data.applicant_reference}</h1>
        <StageStepper stage={data.stage} errorCode={data.error_code} />
      </div>
    )
  }

  if (data.stage === 'FAILED') {
    return (
      <div className="max-w-xl mx-auto space-y-4">
        <h1 className="text-lg font-semibold">{data.applicant_reference}</h1>
        <StageStepper stage={data.stage} errorCode={data.error_code} />
      </div>
    )
  }

  const findings = data.fraud_report?.findings ?? []
  const left = <DocumentIntake applicationId={data.id} documents={data.documents} findings={findings} />
  const right = <DecisionConsole application={data} />

  return (
    <div className="space-y-3">
      <div className="flex items-center justify-between">
        <h1 className="text-lg font-semibold">
          {data.applicant_reference} <span className="text-slate-400 font-normal">· {data.applicant_name}</span>
        </h1>
      </div>
      <ResizableSplit left={left} right={right} />
    </div>
  )
}
