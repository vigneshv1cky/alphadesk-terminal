import { LogOut } from "lucide-react"
import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { on, api, type Access } from "@/lib/api"
import { useAuthMe, useSystem, useUserKeys } from "@/lib/queries"
import { Dialog, Empty, fieldCls, Table, TD, TH, THead, TR, Widget, btnCls } from "@/components/terminal"
import { PROVIDER_MARKS } from "@/components/providerMarks"
import { DeleteAccountDialog } from "@/components/DeleteAccountDialog"
import { AGENT_CLIENTS, agentSetup, type AgentClient } from "@/lib/agentSetup"
import { connectionGroups } from "@/lib/agentConnections"

/** The signed-in user's own page, in the Masthead direction (picked from
 * the design canvas, 2026-09-02): identity as a full-width band — avatar,
 * email, provider chips, a quiet sign-out — with the data panels beneath
 * it. Data goes in table cells; the one sentence of context a panel needs
 * goes in a muted caption under the table, and the roadmap lives in
 * docs/hosted-mode.md, not on screen.
 *
 * Honest to a fault about what exists: the usage meter is the reader's own
 * calls, the Keys panel states plainly whose credential serves each seam
 * (yours when a key is stored, the operator's otherwise), and captions
 * carry the real caps (48h activity window, 100 articles a cycle).
 *
 * On an open (auth off) instance the page says so instead of pretending
 * there is an account.
 */

/** The caption under a panel's table — muted, never bold. One line where the
 * panel is wide enough to hold it; below 520px it wraps rather than ending
 * in an ellipsis, because a clipped sentence is not a caption. */
function Caption({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-4 py-2.5 text-label leading-[1.45] text-muted-foreground @[520px]:truncate">
      {children}
    </div>
  )
}

/** A stat tile — the System page's anatomy, so the two pages read alike.
 * Below 640px of panel it is a list row instead, label left and value right
 * on one line (2026-09-19, the owner: the account "doesnt look good in
 * mobile" — a 2×2 grid of 18px figures wrapped "1,041 stories · 24h" and
 * "0 apps · 0 tokens" over two lines, and the cells' labels sat at different
 * heights). */
function StatCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex min-w-0 items-baseline justify-between gap-3 border-b border-row-rule px-4 py-3 last:border-b-0
                    @[640px]:flex-col @[640px]:items-start @[640px]:justify-center @[640px]:gap-1.5 @[640px]:border-b-0
                    @[640px]:border-r @[640px]:py-6 @[640px]:last:border-r-0">
      <div className="shrink-0 truncate text-label font-medium uppercase tracking-caps text-muted-foreground">{label}</div>
      <div className="num min-w-0 truncate text-body font-bold leading-[1.2] @[640px]:text-figure @[640px]:font-extrabold">{value}</div>
    </div>
  )
}

const labelCls = "mb-1 block text-label font-medium uppercase tracking-caps text-muted-foreground"

/** One row of the Account page: a name, what is on file, and the buttons.
 *
 * ONE SHAPE AT EVERY WIDTH (2026-09-17, the owner's call): the name and its
 * buttons take the first line, and what is on file reads beneath the name
 * across the full width. The row was three-across — a fixed 140px name, a
 * flexible note, the buttons — which at ~360px of pane left the note about
 * 30px wide, one word per line with the buttons printed over it, and at
 * full width left a block of empty space under every name while the note
 * wrapped in a narrow middle column. */
function Row({ label, children, actions }: {
  label: React.ReactNode
  children: React.ReactNode
  actions?: React.ReactNode
}) {
  return (
    <div className="row-rule grid grid-cols-[minmax(0,1fr)_auto] items-start gap-x-3 gap-y-1.5 px-4 py-3.5">
      <span className="min-w-0 text-body font-extrabold">{label}</span>
      <span className="col-span-2 min-w-0 text-caption leading-[1.45] text-muted-foreground">
        {children}
      </span>
      <span className="col-start-2 row-start-1 flex shrink-0 justify-end gap-1.5">
        {actions}
      </span>
    </div>
  )
}

/* The shared small button, 20px caps (2026-09-18, the owner's call): at 22px
   and 12px a row of Replace / Remove outweighed the vendor name it acts on. */
const BTN = btnCls({ size: "sm" })
const BTN_DANGER = btnCls({ variant: "danger", size: "sm" })
/* The way forward on a row (Connect, Add key, Create) differs from Replace
   only in full-strength text: a red outline on every unconnected vendor made
   the table shout at the reader to click (2026-09-18, the owner's call). */
const BTN_PRIMARY = btnCls({ variant: "strong", size: "sm" })

/* Taller rows for the Account tables only (2026-09-18, the owner's call): a
   row carries a key, a status pill and two buttons, and 30px read cramped.
   A descendant rule, because the shared cell hard-codes its own height and,
   without tailwind-merge, a second height class on it would not reliably
   win; this one outranks it by specificity and touches no other table. */
const ROOMY = "[&_td]:h-[44px]"

/** A panel title in the accent red (2026-09-18, the owner's call) — the same
 * red the board gives a widget's symbol prefix, so the colour means "a
 * heading" here as it does there. Chrome-grade: accent is tuned to 3:1
 * against the header band, which holds for 13px bold capitals, not prose. */
const Heading = ({ children }: { children: React.ReactNode }) => <span className="text-accent">{children}</span>

/** A status word in a table cell or a panel header: connected, the plan,
 * how a feed arrives. Tinted, never a filled block, so a column of them
 * reads as a column of facts rather than of buttons. */
function Pill({ tone, children }: { tone: "gain" | "warn" | "info" | "muted"; children: React.ReactNode }) {
  const cls = {
    gain: "bg-gain-tint text-gain",
    warn: "bg-warn-tint text-warn",
    info: "bg-info-tint text-info",
    muted: "bg-surface text-muted-foreground",
  }[tone]
  return (
    <span className={`inline-flex h-[20px] items-center whitespace-nowrap rounded-xs px-2 text-label font-bold uppercase tracking-caps ${cls}`}>
      {children}
    </span>
  )
}

/** A heading row inside a panel, the section labels the matrix is read by.
 * On the card itself above a hairline (2026-09-18): a grey band under a
 * 40%-ink rule read as a slab across the white card. */
function SubLabel({ children, right }: { children: React.ReactNode; right?: React.ReactNode }) {
  return (
    // Wraps: on a phone the controls beside a label ("Connect a client" and
    // its four client tabs) drop to their own line instead of squeezing the
    // label onto two.
    // justify-between, not a margin: on one line the controls sit right;
    // wrapped onto their own line they start at the left rather than hang
    // off the right edge.
    <div className="flex flex-wrap items-center justify-between gap-x-2 gap-y-2 border-b border-row-rule bg-card px-4 pb-2 pt-4">
      <span className="whitespace-nowrap text-label font-bold uppercase tracking-caps text-muted-foreground">{children}</span>
      {right && <span>{right}</span>}
    </div>
  )
}

