import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { on, api } from "@/lib/api"
import { Widget, btnCls, fieldCls } from "@/components/terminal"
import { BTN, BTN_DANGER, BTN_PRIMARY, Heading, Pill, Row, SubLabel } from "@/components/accountParts"
import { AGENT_CLIENTS, agentSetup, dataApiSetup, dataApiUrl, type AgentClient } from "@/lib/agentSetup"
import { connectionGroups } from "@/lib/agentConnections"
import { parseAllowedIps } from "@/lib/allowedIps"

/** Agent access, on its own page (2026-10-02). It sat as one panel at the
 * foot of the Account page and mixed four jobs — the server address, the
 * connected apps, the tokens, and the setup snippets — with no word on what a
 * token is or which way in suits which tool. Each job is a card here, opening
 * with a plain sentence on what it is for, and the data API for ordinary
 * programs has its own tab beside the agent clients.
 *
 * Nothing here can trade or change anything: every door it opens is read-only,
 * and a call runs as the reader on their own keys. */

type Tab = AgentClient | "program"

const GUIDE = "https://github.com/vigneshv1cky/alphadesk-terminal/blob/main/docs/rest-api.md"

/** The sentence under a card's title: what it is for, in words. Not a caption
 * (those truncate to one line): this is meant to be read. */
