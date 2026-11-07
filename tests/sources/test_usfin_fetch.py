"""P63 (PLAN S44): a server that is up but slow is not a server that is down.

`http_csv` maps a refused connection to `missing` (so `Usfin.fetch` falls back to the read-only
ATTACH) but a read timeout to `locked`: `usfin serve` holds the store's lock while it answers, so
an ATTACH straight after a timeout can only meet that lock. httpx MockTransport only, no socket."""

from __future__ import annotations

import httpx
import pytest

from assist.sources import usfin as usfin_mod
from assist.sources.base import SourceUnavailable, http_csv
from assist.sources.usfin import Usfin

URL = "http://127.0.0.1:8660"


def _raising(exc_type):
    def handler(request: httpx.Request) -> httpx.Response:
        raise exc_type("boom", request=request)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_read_timeout_is_locked_not_missing():
    with pytest.raises(SourceUnavailable) as e:
        http_csv(_raising(httpx.ReadTimeout), URL + "/prices/universe", "sec-edgar", timeout=7.0)
    assert e.value.reason == "locked"
    assert "timed out after 7 s" in e.value.detail


def test_connect_error_stays_missing():
    with pytest.raises(SourceUnavailable) as e:
        http_csv(_raising(httpx.ConnectError), URL + "/x", "sec-edgar")
    assert e.value.reason == "missing"


def test_connect_timeout_is_missing():
    """No connection within the timeout: nothing is answering, the file may be free."""
    with pytest.raises(SourceUnavailable) as e:
        http_csv(_raising(httpx.ConnectTimeout), URL + "/x", "sec-edgar")
    assert e.value.reason == "missing"


def _fetch(client):
    u = Usfin(url=URL, path="/nonexistent/usfin.duckdb", client=client)
    attached = []

    def db_fn():
        attached.append(True)
        return ["from the file"]

    return u, attached, lambda: u.fetch(lambda: u.get_csv("/prices/universe"), db_fn)


def test_fetch_after_a_read_timeout_does_not_attach():
    u, attached, run = _fetch(_raising(httpx.ReadTimeout))
    with pytest.raises(SourceUnavailable) as e:
        run()
    assert e.value.reason == "locked" and attached == []
    assert e.value.stale_input == "sec-edgar (locked)"


def test_fetch_with_the_server_down_still_falls_back_to_the_file():
    u, attached, run = _fetch(_raising(httpx.ConnectError))
    assert run() == ["from the file"]
    assert attached == [True] and u.via == "duckdb"


def test_long_timeout_outlasts_the_universe_route():
    assert usfin_mod.US_HTTP_TIMEOUT >= 60.0  # /prices/universe answers in ~22 s live (2026-11-07)
