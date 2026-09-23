"""Live endpoint smoke tests: one call per /snapchat/* route against a
running service, with example values proven to return data (2026-09-23).
The listing tooling reads each route's FIRST call from this file's AST as
its working example, so the values stay literals.

Skipped unless SNAPCHAT_BASE points at a running service:

    ONLY_SCRAPER=snapchat python run.py
    SNAPCHAT_BASE=http://127.0.0.1:6002 python -m pytest snapchat/test_endpoints.py -q
"""
import os

import pytest

BASE = os.environ.get("SNAPCHAT_BASE", "").rstrip("/")

pytestmark = pytest.mark.skipif(not BASE, reason="set SNAPCHAT_BASE to run live endpoint tests")


def call(path, status=200, **params):
    from curl_cffi import requests
    resp = requests.get(BASE + path, params=params, timeout=180)
    assert resp.status_code == status, f"{path} {params} -> {resp.status_code} {resp.text[:300]}"
    body = resp.json()
    assert body, f"{path} returned an empty body"
    return body


def test_users():
    assert call("/snapchat/users/search", query="therock")["users"][0]["username"] == "therock"
    assert call("/snapchat/users/profile", user="wwe")["subscriber_count"] > 1_000_000
    assert "has_story" in call("/snapchat/users/story", user="nba")
    assert call("/snapchat/users/highlights", user="wwe")["highlights"][0]["snaps"]
    assert call("/snapchat/users/spotlights", user="wwe")["spotlights"][0]["stats"]
    assert call("/snapchat/users/lenses", user="jsprinz")["lenses"]
    call("/snapchat/users/profile", user="zzqqxx_nouser_9981", status=404)


def test_spotlight():
    feed = call("/snapchat/spotlight/feed", country="US")
    assert feed["spotlight_count"] > 10 and feed["next_cursor"]
    page2 = call("/snapchat/spotlight/feed", country="US", cursor=feed["next_cursor"])
    assert not {s["id"] for s in feed["spotlights"]} & {s["id"] for s in page2["spotlights"]}
    spot = feed["spotlights"][0]["id"]
    details = call("/snapchat/spotlight/details", spotlight="https://www.snapchat.com/@wwe/spotlight/W7_EDlXWTBiXAEEniNoMPwAAYbnJwb2puY29iAaDHCDLvAaDHCC1ZAAAAAQ")
    assert details["video"] and details["creator"]["username"] == "wwe"
    assert call("/snapchat/spotlight/related", spotlight="W7_EDlXWTBiXAEEniNoMPwAAYbnJwb2puY29iAaDHCDLvAaDHCC1ZAAAAAQ")["spotlights"]
    comments = call("/snapchat/spotlight/comments", spotlight="W7_EDlXWTBiXAEEniNoMPwAAYbnJwb2puY29iAaDHCDLvAaDHCC1ZAAAAAQ")
    assert comments["comments"] and comments["comments"][0]["id"]
    assert call("/snapchat/spotlight/stats", spotlights="W7_EDlXWTBiXAEEniNoMPwAAYbnJwb2puY29iAaDHCDLvAaDHCC1ZAAAAAQ")["spotlights"][0]["stats"]["view_count"]
    assert call("/snapchat/spotlight/stats", spotlights=spot)["spotlight_count"] == 1


def test_discovery():
    assert call("/snapchat/search", query="music")["counts"]["spotlights"] > 0
    assert call("/snapchat/hashtags/spotlights", tag="wweraw")["spotlight_count"] > 10
    assert call("/snapchat/topics/spotlights", topic="taylor-red-lifestyle")["spotlights"]
    assert call("/snapchat/topics/funny")["keyword_count"] > 100
    assert call("/snapchat/topics/funny", keyword="comedy-skit")["spotlights"]
    feed = call("/snapchat/discover/feed", country="US", limit=10)
    assert feed["stories"] and feed["next_cursor"]


def test_lenses():
    browse = call("/snapchat/lenses/browse", category="face")
    assert browse["lens_count"] == 25 and browse["next_cursor"]
    assert call("/snapchat/lenses/details", lens="565e7595ec4e4a0da689762b127308ef")["name"]
    assert call("/snapchat/lenses/creators")["creators"][0]["username"]
    assert call("/snapchat/lenses/search", query="dog")["lenses"]


def test_publishers():
    pub = call("/snapchat/publishers/details", publisher="c8170832-9bd5-4087-a6d7-a6560c696bfc")
    assert pub["seasons"] and pub["latest_episodes"]
    episodes = call("/snapchat/publishers/episodes", publisher="c8170832-9bd5-4087-a6d7-a6560c696bfc", season="1", limit=10)
    assert episodes["episodes"] and episodes["season"]["number"] == 1
    assert call("/snapchat/publishers/episode", episode="3137398530361344")["snaps"]


def test_places():
    assert call("/snapchat/places/details", place="5f880fc0-9992-11e8-9a55-f32d7289aee6")["name"]
    assert call("/snapchat/places/search", query="pizza")["places"]
    assert call("/snapchat/places/local", location="georgia/atlanta", category="bars")["places"]
    assert call("/snapchat/places/local", location="georgia/atlanta")["sections"]
