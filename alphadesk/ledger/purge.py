"""Remove every account but the one login (2026-10-03).

The server became one person's own, so the accounts a Google or GitHub
sign-in made are locked out but their rows, keys and fetched data remain. This
deletes them, whole, one transaction per account (store.delete_account).

It is a maintenance setting, not a command, because the live server has no
shell: ALPHADESK_PURGE_OTHER_ACCOUNTS=count only reports what would go, and
=delete does it. Both act at start, only when a login email is set, and never
touch that account. Unset it after the run.
"""

from __future__ import annotations

import logging
import os

log = logging.getLogger("alphadesk.purge")


def run_at_start(keep_email: str) -> None:
    mode = os.environ.get("ALPHADESK_PURGE_OTHER_ACCOUNTS", "").strip().lower()
    if not mode or not keep_email:
        return
    if mode not in ("count", "delete"):
        log.warning("ALPHADESK_PURGE_OTHER_ACCOUNTS=%r is not 'count' or 'delete': nothing done", mode)
        return
    from alphadesk.ledger import store
    keep = store.get_user_by_email(keep_email)
    if keep is None:
        log.warning("purge: the login account %s does not exist, so nothing is deleted", keep_email)
        return
    others = [u for u in store.list_users() if u["user_id"] != keep["user_id"]]
    log.info("purge: %d account%s besides the login", len(others), "" if len(others) == 1 else "s")
    if mode == "count":
        return
    totals: dict[str, int] = {}
    deleted = 0
    for u in others:
        rows = store.delete_account(u["user_id"])
        if rows is None:
            continue
        deleted += 1
        for table, n in rows.items():
            totals[table] = totals.get(table, 0) + n
    log.info("purge: deleted %d account%s; rows removed per table: %s", deleted,
             "" if deleted == 1 else "s", ", ".join(f"{t}={n}" for t, n in sorted(totals.items()) if n) or "none")
