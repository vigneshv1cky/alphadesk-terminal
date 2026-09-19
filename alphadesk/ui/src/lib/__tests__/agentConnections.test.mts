import assert from "node:assert/strict"
import test from "node:test"
import { connectionGroups } from "../agentConnections.ts"

const row = (id: string, name: string, used: string | null) =>
  ({ grant_id: id, client_name: name, created_at: "2026-09-17T13:00:00Z", last_used_at: used })

test("one entry per app, however many consents are behind it", () => {
  // Four approvals of Claude.ai in one afternoon: four clients, one app.
  const groups = connectionGroups([
    row("g4", "Claude", "2026-09-17T15:42:48Z"),
    row("g3", "Claude", "2026-09-17T15:22:13Z"),
    row("g2", "Claude", "2026-09-17T15:21:46Z"),
    row("g1", "Claude", "2026-09-17T13:43:12Z"),
  ])
  assert.equal(groups.length, 1)
  assert.deepEqual(groups[0].ids, ["g4", "g3", "g2", "g1"])
  assert.equal(groups[0].last_used_at, "2026-09-17T15:42:48Z")
})

test("different apps stay apart, in the order the server listed them", () => {
  const groups = connectionGroups([
    row("g2", "Claude", null), row("g1", "ChatGPT", "2026-09-17T14:00:00Z"),
  ])
  assert.deepEqual(groups.map(g => g.name), ["Claude", "ChatGPT"])
})

test("the group's last use is the newest of its grants, unused staying unused", () => {
  const used = connectionGroups([row("g1", "Claude", null), row("g2", "Claude", "2026-09-17T09:00:00Z")])
  assert.equal(used[0].last_used_at, "2026-09-17T09:00:00Z")
  const never = connectionGroups([row("g1", "Claude", null), row("g2", "Claude", null)])
  assert.equal(never[0].last_used_at, null)
})

test("an app that registered without a name still groups", () => {
  const groups = connectionGroups([row("g1", "", null), row("g2", "", null)])
  assert.equal(groups.length, 1)
  assert.equal(groups[0].name, "agent app")
})
