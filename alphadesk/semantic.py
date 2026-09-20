"""Search by MEANING over each reader's own news (2026-09-19, the owner's
call: "for search I am thinking of using a model" → Qwen3-Embedding-0.6B,
"everywhere search, including mcp").

This lifts the 2026-09-17 "no model here" rule for SEARCH ONLY. The model is
an embedding model, self-hosted in this process: it turns text into a
vector and writes nothing, summarises nothing and acts on nothing, so
invariant 1 (nothing is paraphrased) and invariant 5 (untrusted text stays
untrusted) hold. No text leaves the server and there is no model key.
Qwen3-Embedding-0.6B is Apache 2.0; sentence-transformers and transformers
are Apache 2.0; torch is BSD.

How it works:
  * The WORKER (a daemon thread started with the web server) embeds each
    stored story's HEADLINE once, newest first, and stores the
    vector beside the story under the same owner (store.news_vectors). The
    same text for two readers is embedded once (a small in-process memo).
  * A SEARCH embeds the query with the model's retrieval instruction and
    keeps the stories whose cosine similarity clears THRESHOLD. What it
    returns is a SET: callers merge it with the word matches and show the
    result NEWEST FIRST, each meaning-only match marked "related" — the
    similarity picks what is in, never the order (invariant 3).
  * Each reader's vectors are held in memory for search and topped up from
    the store as new ones land.

Off when ALPHADESK_SEMANTIC_SEARCH is "off", or when the packages or the
model cannot load: every caller then gets no related stories and search is
the word rule alone, as before.
"""

from __future__ import annotations

import base64
import hashlib
import logging
import os
import threading
import time
from collections import OrderedDict
from typing import Any

log = logging.getLogger(__name__)

MODEL_ID = os.environ.get("ALPHADESK_EMBED_MODEL", "Qwen/Qwen3-Embedding-0.6B")
#: Cosine similarity a story must reach to count as related. Calibrated on
#: the owner's window, 2026-09-19 (1,536 headlines, twelve queries): at 0.50
#: every story let in was on topic — "AI data center spending" 8 (Equinix,
#: CleanSpark, Crusoe), "crypto regulation" 4, "oil supply disruption" 2 —
#: and a query with nothing on topic in the window added nothing; at 0.45
#: "banks cutting jobs" let in Joby Aviation's share drop and "drug pricing"
#: an IPO's pricing. Precision over recall: the word matches are still there.
THRESHOLD = float(os.environ.get("ALPHADESK_SEMANTIC_THRESHOLD", "0.50"))
#: The query instruction (Qwen3 embeds a query with a task instruction and a
#: document without). A news-specific one put the Fed's decision first for
#: "interest rate cut", where the generic one put a price-target cut.
QUERY_INSTRUCTION = ("Instruct: Given a financial news search query, retrieve news headlines "
                     "reporting on that event or topic\nQuery: ")
#: The most related stories one search adds, most similar first, before the
#: caller orders everything by time.
MAX_RELATED = 60
#: HEADLINES ONLY (2026-09-19, the owner's pick): measured on this model on
#: CPU, 0.44s a story for the headline against 2.7s with the summary — the
#: summary would keep a CPU busy 3–5 hours a day per reader. 64 tokens holds
#: any headline.
MAX_TOKENS = 64
BATCH = 32
WORKER_IDLE_S = 20.0
INDEX_REBUILD_S = 6 * 3600

_model: Any = None
_model_lock = threading.Lock()
_model_failed = False
_worker_started = False
_memo: "OrderedDict[str, str]" = OrderedDict()   # text hash -> vec, across owners
_MEMO_MAX = 20000
# owner -> {"since": iso, "ids": [...], "pub": [...], "mat": ndarray}
_index: dict[str, dict] = {}
_index_lock = threading.Lock()
# SEARCHES FIRST (2026-09-19, measured locally: a search waited 3–8s behind
# the worker's batch of headlines). One encode at a time; the worker encodes
# CHUNK headlines per turn and steps aside while any search is waiting, so a
# search waits at most one chunk.
_encode_lock = threading.Lock()
_searches_waiting = 0
_waiting_lock = threading.Lock()
CHUNK = 4
# THE WORKER WAITS FOR AN IDLE SERVER (2026-09-19, the live outage): deployed
# with torch on cpu_count()-1 threads, the container reported the HOST's
# cores, the worker took them all from 2 vCPU, requests queued past Cloud
# Run's concurrency and 159 were refused "Rate exceeded" in 15 minutes.
# Now the model runs on ONE thread, the worker thread at the lowest OS
# priority, and a chunk is encoded only while no request is in flight
# (the dashboard's middleware counts them; the live streams do not count).
_in_flight = 0
_flight_lock = threading.Lock()


