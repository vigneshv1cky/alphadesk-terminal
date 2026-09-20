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

IT NEVER RUNS IN A REQUEST. Embedding fourteen fund names takes 6.6 seconds on
this CPU; inline that is the contention that took the service down on
2026-09-19. The classifier runs on the same idle worker as search, at nice 19,
only while no request is in flight, and writes a verdict per fund name that
holds for every reader (a fund name means the same thing to everyone). Until a
verdict exists the panel falls back to what the name declares — see
ingest/related_funds.keep_fund.
"""

from __future__ import annotations

import logging

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

_centroids: tuple | None = None
_centroid_count = 0


def _norm(v):
    import numpy as np
    n = np.linalg.norm(v)
    return v / n if n else v


def centroids(force: bool = False):
    """(positive, negative) centroids, or None while there are too few known
    single-stock names. Rebuilt as the positive set grows."""
    global _centroids, _centroid_count
    import numpy as np

    from alphadesk import semantic
    from alphadesk.ledger import store
    pos_names = store.fund_names_by_verdict("single", 400)
    if len(pos_names) < MIN_POSITIVES:
        return None
    if _centroids is not None and not force and len(pos_names) <= _centroid_count:
        return _centroids
    m = semantic.model()
    if m is None:
        return None
    pos = m.encode(list(pos_names), batch_size=16, normalize_embeddings=True)
    neg = m.encode(list(NEGATIVE_EXAMPLES), batch_size=16, normalize_embeddings=True)
    _centroids = (_norm(np.asarray(pos).mean(0)), _norm(np.asarray(neg).mean(0)))
    _centroid_count = len(pos_names)
    return _centroids


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
    import numpy as np

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
    vecs = semantic.model().encode(names, batch_size=8, normalize_embeddings=True)
    rows = []
    for name, v in zip(names, np.asarray(vecs)):
        margin = float(v @ pos) - float(v @ neg)
        verdict = verdict_for(margin)
        # A name the centroids cannot separate is recorded as "unclear", so
        # it is not asked again every cycle; the fallback then decides it.
        rows.append((name, verdict or "unclear", margin))
    store.save_fund_verdicts(semantic.MODEL_ID, rows)
    log.info("fund classifier: %d names (%s)", len(rows),
             ", ".join(f"{v}×{sum(1 for r in rows if r[1] == v)}" for v in ("single", "sector", "unclear")))
    return len(rows)
