import { useState } from "react"
import { useQuery, useQueryClient } from "@tanstack/react-query"
import { api, type Access, type AdminUser } from "@/lib/api"
import { Empty, Table, TD, TH, THead, Widget, btnCls, fieldCls } from "@/components/terminal"
import { QueryFailure } from "@/components/KeyPrompt"
import { DeleteAccountDialog } from "@/components/DeleteAccountDialog"
import { useAuthMe } from "@/lib/queries"
import { cn } from "@/lib/utils"
import { Search } from "lucide-react"

/** The owner's admin page (2026-09-18): every account and the switches an
 * operator needs — sign out everywhere, disable, delete. Only the addresses
 * in ALPHADESK_OWNER_EMAILS reach it; the server refuses anyone else, so
 * this page hiding itself is courtesy, not the lock.
 *
 * AlphaDesk is FREE for now (the owner, 2026-09-18: "no payments"): while
 * the access gate is off and no processor is set, the page says nothing
 * about trials or subscriptions — every account is simply Active. The trial
 * columns and "+14 days" come back only if the gate is switched on. */

function day(iso: string | null): string {
  if (!iso) return "—"
  const d = new Date(iso)
  return isNaN(d.getTime()) ? "—" : d.toLocaleDateString("en-US", { month: "short", day: "numeric", year: "numeric" })
}

function ago(iso: string | null): string {
  if (!iso) return "never"
  const min = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000)
  if (min < 2) return "just now"
  if (min < 60) return `${min}m ago`
  if (min < 48 * 60) return `${Math.floor(min / 60)}h ago`
  return `${Math.floor(min / 1440)}d ago`
}

export function accessLabel(a: Access): string {
  if (a.state === "owner") return "Owner"
  // Free: no trial or plan to speak of.
  if (!a.enforced && !a.can_subscribe) return "Active"
  if (a.state === "subscribed") return a.plan_status === "canceled" ? `Subscribed to ${day(a.plan_period_end)}` : "Subscribed"
  if (a.state === "trialing") return `Trial · ${a.days_left ?? 0} day${a.days_left === 1 ? "" : "s"} left`
  return "Trial ended"
}

function Stat({ label, value }: { label: string; value: number | string }) {
  return (
    <div className="flex min-w-0 flex-col gap-1 border-r border-row-rule px-4 py-4 last:border-r-0">
      <span className="truncate text-label font-medium uppercase tracking-caps text-muted-foreground">{label}</span>
      <span className="num text-figure font-extrabold leading-none">{value}</span>
    </div>
  )
}

