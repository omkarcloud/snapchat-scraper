"""snapchat/fetch.py's per-app buildId on identity_pool: no network, the
home-page read is faked. The pool's own rules live in tests/test_identity_pool.py.

    python -m pytest snapchat/test_fetch.py -q
"""
import json
import threading
import time

import pytest

from snapchat import fetch


class FakeResponse:
    def __init__(self, status=200, text=""):
        self.status_code, self.text = status, text


@pytest.fixture
def builds(monkeypatch):
    """The module's pool with a counting fake home-page read (b1, b2, ...)."""
    pool = fetch._build_ids
    pool.clear()
    pool._last_mint.clear()
    pool._mint_times.clear()
    reads = []

    def read_home(app, hint):
        time.sleep(0.05)                     # let the wave pile up behind one mint
        reads.append(app)
        return f"b{len(reads)}"

    monkeypatch.setattr(pool, "_mint_fn", read_home)
    monkeypatch.setattr(fetch.config, "RETRY_BACKOFF", 0)
    pool.reads = reads
    yield pool
    pool.clear()
    pool._last_mint.clear()
    pool._mint_times.clear()


def test_a_404_wave_costs_one_home_read_and_none_inside_the_interval(builds, monkeypatch):
    live = {"b2"}

    def fake_request(method, url, *, label, **kwargs):
        build = url.split("/_next/data/")[1].split("/")[0]
        if build not in live:
            return FakeResponse(404, "not found")
        return FakeResponse(200, json.dumps({"pageProps": {"build": build}}))

    monkeypatch.setattr(fetch, "_request", fake_request)

    # the first request of the process learns the buildId (one read)...
    assert fetch.build_id("spotlight") == "b1" and builds.reads == ["spotlight"]
    # ...and a deploy happened since: b1 is gone. The interval since that
    # read has passed, so the 404 may refresh.
    builds._last_mint["spotlight"] -= fetch.BUILD_ID_REFRESH_INTERVAL + 1

    results, errors = [], []

    def worker():
        try:
            results.append(fetch.next_data("spotlight", "/spotlight/x", label="spotlight x"))
        except Exception as e:                # pragma: no cover - the assert below reports it
            errors.append(e)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(10)
    assert not errors and [r["build"] for r in results] == ["b2"] * 8
    assert builds.reads == ["spotlight", "spotlight"], "a 404 wave across threads: ONE home-page read"

    # a 404 on the buildId learned seconds ago is a real not-found: no read
    live.clear()
    with pytest.raises(fetch.SnapchatNotFound):
        fetch.next_data("spotlight", "/spotlight/gone", label="spotlight gone")
    assert builds.reads == ["spotlight", "spotlight"]
    assert fetch.build_id("spotlight") == "b2"