type Seam = "news" | "prices" | "transcripts"

/** The key vault's entry surface: the reader's market-data, news and transcript keys.
 * Plaintext goes up once over HTTPS and never comes back — each row shows
 * provider and hint only. The form refuses to render on an insecure origin
 * (localhost excepted), which is the design's HTTPS rule enforced where it
 * bites. */
function KeysPanel({ newsProviders, transcriptProviders }: {
  newsProviders: string[]
  transcriptProviders: string[]
}) {
  const qc = useQueryClient()
  const { data } = useUserKeys()
  const vendors = useQuery({ queryKey: ["data-vendors"], queryFn: ({ signal }) => on(signal).dataVendors(), staleTime: 30_000 })
  const vendorList = vendors.data?.vendors ?? []
  const vendorLabel = (name: string) => vendorList.find(v => v.name === name)?.label ?? name
  const [editing, setEditing] = useState<Seam | null>(null)
  const [provider, setProvider] = useState("")
  const [apiKey, setApiKey] = useState("")
  const [apiSecret, setApiSecret] = useState("")
  const [paidPlan, setPaidPlan] = useState(false)
  const [baseUrl, setBaseUrl] = useState("")
  const [model, setModel] = useState("")
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const insecure = window.location.protocol !== "https:"
    && !["localhost", "127.0.0.1"].includes(window.location.hostname)
  const stored = (seam: Seam, prov?: string) => (data?.keys ?? []).find(k => k.seam === seam && (!prov || k.provider === prov))
  // News keys ACCUMULATE — one row per provider, each feed its own key.
  const newsRows = (data?.keys ?? []).filter(k => k.seam === "news")
  const done = () => {
    setEditing(null); setApiKey(""); setApiSecret(""); setBaseUrl(""); setModel(""); setError(null)
    // A connected or removed vendor changes what every panel can show, so
    // everything refetches — a panel that read "needs a key" fills at once.
    void qc.invalidateQueries()
  }
  const open = (seam: Seam, preset?: string) => {
    setEditing(seam)
    setProvider(preset ?? (seam === "prices" ? vendorList[0]?.name ?? "alpaca"
                : seam === "transcripts" ? transcriptProviders[0] ?? "finnhub"
                : newsProviders[0] ?? "polygon"))
    setApiKey(""); setApiSecret(""); setBaseUrl(""); setModel(""); setPaidPlan(false); setError(null)
  }

  const save = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy || !editing) return
    setBusy(true); setError(null)
    try {
      await api.setKey(editing, {
        provider, api_key: apiKey,
        api_secret: apiSecret || undefined,
        base_url: baseUrl || undefined, model: model || undefined,
        plan: paidPlan ? "paid" : "free",
      })
      done()
    } catch (err) {
      setError(String((err as Error).message ?? err))
    } finally {
      setBusy(false)
    }
  }

  const remove = async (seam: Seam, provider?: string) => {
    try { await api.deleteKey(seam, provider); done() }
    catch (err) { setError(String((err as Error).message ?? err)) }
  }
  // A SCRAPED source has no key to paste, so switching it on is the button
  // itself rather than a dialog (2026-09-22). Switching it off is the
  // ordinary removal above, which is why there is only one of these.
  const enable = async (name: string) => {
    try { await api.enableSource(name); done() }
    catch (err) { setError(String((err as Error).message ?? err)) }
  }

  const pollMinutes = data?.news_poll_minutes
  const orphanFeeds = data?.orphan_feeds ?? []
  const keepDays = data?.news_keep_days
  const transcript = stored("transcripts")
  // A VENDOR YOU KEYED AND A SOURCE YOU SWITCHED ON ARE DIFFERENT THINGS
  // (2026-09-22). They shared the Market data table, which put social posts
  // under market data and counted three keyless sources among the vendors,
  // so "7 of 9 connected" was answering two questions at once.
  const keyedVendors = vendorList.filter(v => v.official !== false)
  // A LIVE CHECK, on the reader's press only: it reaches a third-party site,
  // so it must never run on a page load (2026-09-23).
  const [checking, setChecking] = useState<string | null>(null)
  const [checks, setChecks] = useState<Record<string, { ok: boolean; rows?: number; reason: string | null }>>({})
  const runCheck = async (name: string) => {
    setChecking(name)
    try {
      const res = await api.checkSource(name)
      setChecks(c => ({ ...c, [name]: { ok: res.ok, rows: res.rows, reason: res.reason } }))
    } catch (e) {
      setChecks(c => ({ ...c, [name]: { ok: false, reason: e instanceof Error ? e.message : "could not be checked" } }))
    } finally {
      setChecking(null)
    }
  }
  const scrapedSources = vendorList.filter(v => v.official === false)
  const connectedCount = keyedVendors.filter(v => stored("prices", v.name)).length
  const scrapedOn = scrapedSources.filter(v => stored("prices", v.name)).length
  const stories = newsRows.reduce((n, r) => n + (r.stories_24h ?? 0), 0)

  // The vault's absence and an insecure origin are the page's whole message
  // when they apply: nothing below can be saved.
  const blocked = data && !data.vault ? (
    <Empty>
      The vault isn't enabled on this instance — the operator sets
      ALPHADESK_VAULT_KEY to turn it on.
    </Empty>
  ) : insecure ? <Empty>Keys are entered over HTTPS only.</Empty> : null

  return (
    <>
      {/* MARKET DATA as a table (2026-09-18, the owner picked the coverage
          matrix from six drafts). Every column is a real field: the panels a
          vendor serves and how many of them its free plan covers come from
          the catalogue, the key hint and the plan from the reader's own key.
          There is deliberately NO routing-order column — the catalogue
          orders vendors per PANEL, so one numbered list would claim an order
          that does not exist. */}
      <Widget span={12} title={<Heading>Market data</Heading>} bodyClassName="@container"
              subtitle="each panel uses the first connected vendor that carries it"
              actions={keyedVendors.length ? <Pill tone={connectedCount ? "gain" : "muted"}>{connectedCount} of {keyedVendors.length} connected</Pill> : undefined}>
        {blocked ?? (
          <>
            {/* THE TABLE NEEDS 820px; below that the panel falls back to one
                row per vendor (2026-09-18). Scrolling it sideways inside a
                narrow pane put every Connect and Replace button off-screen,
                which undid the narrow-pane rework of the day before. */}
            <div className="hidden overflow-x-auto @[820px]:block"><div className="min-w-[820px]">
              <Table className={ROOMY}>
                <THead>
                  <TH className="w-[190px]" title="The vendor. Several can be connected at once; each panel asks the ones that carry it">Vendor</TH>
                  <TH className="w-[118px]" title="The last four characters of your key. The key itself is never shown again">Key</TH>
                  <TH title="The panels this vendor can answer, in the catalogue's words">What it serves</TH>
                  <TH align="right" className="w-[72px]" title="How many panels this vendor can serve on any plan">Panels</TH>
                  <TH align="right" className="w-[84px]" title="How many of those a free key covers">Free plan</TH>
                  {/* 144px: "Not connected" is 122px at the type scale's label size and
                      caps tracking, plus the cell's padding (2026-09-18: at 118 it
                      was cut to "NOT CONNECTE"). */}
                  <TH className="w-[144px]">Status</TH>
                  <TH align="right" className="w-[172px]"><span className="sr-only">Actions</span></TH>
                </THead>
                <tbody>
                  {keyedVendors.map(v => {
                    const row = stored("prices", v.name)
                    // Read off a public page rather than delivered under a key.
                    const scraped = v.official === false
                    const free = v.serves.filter(x => x.tier === "free").length
                    const labels = v.serves.map(x => x.label)
                    const plan = row && v.plan ? v.plan : null
                    const planText = plan
                      ? (plan.realtime
                        ? `Real-time plan: prices, charts${plan.options === "indicative" ? "" : " and options"} from every exchange${plan.options === "indicative" ? "; options still indicative (sign the OPRA agreement)" : ""}`
                        : "Free plan: live prices from one exchange, charts 15 minutes behind, options indicative — Algo Trader Plus makes them real-time")
                      : undefined
                    return (
                      <TR key={v.name}>
                        <TD className="font-extrabold">{v.label}</TD>
                        <TD mono className="text-muted-foreground">
                          {scraped ? <span className="font-sans text-label">no key</span>
                            : row ? <>····{row.key_hint}{!row.last_used_at && <span className="block text-label font-sans">not used yet</span>}</> : "—"}
                        </TD>
                        <TD className="truncate text-caption text-muted-foreground" title={labels.join(" · ")}>
                          {row ? labels.slice(0, 3).join(" · ") : v.note}
                          {row && labels.length > 3 && <span className="text-foreground"> +{labels.length - 3}</span>}
                        </TD>
                        <TD align="right" mono>{scraped ? "—" : v.serves.length}</TD>
                        <TD align="right" mono className="text-muted-foreground">{scraped ? "—" : free}</TD>
                        <TD title={scraped ? "Read from a public page, not delivered under a key — asked only where no vendor you keyed carries the panel" : planText}>
                          {scraped ? (row ? <Pill tone="warn">Scraped</Pill> : <Pill tone="muted">Off</Pill>)
                            : !row ? <Pill tone="muted">Not connected</Pill>
                            : plan ? <Pill tone={plan.realtime ? "gain" : "warn"}>{plan.realtime ? "Real-time" : "Free plan"}</Pill>
                            : <Pill tone="gain">Connected</Pill>}
                        </TD>
                        <TD align="right">
                          <span className="inline-flex items-center justify-end gap-1.5">
                            {/* Nothing to paste and nothing to replace: the
                                button IS the whole of switching one on. */}
                            {scraped ? (
                              row
                                ? <button type="button" onClick={() => void remove("prices", v.name)} className={BTN_DANGER}>Switch off</button>
                                : <button type="button" onClick={() => void enable(v.name)} className={BTN_PRIMARY}>Switch on</button>
                            ) : row ? (
                              <>
                                <button type="button" onClick={() => open("prices", v.name)} className={BTN}>Replace</button>
                                <button type="button" onClick={() => void remove("prices", v.name)} className={BTN_DANGER}>Remove</button>
                              </>
                            ) : (
                              <>
                                <a href={v.signup} target="_blank" rel="noopener noreferrer" className="mr-1 text-caption text-accent-700 underline underline-offset-2">Get a key</a>
                                <button type="button" onClick={() => open("prices", v.name)} className={BTN_PRIMARY}>Connect</button>
                              </>
                            )}
                          </span>
                        </TD>
                      </TR>
                    )
                  })}
                </tbody>
              </Table>
            </div></div>
            <div className="@[820px]:hidden">
              {keyedVendors.map(v => {
                const row = stored("prices", v.name)
                const scraped = v.official === false
                const free = v.serves.filter(x => x.tier === "free").length
                const plan = row && v.plan ? v.plan : null
                return (
                  <Row key={v.name} label={v.label} actions={scraped ? (
                    row
                      ? <button type="button" onClick={() => void remove("prices", v.name)} className={BTN_DANGER}>Switch off</button>
                      : <button type="button" onClick={() => void enable(v.name)} className={BTN_PRIMARY}>Switch on</button>
                  ) : row ? <>
                    <button type="button" onClick={() => open("prices", v.name)} className={BTN}>Replace</button>
                    <button type="button" onClick={() => void remove("prices", v.name)} className={BTN_DANGER}>Remove</button>
                  </> : <button type="button" onClick={() => open("prices", v.name)} className={BTN_PRIMARY}>Connect</button>}>
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      {row && !scraped && <span className="num text-foreground">····{row.key_hint}</span>}
                      {scraped ? (row ? <Pill tone="warn">Scraped</Pill> : <Pill tone="muted">Off</Pill>)
                        : !row ? <Pill tone="muted">Not connected</Pill>
                        : plan ? <Pill tone={plan.realtime ? "gain" : "warn"}>{plan.realtime ? "Real-time" : "Free plan"}</Pill>
                        : <Pill tone="gain">Connected</Pill>}
                    </span>
                    <span className="mt-1 block text-caption">
                      {/* A scraped source serves no named panel: it is asked
                          wherever nothing keyed answered, so a count of
                          panels and a free-key line would both be fiction. */}
                      {scraped
                        ? "No key · read from a public page · asked only where no vendor you keyed carries the panel"
                        : <>{v.serves.length} panels · {free === v.serves.length ? `all ${free}` : free || "none"} on a free key
                          {!row && <>{" · "}<a href={v.signup} target="_blank" rel="noopener noreferrer" className="text-accent-700 underline underline-offset-2">Get a key</a></>}</>}
                    </span>
                  </Row>
                )
              })}
            </div>
            <Caption>Sealed with AES-256-GCM — only the last four characters are ever shown.</Caption>
          </>
        )}
      </Widget>

      {/* SOURCES WITHOUT A KEY, in their own section (2026-09-22). They sat
          in the Market data table, which was wrong twice over: social posts
          are not market data, and counting three keyless sources among the
          vendors made "connected" mean two different things in one number.
          They are not vendors you hold an account with — they are public
          pages this server reads, and the section says so once rather than
          on every row. */}
      {scrapedSources.length > 0 && (
        <Widget span={12} title={<Heading>Sources without a key</Heading>} bodyClassName="@container"
                subtitle="public pages this server reads — asked only where no vendor you keyed answered"
                actions={<Pill tone={scrapedOn ? "warn" : "muted"}>{scrapedOn} of {scrapedSources.length} on</Pill>}>
          {blocked ?? (
            <>
              {scrapedSources.map(v => {
                const row = stored("prices", v.name)
                // WHAT SWITCHING IT ON WOULD ACTUALLY DO (2026-09-23). A keyed
                // vendor is always asked first, so a source whose every
                // surface you already pay for can never answer — and a button
                // reading "Switch on" implied otherwise.
                const only = v.coverage?.only_source_for ?? []
                const taken = v.coverage?.already_covered ?? []
                // Surfaces that ask every vendor and merge, where this
                // source is NOT shut out by a keyed one (2026-09-23, #66).
                // Counting these as covered told the reader a source was
                // idle while it was filling in their earnings week.
                const also = v.coverage?.contributes_alongside ?? []
                const idle = !!v.coverage && only.length === 0 && also.length === 0
                return (
                  <Row key={v.name} label={v.label} actions={row
                    ? <>
                        <button type="button" onClick={() => void runCheck(v.name)}
                                disabled={checking === v.name} className={BTN}
                                title="Read the site now and report what came back">
                          {checking === v.name ? "Checking…" : "Check"}
                        </button>
                        <button type="button" onClick={() => void remove("prices", v.name)} className={BTN_DANGER}>Switch off</button>
                      </>
                    : <button type="button" onClick={() => void enable(v.name)} className={BTN_PRIMARY}>Switch on</button>}>
                    <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                      {row ? <Pill tone="warn">Scraped</Pill> : <Pill tone="muted">Off</Pill>}
                      {idle && <Pill tone="muted">Nothing to serve</Pill>}
                      {/* ON IS NOT WORKING (2026-09-23, the reader saw no
                          posts from a source they had switched on). The page
                          could say a source was on and covering a panel
                          while the site refused this server, and nothing
                          here had ever tried it. */}
                      {checks[v.name] && (
                        <Pill tone={checks[v.name]!.ok ? "info" : "warn"}>
                          {checks[v.name]!.ok ? `Answered · ${checks[v.name]!.rows} rows` : "Not answering"}
                        </Pill>
                      )}
                    </span>
                    {checks[v.name]?.reason && (
                      <span className="mt-1 block text-caption text-warn">{checks[v.name]!.reason}</span>
                    )}
                    {/* A SOURCE THAT IS OFF SAYS LITTLE (2026-09-23, the
                        reader). Three switched-off rows each carried two
                        paragraphs — what it reads, what it would be the only
                        source for, and which vendor covers every surface it
                        has — which is a wall of text about things that are
                        not happening. What survives is the ONE line that
                        decides whether to switch it on; the rest is the
                        row's hover, and the detail returns once it is on and
                        actually answering. */}
                    <span className="mt-1 block text-caption text-muted-foreground"
                          title={[v.note, taken.length
                            ? taken.map(t => `${t.surface} comes from ${t.vendors.join(" or ")}`).join("; ") + "."
                            : ""].filter(Boolean).join(" ")}>
                      {only.length > 0
                        ? <>Only source for {only.join(", ").toLowerCase()}.</>
                        : idle
                          ? <>Nothing a vendor you keyed does not already carry.</>
                          : also.length > 0
                            ? <>Contributes to {also.map(t => t.surface.toLowerCase()).join(" and ")}.</>
                            : v.note}
                    </span>
                    {/* Once it is on, what it is actually answering with. */}
                    {row && also.length > 0 && (
                      // NAMED SEPARATELY FROM THE COVERED ONES, because the
                      // reader's rule is not to scrape what they pay for and
                      // this is the deliberate exception to it: these
                      // surfaces ask every vendor and merge, and the split
                      // calendar needs two vendors agreeing before it will
                      // trust a split at all.
                      <span className="mt-1 block text-caption text-muted-foreground">
                        {also.map(t => `${t.surface} asks every vendor and merges, so this is read beside ${t.vendors.join(" and ")}`).join("; ")}.
                      </span>
                    )}
                    {row && taken.length > 0 && (
                      <span className="mt-1 block text-caption text-muted-foreground">
                        {taken.map(t => `${t.surface} comes from ${t.vendors.join(" or ")}`).join("; ")}.
                      </span>
                    )}
                  </Row>
                )
              })}
              <Caption>
                Read rather than licensed. Every figure one of these answers is marked as
                scraped wherever it appears, and a vendor you keyed is always asked first.
              </Caption>
            </>
          )}
        </Widget>
      )}

      <Widget span={12} title={<Heading>News & transcripts</Heading>} bodyClassName="@container"
              subtitle="your window merges every feed you key, deduplicated by link"
              actions={blocked ? undefined : <>
                {newsRows.length > 0 && <Pill tone="info">{stories.toLocaleString()} stories · 24h</Pill>}
                <button type="button" onClick={() => open("news")} className={BTN_PRIMARY}>Add feed</button>
              </>}>
        {blocked ?? (
          <>
          <div className="hidden overflow-x-auto @[680px]:block"><div className="min-w-[680px]">
            <Table className={ROOMY}>
              <THead>
                <TH className="w-[190px]">Feed</TH>
                <TH className="w-[118px]">Key</TH>
                <TH align="right" className="w-[110px]" title="Stories this feed delivered into your window in the last 24 hours; a story two feeds delivered counts for both">Stories · 24h</TH>
                <TH title="How its stories arrive: over a held socket in seconds, or on the poll">Delivery</TH>
                <TH align="right" className="w-[172px]"><span className="sr-only">Actions</span></TH>
              </THead>
              <tbody>
                {newsRows.map(row => (
                  <TR key={row.provider}>
                    <TD className="font-extrabold">{vendorLabel(row.provider)}</TD>
                    <TD mono className="text-muted-foreground">····{row.key_hint}</TD>
                    <TD align="right" mono className={row.stories_24h ? "" : "text-warn"}>
                      {row.stories_24h == null ? "—" : row.stories_24h.toLocaleString()}
                    </TD>
                    <TD>
                      {/* A FEED THAT KEEPS NOTHING IS NOT A WORKING FEED. It
                          polls, it answers, and the window stays empty because
                          the window is built from stored stories. Saying
                          "Poll · every 5 min" beside it would be the interface
                          asserting a state the system is not in. */}
                      {row.stores === false
                        ? <span title={row.not_stored_reason}><Pill tone="warn">Not kept</Pill></span>
                        : row.delivery === "stream"
                        ? <Pill tone="gain">Stream · seconds</Pill>
                        : <Pill tone="muted">Poll{pollMinutes ? ` · every ${pollMinutes} min` : ""}</Pill>}
                    </TD>
                    <TD align="right">
                      <span className="inline-flex items-center justify-end gap-1.5">
                        <button type="button" onClick={() => open("news", row.provider)} className={BTN}>Replace</button>
                        <button type="button" onClick={() => void remove("news", row.provider)} className={BTN_DANGER}>Remove</button>
                      </span>
                    </TD>
                  </TR>
                ))}
                {/* A feed you no longer hold, whose stories are still in the
                    window. Named rather than left as an unaccountable
                    publisher in the news list (2026-09-22). */}
                {orphanFeeds.map(o => (
                  <TR key={`orphan-${o.provider}`}>
                    <TD className="font-extrabold text-muted-foreground">{vendorLabel(o.provider)}</TD>
                    <TD mono className="text-muted-foreground">no key</TD>
                    <TD align="right" mono className="text-muted-foreground">{o.stories.toLocaleString()}</TD>
                    <TD className="text-caption text-muted-foreground">
                      <Pill tone="muted">Removed</Pill>
                      <span className="ml-2">
                        stories it delivered are still stored{keepDays ? ` — they age out ${keepDays} days after publication` : ""}
                      </span>
                    </TD>
                    <TD align="right"><span className="sr-only">no actions</span></TD>
                  </TR>
                ))}
                {!newsRows.length && !orphanFeeds.length && (
                  <TR>
                    <TD className="font-extrabold">News</TD>
                    <TD className="text-muted-foreground" colSpan={3}>none — news needs your feed key</TD>
                    <TD align="right"><button type="button" onClick={() => open("news")} className={BTN_PRIMARY}>Add key</button></TD>
                  </TR>
                )}
                <TR>
                  <TD className="font-extrabold">Transcripts</TD>
                  <TD mono className="text-muted-foreground">{transcript ? `····${transcript.key_hint}` : "—"}</TD>
                  <TD align="right" className="text-muted-foreground">—</TD>
                  <TD className="text-caption text-muted-foreground">
                    {transcript ? `${vendorLabel(transcript.provider)} · the recorded call` : "SEC EDGAR results releases, free; a keyed vendor adds the recorded call"}
                  </TD>
                  <TD align="right">
                    <span className="inline-flex items-center justify-end gap-1.5">
                      <button type="button" onClick={() => open("transcripts")} className={transcript ? BTN : BTN_PRIMARY}>{transcript ? "Replace" : "Add key"}</button>
                      {transcript && <button type="button" onClick={() => void remove("transcripts")} className={BTN_DANGER}>Remove</button>}
                    </span>
                  </TD>
                </TR>
              </tbody>
            </Table>
          </div></div>
          <div className="@[680px]:hidden">
            {newsRows.map(row => (
              <Row key={row.provider} label={vendorLabel(row.provider)} actions={<>
                <button type="button" onClick={() => open("news", row.provider)} className={BTN}>Replace</button>
                <button type="button" onClick={() => void remove("news", row.provider)} className={BTN_DANGER}>Remove</button>
              </>}>
                <span className="flex flex-wrap items-center gap-x-2 gap-y-1">
                  <span className="num text-foreground">····{row.key_hint}</span>
                  {row.stores === false && <span className="text-warn">not kept — {row.not_stored_reason}</span>}
                  {row.stories_24h != null && <span>{row.stories_24h.toLocaleString()} stories · 24h</span>}
                  {row.delivery === "stream"
                    ? <Pill tone="gain">Stream · seconds</Pill>
                    : <Pill tone="muted">Poll{pollMinutes ? ` · every ${pollMinutes} min` : ""}</Pill>}
                </span>
              </Row>
            ))}
            <Row label="Transcripts" actions={<>
              <button type="button" onClick={() => open("transcripts")} className={transcript ? BTN : BTN_PRIMARY}>{transcript ? "Replace" : "Add key"}</button>
              {transcript && <button type="button" onClick={() => void remove("transcripts")} className={BTN_DANGER}>Remove</button>}
            </>}>
              {transcript
                ? `${vendorLabel(transcript.provider)} · ····${transcript.key_hint} · the recorded call`
                : "SEC EDGAR results releases, free; a keyed vendor adds the recorded call"}
            </Row>
          </div>
          </>
        )}
      </Widget>

      {editing && (
        <Dialog
          title={editing === "prices"
            ? `${stored("prices", provider) ? "Replace" : "Connect"} your ${vendorLabel(provider)} key`
            : `${stored(editing) ? "Replace" : "Add"} your ${editing === "transcripts" ? "transcripts" : "news"} key`}
          onClose={() => setEditing(null)}
          maxWidth="max-w-[540px]"
        >
        <form onSubmit={e => void save(e)} className="space-y-3.5 px-5 py-5">
          <label className="block">
            <span className={labelCls}>
              {editing === "prices" ? "Data vendor" : editing === "transcripts" ? "Transcript provider" : "News provider"}
            </span>
            <select value={provider} onChange={e => setProvider(e.target.value)}
                    className={`${fieldCls} w-full`}>
              {(editing === "prices" ? vendorList.map(v => v.name)
                : editing === "transcripts" ? transcriptProviders
                : newsProviders)
                .map(p => <option key={p} value={p}>{editing === "prices" ? vendorLabel(p) : p}</option>)}
            </select>
          </label>
          {editing === "transcripts" && (
            <p className="text-caption leading-[1.45] text-muted-foreground">
              Without a key the Earnings transcript panel shows no document,
              only a link to the results release the company filed on EDGAR.
              With one, it shows the vendor's recorded call — the analyst
              Q&A included — for your session only. Both vendors gate
              transcripts to paid plans.
            </p>
          )}
          {editing === "prices" && (
            <p className="text-caption leading-[1.45] text-muted-foreground">
              {vendorList.find(v => v.name === provider)?.note}{" "}
              The key serves your session only, and adds to any other
              vendor you connected: each panel uses the first one that
              carries it.
            </p>
          )}
          <label className="block">
            <span className={labelCls}>API key</span>
            <input type="password" value={apiKey} onChange={e => setApiKey(e.target.value)}
                   autoComplete="off" required className={`${fieldCls} w-full`} />
          </label>
          {((editing === "news" && provider === "alpaca")
            || (editing === "prices" && vendorList.find(v => v.name === provider)?.needs_secret)) && (
            <label className="block">
              <span className={labelCls}>API secret</span>
              <input type="password" value={apiSecret} onChange={e => setApiSecret(e.target.value)}
                     autoComplete="off" required className={`${fieldCls} w-full`} />
            </label>
          )}
          {/* TIINGO'S TERMS TURN ON THE PLAN (2026-09-26, #85): a Starter or
              trial plan may not have its data written to durable storage at
              all, and Tiingo publishes no way to ask a token which plan it
              is on. So the account holder says, and says it knowing what
              each answer costs — an undeclared key is read the restrictive
              way, which is the only safe default when the failure is
              silent. */}
          {editing === "news" && provider === "tiingo" && (
            <label className="flex items-start gap-2 border border-border bg-card p-2.5">
              <input type="checkbox" checked={paidPlan} onChange={e => setPaidPlan(e.target.checked)}
                     className="mt-[3px] h-[14px] w-[14px] shrink-0 accent-[var(--accent)]" />
              <span className="min-w-0 text-caption text-muted-foreground">
                <span className="block font-semibold text-foreground">This token is on a paid Tiingo plan</span>
                Tiingo&rsquo;s terms forbid keeping data from a Starter or trial plan, so its
                stories are fetched and then dropped rather than stored — and the news window is
                built from stored stories, so they never appear. Leave this unticked unless you
                are on Power or Commercial.
              </span>
            </label>
          )}
          {error && <p className="text-caption text-loss">{error}</p>}
          <button type="submit" disabled={busy}
                  className={btnCls({ variant: "accent", size: "lg" }, "mt-1 h-[32px] w-full font-extrabold uppercase tracking-caps")}>
            {busy ? "sealing…" : "Save key"}
          </button>
        </form>
        </Dialog>
      )}
      {error && !editing && <p className="px-1 text-caption text-loss" style={{ gridColumn: "span 12 / span 12" }}>{error}</p>}
    </>
  )
}

