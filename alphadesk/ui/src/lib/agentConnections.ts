/** Connected agent apps, one entry per app rather than one per consent
 * (2026-09-17).
 *
 * A grant is created on every completed consent, and the server collapses a
 * repeat consent by the SAME registered app. It cannot collapse more than
 * that: Claude.ai registers afresh every time a connector is added, so four
 * approvals in one afternoon of testing left four rows all reading "Claude",
 * each a different client to the server and each holding its own 90-day
 * refresh token. Four identical rows read as a fault in the page.
 *
 * So the page groups by the name the reader recognises, shows how many
 * connections sit behind it, and disconnects them together.
 */

export interface AgentConnection {
  grant_id: string
  client_name: string
  created_at: string
  last_used_at: string | null
}

export interface ConnectionGroup {
  name: string
  /** Every grant in the group, newest first — what Disconnect revokes. */
  ids: string[]
  /** The newest use across the group, or null when none has been used. */
  last_used_at: string | null
}

export function connectionGroups(rows: AgentConnection[]): ConnectionGroup[] {
  const groups = new Map<string, ConnectionGroup>()
  for (const row of rows) {
    const name = (row.client_name || "agent app").trim()
    const at = groups.get(name)
    if (!at) {
      groups.set(name, { name, ids: [row.grant_id], last_used_at: row.last_used_at })
      continue
    }
    at.ids.push(row.grant_id)
    // Strings, but ISO-8601 in UTC throughout, so lexical order is time order.
    if (row.last_used_at && (!at.last_used_at || row.last_used_at > at.last_used_at)) {
      at.last_used_at = row.last_used_at
    }
  }
  return [...groups.values()]
}
