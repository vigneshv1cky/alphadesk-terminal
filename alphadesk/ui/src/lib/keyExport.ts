/** The pure parts of exporting the reader's keys (2026-10-02): checking the
 * passphrase before anything is sent, and naming the saved file. */

/** Must match the server's floor (alphadesk/ledger/keyexport.py): it refuses a
 * shorter passphrase anyway, but the reader should hear it before the trip. */
export const MIN_PASSPHRASE = 12

/** What is wrong with the two passphrase entries, or null when nothing is.
 * Length is counted in characters (code points), as the server counts it. */
export function passphraseProblem(passphrase: string, again: string): string | null {
  if ([...passphrase].length < MIN_PASSPHRASE) return `Use at least ${MIN_PASSPHRASE} characters.`
  if (passphrase !== again) return "The two entries do not match."
  return null
}

const FALLBACK_NAME = "alphadesk-keys.json"

/** The file's name from the response's Content-Disposition, or a safe default.
 * Only a plain name is accepted — a header naming a path is not trusted to
 * decide where the browser saves. */
export function downloadName(disposition: string | null): string {
  const name = /filename="([^"]+)"/.exec(disposition ?? "")?.[1]
  return name && /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(name) ? name : FALLBACK_NAME
}