/** Agent access (2026-09-17): AlphaDesk runs no agent of its own. A reader
 * issues a token here and points the agent they already use — Claude Code,
 * Cursor, opencode, anything that speaks MCP — at this instance's tool
 * server; every call runs as them, on their keys. The token is shown ONCE,
 * in the row that created it, and is gone on the next render; the list
 * carries only a name and the last four characters. */
function AgentAccessPanel({ span = 12 }: { span?: number }) {
  const qc = useQueryClient()
  const list = useQuery({ queryKey: ["agent-access-tokens"], queryFn: ({ signal }) => on(signal).agentAccessTokens() })
  const [name, setName] = useState("")
  const [fresh, setFresh] = useState<{ id: string; token: string } | null>(null)
  const [copied, setCopied] = useState<string | null>(null)
  const [client, setClient] = useState<AgentClient>("claude-code")
  const connections = useQuery({ queryKey: ["agent-connections"], queryFn: ({ signal }) => on(signal).agentConnections() })
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const url = list.data?.url ?? ""
  const tokens = list.data?.tokens ?? []

  const issue = async (e: React.FormEvent) => {
    e.preventDefault()
    if (busy) return
    setBusy(true); setError(null); setCopied(null)
    try {
      const made = await api.issueAgentAccessToken(name.trim())
      setFresh({ id: made.token_id, token: made.token })
      setName("")
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
   * server on every add, so its rows cannot be collapsed server-side and the
   * reader would otherwise revoke them one at a time. */
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
  const setup = url ? agentSetup(client, url, fresh?.token) : null

  const groups = connectionGroups(connections.data?.connections ?? [])

  return (
    <Widget span={span} title={<Heading>Agent access</Heading>} subtitle="your own agent, over MCP"
            bodyClassName="@container">
      <Row label="Server address"
           actions={url ? <button type="button" className={BTN} onClick={() => copy("url", url)}>
             {copied === "url" ? "Copied" : "Copy"}</button> : null}>
        <code className="num block break-all text-caption text-foreground">{url || "…"}</code>
        {/* Claude.ai and ChatGPT take this address and nothing else: they
            sign the reader in over OAuth, so a "paste this" tab for them
            would only repeat the line above. */}
        <span className="mt-1.5 block text-caption">
          Claude.ai and ChatGPT: add a custom connector with this address, sign in, allow it. No token needed.
        </span>
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
        <div className="row-rule px-4 py-3 text-caption text-muted-foreground">none — add the address above as a connector</div>
      )}
      <SubLabel right={<span className="text-label text-muted-foreground">{tokens.length} of 10 live</span>}>Tokens</SubLabel>
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
            <>····{t.hint} · {t.last_used_at ? `last used ${new Date(t.last_used_at).toLocaleString()}` : "not used yet"}</>
          )}
        </Row>
      ))}
      {/* The form draws the rule: its one row is the form's last child, and
          a last-child row drops its own, which left the Connect band below
          with no line above it (2026-09-18). */}
      <form onSubmit={issue} className="border-b border-row-rule">
        <Row label="New token" actions={<button type="submit" disabled={busy} className={BTN_PRIMARY}>{busy ? "…" : "Create"}</button>}>
          <input value={name} onChange={e => setName(e.target.value)} maxLength={60}
                 aria-label="Name the agent this token is for"
                 placeholder="which agent, e.g. Claude Code on my laptop"
                 className={`${fieldCls} w-full`} />
        </Row>
      </form>
      {error && <div className="px-4 py-2 text-caption text-loss">{error}</div>}
      {setup && (
        <>
          <SubLabel right={
            <span role="tablist" aria-label="Agent" className="flex flex-wrap gap-1.5">
              {AGENT_CLIENTS.map(c => (
                <button key={c.id} type="button" role="tab" aria-selected={client === c.id}
                        onClick={() => { setClient(c.id); setCopied(null) }}
                        // Selected by a soft fill, not a red outline (2026-09-18, the owner's call).
                        className={btnCls({ size: "sm", active: client === c.id }, "normal-case tracking-normal")}>
                  {c.label}
                </button>
              ))}
            </span>
          }>Connect a client</SubLabel>
          <div className="row-rule px-4 py-3.5">
            <div className="flex items-start gap-3">
              <span className="min-w-0 flex-1 text-caption leading-[1.45] text-muted-foreground">
                {setup.where}{" "}
                {!setup.tokenInline ? null : fresh
                  ? "It holds your new token, so keep that file out of version control."
                  : "Create a token above and it is filled in here while it is shown."}
              </span>
              <button type="button" className={BTN} onClick={() => copy("setup", setup.text)}>
                {copied === "setup" ? "Copied" : "Copy"}
              </button>
            </div>
            <pre className="num mt-2 overflow-x-auto whitespace-pre rounded-sm border border-border bg-background px-3 py-2 text-caption leading-[1.45]">{setup.text}</pre>
          </div>
        </>
      )}
      <Caption>
        Each call runs as you, on your keys, at up to 120 requests a minute per token. Revoking stops a token at once.
      </Caption>
      <Caption>
        An app keeps the tool list it saw when it connected — reconnect it to pick up tools added since.
      </Caption>
    </Widget>
  )
}

