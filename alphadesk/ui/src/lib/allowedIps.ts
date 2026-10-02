/** The addresses a new agent token may be used from (2026-10-02): turning the
 * text a reader typed into the list the server takes, and naming any entry
 * that is not an address or range before anything is sent. The server checks
 * again; this is so the reader hears it at the field. */

const V4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/(\d{1,2}))?$/
const V6 = /^[0-9a-fA-F:.]*:[0-9a-fA-F:.]*(?:\/(\d{1,3}))?$/

function valid(entry: string): boolean {
  const v4 = V4.exec(entry)
  if (v4) return v4.slice(1, 5).every(o => Number(o) <= 255) && (v4[5] === undefined || Number(v4[5]) <= 32)
  const v6 = V6.exec(entry)
  return v6 !== null && (v6[1] === undefined || Number(v6[1]) <= 128)
}

/** Entries separated by commas or new lines, trimmed; an empty box is no
 * restriction. Throws naming the first entry that is not an address or range. */
export function parseAllowedIps(text: string): string[] {
  const entries = text.split(/[,\n]/).map(e => e.trim()).filter(Boolean)
  for (const entry of entries) {
    if (!valid(entry)) throw new Error(`${entry} is not an address or range`)
  }
  return entries
}
