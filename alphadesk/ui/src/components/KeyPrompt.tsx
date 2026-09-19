import { Link } from "react-router-dom"
import { isNeedsKey, type KeyPromptBody } from "@/lib/api"
import { Empty } from "@/components/terminal"

/** What a panel shows in place of data when no vendor the user connected
 * serves it (2026-09-13: AlphaDesk carries no market data of its own). Names
 * the vendors that would, free ones first, each with its signup link, and
 * sends the user to the Account page to connect one. When one of the user's
 * own vendors refused the call on plan, that is said first — the key works,
 * the plan does not cover this. */
export function KeyPrompt({ prompt, compact = false }: { prompt: KeyPromptBody; compact?: boolean }) {
  const free = prompt.vendors.filter(v => v.tier === "free")
  const paid = prompt.vendors.filter(v => v.tier === "paid")
  const list = (vs: KeyPromptBody["vendors"]) => vs.map((v, i) => (
    <span key={v.name}>
      {i > 0 && (i === vs.length - 1 ? " or " : ", ")}
      <a href={v.signup} target="_blank" rel="noopener noreferrer"
         className="font-medium text-foreground underline decoration-dotted underline-offset-2 hover:text-accent-700">{v.label}</a>
    </span>
  ))
  if (!prompt.signed_in) {
    return <Empty>Sign in and connect a data key to see {prompt.label.toLowerCase()}.</Empty>
  }
  // Every vendor that carries this is one the reader already connected, on a
  // plan that refuses it: "Connect a key" would be advice that cannot work,
  // so the panel states the position and links the plan (2026-09-15).
  const refused = prompt.refused.map(r => r.toLowerCase())
  if (prompt.refused.length && prompt.vendors.every(v => refused.includes(v.label.toLowerCase()))) {
    return (
      <div className={`px-3 ${compact ? "py-2.5" : "py-4"} text-body leading-[1.55] text-muted-foreground`}>
        {prompt.label} is not part of your {prompt.refused.join(" or ")} plan
        {prompt.vendors.length === 1 ? <>, and no other vendor here carries it</> : null}. It is on{" "}
        {list(prompt.vendors)}&apos;s paid plans.
      </div>
    )
  }
  return (
    <div className={`px-3 ${compact ? "py-2.5" : "py-4"} text-body leading-[1.55] text-muted-foreground`}>
      <p className="font-semibold text-foreground">
        {prompt.refused.length
          ? `Your ${prompt.refused.join(" and ")} plan doesn't include ${prompt.label.toLowerCase()}.`
          : `${prompt.label} needs a data key.`}
      </p>
      <p className="mt-1">
        {free.length > 0 && <>A free key from {list(free)} fills this panel{paid.length ? "; " : "."}</>}
        {paid.length > 0 && <>{free.length ? "so does a paid plan from " : "It needs a paid plan from "}{list(paid)}.</>}
        {" "}
        <Link to="/account" className="text-accent-700 underline underline-offset-2">Connect a key</Link>
      </p>
    </div>
  )
}

/** A query's failure, rendered: the key prompt when the server said no
 * connected vendor serves this, otherwise the panel's own sentence. */
export function QueryFailure({ error, children, compact }: { error: unknown; children: React.ReactNode; compact?: boolean }) {
  if (isNeedsKey(error)) return <KeyPrompt prompt={error.prompt} compact={compact} />
  return <Empty>{children}</Empty>
}