/** The totals the matrix is read from, one line above it: how many vendors,
 * how much news, how many agents, what kind of session. Every figure is read
 * from the same queries the panels below use, so the two cannot disagree. */
function StatStrip({ open }: { open: boolean }) {
  const { data: keys } = useUserKeys()
  const vendors = useQuery({ queryKey: ["data-vendors"], queryFn: ({ signal }) => on(signal).dataVendors(), staleTime: 30_000 })
  const tokens = useQuery({ queryKey: ["agent-access-tokens"], queryFn: ({ signal }) => on(signal).agentAccessTokens() })
  const connections = useQuery({ queryKey: ["agent-connections"], queryFn: ({ signal }) => on(signal).agentConnections() })
  const vendorList = vendors.data?.vendors ?? []
  const rows = keys?.keys ?? []
  // Vendors you KEYED, counted against vendors you could key. A keyless
  // scraped source is not one of them and used to be counted as both
  // (2026-09-22), which is why this read "7 of 9" with six keys.
  const keyed = vendorList.filter(v => v.official !== false)
  const connected = keyed.filter(v => rows.some(k => k.seam === "prices" && k.provider === v.name)).length
  const scraped = vendorList.filter(v => v.official === false)
    .filter(v => rows.some(k => k.seam === "prices" && k.provider === v.name)).length
  const feeds = rows.filter(k => k.seam === "news")
  const stories = feeds.reduce((n, k) => n + (k.stories_24h ?? 0), 0)
  const apps = connectionGroups(connections.data?.connections ?? []).length
  const live = tokens.data?.tokens.length ?? 0
  const plural = (n: number, word: string) => `${n} ${word}${n === 1 ? "" : "s"}`
  return (
    <section className="@container overflow-hidden rounded-lg border border-card-border bg-card shadow-card"
             style={{ gridColumn: "span 12 / span 12" }} aria-label="Account totals">
      <div className="grid grid-cols-1 @[640px]:grid-cols-4">
        <StatCell label="Market data"
                  value={keyed.length
                    ? `${connected} of ${keyed.length} vendors${scraped ? ` · ${scraped} scraped` : ""}`
                    : "—"} />
        <StatCell label="News" value={feeds.length ? `${stories.toLocaleString()} stories · 24h` : "no feed"} />
        <StatCell label="Agent access" value={`${plural(apps, "app")} · ${plural(live, "token")}`} />
        <StatCell label="Session" value={open ? "Open instance" : "14 days · HMAC"} />
      </div>
    </section>
  )
}

