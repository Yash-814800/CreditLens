import { Component, type ReactNode } from 'react'
import { AlertTriangle } from 'lucide-react'

interface Props {
  children: ReactNode
}
interface State {
  error: Error | null
}

/** Catches render-time crashes in any subtree so one broken panel (e.g. a
 * malformed fraud-report shape) can't blank the entire workbench. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error) {
    console.error('ErrorBoundary caught:', error)
  }

  render() {
    if (this.state.error) {
      return (
        <div
          role="alert"
          className="flex flex-col items-center gap-2 rounded-lg border border-red-200 bg-red-50 p-6 text-center text-red-800 dark:border-red-900 dark:bg-red-950 dark:text-red-300"
        >
          <AlertTriangle size={24} aria-hidden="true" />
          <p className="font-semibold">Something went wrong rendering this section.</p>
          <p className="text-sm opacity-80">{this.state.error.message}</p>
        </div>
      )
    }
    return this.props.children
  }
}
