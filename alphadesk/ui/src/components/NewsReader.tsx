import { ArrowLeft } from "lucide-react"
import { useQuery } from "@tanstack/react-query"
import { useEarningsFind } from "@/lib/queries"
import { reportBehindStory, reportedLine } from "@/lib/storyReport"
import { HeadlineTickers } from "@/components/HeadlineTickers"
import { api, type NewsArticle } from "@/lib/api"
import { vendorLabel, viaFeeds } from "@/lib/vendors"
import { Empty } from "@/components/terminal"

/** The article reader — one implementation for every news surface.
 *
 * It shows what the pipeline actually holds: title, source, time, the
 * provider's summary and the story's tickers — with the original a
 * deliberate click away.
 * A feed that delivers the full text (Alpaca's Benzinga stories) reads here
 * in whole; otherwise the summary shows, and the reader says where ours
 * ends and links out rather than pretending.
 *
 * On the News view it fills the pane beside the list; inside a tile it
 * REPLACES the list in place — pass `onBack` and it grows the back row, so
 * reading a story never navigates away from the board you were on.
 */

function when(iso: string | null): string {
  if (!iso) return ""
  const d = new Date(iso)
  return `${d.toLocaleDateString("en-US", {
    timeZone: "America/New_York", month: "long", day: "numeric", year: "numeric",
  })} · ${d.toLocaleTimeString("en-US", {
    timeZone: "America/New_York", hour: "numeric", minute: "2-digit",
  })} ET`
}

/** The feeds licensed to deliver an article's text. Measured on the live
 * store (2026-09-15): of 200 stored stories, the 11 with a body all came
 * from Alpaca's Benzinga feed; the other 188, from FMP, carried a summary
 * of a few hundred characters. The other six feeds AlphaDesk ships send
 * summaries by licence too, so a short story is the vendor's limit, not a
 * failure here — and the reader now says which it is. */
const FULL_TEXT_FEEDS = ["alpaca", "benzinga"]

export function NewsReader({ article: listed, onBack }: {
  article: NewsArticle | null
  onBack?: () => void
}) {
  // A story stored before its feed was asked for the text (2026-09-15) is
  // fetched once with it when it opens; the server stores what it gets.
  // The list carries no text, so a story with it (or an Alpaca story that
  // may gain it) fetches it when it opens.
  const wantsText = !!listed && !listed.body && (!!listed.has_body || (listed.feeds ?? []).includes("alpaca"))
  const story = useQuery({
    queryKey: ["news", "story", listed?.article_id],
    queryFn: () => api.newsStory(listed!.article_id),
    enabled: wantsText,
    staleTime: Infinity,
    retry: false,
  })
  const article = listed && story.data?.body ? { ...listed, body: story.data.body } : listed
  // Named plainly: the feed that carried this story does not license its
  // text, so the summary is everything there is to show.
  const summaryOnly = !!article && !article.body
    && !(article.feeds ?? []).some(f => FULL_TEXT_FEEDS.includes(f))
  const carrier = (article?.feeds ?? []).map(f => vendorLabel(f) ?? f).join(" and ")
  // Only when the story is about ONE company: with several tickers there is
  // no single report the date would belong to.
  const subject = (article?.tickers ?? []).length === 1 ? article!.tickers![0] : null
  const found = useEarningsFind(subject)
  const behind = reportBehindStory(found.data?.reports, article?.published_at ?? null)
  const reported = behind ? reportedLine(behind.report_date, article?.published_at ?? null) : null
  if (!article) {
    return <Empty>Pick a headline on the left to read it here.</Empty>
  }
  return (
    <div>
      {onBack && (
        <button
          type="button"
          onClick={onBack}
          className="flex w-full items-center gap-2 border-b border-row-rule px-3 py-2 text-left text-label uppercase tracking-caps text-muted-foreground hover:bg-foreground/5 hover:text-foreground"
        >
          <ArrowLeft className="h-[12px] w-[12px] shrink-0" aria-hidden="true" />
          Back to the headlines
        </button>
      )}
      <div className="px-4 py-3">
        <div className="mb-1.5 flex flex-wrap items-baseline gap-x-2 gap-y-1 text-label font-medium uppercase tracking-caps">
          <span className="text-accent-700">{article.source}</span>
          {viaFeeds(article.feeds) && (
            <span className="normal-case tracking-normal text-muted-foreground" title="The news feeds you connected that delivered this story">
              {viaFeeds(article.feeds)}
            </span>
          )}
        </div>
        <h3 className="text-figure font-extrabold leading-[1.2] tracking-tight">
          {article.title}
        </h3>
        <div className="mt-1 text-caption text-muted-foreground">
          {article.author && <span className="text-foreground">By {article.author}</span>}
          {article.author && " · "}
          {when(article.published_at)}
        </div>
        {reported && (
          <div className="mt-0.5 text-caption text-muted-foreground" title={`${subject}'s last results before this story was published`}>
            <span className="text-accent-700">{subject}</span> · {reported}
          </div>
        )}
        <div className="mt-2 flex flex-wrap gap-1.5">
          <HeadlineTickers symbols={article.tickers} />
        </div>
        {/* No article image, by decision (2026-09-02): the reader is text.
            The feed's image_url stays ingested and on the API for anyone who
            wants it; this surface just doesn't render it. */}
        {/* The article is the contract: a story carrying its full body (a
            feed licensed to deliver it) reads here in whole; one carrying a
            summary shows the summary with the rest a deliberate click away.
            The closing line states which of the two this is. */}
        {article.body ? (
          <p className="mt-3 whitespace-pre-wrap text-body leading-[1.6]">{article.body}</p>
        ) : article.summary ? (
          <>
            <p className="mt-3 whitespace-pre-wrap text-body leading-[1.6]">{article.summary}</p>
            {wantsText && story.isFetching && <p className="mt-2 text-caption text-muted-foreground">loading the full story…</p>}
            {summaryOnly && !story.isFetching && (
              <p className="mt-2 text-caption text-muted-foreground">
                {carrier ? `${carrier} sends` : "This feed sends"} a summary, not the article — the full text stays with the publisher.
              </p>
            )}
          </>
        ) : (
          <p className="mt-3 text-body text-muted-foreground">
            The feed carried no summary for this story{summaryOnly && carrier ? `; ${carrier} does not deliver article text` : ""}.
          </p>
        )}
        <div className="mt-3 border-t border-row-rule pt-2.5">
          <a
            href={article.url}
            target="_blank"
            rel="noreferrer"
            className="text-caption font-semibold text-accent-700 hover:underline"
          >
            {article.body
              ? `From ${article.source || "the source"} — original ↗`
              : `Read the full story on ${article.source || "the source"} ↗`}
          </a>
        </div>
      </div>
    </div>
  )
}
