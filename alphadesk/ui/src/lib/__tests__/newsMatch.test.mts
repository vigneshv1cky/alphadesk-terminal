import assert from "node:assert/strict"
import test from "node:test"
import { matchesQuery, matchesStory, stem } from "../newsMatch.ts"

test("a word must be a word, which is what 'hood' got wrong", () => {
  // The reader's own report, 2026-09-17.
  assert.equal(matchesQuery("hood", "Amazon Is Spending $6.8 Billion to Manufacture Walmart's Geography Advantage — a neighborhood store network"), false)
  assert.equal(matchesQuery("hood", "predicting the likelihood of lung cancer"), false)
  assert.equal(matchesQuery("hood", "HOOD MS"), true)
})

test("a ticker is not the start of a longer word, which is what 'ARM' got wrong", () => {
  // The reader's own report, 2026-09-18.
  assert.equal(matchesQuery("ARM", "Shaheen Has Blocked An Arms Sale To Israel"), false)
  assert.equal(matchesQuery("ARM", "Sen. Alan Armstrong Bought Up to $65K of Williams Companies Stock"), false)
  assert.equal(matchesQuery("ARM", "AMD ARM NVDA"), true)                 // the story's ticker tags
  assert.equal(matchesQuery("ARM", "Arm Holdings Rises On New Licensing Deal"), true)
})

test("a last word of five characters or more may still stop part-way", () => {
  assert.equal(matchesQuery("robin", "Why Is Robinhood Markets Stock Falling"), true)
  assert.equal(matchesQuery("semicond", "Semiconductor stocks rally"), true)
  assert.equal(matchesQuery("benz", "benzinga"), false)                 // four: whole words only
})

test("several words are a phrase, in order", () => {
  assert.equal(matchesQuery("jobless claims", "US Weekly Jobless Claims Fall"), true)
  assert.equal(matchesQuery("claims jobless", "US Weekly Jobless Claims Fall"), false)
  assert.equal(matchesQuery("rate cut", "Fed rate cuts loom"), true)     // a plural matches its singular
  assert.equal(matchesQuery("rate decis", "the Fed rate decision"), true)
})

test("punctuation and case are not part of the word", () => {
  assert.equal(matchesQuery("robinhood", "Robinhood's prediction markets"), true)
  assert.equal(matchesQuery("s&p 500", "the S&P 500 lost 0.5%"), true)
})

test("any field can carry the match, and an empty query matches everything", () => {
  assert.equal(matchesQuery("hood", "AAPL MSFT", "Apple rallies", "benzinga"), false)
  assert.equal(matchesQuery("", "anything"), true)
  assert.equal(matchesQuery("nvda", null, undefined, "NVDA"), true)
})

test("a plural matches its singular and back, but a capitalised ticker stays exact", () => {
  assert.equal(matchesQuery("tariff", "New tariffs on steel"), true)
  assert.equal(matchesQuery("companies", "the company said"), true)
  assert.equal(matchesQuery("crash", "market crashes"), true)
  assert.equal(matchesQuery("arm", "an arms sale"), true)                 // lower case: the word
  assert.equal(matchesQuery("ARM", "an arms sale"), false)                // capitals: the ticker
  assert.equal(stem("news"), "news")
})

test("a company the query names widens it to that company's tag and headlines", () => {
  const hood = { tickers: ["HOOD"], names: ["robinhood"] }
  assert.equal(matchesStory("robinhood", { title: "Shares jump on crypto news", tickers: ["HOOD"] }, { tickers: ["HOOD"], names: [] }), true)
  assert.equal(matchesStory("HOOD", { title: "Robinhood Rallies After Launch", tickers: [] }, hood), true)
  assert.equal(matchesStory("HOOD", { title: "Apple rallies", tickers: ["AAPL"] }, hood), false)
  assert.equal(matchesStory("fed", { title: "FedEx beats", tickers: ["FDX"] }, { tickers: [], names: [] }), false)
})

test("a ticker in capitals that names a company skips the word in summaries", () => {
  const hood = { tickers: ["HOOD"], names: ["robinhood"] }
  assert.equal(matchesStory("HOOD", { title: "SCHD vs. VIG", summary: "They diverge under the hood", tickers: ["SCHD"] }, hood), false)
  const arm = { tickers: ["ARM"], names: ["arm"] }
  assert.equal(matchesStory("ARM", { title: "Arm vs. Intel: Which Is a Better Buy", tickers: ["INTC"] }, arm), true)
  assert.equal(matchesStory("ARM", { title: "Senate Blocks Arms Sale", tickers: ["SPY"] }, arm), false)
})
