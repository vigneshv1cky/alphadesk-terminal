/** About — a PUBLIC page, readable before sign-in like the Terms, because
 * what the thing is should not sit behind a login. Written 2026-09-08 for
 * the integration-platform posture: a research workspace that connects,
 * verifies and presents, on the reader's own keys, and does not trade.
 */

const H = ({ children }: { children: React.ReactNode }) => (
  <h2 className="mb-1.5 mt-7 text-body font-bold uppercase tracking-caps">{children}</h2>
)
const P = ({ children }: { children: React.ReactNode }) => (
  <p className="mb-2.5 text-body leading-[1.65] text-foreground/90">{children}</p>
)
const L = ({ items }: { items: React.ReactNode[] }) => (
  <ul className="mb-2.5 list-disc space-y-1 pl-5 text-body leading-[1.6] text-foreground/90">
    {items.map((it, i) => <li key={i}>{it}</li>)}
  </ul>
)

export default function AboutPage() {
  return (
    <div className="min-h-0 flex-1 overflow-y-auto">
      <div className="mx-auto w-full max-w-[720px] px-5 py-8">
        <h1 className="text-display font-extrabold tracking-tight">About AlphaDesk</h1>
        <p className="mt-1 text-caption text-muted-foreground">
          A market research workspace that connects your own data providers, checks what they return, and presents it for reading — and hands the records to your own AI agent.
        </p>

        <H>What it is</H>
        <P>
          AlphaDesk is a terminal for reading the market: prices and charts,
          news, SEC filings, earnings and options. It runs no model of its
          own; the AI is yours, connected over MCP, and it reads the same
          records the screen shows. It is an integration platform rather than
          a data vendor. You bring
          the keys to the providers you already pay for, and AlphaDesk is the
          workspace that connects them, checks their output, and lays it out on
          one screen.
        </P>
        <P>
          It is a consumption terminal. It fetches, reads and presents. It does
          not place orders, hold positions, route trades, or score decisions.
          Deciding is the reader's part, and the terminal is built so that
          every figure on screen can be traced to whoever published it.
        </P>

        <H>Your keys, your providers</H>
        <P>
          Every seam is a plugin: the news feed, market data and the
          transcript source are each a provider you choose and key on your
          Account page.
          Keys are stored encrypted and used only to serve your own requests.
          AlphaDesk never resells or redistributes a provider's data; it is the
          software through which your own access is exercised.
        </P>
        <L items={[
          <><strong>News.</strong> Polygon, Alpaca, Finnhub, Benzinga, Tiingo, Alpha Vantage, Marketaux, FMP. Key several and your window merges them, de-duplicated by URL.</>,
          <><strong>Market data.</strong> Alpaca, Polygon, Finnhub, Alpha Vantage, Financial Modeling Prep and CoinGecko, each on your own key. Connect several and each panel asks them in turn; a panel none of them carries says which vendors would.</>,
          <><strong>Filings, financial statements and release times.</strong> Straight from SEC EDGAR, and Treasury yields from the US Treasury. Public government data, no key.</>,
        ]} />
        <P>
          AlphaDesk is not an aggregator. There is no shared feed: aggregation
          is your act, on your credentials, and it merges your window and
          nobody else's.
        </P>

        <H>Nothing is paraphrased</H>
        <P>
          No model runs here, so nothing on this screen is a summary of a
          record: it is the record. A filing arrives as the filing, in pages;
          a story as the text your feed delivered; a statement series as the
          company's own XBRL figures. The same holds for the tools your agent
          calls. Where a figure cannot be shown with its source, it is not
          shown.
        </P>
        <P>
          The same honesty applies to the chart. Indicators hide themselves
          when the feed is too sparse to compute them, rather than drawing
          something that looks right. A silent live symbol means the feed saw no print, not
          that the market is closed, and the readout says when it last heard
          one.
        </P>

        <H>The AI is yours</H>
        <P>
          There are no background digests and no model calls at all: an idle
          terminal spends nothing. Ask your own agent instead — Claude,
          ChatGPT, Claude Code, Cursor, opencode — connected to AlphaDesk's
          read-only tools over MCP from the Account page. Every call runs as
          you, on your own vendor keys, and you can disconnect it there at any
          time.
        </P>
        <P>
          External text stays untrusted. Headlines, article bodies, filings
          and transcripts are the publisher's or the filer's words: nothing
          here acts on them, and the tools that hand them to your agent say so,
          so it treats them as data. A press release can carry text aimed at
          whoever reads it; the platform assumes one will.
        </P>

        <H>The chart</H>
        <P>
          The chart is built here, not embedded. Eleven series types, twenty
          parameterised indicators with their own settings, fifteen drawing
          tools with undo, magnet and shortcuts, symbol comparison on a
          percent axis, event markers, display time zones, bar replay,
          multi-chart layouts and saved templates. Drawings and settings
          follow your account. The renderer batches candles into a constant
          number of paths, so a five-year daily series pans as smoothly as a
          day of minutes.
        </P>

        <H>Sources you should know about</H>
        <P>
          AlphaDesk holds no vendor keys of its own, and runs no model of its
          own. Every price, headline and estimate is fetched on the key you
          connected, under your agreement with that vendor; the reading and
          the reasoning happen in your own AI agent, connected over MCP. The
          only sources read without a key are public government data: SEC
          EDGAR and the US Treasury's yield curve. The platform reads them; it
          does not warrant them.
        </P>

        <H>Licence</H>
        <P>
          AlphaDesk is open source under the GNU Affero General Public
          License, version 3: anyone may run, study, change and share it, and
          whoever offers a changed copy to others over a network must offer
          them its source. A commercial licence is available for uses the
          AGPL does not suit, and this hosted service is run under its own
          terms. Every dependency is permissively licensed, checked on
          purpose: a copyleft dependency would rule out the commercial
          licence.
        </P>

        <p className="mt-8 border-t border-row-rule pt-4 text-caption text-muted-foreground">
          Research, not advice. Nothing on this service is a recommendation to
          buy, sell or hold anything. See the{" "}
          <a href="/terms" className="underline decoration-dotted hover:text-foreground">Terms of Service</a>.
        </p>
      </div>
    </div>
  )
}
