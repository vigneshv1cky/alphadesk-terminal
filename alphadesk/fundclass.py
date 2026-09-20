"""What a fund's own name says it is: a product built on ONE company, or a
basket that merely shares a word with it (2026-09-20).

THE PROBLEM. "Funds on this stock" matches a fund name against the company's
distinctive word. That word is the company's own coinage for NVIDIA or Tesla,
but Space Exploration Technologies gives "space" — and twelve space-sector
ETFs (ARK, Procure, VanEck, Global X, WisdomTree, Amplify …) joined SPCX's
panel beside its real 2x longs and shorts.

WHY A MODEL HERE, WHEN NOTHING ELSE USES ONE. Measured on those 22 funds:
  * Two prose descriptions ("a fund tracking one company" against "a fund
    holding a basket") scored 18 of 20, by margins of thousandths — it called
    a genuine SPCX buffer fund a sector fund and VanEck's sector ETF
    single-stock. Useless.
  * CENTROIDS OF REAL EXAMPLES scored 20 of 20, with margins an order of
    magnitude wider, and settled the two names a rule cannot: "Defiance Pure
    Space Daily 2X Strategy ETF" reads single-stock, "Tuttle Capital Space
    Industry Income Blast ETF" sector.
The positive examples label themselves: a fund whose name carries a TICKER is
a single-stock product by construction, so every ticker match the panel makes
is recorded as one. The negatives are a small fixed list of sector ETFs from
other industries, so nothing here is learned from the case being judged.

NOTHING IS TRAINED. The model's weights are never touched — it is asked for
numbers and nothing else. What grows is the set of known names, and a
reference point is the average of their numbers.

IT NEVER RUNS IN A REQUEST, AND NEVER AGAINST ONE. Reading fourteen fund
names takes 6.6 seconds on this CPU; inline that is the contention that took
the service down on 2026-09-19. Everything here goes through semantic.encode,
which stands aside while a request is in flight and yields between chunks —
the first version called the model directly and ignored both fences. The
worker runs at nice 19 and writes a verdict per fund name that holds for
every reader (a fund name means the same thing to everyone). Until a verdict
exists the panel falls back to what the name declares — see
ingest/related_funds.keep_fund.

EACH EXAMPLE'S NUMBERS ARE KEPT (store.fund_name_verdicts.vec), so a
reference point is an average over stored rows. The first version read up to
four hundred names through the model again every time the known set grew by
one, which is minutes of processor time for an answer that had barely moved.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("alphadesk.fundclass")

#: Sector and thematic ETFs from industries other than any the classifier is
#: asked about, so the negative centroid is never built from the names under
#: judgement. Deliberately small and fixed: it is a reference, not training.
NEGATIVE_EXAMPLES = (
    "VanEck Semiconductor ETF",
    "Global X Robotics & Artificial Intelligence ETF",
    "ARK Innovation ETF",
    "iShares Biotechnology ETF",
    "SPDR S&P Oil & Gas Exploration & Production ETF",
    "First Trust Cloud Computing ETF",
    "Invesco Solar ETF",
    "Global X Lithium & Battery Tech ETF",
    "Amplify Cybersecurity ETF",
    "Roundhill Video Games ETF",
    "iShares US Aerospace & Defense ETF",
    "WisdomTree Cloud Computing Fund",
    "VistaShares Artificial Intelligence Supercycle ETF",
    "Tema Cardiovascular and Metabolic ETF",
    "Procure Disaster Recovery Strategy ETF",
)

#: Below this many known single-stock names the positive centroid is noise,
#: and the classifier stays silent rather than guessing. Reached quickly: one
#: NVIDIA panel alone records twenty.
MIN_POSITIVES = 20

#: How far the two centroids must disagree before a verdict is recorded. The
#: measured spread was +0.012 to +0.094 for single-stock funds and -0.024 to
#: -0.086 for sector funds, so anything inside this band is a name the model
#: cannot separate and is left to the fallback.
MARGIN = 0.005

#: The most known names one centroid averages, newest first.
MAX_EXAMPLES = 400
#: Known names whose numbers are missing that one turn reads. Bounded so a
#: cold table warms over a few turns instead of holding the worker for
#: minutes; the numbers are kept, so it happens once per name ever.
NEW_EXAMPLES_PER_TURN = 12

#: The fixed list's centre, read once per process: fifteen names that never
#: change, against hundreds that do.
_negative: Any = None


def _norm(v):
    import numpy as np
    n = np.linalg.norm(v)
    return v / n if n else v


def _centre(vectors):
    import numpy as np
    return _norm(np.asarray(vectors).mean(0))


def _negative_centre():
    global _negative
    if _negative is None:
        from alphadesk import semantic
        vecs = semantic.encode(list(NEGATIVE_EXAMPLES))
        if not vecs:
            return None
        _negative = _centre(vecs)
    return _negative


def _positive_centre():
    """The centre of the known single-stock names. Stored numbers are read
    from the table; only names that have none go through the model, and what
    they give is kept."""
    from alphadesk import semantic
    from alphadesk.ledger import store
    rows = store.fund_examples("single", MAX_EXAMPLES, semantic.MODEL_ID)
    if len(rows) < MIN_POSITIVES:
        return None
    vecs = [semantic.unpack(v) for _, v in rows if v]
    missing = [n for n, v in rows if not v][:NEW_EXAMPLES_PER_TURN]
    if missing:
        fresh = semantic.encode(missing)
        if fresh:
            store.save_fund_vectors(semantic.MODEL_ID,
                                    [(n, semantic.pack(v)) for n, v in zip(missing, fresh)])
            vecs.extend(fresh)
    if len(vecs) < MIN_POSITIVES:
        return None                          # still warming: a later turn decides
    return _centre(vecs)


def centroids():
    """(positive, negative) centroids, or None while there are too few known
    single-stock names or the model cannot load."""
    pos = _positive_centre()
    if pos is None:
        return None
    neg = _negative_centre()
    return None if neg is None else (pos, neg)


def verdict_for(margin: float) -> str | None:
    """single / sector / None (too close to call). Pure."""
    if margin > MARGIN:
        return "single"
    if margin < -MARGIN:
        return "sector"
    return None


def classify_pending(limit: int = 16) -> int:
    """Classify queued fund names. Returns how many verdicts were written.
    Called only from the idle worker."""
    from alphadesk import semantic
    from alphadesk.ledger import store
    if semantic.model() is None:
        return 0
    names = store.pending_fund_names(limit)
    if not names:
        return 0
    cents = centroids()
    if cents is None:
        return 0
    pos, neg = cents
    vecs = semantic.encode(names)
    if not vecs:
        return 0
    rows = []
    for name, v in zip(names, vecs):
        margin = float(v @ pos) - float(v @ neg)
        # A name the centroids cannot separate is recorded as "unclear", so
        # it is not asked again every cycle; the fallback then decides it.
        # Its numbers are kept either way, so a later margin costs no reading.
        rows.append((name, verdict_for(margin) or "unclear", margin, semantic.pack(v)))
    store.save_fund_verdicts(semantic.MODEL_ID, rows)
    log.info("fund classifier: %d names (%s)", len(rows),
             ", ".join(f"{v}×{sum(1 for r in rows if r[1] == v)}" for v in ("single", "sector", "unclear")))
    return len(rows)