def request_started() -> None:
    global _in_flight
    with _flight_lock:
        _in_flight += 1


def request_finished() -> None:
    global _in_flight
    with _flight_lock:
        _in_flight = max(0, _in_flight - 1)


def _server_busy() -> bool:
    return bool(_in_flight or _searches_waiting)


def enabled() -> bool:
    return os.environ.get("ALPHADESK_SEMANTIC_SEARCH", "on").lower() not in ("off", "0", "false", "no")


def model() -> Any:
    """The embedding model, loaded once; None when it cannot be."""
    global _model, _model_failed
    if _model is not None or _model_failed or not enabled():
        return _model
    with _model_lock:
        if _model is None and not _model_failed:
            try:
                os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
                import torch
                # ONE thread, whatever the machine reports: inside a
                # container os.cpu_count() is the host's cores, not the
                # service's 2 vCPU (see _in_flight above).
                torch.set_num_threads(1)
                torch.set_num_interop_threads(1)
                from sentence_transformers import SentenceTransformer
                t = time.time()
                m = SentenceTransformer(MODEL_ID, device="cpu")
                m.max_seq_length = MAX_TOKENS
                _model = m
                log.info("semantic search: %s loaded in %.1fs (machine reports %s cores; model on %s thread)",
                         MODEL_ID, time.time() - t, os.cpu_count(), torch.get_num_threads())
            except Exception as exc:                   # no packages, no weights: word search only
                _model_failed = True
                log.warning("semantic search off: %s", exc)
    return _model


def ready() -> bool:
    return _model is not None


def story_text(title: str | None, summary: str | None = None) -> str:
    """What a story's meaning is read from: its HEADLINE (see MAX_TOKENS);
    the summary only when a story has no headline. Pure."""
    t, s = (title or "").strip(), (summary or "").strip()
    return t or s[:300]


def pack(vec) -> str:
    """A normalised vector as base64 float16 text. Pure."""
    import numpy as np
    return base64.b64encode(np.asarray(vec, dtype=np.float16).tobytes()).decode("ascii")


def unpack(text: str):
    import numpy as np
    return np.frombuffer(base64.b64decode(text), dtype=np.float16).astype(np.float32)


def encode(texts: list[str]):
    """Normalised vectors for `texts`, CHUNK at a time — THE ONE PATH every
    background caller goes through. It waits while any request is in flight
    and releases the lock between chunks, so a search never queues behind
    more than one chunk and the model never competes with the web server
    (see _in_flight above). None when the model cannot load.

    Anything encoding in the background calls THIS, not the model directly:
    the classifier's first version called the model itself, and its batch of
    eight fund names (about five seconds) ignored both fences."""
    m = model()
    if m is None:
        return None
    out = []
    for start in range(0, len(texts), CHUNK):
        part = texts[start:start + CHUNK]
        while _server_busy():
            time.sleep(0.05)
        with _encode_lock:
            out.extend(m.encode(part, batch_size=CHUNK, normalize_embeddings=True,
                                show_progress_bar=False))
    return out


def embed_stories(texts: list[str]) -> list[str] | None:
    if model() is None:
        return None
    out: list[str | None] = [None] * len(texts)
    todo, keys = [], []
    for i, t in enumerate(texts):
        k = hashlib.sha1(t.encode("utf-8", "ignore")).hexdigest()
        keys.append(k)
        if k in _memo:
            out[i] = _memo[k]
        else:
            todo.append(i)
    for i, v in zip(todo, encode([texts[i] for i in todo]) or []):
        packed = pack(v)
        out[i] = packed
        _memo[keys[i]] = packed
        if len(_memo) > _MEMO_MAX:
            _memo.popitem(last=False)
    return [o for o in out if o is not None]


def embed_query(query: str):
    m = model()
    if m is None:
        return None
    global _searches_waiting
    with _waiting_lock:
        _searches_waiting += 1
    try:
        with _encode_lock:
            return m.encode([QUERY_INSTRUCTION + query], normalize_embeddings=True, show_progress_bar=False)[0]
    finally:
        with _waiting_lock:
            _searches_waiting -= 1


def embed_pending(limit: int = 256) -> int:
    """Embed up to `limit` stored stories that have no vector yet. Returns
    how many were stored."""
    from alphadesk.ledger import store
    if model() is None:
        return 0
    rows = store.unembedded_articles(MODEL_ID, limit)
    rows = [r for r in rows if story_text(r.get("title"), r.get("summary"))]
    if not rows:
        return 0
    vecs = embed_stories([story_text(r.get("title"), r.get("summary")) for r in rows]) or []
    store.save_news_vectors(MODEL_ID, [(r["owner"], r["article_id"], v) for r, v in zip(rows, vecs)])
    return len(vecs)


