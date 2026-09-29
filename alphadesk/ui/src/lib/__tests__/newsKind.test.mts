import { strict as assert } from "node:assert"
import { test } from "node:test"
import { isWireRelease, storyKind } from "../newsKind.ts"

test("a wire host is the company's own word, a reporter's article is not", () => {
  assert.equal(isWireRelease({ url: "https://www.globenewswire.com/x", source: "globenewswire.com" }), true)
  assert.equal(isWireRelease({ url: "https://www.businesswire.com/y", source: "businesswire.com" }), true)
  assert.equal(isWireRelease({ url: "https://ir.example.com/a", source: "prnewswire.com" }), true)
  // A reporter writing ABOUT a company is not the company speaking.
  assert.equal(isWireRelease({ url: "https://www.benzinga.com/news/x", source: "benzinga" }), false)
  assert.equal(isWireRelease({ url: "https://www.reuters.com/x", source: "reuters.com" }), false)
  // A lookalike host must not pass.
  assert.equal(isWireRelease({ url: "https://notglobenewswire.com/x", source: "" }), false)
  assert.equal(isWireRelease({ url: "", source: "" }), false)
})

// EVERY CASE BELOW IS A REAL STORY from the live window on 2026-09-29, kept
// with its own URL and headline. An invented headline would test the regex
// against itself; these test it against what the publisher actually files.
const bz = (channel: string, title = "") =>
  ({ url: `https://www.benzinga.com/${channel}/26/09/62057613/slug`, source: "benzinga", title })

test("the publisher's own channel names the kind", () => {
  assert.equal(storyKind(bz("wiim", "Carnival shares are trading higher after the company reported")), "why")
  assert.equal(storyKind(bz("news/earnings", "Turbo Energy H1 Sales $17.200M")), "earnings")
  assert.equal(storyKind(bz("markets/earnings", "CarMax Says Even Its Lowest-Income Customers Are Holding Up")), "earnings")
  assert.equal(storyKind(bz("trading-ideas/movers", "Nu Holdings Stock Bounces Back: What's Happening?")), "movers")
  assert.equal(storyKind(bz("markets/offerings", "Snowflake Upsizes Convertible Note Offering to $3.75 Billion")), "offering")
  assert.equal(storyKind(bz("etfs/new-etfs", "QUICK SPARK: Bitwise Launches First Spot NEAR ETF In US")), "fund")
  assert.equal(storyKind(bz("economics/macro-economic-events", "Trump Administration Says Several EU Member Countries")), "macro")
  assert.equal(storyKind(bz("crypto/cryptocurrency", "Bitcoin's Rally Breaks Analyst's Bear Thesis")), "crypto")
  assert.equal(storyKind(bz("m-a", "Amaze Turns to Gold and Defi With $155 Million BullionFx Reverse Acquisition Offer")), "ma")
  assert.equal(storyKind(bz("m", "Valley To Acquire Bluevine For ~$340M")), "ma")
})

test("a narrower channel beats the section it sits in", () => {
  // "markets" is not a kind; "markets/earnings" is. Without longest-prefix
  // matching, a section entry would swallow every channel beneath it.
  assert.equal(storyKind(bz("markets/tech", "Meta Brings Its New Enterprise AI Push to the White House")), "company")
  assert.equal(storyKind(bz("markets/earnings", "Carnival CEO Says Vacation Demand Is Defying Economic Angst")), "earnings")
})

test("the two kinds the channel scatters are read from the title", () => {
  // MEASURED: four of the twelve generic stories were analyst notes, filed
  // under the generic channel while others sit under their own. Reading the
  // title first gives one kind rather than two names for the same thing.
  assert.equal(storyKind(bz("news", "HSBC Maintains Hold on JPMorgan Chase, Raises Price Target to $377")), "rating")
  assert.equal(storyKind(bz("news", "TD Cowen Maintains Buy on ExxonMobil Holdings, Raises Price Target to $180")), "rating")
  assert.equal(storyKind(bz("analyst-stock-ratings/price-target", "These Analysts Revise Their Forecasts On Vail Resorts Following Q4 Results")), "rating")
  // A transcript is ALWAYS filed generic.
  assert.equal(storyKind(bz("news", "Full Transcript: Pfizer Q2 2026 Earnings Call")), "transcript")
  assert.equal(storyKind(bz("news", "ReposiTrak Reports Q4 2026 Results: Full Earnings Call Transcript")), "transcript")
})

test("a third-party pickup is quoted with its publication trailing", () => {
  assert.equal(storyKind(bz("news", "'JPMorgan Tweaks Data-Sharing Notices in Battle With Fintechs' - Bloomberg")), "pickup")
  assert.equal(storyKind(bz("news", "'Anthropic Discloses up to $84.5 Billion in SpaceX Compute Agreements' - The Information")), "pickup")
  // A company's own announcement is NOT a pickup, and this is the case the
  // rule must not swallow — the generic bucket is mostly these.
  assert.equal(storyKind(bz("news", "SLB's OneSubsea JV Receives ExxonMobil Contract To Provide Subsea Production Systems")), "company")
})

test("a wire release is the company's own word, whatever the channel", () => {
  assert.equal(storyKind({ url: "https://www.globenewswire.com/x", source: "globenewswire.com", title: "Acme Reports Q3" }), "release")
})

test("an unknown publisher is left unlabelled rather than guessed at", () => {
  // Another feed brings its own paths. Inventing a kind for a URL shape we
  // have never measured is the thing this rule exists to avoid.
  assert.equal(storyKind({ url: "https://www.reuters.com/markets/x", source: "reuters", title: "Some headline" }), null)
  assert.equal(storyKind({ url: "", source: "", title: "" }), null)
})
