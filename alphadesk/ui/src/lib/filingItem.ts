/** THE SEC'S ITEM NAMES RUN LONG, and the count is the part that gets lost.
 * "Departure of Directors or Certain Officers; Election of Directors;
 * Appointment of Certain Officers: Compensatory Arrangements of Certain
 * Officers" pushed its own "· 1" off the end of the picker's option, so two
 * of the window's items looked like they had no filings behind them.
 *
 * Cut at the FIRST CLAUSE, which is where the SEC itself puts the substance,
 * and never in the middle of a word. Nothing is reworded — the full wording
 * is on every row that matches, and the number is the registrant's own choice
 * from a fixed list filed under signature. Pure, so it is tested.
 */
const ITEM_MAX = 52

export function shortItem(label: string): string {
  const clause = (label ?? "").split(/[;:]/)[0].trim()
  if (clause.length <= ITEM_MAX) return clause
  const cut = clause.slice(0, ITEM_MAX)
  const space = cut.lastIndexOf(" ")
  return `${(space > 20 ? cut.slice(0, space) : cut).trimEnd()}…`
}
