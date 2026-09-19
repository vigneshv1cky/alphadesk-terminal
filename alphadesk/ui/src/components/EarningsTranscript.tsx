import { useEffect, useMemo, useState } from "react"
import { QueryFailure } from "@/components/KeyPrompt"
import { Link } from "react-router-dom"
import { ExternalLink } from "lucide-react"
import { useTranscript, useTranscripts } from "@/lib/queries"
import { Empty, fieldCls, Widget } from "@/components/terminal"

/** What the company said about a quarter, as a document.
 *
 * A transcript is the recorded call, and only a vendor that records calls
 * has one — so without a keyed vendor this panel shows NO document, only
 * which keys would fill it (the reader's call, 2026-09-12: "if no source
 * exists, don't show gibberish"). The results press release the company
 * filed on EDGAR is still one click away as a link, but its extracted text
 * — forty thousand characters of statements and tables — is not drawn as
 * if it were a transcript. A reader who keys a vendor on the Account page
 * sees calls here, for their session.
 *
 * The guidance extraction that once sat here went with the in-app model
 * (2026-09-17). What remains is the document itself, which was always the
 * point: a reader (or their own agent, through the transcript tools) reads
 * the company's words rather than a summary of them. */
export function EarningsTranscriptPanel({ symbol, span = 6, scroll }: { symbol: string; span?: number; scroll?: number | string }) {
  const list = useTranscripts(symbol)
  const rows = useMemo(() => list.data?.transcripts ?? [], [list.data])
  const [picked, setPicked] = useState<string | null>(null)
  // Newest document opens by itself; a pick sticks until the symbol changes.
  useEffect(() => { setPicked(null) }, [symbol])
  const id = picked ?? rows[0]?.id ?? null
  const doc = useTranscript(symbol, id)
  const kind = list.data?.kind
  // No keyed vendor: the server falls back to EDGAR's releases, which are
  // not transcripts. Nothing is drawn but the way to get one.
  const unkeyed = !!list.data && list.data.provider === "edgar"
  const subtitle = !list.data ? "loading…"
    : unkeyed ? "no transcript source keyed"
    : `recorded call · ${list.data.provider}`
  const release = unkeyed ? rows[0] : undefined

  const paragraphs = useMemo(() => {
    const t = doc.data?.text ?? ""
    // A call arrives as "Speaker: words" paragraphs; a release as one long
    // extracted run. Either way, break on blank lines, else on sentence
    // runs so a 40,000-character release reads as prose rather than a wall.
    if (t.includes("\n\n")) return t.split(/\n{2,}/).map(p => p.trim()).filter(Boolean)
    // Sentence ends followed by a capital start; "Item 2.02" and "$37.5
    // billion" keep their dots. Three sentences to a paragraph.
    const sentences = t.split(/(?<=[.!?])\s+(?=[A-Z"“(])/)
    const out: string[] = []
    for (let i = 0; i < sentences.length; i += 3) out.push(sentences.slice(i, i + 3).join(" ").trim())
    return out.filter(Boolean)
  }, [doc.data])

  return (
    <Widget span={span} symbol={symbol} title="Earnings transcript" subtitle={subtitle}
            scroll={unkeyed ? undefined : (scroll ?? "max(520px, calc(100vh - 320px))")} expandable={false}
            actions={rows.length > 0 && !unkeyed ? (
              <select value={id ?? ""} onChange={e => setPicked(e.target.value)}
                      aria-label="Which document" className={`${fieldCls} h-[24px] max-w-[260px] py-0 text-caption`}>
                {rows.map(r => <option key={r.id} value={r.id}>{r.title}{r.date ? ` · ${r.date}` : ""}</option>)}
              </select>
            ) : undefined}>
      {list.isPending ? <Empty>loading…</Empty>
        : list.isError ? <QueryFailure error={list.error}>the transcript source is unavailable right now</QueryFailure>
        : list.data?.error ? <Empty>{list.data.error}</Empty>
        : unkeyed ? (
          <div className="px-3 py-4 text-body leading-[1.55] text-muted-foreground">
            <p className="font-semibold text-foreground">No transcript source is keyed.</p>
            <p className="mt-1.5">
              Recorded earnings calls come from a vendor that records them. Add a <span className="font-medium text-foreground">Finnhub</span> or{" "}
              <span className="font-medium text-foreground">Financial Modeling Prep</span> key under Transcripts on the{" "}
              <Link to="/account" className="text-accent-700 underline underline-offset-2">Account page</Link>{" "}
              and this panel shows {symbol}'s calls, speaker by speaker, with guidance extraction over the text.
              Transcripts sit behind each vendor's own plan, above the keys that serve the rest of this
              terminal: Finnhub's on its paid tiers, and Financial Modeling Prep's on Ultimate — a Premium
              key is refused (measured 2026-09-14).
            </p>
            {release?.url && (
              <p className="mt-3">
                Until then, the company's own results release is on EDGAR:{" "}
                <a href={release.url} target="_blank" rel="noopener noreferrer"
                   className="inline-flex items-center gap-1 text-accent-700 hover:underline">
                  {release.title}{release.date ? ` · ${release.date}` : ""} <ExternalLink className="h-[11px] w-[11px]" />
                </a>
              </p>
            )}
          </div>
        )
        : rows.length === 0 ? <Empty>no earnings calls on record for {symbol}</Empty>
        : doc.isPending ? <Empty>reading the document…</Empty>
        : doc.isError || !doc.data ? <Empty>that document could not be read from the source</Empty> : (
        <>
          <div className="flex flex-wrap items-center gap-x-3 gap-y-1.5 border-b border-row-rule px-3 py-2 text-caption text-muted-foreground">
            <span className="font-semibold text-foreground">{doc.data.title}</span>
            {doc.data.date && <span className="num">{doc.data.date}</span>}
            {doc.data.url && (
              <a href={doc.data.url} target="_blank" rel="noopener noreferrer"
                 className="inline-flex items-center gap-1 text-accent-700 hover:underline">
                open the source <ExternalLink className="h-[11px] w-[11px]" />
              </a>
            )}
          </div>
          <div className="space-y-3 px-3 py-3 text-body leading-[1.55]">
            {paragraphs.map((p, i) => {
              const m = kind === "call" ? p.match(/^([^:]{2,60}):\s/) : null
              return (
                <p key={i}>
                  {m ? <><span className="font-semibold">{m[1]}:</span> {p.slice(m[0].length)}</> : p}
                </p>
              )
            })}
          </div>
        </>
      )}
    </Widget>
  )
}