/** How the reader signs in, and the session that results — the two used to
 * be separate panels of two rows each. */
function SecurityPanel({ providers, sso, signIns, onSignOutEverywhere, email, owner }: {
  email?: string
  owner?: boolean
  providers: { id: string; label: string }[]
  sso: boolean
  /** The methods THIS account has signed in with (recorded from 2026-09-18). */
  signIns: { method: string; last_at: string | null }[]
  onSignOutEverywhere: () => void
}) {
  const [deleting, setDeleting] = useState(false)
  // "Active" used to mean the server offers the method — so a reader who
  // only ever used GitHub saw Google active too (2026-09-18). Now: USED, with
  // when, for a method this account has signed in with; AVAILABLE otherwise.
  const used = new Map(signIns.map(s => [s.method, s.last_at]))
  const when = (iso: string | null | undefined) =>
    iso ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : ""
  return (
    <Widget span={6} title={<Heading>Security</Heading>} subtitle="how you sign in, and where" bodyClassName="@container">
      {providers.map(p => (
        <Row key={p.id}
             label={<span className="flex min-w-0 items-center gap-2">
               <span aria-hidden="true" className="flex w-[20px] shrink-0 items-center justify-center">
                 {PROVIDER_MARKS[p.id]}
               </span>
               <span className="truncate">{p.label}</span>
             </span>}
             actions={used.has(p.id) ? <Pill tone="gain">Used</Pill> : <Pill tone="muted">Available</Pill>}>
          {used.has(p.id)
            ? `you sign in with ${p.label} · last ${when(used.get(p.id))}`
            : "offered here · not used by this account (recorded since Sep 18, 2026)"}
        </Row>
      ))}
      {/* Only when it IS the door: an SSO instance refuses passwords,
          and a row whose whole message is "refused" earns no place. */}
      {!sso && (
        <Row label="Password" actions={used.has("password") ? <Pill tone="gain">Used</Pill> : <Pill tone="muted">Available</Pill>}>the gate on this instance</Row>
      )}
      <Row label="Session" actions={
        <button type="button" onClick={onSignOutEverywhere} className={BTN_DANGER}>Sign out everywhere</button>}>
        HMAC-signed cookie · 14-day lifetime · other devices stay signed in until you sign them out
      </Row>
      {/* Deleting the account (2026-09-18): everything in it, at once. An
          owner is refused by the server, so the row is not offered. */}
      {!owner && email && (
        <Row label="Account" actions={
          <button type="button" onClick={() => setDeleting(true)} className={BTN_DANGER}>Delete account</button>}>
          delete this account and everything in it — keys, views, baskets, stored data, agent access
        </Row>
      )}
      {deleting && email && (
        <DeleteAccountDialog email={email} own onClose={() => setDeleting(false)}
          onConfirm={typed => api.deleteMyAccount(typed).then(() => { window.location.href = "/" })} />
      )}
    </Widget>
  )
}

