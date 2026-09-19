"""Search by meaning (alphadesk/semantic.py): the pure parts. The model
itself is not loaded here — without it every search is words-only."""

from alphadesk import semantic


def test_a_story_is_read_by_its_headline():
    assert semantic.story_text("Fed raises rates", "Long summary…") == "Fed raises rates"
    assert semantic.story_text("", "Only a summary") == "Only a summary"
    assert semantic.story_text(None, None) == ""


def test_vectors_round_trip_through_text():
    import numpy as np
    v = np.array([0.5, -0.25, 0.125, 1.0], dtype=np.float32)
    assert np.allclose(semantic.unpack(semantic.pack(v)), v, atol=1e-3)


def test_merge_is_newest_first_each_story_once():
    words = [{"article_id": "a", "published_at": "2026-09-19T10:00"}, {"article_id": "b", "published_at": "2026-09-18T10:00"}]
    rel = [{"article_id": "c", "published_at": "2026-09-19T12:00", "why": "related"},
           {"article_id": "a", "published_at": "2026-09-19T10:00", "why": "related"}]
    got = semantic.merge(words, rel, 10)
    assert [g["article_id"] for g in got] == ["c", "a", "b"]
    assert "why" not in got[1]          # a word match stays a word match
    assert len(semantic.merge(words, rel, 2)) == 2


def test_no_model_means_no_related_stories(monkeypatch):
    monkeypatch.setattr(semantic, "_model", None)
    assert semantic.related("owner", "chip export controls") == []
    assert semantic.related_articles("owner", "chip export controls") == []


def test_the_worker_waits_while_any_request_is_in_flight():
    semantic._in_flight = 0
    semantic._searches_waiting = 0
    assert not semantic._server_busy()
    semantic.request_started()
    assert semantic._server_busy()
    semantic.request_finished()
    assert not semantic._server_busy()
    semantic.request_finished()          # never below zero
    assert semantic._in_flight == 0



def test_the_dashboard_registers_the_in_flight_counter():
    # Checked by registration, not by a request: a TestClient request here
    # disturbed the movers tests' background refresh in the full suite.
    from alphadesk.app.dashboard import app
    names = [getattr(m.kwargs.get("dispatch"), "__name__", "") for m in app.user_middleware]
    assert "_count_in_flight" in names
