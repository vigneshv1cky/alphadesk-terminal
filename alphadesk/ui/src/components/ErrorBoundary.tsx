import { Component, type ReactNode } from "react"
import { Btn } from "@/components/terminal"

/** A fence around one chart (2026-09-10). A render-time throw anywhere in
 * the tree unmounts the whole React root — the board went blank — and when
 * the cause is a saved preference, every reload does it again. Here the
 * chart alone shows the failure, with a way to clear what it was reading. */
export class ErrorBoundary extends Component<
  { children: ReactNode; label?: string; onReset?: () => void | Promise<void> },
  { error: Error | null }
> {
  state = { error: null as Error | null }
  static getDerivedStateFromError(error: Error) { return { error } }
  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="flex h-full min-h-[120px] flex-col items-center justify-center gap-2 px-4 py-6 text-center">
        <div className="text-body font-semibold">{this.props.label ?? "This chart"} hit an error and stopped.</div>
        <div className="max-w-[420px] text-caption text-muted-foreground">{String(this.state.error.message || this.state.error)}</div>
        <div className="mt-1 flex gap-1.5">
          <Btn onClick={() => this.setState({ error: null })}>Try again</Btn>
          {this.props.onReset && (
            <Btn variant="accent" onClick={() => { void Promise.resolve(this.props.onReset?.()).then(() => this.setState({ error: null })) }}>
              Reset chart settings
            </Btn>
          )}
        </div>
      </div>
    )
  }
}
