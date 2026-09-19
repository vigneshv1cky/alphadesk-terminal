import assert from "node:assert/strict"
import test from "node:test"
import { AGENT_CLIENTS, agentSetup, TOKEN_PLACEHOLDER } from "../agentSetup.ts"

const URL_ = "https://alphadesk.example.com/api/agent/tools/mcp"
const TOKEN = "adk_AbC-123_xyz"

test("Claude Code gets one command with the address and the bearer header", () => {
  const s = agentSetup("claude-code", URL_, TOKEN)
  assert.equal(s.kind, "command")
  assert.equal(s.text,
    `claude mcp add --transport http alphadesk "${URL_}" --header "Authorization: Bearer ${TOKEN}"`)
})

test("Cursor gets an mcpServers entry with url and headers", () => {
  const cfg = JSON.parse(agentSetup("cursor", URL_, TOKEN).text)
  assert.deepEqual(cfg, { mcpServers: { alphadesk: { url: URL_, headers: { Authorization: `Bearer ${TOKEN}` } } } })
})

test("opencode gets a remote mcp entry", () => {
  const cfg = JSON.parse(agentSetup("opencode", URL_, TOKEN).text)
  assert.deepEqual(cfg.mcp.alphadesk,
    { type: "remote", url: URL_, headers: { Authorization: `Bearer ${TOKEN}` }, enabled: true })
})

test("a connector app is not a client here — it takes the address alone", () => {
  // Claude.ai and ChatGPT sign in over OAuth, so the panel points them at
  // the server address row rather than offering a snippet to paste.
  assert.deepEqual(AGENT_CLIENTS.map(c => c.id), ["claude-code", "codex", "cursor", "opencode"])
})

test("without the token on screen, every snippet that holds one carries the placeholder", () => {
  for (const { id } of AGENT_CLIENTS.filter(c => agentSetup(c.id, URL_, null).tokenInline)) {
    const s = agentSetup(id, URL_, null)
    assert.ok(s.text.includes(TOKEN_PLACEHOLDER), id)
    assert.ok(!s.text.includes("adk_"), id)
  }
})

test("a shell snippet never lets a value break out of its quotes", () => {
  const s = agentSetup("claude-code", 'https://x/"; rm -rf ~; echo "', 'a$(b)`c`')
  assert.ok(s.text.includes('\\"; rm -rf ~; echo \\"'))
  assert.ok(s.text.includes("a\\$(b)\\`c\\`"))
})

test("Codex gets OpenAI's remote-server table, and the token stays out of the file", () => {
  // learn.chatgpt.com/docs/extend/mcp, checked 2026-09-18: [mcp_servers.<name>]
  // with url, and bearer_token_env_var naming where the token lives.
  const s = agentSetup("codex", URL_, TOKEN)
  assert.equal(s.kind, "toml")
  assert.equal(s.tokenInline, false)
  assert.equal(s.text,
    `[mcp_servers.alphadesk]\nurl = "${URL_}"\nbearer_token_env_var = "ALPHADESK_TOKEN"`)
  assert.ok(!s.text.includes(TOKEN) && !s.text.includes("adk_"))   // even with a fresh token on screen
  assert.ok(s.where.includes("ALPHADESK_TOKEN") && s.where.includes("~/.codex/config.toml"))
})

test("a TOML string never lets a value break out of its quotes", () => {
  const s = agentSetup("codex", 'https://x/" injected = "1', null)
  assert.ok(s.text.includes('url = "https://x/\\" injected = \\"1"'))
})
