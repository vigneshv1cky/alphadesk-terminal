/** Monochrome identity-provider marks, drawn in currentColor so they sit in
 * the terminal's palette instead of shouting brand colours. Shared by the
 * login gate's buttons and the Account page's provider chips; the label's
 * first letter is the fallback for a provider without a mark. */
export const PROVIDER_MARKS: Record<string, React.ReactNode> = {
  google: (
    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor" aria-hidden="true">
      <path d="M12 10.2v3.9h5.5c-.25 1.4-1.66 4.1-5.5 4.1-3.3 0-6-2.75-6-6.2s2.7-6.2 6-6.2c1.9 0 3.16.8 3.9 1.5l2.63-2.55C16.85 3.2 14.65 2 12 2 6.5 2 2 6.5 2 12s4.5 10 10 10c5.75 0 9.6-4.05 9.6-9.75 0-.7-.08-1.4-.2-2.05H12z" />
    </svg>
  ),
  github: (
    <svg viewBox="0 0 16 16" width="14" height="14" fill="currentColor" aria-hidden="true">
      <path d="M8 0C3.58 0 0 3.58 0 8c0 3.54 2.29 6.53 5.47 7.59.4.07.55-.17.55-.38 0-.19-.01-.82-.01-1.49-2.01.37-2.53-.49-2.69-.94-.09-.23-.48-.94-.82-1.13-.28-.15-.68-.52-.01-.53.63-.01 1.08.58 1.23.82.72 1.21 1.87.87 2.33.66.07-.52.28-.87.51-1.07-1.78-.2-3.64-.89-3.64-3.95 0-.87.31-1.59.82-2.15-.08-.2-.36-1.02.08-2.12 0 0 .67-.21 2.2.82.64-.18 1.32-.27 2-.27s1.36.09 2 .27c1.53-1.04 2.2-.82 2.2-.82.44 1.1.16 1.92.08 2.12.51.56.82 1.27.82 2.15 0 3.07-1.87 3.75-3.65 3.95.29.25.54.73.54 1.48 0 1.07-.01 1.93-.01 2.2 0 .21.15.46.55.38A8.01 8.01 0 0 0 16 8c0-4.42-3.58-8-8-8z" />
    </svg>
  ),
  microsoft: (
    <svg viewBox="0 0 16 16" width="13" height="13" fill="currentColor" aria-hidden="true">
      <path d="M0 0h7.5v7.5H0zM8.5 0H16v7.5H8.5zM0 8.5h7.5V16H0zM8.5 8.5H16V16H8.5z" />
    </svg>
  ),
}