/** The Account page as a COVERAGE MATRIX (2026-09-18, the owner's pick of six
 * drafts on the design canvas): a one-line identity, the totals, then market
 * data and news as real tables, with agent access and security side by side.
 * 1160px wide rather than 920 — the single column left a third of a desktop
 * screen empty. Below 900px the grid collapses to one column as every board
 * does, and the tables scroll sideways inside their panels. */
/** The reader's plan (2026-09-18): trial days left, or the subscription,
 * with the door to the payment processor. With no processor configured the
 * buttons say payments are not open yet rather than pretending to charge. */
function PlanPanel({ access }: { access: Access }) {
  const [note, setNote] = useState<string | null>(null)
  const go = (call: () => Promise<{ url: string }>) =>
    call().then(r => window.location.assign(r.url)).catch(e => setNote(String(e.message ?? e)))
  const until = (iso: string | null) => iso
    ? new Date(iso).toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" }) : "—"
  const line =
    access.state === "owner" ? "Owner — full access, never billed"
    : access.state === "subscribed" ? (access.plan_status === "canceled"
      ? `Subscription canceled — access until ${until(access.plan_period_end)}`
      : `Subscribed${access.plan_period_end ? ` — renews ${until(access.plan_period_end)}` : ""}`)
    : access.state === "trialing" ? `Free trial — ${access.days_left ?? 0} day${access.days_left === 1 ? "" : "s"} left, ends ${until(access.trial_ends_at)}`
    : "Free trial ended"
  return (
    <Widget span={12} title="Plan" subtitle={access.enforced ? undefined : "subscriptions are not required yet"}>
      <div className="flex flex-wrap items-center gap-3 px-3 py-3">
        <span className="min-w-0 flex-1 text-body font-semibold">{line}</span>
        {access.state === "subscribed" ? (
          <button type="button" disabled={!access.can_subscribe} onClick={() => go(api.billingPortal)}
                  className={btnCls({ variant: "strong", size: "lg" })}>Manage billing</button>
        ) : access.state !== "owner" && (
          <>
            <button type="button" disabled={!access.can_subscribe} onClick={() => go(() => api.billingCheckout("monthly"))}
                    className={btnCls({ variant: "accent", size: "lg" }, "px-4 uppercase tracking-caps")}>Subscribe monthly</button>
            <button type="button" disabled={!access.can_subscribe} onClick={() => go(() => api.billingCheckout("yearly"))}
                    className={btnCls({ variant: "strong", size: "lg" })}>Yearly</button>
          </>
        )}
      </div>
      {!access.can_subscribe && access.state !== "owner" && (
        <div className="border-t border-row-rule px-3 py-2 text-caption text-muted-foreground">Payments are not open yet.</div>
      )}
      {note && <div className="border-t border-row-rule px-3 py-2 text-caption text-loss">{note}</div>}
    </Widget>
  )
}