function About({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-3 text-caption leading-[1.55] text-muted-foreground">{children}</p>
}

export default function AgentAccessPage() {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ["agent-access-tokens"], queryFn: ({ signal }) => on(signal).agentAccessTokens() })
  const connections = useQuery({ queryKey: ["agent-connections"], queryFn: ({ signal }) => on(signal).agentConnections() })
  const [name, setName] = useState("")
  const [ips, setIps] = useState("")
  const [fresh, setFresh] = useState<{ id: string; token: string } | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>("claude-code")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const url = list.data?.url ?? ""
  const tokens = list.data?.tokens ?? []
  const groups = connectionGroups(connections.data?.connections ?? [])

  const issue = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true); setError(null); setCopied(null)
    try {
      // Parsed first: an entry that is not an address is named in the field's
      // own error before anything is sent or any token is made.
      const made = await api.issueAgentAccessToken(name.trim(), parseAllowedIps(ips))
      setFresh({ id: made.token_id, token: made.token })
      setName("")
      setIps("")
      void qc.invalidateQueries({ queryKey: ["agent-access-tokens"] })
    } catch (err) {
      setError(String((err as Error).message ?? err))
    } finally {
      setBusy(false)
    }
  }
  const revoke = async (id: string) => {
    try {
      await api.revokeAgentAccessToken(id)
      if (fresh?.id === id) setFresh(null)
      void qc.invalidateQueries({ queryKey: ["agent-access-tokens"] })
    } catch (err) {
      setError(String((err as Error).message ?? err))
    }
  }
  /** Disconnect every grant in one app's group. An app that registers afresh
   * each time it is added (Claude.ai does) is a different client to the
   * server on every add, so its rows cannot be collapsed server-side. */
  const disconnect = async (ids: string[]) => {
    try {
      for (const id of ids) await api.revokeAgentConnection(id)
      void qc.invalidateQueries({ queryKey: ["agent-connections"] })
    } catch (err) {
      setError(String((err as Error).message ?? err))
    }
  }
  const copy = (what: string, text: string) => {
    void navigator.clipboard?.writeText(text).then(() => setCopied(what), () => setCopied(null))
  }

  const setup = url
    ? (tab === "program" ? dataApiSetup(url, fresh?.token) : agentSetup(tab, url, fresh?.token))
    : null
  const tabs: { id: Tab; label: string }[] = [...AGENT_CLIENTS, { id: "program", label: "Your own program" }]

  return (
    <div className="collage mx-auto w-full max-w-[1160px] !pb-4">
      <p className="px-1 text-body leading-[1.55] text-muted-foreground" style={{ gridColumn: "span 12 / span 12" }}>
        Let your own AI assistant or your own program read AlphaDesk's data <strong className="text-foreground">as you</strong>,
        on the market-data keys you have connected. It is read-only: nothing here can place an order or change anything
        in your account.
      </p>

      <Widget span={6} title={<Heading>AI assistants</Heading>} subtitle="Claude.ai, ChatGPT and other chat apps" bodyClassName="@container">
        <About>
          The easiest way in. Add AlphaDesk to your assistant as a connector using the address below, sign in when it
          asks, and allow it. No token is needed.
        </About>
        <Row label="Server address"
             actions={url ? <button type="button" className={BTN} onClick={() => copy("url", url)}>
               {copied === "url" ? "Copied" : "Copy"}</button> : null}>
          <code className="num block break-all text-caption text-foreground">{url || "…"}</code>
        </Row>
        <SubLabel>Connected apps</SubLabel>
        {groups.length ? groups.map(g => (
          <Row key={g.name + g.ids[0]} label={<span className="truncate">{g.name}</span>}
               actions={<button type="button" onClick={() => void disconnect(g.ids)} className={BTN_DANGER}>
                 {g.ids.length > 1 ? `Disconnect ${g.ids.length}` : "Disconnect"}</button>}>
            {g.ids.length > 1 ? `${g.ids.length} connections` : "1 connection"} · {g.last_used_at
              ? `last used ${new Date(g.last_used_at).toLocaleString()}`
              : "not used yet"}
          </Row>
        )) : (
          <div className="row-rule px-4 py-3 text-caption text-muted-foreground">
            none yet — add the address above as a connector in your assistant
          </div>
        )}
      </Widget>

      <Widget span={6} title={<Heading>Tokens</Heading>} subtitle="for your own programs and tools"
              actions={<Pill tone="muted">{tokens.length} of 10 live</Pill>} bodyClassName="@container">
        <About>
          A token is a password for one program. Make one for each program you run, so you can switch one off without
          touching the others. It is shown <strong className="text-foreground">once</strong>, when you create it: copy
          it straight away. Anyone who holds it can read your data until you revoke it.
        </About>
        {tokens.map(t => (
          <Row key={t.token_id} label={<span className="truncate">{t.name}</span>}
               actions={<button type="button" onClick={() => void revoke(t.token_id)} className={BTN_DANGER}>Revoke</button>}>
            {fresh?.id === t.token_id ? (
              <>
                <span className="flex min-w-0 flex-wrap items-center gap-2">
                  <code className="num min-w-0 break-all text-foreground">{fresh.token}</code>
                  <button type="button" className={BTN} onClick={() => copy("token", fresh.token)}>
                    {copied === "token" ? "Copied" : "Copy"}
                  </button>
                </span>
                <span className="block text-label text-warn">Copy it now: it is not shown again.</span>
              </>
            ) : (
              <>
                ····{t.hint} · {t.last_used_at ? `last used ${new Date(t.last_used_at).toLocaleString()}` : "not used yet"}
                {" · "}{t.allowed_ips?.length ? `only from ${t.allowed_ips.join(", ")}` : "from any address"}
              </>
            )}
          </Row>
        ))}
        <SubLabel>New token</SubLabel>
        {/* The form draws the rule: its last row drops its own, which left the
            card with no line above what follows (2026-09-18). */}
        <form onSubmit={issue} className="border-b border-row-rule">
          <Row label="Name" actions={<button type="submit" disabled={busy} className={BTN_PRIMARY}>{busy ? "…" : "Create"}</button>}>
            <input value={name} onChange={e => setName(e.target.value)} maxLength={60}
                   aria-label="Name the program this token is for"
                   placeholder="which program, e.g. my trading bot"
                   className={`${fieldCls} w-full`} />
            <span className="mt-1.5 block">What it is for, so you can tell tokens apart later.</span>
          </Row>
          <Row label="Only from">
            <input value={ips} onChange={e => setIps(e.target.value)} maxLength={400}
                   aria-label="Addresses this token may be used from (optional)"
                   placeholder="optional, e.g. 203.0.113.7, 198.51.100.0/24"
                   className={`${fieldCls} w-full`} />
            <span className="mt-1.5 block">
              Optional. The address your program runs from, such as your server's. A token tied to an address is
              refused from anywhere else, so a leaked one is useless. Leave it empty to allow any address; for
              several, separate them with commas. You cannot change it later — make a new token instead.
            </span>
          </Row>
        </form>
        {error && <div className="px-4 py-2 text-caption text-loss">{error}</div>}
      </Widget>

      <Widget span={12} title={<Heading>Connect a tool</Heading>} subtitle="ready-to-paste setup" bodyClassName="@container">
        <About>
          Pick what you use. A snippet already holds your new token while it is on screen; once you leave, it shows a
          placeholder, because the page never sees a token again. <strong className="text-foreground">Your own program</strong>{" "}
          is for code that is not an AI assistant, such as a script or a trading bot, using the plain data API.
        </About>
        <SubLabel right={
          <span role="tablist" aria-label="Tool" className="flex flex-wrap gap-1.5">
            {tabs.map(c => (
              <button key={c.id} type="button" role="tab" aria-selected={tab === c.id}
                      onClick={() => { setTab(c.id); setCopied(null) }}
                      // Selected by a soft fill, not a red outline (2026-09-18, the owner's call).
                      className={btnCls({ size: "sm", active: tab === c.id }, "rounded-md normal-case tracking-normal")}>
                {c.label}
              </button>
            ))}
          </span>
        }>{tab === "program" ? "Data API" : "Connect a client"}</SubLabel>
        {setup ? (
          <div className="row-rule px-4 py-3.5">
            <div className="flex items-start gap-3">
              <span className="min-w-0 flex-1 text-caption leading-[1.45] text-muted-foreground">
                {setup.where}{" "}
                {!setup.tokenInline ? null : fresh
                  ? "It holds your new token, so keep it out of version control."
                  : "Create a token above and it is filled in here while it is shown."}
              </span>
              <button type="button" className={BTN} onClick={() => copy("setup", setup.text)}>
                {copied === "setup" ? "Copied" : "Copy"}
              </button>
            </div>
            <pre className="num mt-2 overflow-x-auto whitespace-pre rounded-sm border border-border bg-background px-3 py-2 text-caption leading-[1.45]">{setup.text}</pre>
            {tab === "program" && (
              <p className="mt-2 text-caption leading-[1.5] text-muted-foreground">
                The first call is a quote; the second is every daily bar of history. The endpoints and their inputs
                are listed at <code className="num text-foreground">{dataApiUrl(url)}/openapi.json</code> (it needs
                your token too). The full guide is{" "}
                <a href={GUIDE} target="_blank" rel="noreferrer" className="text-foreground underline underline-offset-2">in the repository</a>.
                It answers requests; it does not stream, so it suits research and slower decisions, not live ticks.
              </p>
            )}
          </div>
        ) : null}
      </Widget>

      <Widget span={12} title={<Heading>Limits and safety</Heading>} bodyClassName="@container">
        <ul className="list-disc space-y-1.5 py-3 pl-9 pr-4 text-caption leading-[1.55] text-muted-foreground">
          <li><strong className="text-foreground">Read-only.</strong> Nothing here can place an order, move money or change your account. Your program sends any orders through its own broker.</li>
          <li><strong className="text-foreground">Runs as you.</strong> Every call uses your own market-data keys. If a key is missing, the answer says which vendor would fill the gap.</li>
          <li><strong className="text-foreground">120 requests a minute</strong> per token. A program can read how many it has left from each answer, and is told how long to wait if it goes over.</li>
          <li><strong className="text-foreground">Revoking is immediate.</strong> A revoked token stops working at once, and removing a connected app cuts it off the same way.</li>
        </ul>
      </Widget>
    </div>
  )
}