def _worker() -> None:
    # The lowest scheduling priority for this thread (Linux: per thread), so
    # the web server's threads always run first.
    try:
        os.setpriority(os.PRIO_PROCESS, threading.get_native_id(), 19)
    except (AttributeError, OSError):
        pass
    while True:
        try:
            n = embed_pending(32)
        except Exception as exc:
            log.warning("semantic worker: %s", exc)
            n = 0
        try:
            # The same idle budget classifies fund names (fundclass.py):
            # stories first, because a reader is waiting on search.
            from alphadesk import fundclass
            n += fundclass.classify_pending(8) if not n else 0
        except Exception as exc:
            log.warning("fund classifier: %s", exc)
        time.sleep(0.5 if n else WORKER_IDLE_S)


def start_worker() -> None:
    """Load the model and start embedding stored stories, in the background:
    the web server does not wait for it, and search is words-only until the
    model is ready."""
    global _worker_started
    if _worker_started or not enabled():
        return
    _worker_started = True
    threading.Thread(target=_worker, name="semantic-worker", daemon=True).start()


def _owner_index(owner: str) -> dict:
    """The owner's vectors, loaded once and topped up since the last read."""
    import numpy as np
    from alphadesk.ledger import store
    with _index_lock:
        ix = _index.get(owner)
    # Rebuilt from the store every INDEX_REBUILD_S, so stories pruned since
    # (7 days, a removed key) leave the index too.
    if not ix or time.time() - ix.get("built", 0) > INDEX_REBUILD_S:
        ix = {"since": "", "ids": [], "pub": [], "mat": np.zeros((0, 0), dtype=np.float32), "built": time.time()}
    new = store.news_vectors_since(owner, MODEL_ID, ix["since"])
    if new:
        known = set(ix["ids"])
        fresh = [r for r in new if r["article_id"] not in known]
        if fresh:
            add = np.vstack([unpack(r["vec"]) for r in fresh])
            mat = add if ix["mat"].size == 0 else np.vstack([ix["mat"], add])
            ix = {"since": new[-1]["embedded_at"], "ids": ix["ids"] + [r["article_id"] for r in fresh],
                  "pub": ix["pub"] + [r["published_at"] or "" for r in fresh], "mat": mat, "built": ix["built"]}
        else:
            ix = {**ix, "since": new[-1]["embedded_at"]}
    with _index_lock:
        _index[owner] = ix
    return ix


def related(owner: str, query: str, before: str | None = None, since: str | None = None,
            limit: int = MAX_RELATED) -> list[tuple[str, float]]:
    """(article_id, similarity) for `owner`'s stories related in meaning to
    `query`, optionally published before `before` / at or after `since` —
    the most similar `limit` that clear THRESHOLD. Empty when the model is
    not ready (search stays words-only) or the query is too short to mean
    anything."""
    import numpy as np
    q = (query or "").strip()
    if len(q) < 3 or not enabled() or not ready():
        return []
    ix = _owner_index(owner)
    if not ix["ids"]:
        return []
    qv = embed_query(q)
    if qv is None:
        return []
    sims = ix["mat"] @ np.asarray(qv, dtype=np.float32)
    out: list[tuple[str, float]] = []
    for i in np.argsort(-sims):
        s = float(sims[i])
        if s < THRESHOLD or len(out) >= limit:
            break
        pub = ix["pub"][i]
        if before and pub and pub >= before:
            continue
        if since and pub and pub < since:
            continue
        out.append((ix["ids"][i], s))
    return out


def related_articles(owner: str, query: str, before: str | None = None, since: str | None = None,
                     exclude: set[str] | None = None, limit: int = MAX_RELATED) -> list[dict]:
    """The related stories themselves, each marked why="related", newest
    first, minus `exclude` (the word matches already shown). A story pruned
    since the index was built is simply absent."""
    from alphadesk.ledger import store
    hits = [aid for aid, _ in related(owner, query, before=before, since=since, limit=limit)
            if not exclude or aid not in exclude]
    rows = store.articles_by_ids(owner, hits)
    for r in rows:
        r["why"] = "related"
    return rows


def merge(words: list[dict], rel: list[dict], limit: int) -> list[dict]:
    """Word matches and related stories as ONE list, each story once,
    newest first, capped. Pure."""
    seen, out = set(), []
    for a in sorted([*words, *rel], key=lambda a: a.get("published_at") or "", reverse=True):
        if a["article_id"] in seen:
            continue
        seen.add(a["article_id"])
        out.append(a)
    return out[:limit]