export default function AccountPage() {
  const { data: me } = useAuthMe()
  const { data: sys } = useSystem()

  const signOut = () =>
    void api.logout().finally(() => { window.location.href = "/" })
  const signOutEverywhere = () =>
    void api.logoutAll().finally(() => { window.location.href = "/" })

  if (!me) return null

  const open = !me.auth_required
  const email = me.user?.email ?? "—"
  const providers = me.providers ?? []
  const sso = providers.length > 0
  const newsProviders = sys?.providers?.available?.news ?? ["polygon", "alpaca"]
  const transcriptProviders = (sys?.providers?.available?.transcripts ?? ["finnhub", "fmp"]).filter(p => p !== "edgar")

  // THE FOOTER CLOSES THE PAGE (2026-09-18, the owner's call): outside the
  // grid, at the foot of a column at least as tall as the view, so a short
  // page puts it at the bottom of the screen and a long one right after the
  // last panel. Inside the grid, the board's 120px of trailing air sat under
  // it and left it floating. That air is the board's rule, not this page's.
  return (
    <div className="flex min-h-full flex-col">
    <div className="collage mx-auto w-full max-w-[1160px] !pb-4">
      {open ? (
        // An open instance acts as its one local account: keys work the same.
        <p className="px-1 text-body leading-[1.5] text-muted-foreground" style={{ gridColumn: "span 12 / span 12" }}>
          This instance is open — it runs without sign-in (ALPHADESK_AUTH=off) as one local account.
          Keys connected below serve this instance.
        </p>
      ) : (
        // A card like every panel below it, one line on a phone (2026-09-19,
        // the owner: the account "still not good for mobile" — the caps
        // subtitle wrapped, and the provider chips and Sign out fell onto a
        // row of their own). The chips hide on a phone: Security lists them.
        <section className="flex min-w-0 items-center gap-3 rounded-lg border border-card-border bg-card px-4 py-3 shadow-card"
                 style={{ gridColumn: "span 12 / span 12" }}>
          <span aria-hidden="true"
                className="flex h-[40px] w-[40px] shrink-0 items-center justify-center rounded-sm bg-info text-figure font-extrabold uppercase text-background">
            {email[0]}
          </span>
          <div className="min-w-0 flex-1">
            <div className="truncate text-body font-extrabold sm:text-emph">{email}</div>
            <div className="mt-0.5 truncate text-caption text-muted-foreground">
              <span className="sm:hidden">{sso ? "Via SSO" : "Operator-created"} · 14-day session</span>
              <span className="max-sm:hidden">{sso ? "Self-provisioned via SSO" : "Operator-created account"} · 14-day signed session</span>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-2">
            {providers.map(p => (
              <span key={p.id}
                    className="hidden h-[28px] items-center gap-2 rounded-sm border border-border px-2.5 text-caption font-semibold uppercase tracking-caps sm:flex">
                {PROVIDER_MARKS[p.id]}{p.label}
              </span>
            ))}
            {/* An icon on a phone, so the email keeps the line. */}
            <button type="button" onClick={signOut} aria-label="Sign out" title="Sign out"
                    className={btnCls({ variant: "danger" }, "max-sm:w-[28px] max-sm:px-0 sm:h-[28px] sm:px-3 max-sm:h-[28px]")}>
              <LogOut className="h-[14px] w-[14px] sm:hidden" aria-hidden="true" />
              <span className="max-sm:hidden">Sign out</span>
            </button>
          </div>
        </section>
      )}

      <StatStrip open={open} />
      {/* Only once there is a plan to speak of: AlphaDesk is free for now
          (2026-09-18, "no payments"), so with the gate off and no payment
          processor there is nothing to show. */}
      {!open && me.user?.access && (me.user.access.enforced || me.user.access.can_subscribe) && <PlanPanel access={me.user.access} />}
      <KeysPanel newsProviders={newsProviders} transcriptProviders={transcriptProviders} />
      <AgentAccessPanel span={open ? 12 : 6} />
      {!open && <SecurityPanel providers={providers} sso={sso} signIns={me.user?.sign_ins ?? []} onSignOutEverywhere={signOutEverywhere}
                                email={me.user?.email} owner={!!me.user?.owner} />}

    </div>
      <footer className="mx-auto mt-auto w-full max-w-[1160px] px-4 pb-4 max-sm:px-2">
        {/* The header's mark and line on the left, the two documents on the
            right, a rule above. */}
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2 border-t border-row-rule px-1 pt-3.5 text-label text-muted-foreground">
          <span className="flex items-center gap-2">
            <span aria-hidden="true" className="h-[8px] w-[8px] rounded-[2px] bg-accent" />
            <span className="font-extrabold uppercase tracking-caps text-foreground">AlphaDesk</span>
            <span>Research workspace — no order routing</span>
          </span>
          <nav aria-label="About AlphaDesk" className="ml-auto flex flex-wrap items-center gap-x-4 gap-y-1 font-semibold uppercase tracking-caps">
            <a href="/about" className="hover:text-foreground hover:underline hover:underline-offset-4">About</a>
            <a href="/terms" className="hover:text-foreground hover:underline hover:underline-offset-4">Terms of Service</a>
            <a href="/privacy" className="hover:text-foreground hover:underline hover:underline-offset-4">Privacy Policy</a>
            <a href="/disclaimer" className="hover:text-foreground hover:underline hover:underline-offset-4">Not investment advice</a>
          </nav>
        </div>
      </footer>
    </div>
  )
}
