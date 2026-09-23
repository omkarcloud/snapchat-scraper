"""Offline tests for the Snapchat refs, protobuf codec and parsers — no
network.

Every fixture in snapchat/fixtures/ is a real upstream payload captured on
2026-09-22/23 through snapchat/fetch.py: page props (`__NEXT_DATA__` /
_next/data JSON) with lists trimmed to a few items and the UI string
tables dropped, GraphQL `data` objects verbatim, one fetchSpotlight
answer, and one raw protobuf getreplies response. The assertions pin the
field mapping decoded from live data, so a silent upstream rename shows
up here rather than as nulls in a customer's response.

    python -m pytest snapchat/test_parsers.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest  # noqa: E402

from snapchat import parsers as P, proto, refs, schemas  # noqa: E402
from schema_fields import load_query  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SPOT = "W7_EDlXWTBiXAEEniNoMPwAAYbnJwb2puY29iAaDHCDLvAaDHCC1ZAAAAAQ"


def load(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return json.load(handle)


# ---- refs --------------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["wwe", "@WWE", " wwe ", "https://www.snapchat.com/@wwe", "snapchat.com/add/wwe?share_id=x",
                                   f"https://www.snapchat.com/@wwe/spotlight/{SPOT}"])
def test_user_forms(value):
    assert refs.resolve_user(value) == "wwe"


@pytest.mark.parametrize("value", ["", "not a user!", "https://instagram.com/wwe", "https://t.snapchat.com/abc",
                                   "https://www.snapchat.com/spotlight"])
def test_user_rejects(value):
    with pytest.raises(ValueError):
        refs.resolve_user(value)


def test_spotlight_forms():
    assert refs.resolve_spotlight(SPOT) == {"id": SPOT, "username": None}
    assert refs.resolve_spotlight(f"https://www.snapchat.com/spotlight/{SPOT}/embed") == {"id": SPOT, "username": None}
    assert refs.resolve_spotlight(f"https://www.snapchat.com/@WWE/spotlight/{SPOT}") == {"id": SPOT, "username": "wwe"}
    assert refs.resolve_spotlight(f"https://www.snapchat.com/p/602c2453-eef7-4a38-a4f0-4d61f601c512/spotlight/{SPOT}")["id"] == SPOT
    with pytest.raises(ValueError):
        refs.resolve_spotlight("12345")


def test_lens_forms():
    uuid = "565e7595ec4e4a0da689762b127308ef"
    assert refs.resolve_lens(uuid.upper()) == uuid
    assert refs.resolve_lens("3411441095283405") == "3411441095283405"
    assert refs.resolve_lens(f"https://www.snapchat.com/unlock/?type=SNAPCODE&uuid={uuid}&metadata=01") == uuid
    assert refs.resolve_lens(f"https://lens.snapchat.com/{uuid}") == uuid
    assert refs.resolve_lens("https://www.snapchat.com/lens/60922281601") == "60922281601"
    with pytest.raises(ValueError):
        refs.resolve_lens("https://www.snapchat.com/@wwe")


def test_tag_topic_publisher_episode_place_location_comment():
    assert refs.resolve_tag("#WWE Raw") == "wweraw"
    assert refs.resolve_tag("https://www.snapchat.com/tag/wweraw") == "wweraw"
    assert refs.resolve_topic("Taylor Red Lifestyle") == "taylor-red-lifestyle"
    assert refs.resolve_topic("https://www.snapchat.com/topic/taylor-red-lifestyle") == "taylor-red-lifestyle"
    bp = "c8170832-9bd5-4087-a6d7-a6560c696bfc"
    assert refs.resolve_publisher(f"https://story.snapchat.com/p/{bp.upper()}/3137398530361344") == bp
    assert refs.resolve_episode(f"https://www.snapchat.com/p/{bp}/3137398530361344") == {"id": "3137398530361344", "publisher_id": bp}
    assert refs.resolve_episode("3137398530361344") == {"id": "3137398530361344", "publisher_id": None}
    pid = "5f880fc0-9992-11e8-9a55-f32d7289aee6"
    assert refs.resolve_place(f"https://www.snapchat.com/place/crystal-lanes-bowling-alley/{pid}") == pid
    assert refs.resolve_location("Georgia/Atlanta/Midtown/Restaurants") == {
        "state": "georgia", "city": "atlanta", "neighborhood": "midtown", "category": "restaurants"}
    assert refs.resolve_location("https://www.snapchat.com/local/united-states/georgia/atlanta") == {
        "state": "georgia", "city": "atlanta", "neighborhood": None, "category": None}
    with pytest.raises(ValueError):
        refs.resolve_location("atlanta")
    assert refs.resolve_comment("13165312488468533182-11545844533123289111") == "13165312488468533182-11545844533123289111"
    with pytest.raises(ValueError):
        refs.resolve_comment("abc")


def test_feed_cursor_round_trip():
    ids = ["5458327481900007940", "-5521928733205921276"] + [str(10 ** 18 + i) for i in range(500)]
    cursor = refs.encode_seen(ids)
    assert len(cursor) < 2000
    assert refs.decode_seen(cursor) == ids[-refs.SEEN_LIMIT:]
    assert refs.decode_seen(None) == []
    with pytest.raises(ValueError):
        refs.decode_seen("garbage")


# ---- protobuf ------------------------------------------------------------------------

def test_proto_round_trip_and_replies_decode():
    body = proto.encode({1: {1: "abc", 2: 123, 3: 20, 4: {1: proto.uuid_message("1-2"), 6: "US"}}, 2: "snap", 5: 3})
    fields = proto.decode(body)
    meta = proto.message(fields, 1)
    assert proto.text(meta, 1) == "abc" and proto.first(meta, 2) == 123
    assert proto.uuid_pair(proto.message(proto.message(meta, 4), 1)) == "1-2"
    assert proto.text(fields, 2) == "snap"

    with open(os.path.join(FIXTURES, "replies.bin"), "rb") as handle:
        raw = handle.read()
    fields = proto.decode(raw)
    replies = [P.comment_from_proto(r) for r in proto.messages(fields, 2)]
    assert len(replies) >= 2
    first = replies[0]
    assert first["id"] == "6202152588812304481-10276667619661795366"
    assert first["snap_id"] == SPOT
    assert first["text"].startswith("As a millionaire")
    assert first["author"]["display_name"] == "Shuan Bankz"
    assert first["author"]["business_profile_id"] == "7180049752140498761-12162601927817574992"
    assert first["reply_count"] == 2 and first["is_approved"] is True
    assert first["posted_at"] == "2026-09-22T05:37:40Z"
    assert proto.first(fields, 4) is None   # exhausted: no cursor


# ---- profiles ------------------------------------------------------------------------

def test_public_profile():
    prof = P.profile(load("profile_wwe.json"), "wwe")
    assert prof["type"] == "public_profile"
    assert prof["display_name"] == "WWE" and prof["username"] == "wwe"
    assert prof["subscriber_count"] == 2152800 and prof["is_verified"] is True
    assert prof["website"] == "https://www.wwe.com"
    assert prof["business_profile_id"] == "602c2453-eef7-4a38-a4f0-4d61f601c512"
    assert prof["related_accounts"][0]["display_name"] == "WWE Top 10"
    assert prof["created_at"] and prof["counts"]["lenses"] == 2
    assert prof["snapcode_links"]["png"].endswith("type=PNG&bitmoji=enable")
    nba = P.profile(load("profile_nba.json"), "nba")
    assert nba["category"] == "Business Group" and nba["subcategory"] == "Sports League"
    assert nba["has_story"] is True


def test_plain_user_and_missing():
    prof = P.profile(load("profile_espn.json"), "espn")
    assert prof["type"] == "user" and prof["display_name"] == "espn"
    assert prof["bitmoji"]["avatar_image"].endswith(".webp?ua=2")
    assert prof["subscriber_count"] is None and prof["is_verified"] is False
    assert P.profile(load("profile_missing.json"), "x") is None


def test_story_highlights_and_user_spotlights():
    page = load("profile_nba.json")
    story = P.story(page["story"])
    assert story["type"] == "public_story" and story["snap_count"] == 2
    assert story["snaps"][0]["media_type"] == "video" and story["snaps"][0]["media"].startswith("https://")
    assert story["snaps"][0]["posted_at"]
    highlight = P.story(page["curatedHighlights"][0])
    assert highlight["type"] == "curated_highlight" and highlight["id"] and highlight["title"]
    page = load("profile_wwe.json")
    item = P.spotlight(page["spotlightHighlights"][0], page["spotlightStoryMetadata"][0])
    assert item["id"] == SPOT and item["link"] == f"https://www.snapchat.com/@wwe/spotlight/{SPOT}"
    assert item["caption"] == "PENTA ➡️ #MITB! #WWERaw" and item["hashtags"] == ["MITB", "WWERaw"]
    assert item["stats"]["boost_count"] == 259 and item["stats"]["comment_count"] == 6
    assert item["sound"]["is_original_sound"] is True and item["sound"]["id"] == "148566888704"
    assert item["ai"]["title"].startswith("Penta El Zero Miedo") and item["ai"]["language"] == "en"
    assert item["duration_ms"] == 27930 and item["transcript_link"].endswith(".vtt?bo=EgkyAX1IAlAuYAE%3D&uc=46")
    groups = P.comments_from_json(page["encodedSpotlightComments"])
    assert groups[0][0]["snap_id"] == SPOT and groups[0][0]["author"]["display_name"] == "Shuan Bankz"


def test_user_lens():
    lens = P.lens(load("profile_wwe.json")["lenses"][0])
    assert lens["name"] == "WWE Roman Reigns" and lens["uuid"] == "ecc70f9e3c3945f183d786bf147641a4"
    assert lens["link"] == "https://www.snapchat.com/lens/ecc70f9e3c3945f183d786bf147641a4"
    assert lens["preview_video"].endswith(".mp4") and lens["updated_at"] == "2024-02-15T14:44:26Z"


# ---- spotlight -----------------------------------------------------------------------

def test_spotlight_page_details():
    page = load("spotlight_page.json")
    entry = page["spotlightFeed"]["spotlightStories"][0]
    transcript = P.transcript_entry(page["transcriptMap"][SPOT])
    item = P.spotlight(entry["story"], entry["metadata"], comments=P.comments_from_json(page["encodedComments"]),
                       transcript=transcript)
    assert item["id"] == SPOT and item["creator"]["username"] == "wwe"
    assert item["stats"]["view_count"] == 9537 and item["stats"]["share_count"] == 67
    assert item["context_cards"][1]["type"] == "creator" and item["context_cards"][1]["has_badge"] is True
    assert item["transcript"]["cues"][0]["start"] == "00:00:00.000" and "Penta" in item["transcript"]["text"]
    assert len(item["comments"]) == 2 and item["comments"][0]["reply_count"] == 2


def test_spotlight_feed_graphql():
    entry = load("gql_spotlight_feed.json")["spotlightFeed"]["stories"][0]
    item = P.spotlight(entry["story"], entry["metadata"])
    assert item["tap_id"] and item["id"] and item["video"].endswith("&uc=46")
    assert item["caption"] is None                      # "Another Spotlight Snap brought to you by Snapchat" is nulled
    assert item["stats"]["view_count"] > 0 and item["stats"]["comment_count"] == 65
    assert item["creator"]["username"] == "chii_niith"


def test_story_card_and_hydration():
    card = P.story_card(load("tag_wweraw.json")["spotlights"][0])
    assert card["creator"]["username"] == "oracle_115" and card["link"].endswith(card["id"])
    assert card["hashtags"] == ["wwe", "wweraw"]      # (fixture trimmed to two)
    assert card["video"].startswith("https://") and card["media_type"] == "video" and card["duration_seconds"] == 58.63
    assert card["stats"]["view_count"] == 76796 and card["stats"]["subscription_count"] == 579
    assert card["expires_at"] is None and card["posted_at"] == "2025-11-18T04:29:40Z"
    assert card["ai"]["model"] == "qwen3" and card["ai"]["languages"][0]["code"] == "en"
    hydrated = P.hydrated_spotlight(load("fetch_spotlight.json")[0])
    assert hydrated["id"] == SPOT and hydrated["creator"]["is_official"] is True
    assert hydrated["creator"]["business_profile_id"] == "602c2453-eef7-4a38-a4f0-4d61f601c512"
    assert hydrated["video_without_watermark"].startswith("https://") and hydrated["stats"]["boost_count"] == 806


# ---- search / discovery -----------------------------------------------------------------

def test_search_sections():
    results = P.search_results(load("explore_therock.json"))
    assert set(results) == {"users", "lenses", "places", "topics", "spotlights"}
    user = results["users"][0]
    assert user["username"] == "therock" and user["display_name"] == "Dwayne Johnson" and user["subscriber_count"] == 2908971
    assert user["is_official"] is True and user["business_profile_id"] == "6beee624-5461-4f97-89a8-abcb4eb909eb"
    lens = results["lenses"][0]
    assert lens["id"] == "60922281601" and lens["uuid"] == "83ee4a693b1247669e30171db7604df8" and len(lens["preview_frames"]) == 6
    place = results["places"][0]
    assert place["category"] == "Jewelry Store" and place["location"]["latitude"] == pytest.approx(-34.875, abs=0.01)
    assert results["topics"][0]["snap_count"] == 277
    spot = results["spotlights"][0]
    assert spot["creator"]["username"] == "shakastrong" and spot["hashtags"] == ["therock"]
    music = P.search_results(load("explore_music.json"))
    assert music["shows"][0]["name"] == "MuchMusic" and music["shows"][0]["link"].startswith("https://www.snapchat.com/p/")
    assert music["episodes"][0]["title"] == "The Music Trailed Off 😬" and music["episodes"][0]["publisher"]["name"] == "askthereddit"


def test_discover_feed():
    stories = [P.discover_story(s) for s in load("gql_discover.json")["discoverFeed"]["stories"]]
    public = next(s for s in stories if s["type"] == "public_story")
    show = next(s for s in stories if s["type"] == "show")
    assert public["creator"]["is_verified"] is True and public["creator"]["badge"] == "tick"
    assert public["snaps"][0]["media"].startswith("https://") and public["published_at"]
    assert show["video_track"].endswith("m3u8") or ".m3u8?" in show["video_track"]
    assert show["link"].startswith("https://www.snapchat.com/p/") and show["thumbnail"].startswith("https://cf-st")


def test_topic_and_funny():
    with open(os.path.join(FIXTURES, "topic_page.html"), encoding="utf-8") as handle:
        html = handle.read()
    topic = P.topic(load("topic_ld.json"), html, "taylor-red-lifestyle")
    assert topic["name"] == "Taylor Red Lifestyle Videos" and topic["spotlight_count"] == 3
    video = topic["spotlights"][0]
    assert video["creator"]["username"] == "taylorred_music" and video["id"] and video["video"]
    assert video["duration_seconds"] and (video["stats"] is None or all(k.endswith("_count") for k in video["stats"]))
    assert topic["related_topics"][0]["slug"] == "taylor-red-fashion"
    funny = P.funny_page(load("ent_funny_kw.json"))
    assert funny["topic"]["name"] == "Comedy Skit" and funny["spotlight_count"] == 2
    assert P.funny_keyword(load("ent_funny.json")["items"][0])["slug"] == "animal-comedy-clips"


# ---- lenses ---------------------------------------------------------------------------

def test_lenses():
    lens = P.lens(load("lens_index.json")["topLenses"][0])
    assert lens["id"] == "3411441095283405" and lens["uuid"] == "565e7595ec4e4a0da689762b127308ef"
    assert lens["is_official"] is True and lens["tags"][0] == "ai filter" and lens["snapcode_image"]
    detail = load("lens_detail.json")
    using = P.lens_spotlight(detail["spotlightsUsingThisLens"][0], detail["spotlightsUsingThisLensMetadata"][0])
    assert using["creator"]["username"] == "os.sksk" and using["duration_seconds"] == 47.21
    creator = P.lens_creator(load("lens_creators.json")["creatorDisplayInfos"][0])
    assert creator["username"] == "vidtech_ai" and creator["is_official"] is True and creator["lens_previews"]


# ---- publishers --------------------------------------------------------------------------

def test_publisher_and_episodes():
    pub = P.publisher(load("publisher.json"), "c8170832-9bd5-4087-a6d7-a6560c696bfc")
    assert pub["type"] == "publisher" and pub["display_name"] == "askthereddit"
    assert pub["subscriber_count"] == 359300 and pub["publisher_type"] == "SHOW" and pub["primary_color"] == "#9B55A0"
    assert pub["seasons"][0] == {"id": "55e465e7-cbc9-463e-8202-7a9d9a7e7ac7", "number": 1, "episode_count": 71}
    assert pub["latest_episodes"][0]["link"].startswith("https://www.snapchat.com/p/c8170832")
    episode = P.episode(load("gql_premium_story.json")["premiumStory"])
    assert episode["title"] == "The Music Trailed Off 😬" and episode["snap_count"] == 2
    assert episode["snaps"][0]["media"].endswith("&uc=5") or ".m3u8" in episode["snaps"][0]["media"]
    assert episode["publisher_id"] == "c8170832-9bd5-4087-a6d7-a6560c696bfc"
    page = load("gql_published_stories.json")["publisher"]["publishedPremiumStoriesConnection"]
    summary = P.episode_summary(page["premiumStories"][0], "c8170832-9bd5-4087-a6d7-a6560c696bfc")
    assert summary["season_number"] == 1 and summary["title"] and summary["published_at"]


# ---- places ---------------------------------------------------------------------------

def test_place():
    place = P.place(load("place.json"))
    assert place["name"] == "Crystal Lanes Bowling Alley" and place["category"] == "Bowling Alley"
    assert place["address"]["postal_code"] == "14830-3657" and place["contact"]["phone"] == "+16079625391"
    assert place["opening_hours"]["timezone"] == "America/New_York" and place["opening_hours"]["days"][0]["day"] == "sunday"
    assert place["ratings"][0]["provider"] == "Tripadvisor" and place["ratings"][0]["count"] == 3
    assert place["favorite_count"] == 41 and place["reviews"][0]["link"].startswith("https://www.tripadvisor.com/")
    assert {"provider": "tripadvisor", "id": "9752564"} in place["external_ids"]
    assert place["nearby"][0]["places"][0]["name"] == "Harris Hill Overlook"
    assert place["stories"][0]["type"] == "spotlight" and place["stories"][0]["video"]


def test_local_pages():
    hub = P.local_page(load("local_hub.json"))
    assert hub["type"] == "hub" and hub["city"]["name"] == "Atlanta" and hub["sections"][0]["category"]["slug"] == "bars"
    assert hub["sections"][0]["places"][0]["name"] == "Park Bar" and hub["sections"][0]["places"][0]["is_popular"] is True
    leaf = P.local_page(load("local_leaf.json"))
    assert leaf["type"] == "places" and leaf["neighborhood"]["name"] == "Midtown" and leaf["total_count"] == 40
    place = leaf["places"][0]
    assert place["price"]["label"] == "$$" and place["rating"]["value"] == pytest.approx(4.4, abs=0.01) and isinstance(place["attributes"], list)


# ---- schemas ---------------------------------------------------------------------------

def test_schemas():
    data, error = load_query(schemas.UserSchema, {"user": "https://www.snapchat.com/add/WWE"})
    assert error is None and data == {"user": "wwe"}
    data, _ = load_query(schemas.SpotlightBatchSchema, {"spotlights": f"{SPOT}, https://www.snapchat.com/@wwe/spotlight/{SPOT}"})
    assert data["spotlights"] == [SPOT]
    _, error = load_query(schemas.SpotlightBatchSchema, {"spotlights": ",".join(f"{SPOT[:-2]}{i:02d}" for i in range(32))})
    assert error and "31" in error["error"]
    data, _ = load_query(schemas.SearchSchema, {"query": "music", "type": "Places", "country": "us"})
    assert data["type"] == "places" and data["country"] == "US" and data["locale"] == "en-US"
    _, error = load_query(schemas.LensBrowseSchema, {"category": "nope"})
    assert error
    data, _ = load_query(schemas.LocalSchema, {"location": "georgia/atlanta", "category": "Bars"})
    assert data["location"]["city"] == "atlanta" and data["category"] == "Bars"
