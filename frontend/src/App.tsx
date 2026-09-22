import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Navigate, Route, Routes } from 'react-router-dom'
import { AuthProvider } from './auth/AuthContext'
import { RequireAuth } from './auth/RequireAuth'
import { AppShell } from './components/AppShell'
import { ErrorBoundary } from './components/ErrorBoundary'
import { LoginPage } from './features/login/LoginPage'
import { ApplicationsQueuePage } from './features/queue/ApplicationsQueuePage'
import { NewApplicationPage } from './features/new-application/NewApplicationPage'
import { WorkbenchPage } from './features/workbench/WorkbenchPage'
import { SyndicateGraphPage } from './features/syndicate/SyndicateGraphPage'
import { AuditLogPage } from './features/audit/AuditLogPage'
import { ScorecardPage } from './features/scorecard/ScorecardPage'

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
})

/** Routed cockpit shell (Phase 7). Replaces the Phase 0 healthz placeholder. */
function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <BrowserRouter>
        <AuthProvider>
          <Routes>
            <Route path="/login" element={<LoginPage />} />
            <Route
              path="/*"
              element={
                <RequireAuth>
                  <AppShell>
                    <ErrorBoundary>
                      <Routes>
                        <Route path="/" element={<Navigate to="/applications" replace />} />
                        <Route path="/applications" element={<ApplicationsQueuePage />} />
                        <Route path="/applications/new" element={<NewApplicationPage />} />
                        <Route path="/applications/:id" element={<WorkbenchPage />} />
                        <Route path="/syndicate" element={<SyndicateGraphPage />} />
                        <Route
                          path="/audit"
                          element={
                            <RequireAuth roles={['auditor', 'admin']}>
                              <AuditLogPage />
                            </RequireAuth>
                          }
                        />
                        <Route path="/scorecard" element={<ScorecardPage />} />
                        <Route path="*" element={<Navigate to="/applications" replace />} />
                      </Routes>
                    </ErrorBoundary>
                  </AppShell>
                </RequireAuth>
              }
            />
          </Routes>
        </AuthProvider>
      </BrowserRouter>
    </QueryClientProvider>
  )
}

export default App
