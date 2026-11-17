"""P125: a locked store is tried again after a wait, so a sibling's own write job (sec-edgar's
EDGAR feed or reconcile inside `usfin serve`, a dbnomics refresh) no longer drops an input for
the whole run. httpx MockTransport only, no socket; no real sleep."""

from __future__ import annotations

import duckdb
import httpx
import pytest

from assist.sources import base
from assist.sources.base import SourceUnavailable, attach_ro, http_csv, retry_locked

URL = "http://127.0.0.1:8660"


@pytest.fixture
def waits(monkeypatch):
    slept: list[float] = []
    now = [0.0]
    monkeypatch.setattr(base, "LOCKED_WAITS", (30.0, 60.0, 120.0))
    monkeypatch.setattr(base, "_sleep", lambda s: (slept.append(s), now.__setitem__(0, now[0] + s)))
    monkeypatch.setattr(base, "_clock", lambda: now[0])
    return slept, now


def _client(answers):
    """Each request takes the next answer: an exception type to raise or a status code."""
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions.get("timeout", {}).get("read"))
        a = answers.pop(0)
        if isinstance(a, type):
            raise a("boom", request=request)
        return httpx.Response(a, text="date,value\n2026-11-14,1.5\n")

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def test_read_timeout_then_answer(waits):
    slept, _ = waits
    client, seen = _client([httpx.ReadTimeout, 200])
    assert http_csv(client, URL + "/series/fred/DFII10", "sec-edgar") == [
        {"date": "2026-11-14", "value": "1.5"}]
    assert slept == [30.0]
    assert seen == [base.HTTP_TIMEOUT, base.RETRY_TIMEOUT]  # the retry waits longer


def test_503_then_answer(waits):
    slept, _ = waits
    client, _ = _client([503, 503, 200])
    assert len(http_csv(client, URL + "/api/series/x", "dbnomics")) == 1
    assert slept == [30.0, 60.0]


def test_still_locked_after_every_wait(waits):
    slept, _ = waits
    client, _ = _client([httpx.ReadTimeout] * 4)
    with pytest.raises(SourceUnavailable) as e:
        http_csv(client, URL + "/x", "sec-edgar")
    assert e.value.reason == "locked" and slept == [30.0, 60.0, 120.0]
    assert "still locked after 3 retries" in e.value.detail
    assert e.value.stale_input == "sec-edgar (locked)"


def test_gave_up_source_fails_at_once_then_waits_again_later(waits):
    slept, now = waits
    client, _ = _client([httpx.ReadTimeout] * 4 + [httpx.ReadTimeout] + [httpx.ReadTimeout, 200])
    with pytest.raises(SourceUnavailable):
        http_csv(client, URL + "/a", "sec-edgar")
    slept.clear()
    with pytest.raises(SourceUnavailable) as e:  # same process, inside GIVE_UP_SECONDS
        http_csv(client, URL + "/b", "sec-edgar")
    assert slept == [] and "retries" not in e.value.detail
    now[0] += base.GIVE_UP_SECONDS + 1
    assert len(http_csv(client, URL + "/c", "sec-edgar")) == 1
    assert slept == [30.0]


def test_other_sources_still_wait(waits):
    slept, _ = waits
    base._gave_up["sec-edgar"] = 0.0
    client, _ = _client([503, 200])
    assert len(http_csv(client, URL + "/api/series/x", "dbnomics")) == 1
    assert slept == [30.0]


@pytest.mark.parametrize("answer, reason", [(httpx.ConnectError, "missing"), (500, "error")])
def test_not_locked_is_not_retried(waits, answer, reason):
    slept, _ = waits
    client, _ = _client([answer])
    with pytest.raises(SourceUnavailable) as e:
        http_csv(client, URL + "/x", "sec-edgar")
    assert e.value.reason == reason and slept == []


def test_attach_retries_a_held_lock(waits, tmp_path):
    slept, _ = waits
    path = tmp_path / "store.duckdb"
    duckdb.connect(str(path)).close()
    con = duckdb.connect()
    calls = []

    class Flaky:
        def execute(self, sql):
            calls.append(sql)
            if len(calls) == 1:
                raise duckdb.IOException(f'IO Error: Could not set lock on file "{path}": '
                                         "Conflicting lock is held in python3")
            return con.execute(sql)

    attach_ro(Flaky(), path, "s", "sec-edgar")
    assert slept == [30.0] and len(calls) == 2
    assert con.execute("select database_name from duckdb_databases() where database_name = 's'"
                       ).fetchall() == [("s",)]


def test_retry_locked_returns_first_success(waits):
    slept, _ = waits
    assert retry_locked("x", lambda i: i) == 0 and slept == []
