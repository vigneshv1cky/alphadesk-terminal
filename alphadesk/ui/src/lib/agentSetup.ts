/** Ready-to-paste setup for connecting a reader's own agent to AlphaDesk's
 * tool server (2026-09-17). Each client wants the same two facts — the
 * server address and the bearer token — in its own shape.
 *
 * The token is filled in only while it is on screen for the first (and only)
 * time; otherwise the snippet carries a placeholder, because the page never
 * has the token again.
 */

/** Connector apps (Claude.ai, ChatGPT) are deliberately absent: they take the
 * bare server address and sign the reader in over OAuth, so their "snippet"
 * was the address already shown at the top of the panel, copied twice
 * (2026-09-17). The address row carries that instruction instead. */
export type AgentClient = "claude-code" | "cursor" | "opencode" | "codex"

export const TOKEN_PLACEHOLDER = "YOUR_ALPHADESK_TOKEN"

export interface AgentSetup {
  client: AgentClient
  label: string
  /** Where the snippet goes, in words. */
  where: string
  /** "command" runs in a terminal; "json" and "toml" are merged into a
   * config file. */
  kind: "command" | "json" | "toml"
  text: string
  /** Whether the token is written INTO the snippet. False for Codex, which
   * reads it from an environment variable — so the page must not promise to
   * fill it in, nor warn that the file holds it. */
  tokenInline: boolean
}

export const AGENT_CLIENTS: { id: AgentClient; label: string }[] = [
  { id: "claude-code", label: "Claude Code" },
  { id: "codex", label: "Codex" },
  { id: "cursor", label: "Cursor" },
  { id: "opencode", label: "opencode" },
]

/** The environment variable Codex reads the token from. */
export const CODEX_TOKEN_ENV = "ALPHADESK_TOKEN"

/** A TOML basic string: backslash and double quote escaped. An address is a
 * URL, so this is belt and braces, as shellQuote is below. */
function tomlString(value: string): string {
  return `"${value.replace(/(["\\])/g, "\\$1")}"`
}

const SERVER_NAME = "alphadesk"

/** Double quotes and backslashes escaped for a POSIX shell argument in "…".
 * A token is URL-safe base64 and an address is a URL, so this is belt and
 * braces — but a snippet someone pastes into a shell must never surprise. */
function shellQuote(value: string): string {
  return `"${value.replace(/(["\\$`])/g, "\\$1")}"`
}

export function agentSetup(client: AgentClient, url: string, token?: string | null): AgentSetup {
  const tok = token || TOKEN_PLACEHOLDER
  const auth = `Bearer ${tok}`
  switch (client) {
    case "claude-code":
      return {
        client, label: "Claude Code", kind: "command", tokenInline: true,
        where: "Run in a terminal. Add --scope user to use it in every project.",
        text: `claude mcp add --transport http ${SERVER_NAME} ${shellQuote(url)} --header ${shellQuote(`Authorization: ${auth}`)}`,
      }
    case "cursor":
      return {
        client, label: "Cursor", kind: "json", tokenInline: true,
        where: "Merge into ~/.cursor/mcp.json (every project) or .cursor/mcp.json (one project).",
        text: JSON.stringify({ mcpServers: { [SERVER_NAME]: { url, headers: { Authorization: auth } } } }, null, 2),
      }
    case "opencode":
      return {
        client, label: "opencode", kind: "json", tokenInline: true,
        where: "Merge into ~/.config/opencode/opencode.json (every project) or opencode.json (one project).",
        text: JSON.stringify({
          $schema: "https://opencode.ai/config.json",
          mcp: { [SERVER_NAME]: { type: "remote", url, headers: { Authorization: auth }, enabled: true } },
        }, null, 2),
      }
    case "codex":
      // OpenAI's documented form for a remote server (checked 2026-09-18 at
      // learn.chatgpt.com/docs/extend/mcp): a [mcp_servers.<name>] table with
      // `url`, and the token named by `bearer_token_env_var` rather than
      // written into the file. There is no `codex mcp add` for a remote
      // server — the docs show that command for local ones only.
      return {
        client, label: "Codex", kind: "toml", tokenInline: false,
        where: `Merge into ~/.codex/config.toml (every project) or .codex/config.toml (one project), then set ${CODEX_TOKEN_ENV} to your token in the shell Codex runs from — it reads the token from there, so none is written into the file.`,
        text: `[mcp_servers.${SERVER_NAME}]\nurl = ${tomlString(url)}\nbearer_token_env_var = ${tomlString(CODEX_TOKEN_ENV)}`,
      }
  }
}
