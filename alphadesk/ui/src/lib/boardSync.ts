/** WHICH COPY OF A BOARD WINS (2026-09-21).
 *
 * A board is held in three places: the URL, this browser, and the reader's
 * account. The first attempt at keeping them together let the browser win
 * whenever it had anything at all, which meant two devices that had both
 * been used each kept their own board forever and never converged — the
 * exact fault it was meant to fix.
 *
 * The rule is now simply that the LATER ARRANGEMENT WINS, with two edges
 * that matter more than they look:
 *
 *   * A local copy with NO time predates all of this. It loses to a row on
 *     the account, because that row is an arrangement somebody saved,
 *     whereas an undated local copy might be anything.
 *   * A page the account has never seen is pushed UP rather than left
 *     behind, so a board arranged before any of this existed still reaches
 *     the account without being touched again.
 *
 * Pure, and separate from the hooks, because this is the part that was
 * wrong the first time.
 */

export type Side = { tiles: string; at: string | null | undefined }
export type Verdict = "keep" | "adopt" | "push"

/** What to do with `mine` given `theirs`: keep what this browser has, adopt
 * the account's, or push this browser's up to the account. */
export function whichWins(mine: Side, theirs: Side | null | undefined): Verdict {
  if (!theirs?.tiles) return mine.tiles ? "push" : "keep"
  if (!mine.tiles) return "adopt"
  if (theirs.tiles === mine.tiles) return "keep"
  // Undated local copy: older than the feature, so the saved one wins.
  if (!mine.at) return "adopt"
  if (!theirs.at) return "push"
  return theirs.at > mine.at ? "adopt" : "push"
}
