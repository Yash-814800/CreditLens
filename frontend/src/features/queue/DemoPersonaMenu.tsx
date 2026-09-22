import { useState } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useNavigate } from 'react-router-dom'
import { FlaskConical, ChevronDown } from 'lucide-react'
import { api } from '../../api/client'

/** "Load demo persona" menu (Phase 7 spec), only shown to underwriter/admin
 * and only meaningful when the backend has ENABLE_DEMO_ENDPOINTS=true --
 * listDemoPersonas 404s otherwise, which we treat as "hide the menu". */
export function DemoPersonaMenu() {
  const [open, setOpen] = useState(false)
  const navigate = useNavigate()
  const queryClient = useQueryClient()

  const { data: personas } = useQuery({
    queryKey: ['demo-personas'],
    queryFn: api.listDemoPersonas,
    retry: false,
  })

  const submit = useMutation({
    mutationFn: api.submitDemoPersona,
    onSuccess: (res) => {
      setOpen(false)
      queryClient.invalidateQueries({ queryKey: ['applications'] })
      navigate(`/applications/${res.id}`)
    },
  })

  if (!personas || personas.length === 0) return null

  return (
    <div className="relative">
      <button
        onClick={() => setOpen((o) => !o)}
        className="flex items-center gap-1.5 rounded-md border border-slate-300 dark:border-slate-700 px-3 py-1.5 text-sm hover:bg-slate-100 dark:hover:bg-slate-800"
      >
        <FlaskConical size={14} aria-hidden="true" />
        Load demo persona
        <ChevronDown size={14} aria-hidden="true" />
      </button>
      {open && (
        <div className="absolute right-0 z-20 mt-1 w-80 rounded-md border border-slate-200 dark:border-slate-700 bg-white dark:bg-slate-900 shadow-lg max-h-96 overflow-y-auto">
          {personas.map((p) => (
            <button
              key={p.persona_id}
              disabled={submit.isPending}
              onClick={() => submit.mutate(p.persona_id)}
              className="w-full text-left px-3 py-2 text-sm hover:bg-slate-50 dark:hover:bg-slate-800 border-b border-slate-100 dark:border-slate-800 last:border-0 disabled:opacity-50"
            >
              <div className="font-medium">
                {p.persona_id} · <span className="font-normal text-slate-500">{p.expected_outcome}</span>
              </div>
              <div className="text-xs text-slate-500 dark:text-slate-400">{p.notes}</div>
            </button>
          ))}
        </div>
      )}
    </div>
  )
}
