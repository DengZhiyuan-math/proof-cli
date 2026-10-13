"""Deterministic audit probe for the reported empty reply; expected to expose the read race."""

import json
import threading

from test_discussion_web import _queue, page
from proof_web import studios


def test_completed_discussion_view_contains_the_reply_from_that_completion(page, monkeypatch):
    store, client, log, queue = page
    hub = client.app.studios
    ready, go, finished = threading.Event(), threading.Event(), threading.Event()
    real_record = studios.proof_map.record_discussion_turn
    real_finish = hub._discussion_finish
    real_read = studios.proof_map.discussion_turns
    reply = "Claim " * 1500

    def record(store_, **kwargs):
        if kwargs.get("phase") == "ended":
            ready.set()
            assert go.wait(10), "ending gate timed out"
        return real_record(store_, **kwargs)

    def finish(*args, **kwargs):
        try:
            return real_finish(*args, **kwargs)
        finally:
            finished.set()

    monkeypatch.setattr(studios.proof_map, "record_discussion_turn", record)
    monkeypatch.setattr(hub, "_discussion_finish", finish)
    _queue(queue, [["say", reply]])
    try:
        assert client.post("/api/discussion", {"prompt": "all of it", "provider": "claude"})[0] == 200
        assert ready.wait(10), "the backend did not finish"

        def read_then_finish(store_):
            old = real_read(store_)
            go.set()
            assert finished.wait(10), "the completed record did not settle"
            return old

        monkeypatch.setattr(studios.proof_map, "discussion_turns", read_then_finish)
        view = client.get("/api/discussion")[1]["data"]
        actual = real_read(store)
        print(json.dumps({
            "view_running": view["running"],
            "view_ended": view["turns"][0]["ended"],
            "view_reply_length": len(view["turns"][0]["reply"]),
            "persisted_ended": actual[0]["ended"],
            "persisted_reply_length": len(actual[0]["reply"]),
            "expected_reply_length": len(reply),
            "transcript_present": bool(actual[0].get("transcript")),
        }, indent=2))
        assert view["running"] is None
        assert view["turns"][0]["reply"] == reply, "a settled view must include its completed reply"
    finally:
        go.set()
        finished.wait(10)
