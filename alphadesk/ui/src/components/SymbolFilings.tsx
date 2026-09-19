import { useEffect, useState } from "react"
import { useSearchParams } from "react-router-dom"
import { api, type FilingRow } from "@/lib/api"
import { Empty, Table, TD, TH, THead, Widget } from "@/components/terminal"

/** SEC filings for one symbol, straight from EDGAR — free, no vendor, no API
 * key. A row opens the document on EDGAR. Asking a filing questions now
 * happens in the reader's own agent over MCP, whose filing tool returns only
 * verbatim quotes checked against the document text server-side. */
export function SymbolFilings({ symbol: requested }: { symbol: string }) {
  const [params, setParams] = useSearchParams()
  const [symbol, setSymbol] = useState("")
  const [filings, setFilings] = useState<FilingRow[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const accession = params.get("accession")

  const load = (sym: string) => {
    if (!sym) return
    setLoading(true)
    setErr(null)
    api.filings(sym)
      .then(d => { setFilings(d.filings); setSymbol(d.symbol) })
      .catch(e => { setFilings(null); setErr(String(e.message ?? e)) })
      .finally(() => setLoading(false))
  }

  // eslint-disable-next-line react-hooks/exhaustive-deps -- follow the symbol
  // Analysis is scoped to, not this component's own identity
  useEffect(() => { if (requested) load(requested) }, [requested])

  const select = (f: FilingRow) => {
    // Mirror the selection into the URL, so a shared link keeps the filing
    // marked.
    const next = new URLSearchParams(params)
    next.set("symbol", f.symbol)
    next.set("accession", f.accession)
    setParams(next, { replace: true })
  }
  /** The whole row is the link (2026-09-11, the reader's call): it opens
   * the document on SEC EDGAR in a new tab and marks the row. An ownership
   * form (3, 4, 144, 13G) is an XML table, not a document, so it only
   * opens — listed so the view matches EDGAR's own, never marked. */
  const open = (f: FilingRow) => {
    if (f.readable) select(f)
    window.open(f.url, "_blank", "noopener,noreferrer")
  }

  return (
    <Widget span={4} symbol={requested} title="Filings" subtitle="SEC EDGAR direct" scroll={560} expandable={false}>
      {loading && <Empty>loading…</Empty>}
      {err && <div className="px-3 py-2 text-body text-loss">{err}</div>}
      {filings && filings.length === 0 && <Empty>No filings found for {symbol}.</Empty>}
      {filings && filings.length > 0 && (
        <>
          {/* The accession column needs ~160px of its own; below a 400px
              panel (a span-4 tile on a narrow board) it hides and the full
              value stays in the row's tooltip, so the form, CIK and date
              never truncate. */}
          <div className="@container">
          <Table>
            <THead>
              <TH className="w-[64px]" title="The SEC form: 10-K annual report, 10-Q quarterly report, 8-K current event and so on. Bold forms are narrative documents; the rest are data tables">Form</TH>
              <TH className="w-[96px]" title="The SEC's Central Index Key: the filer's permanent identifier">CIK</TH>
              <TH className="hidden @[400px]:table-cell" title="The filing's accession number: its unique SEC identifier">Accession</TH>
              <TH align="right" className="w-[88px]" title="The day the filing was made">Filed</TH>
            </THead>
            <tbody>
              {filings.map(f => {
                const on = accession === f.accession
                return (
                  <tr
                    key={f.accession}
                    role="link" tabIndex={0}
                    title={f.readable
                      ? `Open ${f.form} ${f.accession} on SEC EDGAR`
                      : `Open Form ${f.form} ${f.accession} on SEC EDGAR — a data table, not a narrative document`}
                    onClick={() => open(f)}
                    onKeyDown={e => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(f) } }}
                    aria-selected={on}
                    className={`cursor-pointer ${on ? "bg-row-selected" : "hover:bg-foreground/5"}`}
                  >
                    <TD className={f.readable ? "font-extrabold" : "font-medium text-muted-foreground"}>{f.form}</TD>
                    <TD mono className="text-muted-foreground">{f.cik}</TD>
                    <TD mono className="hidden text-caption text-muted-foreground @[400px]:table-cell" title={f.accession}>{f.accession}</TD>
                    <TD align="right" mono className="text-muted-foreground">{f.filing_date}</TD>
                  </tr>
                )
              })}
            </tbody>
          </Table>
          </div>
          <div className="border-t border-row-rule px-3 py-2 text-label leading-[1.45] text-muted-foreground">
            A row opens the filing on SEC EDGAR. 10-Ks, 10-Qs, 8-Ks and
            amendments are narrative documents; Forms 3, 4, 144 and holder
            notices are data tables.
          </div>
        </>
      )}
    </Widget>
  )
}
