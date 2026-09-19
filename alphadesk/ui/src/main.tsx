import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { ApiError } from './lib/api'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import './index.css'
import App from './App.tsx'

// Every deploy replaces the hashed chunk names, so a tab left open across
// one asks for files that no longer exist and lazy routes fail to load —
// "the Markets tab looks broken" until a hard reload. Vite announces that
// exact failure; answering it with a reload picks up the new shell, and the
// URL carries the whole board state so nothing is lost.
window.addEventListener("vite:preloadError", () => {
  window.location.reload()
})

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Keep polling while the tab is in the background. This is NOT the
      // default: TanStack Query pauses refetchInterval on a hidden document,
      // which would be right for a normal web app and wrong for a terminal —
      // this thing lives on a second monitor, and the old setInterval polled
      // regardless of focus. Without it the desk silently freezes whenever it
      // is not the focused tab.
      refetchIntervalInBackground: true,
      // Each widget already polls on its own interval, so a focus refetch
      // would just fire a burst of redundant requests on every tab switch.
      refetchOnWindowFocus: false,
      // Keep the last good data on screen while a refetch is in flight — on a
      // grid of a dozen tiles, blanking one because a poll is mid-flight reads
      // as breakage.
      placeholderData: (prev: unknown) => prev,
      staleTime: 5_000,
      // A missing data key is an answer, not a transient failure: asking
      // again cannot fill it.
      retry: (count: number, err: unknown) => !(err instanceof ApiError && (err.status === 428 || err.status === 402)) && count < 1,
    },
  },
})

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
    </QueryClientProvider>
  </StrictMode>,
)