export default function AdminPage() {
  const { data: me } = useAuthMe()
  const qc = useQueryClient()
  const users = useQuery({ queryKey: ["admin-users"], queryFn: api.adminUsers, enabled: !!me?.user?.owner, retry: false })
  const [busy, setBusy] = useState<string | null>(null)
  const [note, setNote] = useState<string | null>(null)
  const [query, setQuery] = useState("")
  const [open, setOpen] = useState<string | null>(null)
  const [deleting, setDeleting] = useState<AdminUser | null>(null)

  if (me && !me.user?.owner) {
    return <div className="collage"><Widget span={12} title="Admin"><Empty>Only the owner can open this page.</Empty></Widget></div>
  }

  const act = (key: string, run: () => Promise<unknown>, done: string) => {
    setBusy(key)
    setNote(null)
    run()
      .then(() => { setNote(done); void qc.invalidateQueries({ queryKey: ["admin-users"] }) })
      .catch(e => setNote(String(e.message ?? e)))
      .finally(() => setBusy(null))
  }

  const d = users.data
  const paid = !!d && (d.enforced || d.payments)
  const q = query.trim().toLowerCase()
  const shown = (d?.users ?? []).filter(u => !q || u.email.includes(q))
  const detail = (u: AdminUser) => {
    const c = u.counts
    if (!c) return null
    const bits = [
      `${c.keys} key${c.keys === 1 ? "" : "s"}`,
      `${c.views} view${c.views === 1 ? "" : "s"}`,
      `${c.baskets} basket${c.baskets === 1 ? "" : "s"}`,
      `${c.agent_tokens} agent token${c.agent_tokens === 1 ? "" : "s"}`,
      `${c.agent_apps} agent app${c.agent_apps === 1 ? "" : "s"}`,
    ]
    return (
      <tr key={u.user_id + "-detail"}>
        <TD colSpan={6} className="bg-foreground/[0.03] text-caption text-muted-foreground">
          Holds {bits.join(" · ")} · joined {day(u.created_at)} · sign-in: {u.sign_ins.join(", ") || "none recorded"}
        </TD>
      </tr>
    )
  }
  const row = (u: AdminUser) => {
    const self = u.email === me?.user?.email
    const expanded = open === u.user_id
    return [
      <tr key={u.user_id} className="hover:bg-foreground/5">
        <TD className="font-semibold" title={u.email}>
          <button type="button" onClick={() => setOpen(expanded ? null : u.user_id)}
                  aria-expanded={expanded} className="block max-w-full truncate rounded-none text-left hover:underline">
            {u.email}
          </button>
        </TD>
        <TD className={u.disabled ? "text-loss" : u.access.state === "expired" ? "text-warn" : ""}>
          {u.disabled ? "Disabled" : accessLabel(u.access)}
        </TD>
        <TD mono className="text-muted-foreground">{day(u.created_at)}</TD>
        <TD mono className="text-muted-foreground">{ago(u.last_seen_at)}</TD>
        <TD className="text-muted-foreground">{u.sign_ins.join(", ") || "—"}</TD>
        <TD align="right">
          <span className="inline-flex flex-nowrap justify-end gap-1.5">
            {paid && u.access.state !== "owner" && (
              <button type="button" disabled={!!busy} className={btnCls()}
                      onClick={() => act(u.user_id + "t", () => api.adminExtendTrial(u.user_id, 14), `${u.email}: trial extended by 14 days`)}>
                +14 days
              </button>
            )}
            <button type="button" disabled={!!busy} className={btnCls()}
                    onClick={() => act(u.user_id + "s", () => api.adminSignOut(u.user_id), `${u.email}: signed out everywhere`)}>
              Sign out
            </button>
            {!self && (
              <button type="button" disabled={!!busy} className={btnCls()}
                      onClick={() => {
                        if (!u.disabled && !window.confirm(`Disable ${u.email}? They are signed out and cannot sign in until you enable them again.`)) return
                        act(u.user_id + "d", () => api.adminSetDisabled(u.user_id, !u.disabled),
                            `${u.email}: ${u.disabled ? "enabled" : "disabled"}`)
                      }}>
                {u.disabled ? "Enable" : "Disable"}
              </button>
            )}
            {!self && (
              <button type="button" disabled={!!busy} className={btnCls({ variant: "danger" })}
                      onClick={() => setDeleting(u)}>
                Delete
              </button>
            )}
          </span>
        </TD>
      </tr>,
      expanded ? detail(u) : null,
    ]
  }

  return (
    <div className="collage mx-auto w-full max-w-[1160px]">
      <Widget span={12} title="Accounts"
              subtitle={d ? (paid
                ? `${d.enforced ? "Access gate ON" : "Access gate off"} · ${d.trial_days}-day trial · payments ${d.payments ? "connected" : "not set up"}`
                : "Free — every account has full access") : undefined}
              actions={d && (
                // Through cn(), so the height REPLACES the field's 32px — a
                // template string kept both and the stylesheet picked 32,
                // crowding the 40px header (2026-09-18).
                <label className="relative block">
                  <Search aria-hidden="true" className="pointer-events-none absolute left-2 top-1/2 h-[13px] w-[13px] -translate-y-1/2 text-muted-foreground" />
                  <input value={query} onChange={e => setQuery(e.target.value)} placeholder="Search email"
                         aria-label="Search accounts by email"
                         className={cn(fieldCls, "h-[28px] w-[220px] rounded-sm border-card-border pl-7 text-caption")} />
                </label>
              )}>
        {users.isPending ? <Empty>loading…</Empty>
          : users.isError ? <QueryFailure error={users.error}>the account list is unavailable</QueryFailure>
          : d && (
            <>
              {paid ? (
                <div className="grid grid-cols-3 border-b border-row-rule sm:grid-cols-6">
                  <Stat label="Accounts" value={d.totals.accounts} />
                  <Stat label="Subscribed" value={d.totals.subscribed} />
                  <Stat label="On trial" value={d.totals.trialing} />
                  <Stat label="Trial ended" value={d.totals.expired} />
                  <Stat label="Disabled" value={d.totals.disabled} />
                  <Stat label="Owners" value={d.totals.owner} />
                </div>
              ) : (
                <div className="grid grid-cols-2 border-b border-row-rule sm:grid-cols-4">
                  <Stat label="Accounts" value={d.totals.accounts} />
                  <Stat label="Active this week" value={d.users.filter(u => u.last_seen_at && Date.now() - new Date(u.last_seen_at).getTime() < 7 * 86_400_000).length} />
                  <Stat label="Disabled" value={d.totals.disabled} />
                  <Stat label="Owners" value={d.totals.owner} />
                </div>
              )}
              {note && <div className="border-b border-row-rule px-3 py-2 text-caption text-muted-foreground">{note}</div>}
              <div className="overflow-x-auto">
                <Table className="min-w-[900px]">
                  <THead>
                    <TH className="w-[260px]">Email</TH>
                    <TH className="w-[170px]">Access</TH>
                    <TH className="w-[110px]">Joined</TH>
                    <TH className="w-[100px]">Last seen</TH>
                    <TH>Sign-in</TH>
                    <TH align="right" className="w-[244px]">Actions</TH>
                  </THead>
                  <tbody>{shown.map(row)}</tbody>
                </Table>
              </div>
              {!shown.length && <Empty>No account matches “{query}”.</Empty>}
            </>
          )}
      </Widget>
      {deleting && (
        <DeleteAccountDialog email={deleting.email} own={false} onClose={() => setDeleting(null)}
          onConfirm={typed => api.adminDeleteUser(deleting.user_id, typed).then(() => {
            setNote(`${deleting.email}: deleted`)
            setDeleting(null)
            void qc.invalidateQueries({ queryKey: ["admin-users"] })
          })} />
      )}
    </div>
  )
}
