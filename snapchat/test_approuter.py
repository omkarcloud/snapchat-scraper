"""Offline tests for the App Router pages (profile, Spotlight, search): the
flight-stream decoder (flight.py) and the mapping back onto the old page
shapes (approuter.py). No network.

The `app_*.html` fixtures are real documents fetched on 2026-11-18 through
snapchat/fetch.py, cut down to what the code reads: the flight rows that hold
the page's data, each byte for byte as the site sent it and wrapped in the same
`self.__next_f.push([1,"…"])` script tags, plus the ld+json blocks the code
uses. (A whole profile document is 0.8 MB, mostly styles and UI strings.)

Two things are pinned here. The values decoded from live data, so an upstream
rename shows up as a failing test instead of nulls in a customer's response.
And the response SHAPE: every field the old pages' parsers returned is still
returned for the new pages, checked against the old-format fixtures.

    python -m pytest snapchat/test_approuter.py -q
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from snapchat import approuter, flight, parsers as P  # noqa: E402
from snapchat.fetch import ld_objects  # noqa: E402

FIXTURES = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
SPOT = "W7_EDlXWTBiXAEEniNoMPwAAYbnJwb2puY29iAaDHCDLvAaDHCC1ZAAAAAQ"


def read(name):
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as handle:
        return handle.read()


def old(name):
    return json.loads(read(name))


def fields(value, prefix=""):
    """Every field path of a response, lists merged over their items. An
    empty list or a null object has no paths below it."""
    out = set()
    if isinstance(value, dict):
        for key, item in value.items():
            out.add(prefix + key)
            out |= fields(item, prefix + key + ".")
    elif isinstance(value, list):
        for item in value:
            out |= fields(item, prefix)
    return out


def top(items):
    """The top-level field names of a list of response objects."""
    return set().union(*(item.keys() for item in items))


def document(*rows, text_rows=()):
    """A document with the given flight rows, cut into two script tags in an
    awkward place, as the site does."""
    stream = "".join(f"{row_id}:{json.dumps(value, ensure_ascii=False)}\n" for row_id, value in rows)
    for row_id, text in text_rows:
        stream += f"{row_id}:T{len(text.encode('utf-8')):x},{text}"
    cut = len(stream) // 2
    return "".join(f"<script>self.__next_f.push([1,{json.dumps(part, ensure_ascii=False)}])</script>"
                   for part in (stream[:cut], stream[cut:]))


# ---- flight.py ----------------------------------------------------------------------------

def test_stream_joins_the_chunks_and_undoes_their_escaping():
    html = document(("1", {"quote": 'say "hi"', "emoji": "👑", "newline": "a\nb"}))
    assert flight.rows(flight.stream(html)) == {"1": {"quote": 'say "hi"', "emoji": "👑", "newline": "a\nb"}}
    assert flight.stream("<html>no stream here</html>") == ""
    assert not flight.Page("<html>no stream here</html>")


def test_rows_text_rows_are_measured_in_bytes_and_have_no_newline():
    # A text row holds exactly <hex length> BYTES; the next row starts right after it.
    stream = '1:{"a":1}\n2:T8,é:1:[\n]3:["after"]\n'
    assert flight.rows(stream) == {"1": {"a": 1}, "2": "é:1:[\n]", "3": ["after"]}


def test_rows_skips_what_is_not_data():
    stream = ('1:I["chunk.js",["a"],"default"]\n'       # a module import
              '2:HL["/font.woff2","font"]\n'            # a preload hint
              '3:o0,'                                   # an empty binary row, no newline
              '4:{"kept":true}\n'
              '5:{"broken json\n')
    assert flight.rows(stream) == {"4": {"kept": True}}


def test_resolve_follows_rows_paths_and_undefined():
    page = flight.Page(document(
        ("a", ["$", "$L9", None, {"content": {"items": [{"id": "first"}, {"id": "second"}]}}]),
        ("b", {"tile": "$a:props:content:items:1", "missing": "$undefined", "row": "$La", "plain": "$5 off", "gone": "$ff"}),
    ))
    row = page.rows["b"]
    assert page.resolve(row["tile"]) == {"id": "second"}          # `props` = the element's fourth item
    assert page.resolve(row["missing"]) is None
    assert page.resolve(row["row"])[0] == "$"                      # a whole row
    assert page.resolve(row["plain"]) == "$5 off"                  # text that merely starts with $
    assert page.resolve(row["gone"]) == "$ff"                      # a row the document does not have
    assert page.resolve("$a:props:content:items:9") is None        # a path that leads nowhere
    assert page.element_props("$La") == {"content": {"items": [{"id": "first"}, {"id": "second"}]}}
    assert page.element_props(row["tile"]) is None


def test_expand_follows_references_at_any_depth():
    page = flight.Page(document(
        ("a", {"video": {"id": "v1", "poster": "$undefined"}}),
        ("b", {"items": ["$a:video", {"tile": {"video": "$a:video"}}, "text", 7]}),
    ))
    assert page.expand(page.rows["b"]) == {"items": [{"id": "v1", "poster": None}, {"tile": {"video": {"id": "v1", "poster": None}}}, "text", 7]}
    assert page.items(page.rows["b"]["items"]) == [{"id": "v1", "poster": None}, {"tile": {"video": {"id": "v1", "poster": None}}}]
    assert page.items("$undefined") == [] and page.items(None) == []


def test_find_props_finds_an_object_by_its_keys_wherever_it_sits():
    page = flight.Page(document(
        ("1", ["$", "div", None, {"children": [["$", "$L2", None, {"username": "nfl", "variant": "public", "extra": 1}]]}]),
        ("2", {"username": "someone else"}),
    ))
    assert page.find_props("variant", "username")["username"] == "nfl"
    assert page.find_props("username")["username"] == "nfl"           # the first one in stream order
    assert page.find_props("nothing", "like", "this") is None


def test_clean_turns_undefined_into_none():
    assert flight.clean({"a": "$undefined", "b": [{"c": "$undefined"}, "x"]}) == {"a": None, "b": [{"c": None}, "x"]}


# ---- times in snap ids -------------------------------------------------------------------

def test_snap_time_matches_the_time_the_old_pages_printed_beside_each_id():
    checked = 0
    for name in ("profile_nba.json", "profile_wwe.json"):
        page = old(name)
        snaps = list((page.get("story") or {}).get("snapList") or [])
        for story in page.get("spotlightHighlights") or []:
            snaps += story.get("snapList") or []
        for snap in snaps:
            snap_id, seconds = P.val(snap.get("snapId")), P.to_int(snap.get("timestampInSec"))
            if snap_id and seconds and approuter.snap_time_ms(snap_id):
                assert approuter.snap_time_ms(snap_id) // 1000 == seconds
                checked += 1
    assert checked >= 4


def test_snap_time_is_none_for_ids_without_one():
    assert approuter.snap_time_ms("f4cdb71a-5fc6-4854-81b5-b247f39826fa") is None     # a highlight snap: a plain UUID
    assert approuter.snap_time_ms("") is None and approuter.snap_time_ms(None) is None
    assert approuter.snap_time_ms("A" * 59) is None                                   # right length, no sane time
    assert approuter.snap_time_ms("not base64 at all, but long enough to be tried !!!!!!!!!!!!") is None


# ---- profile -------------------------------------------------------------------------------

def nfl():
    html = read("app_profile_nfl.html")
    return approuter.profile_props(flight.Page(html), "nfl", snapcode_image="https://example.test/snapcode")


def test_profile_public():
    profile = P.profile(nfl(), username="nfl")
    assert profile["username"] == "nfl" and profile["display_name"] == "NFL Official" and profile["type"] == "public_profile"
    assert profile["is_verified"] is True and profile["badge"] == 1
    assert profile["subscriber_count"] == 2341400
    assert profile["subcategory"] == "Sports League"
    assert profile["user_id"] == "466f4d24-41e6-4b2e-ac68-2de78d454054"
    assert profile["business_profile_id"] == "21f4e252-2d8b-44f7-a7ac-21a767730b7f"
    assert profile["created_at"] == "2018-05-23T20:41:49Z"
    assert profile["snapcode_image"] == "https://example.test/snapcode"
    assert profile["has_story"] is True
    assert profile["counts"] == {"story_snaps": 65, "curated_highlights": 32, "spotlights": 32, "lenses": 16}
    related = profile["related_accounts"][0]
    assert related["username"] == "nba" and related["display_name"] == "NBA" and related["is_verified"] is True
    assert related["link"] == "https://www.snapchat.com/@nba"


def test_profile_keeps_every_field_of_the_old_response():
    before = P.profile(old("profile_wwe.json"), username="wwe")
    assert fields(P.profile(nfl(), username="nfl")) >= fields(before) - {"related_accounts.subscribe_link"} | {"related_accounts.subscribe_link"}
    assert set(P.profile(nfl(), username="nfl")) == set(before)


def test_profile_story_is_the_pinned_live_story():
    story = P.story(nfl()["story"])
    assert story["id"] == "nfl" and story["type"] == "public_story" and story["snap_count"] == 65
    first = story["snaps"][0]
    assert first["index"] == 0 and first["media_type"] == "video" and first["media"].startswith("https://cf-st.sc-cdn.net/")
    assert first["posted_at"] == "2026-11-16T20:14:27Z"            # read from the snap id
    assert [snap["index"] for snap in story["snaps"]] == list(range(65))
    assert all(snap["posted_at"] for snap in story["snaps"])
    assert set(story) == set(P.story(old("profile_nba.json")["story"]))
    assert set(first) == set(P.story(old("profile_nba.json")["story"])["snaps"][0])


def test_profile_highlights():
    highlights = [P.story(h) for h in nfl()["curatedHighlights"]]
    assert len(highlights) == 32
    first = highlights[0]
    assert first["id"] == "37011869-c294-49f8-b49b-655998cf8220" and first["type"] == "curated_highlight"
    assert first["snap_count"] == 1 and first["snaps"][0]["media_type"] == "video"
    assert first["snaps"][0]["posted_at"] is None                 # a highlight snap's id carries no time
    assert all(h["snap_count"] > 0 for h in highlights)            # a highlight listed without its snaps is skipped


def test_profile_spotlights():
    page = nfl()
    spotlights = [P.spotlight(story, meta) for story, meta in zip(page["spotlightHighlights"], page["spotlightStoryMetadata"])]
    assert len(spotlights) == 32 and all(s["id"] and s["video"] for s in spotlights)
    first = spotlights[0]
    assert first["id"] == "W7_EDlXWTBiXAEEniNoMPwAAYYnR5Zmh1bG51AaHr7zShAaHr7zQjAAAAAA"
    assert first["link"] == f"https://www.snapchat.com/@nfl/spotlight/{first['id']}"
    assert first["posted_at"] == "2026-11-17T23:54:44Z"
    assert first["creator"]["username"] == "nfl" and first["creator"]["display_name"] == "NFL Official"
    # "likes" on the page are the old boost count
    assert first["stats"] == {"view_count": 2528, "share_count": 1, "comment_count": 3, "boost_count": 81, "recommend_count": 5}
    assert first["ai"]["title"] == "Josh Metellus Inspires Rookie Jakobe Thomas on Vikings' Debut"
    before = old("profile_wwe.json")
    assert set(first) == set(P.spotlight(before["spotlightHighlights"][0], before["spotlightStoryMetadata"][0]))


def test_profile_lenses():
    lenses = [P.lens(l) for l in nfl()["lenses"]]
    assert len(lenses) == 16
    assert lenses[0]["id"] == "63555221023" and lenses[0]["name"] == "Super Bowl 2024"
    assert lenses[0]["uuid"] == "1eb6f9c47fc744b18ea2b11df8c0a720"     # from the unlock link
    assert lenses[0]["creator"]["display_name"] == "NFL Official"
    assert lenses[0]["preview_image"] and lenses[0]["icon"]


def test_profile_plain_account():
    html = read("app_profile_espn.html")
    person = next(o["mainEntity"] for o in ld_objects(html) if o.get("@type") == "ProfilePage")
    page = approuter.profile_props(flight.Page(html), "espn", display_name=person.get("name"))
    assert page["userProfile"]["$case"] == "userInfo"
    assert page["story"] is None and page["curatedHighlights"] == [] and page["spotlightHighlights"] == [] and page["lenses"] == []
    profile = P.profile(page, username="espn")
    assert profile["type"] == "user" and profile["username"] == "espn" and profile["display_name"] == "espn"
    assert profile["is_verified"] is False and profile["subscriber_count"] is None and profile["counts"] is None
    assert profile["bitmoji"]["avatar_image"].startswith("https://cf-st.sc-cdn.net/3d/render/")
    assert "snapcode?username=espn" in profile["snapcode_image"]
    assert set(profile) == set(P.profile(old("profile_espn.json"), username="espn"))


def test_profile_props_is_none_for_a_page_without_a_profile():
    assert approuter.profile_props(flight.Page(document(("1", {"something": "else"}))), "nobody") is None


# ---- one Spotlight -------------------------------------------------------------------------

def spotlight_page():
    html = read("app_spotlight_wwe.html")
    return approuter.spotlight_props(flight.Page(html), ld_objects(html))


def test_spotlight_details():
    found = spotlight_page()
    item = P.spotlight(*found["own"], comments=[P.comment(c) for c in found["comments"]])
    assert item["id"] == SPOT and item["link"] == f"https://www.snapchat.com/@wwe/spotlight/{SPOT}"
    assert item["caption"] == "PENTA ➡️ #MITB! #WWERaw" and item["hashtags"] == ["MITB", "WWERaw"]
    assert item["posted_at"] == "2026-09-22T02:53:17Z" and item["is_attributed"] is True
    assert item["creator"]["username"] == "wwe" and item["creator"]["display_name"] == "WWE"
    assert item["stats"] == {"view_count": 12190, "share_count": 74, "comment_count": 23, "boost_count": 994, "recommend_count": 129}
    # size and length are printed only in the page's structured data
    assert (item["width"], item["height"], item["duration_ms"]) == (540, 960, 28000)
    assert item["video"].startswith("https://cf-st.sc-cdn.net/") and item["transcript_link"].endswith("uc=46")
    assert item["sound"]["title"] == "Original Sound" and item["sound"]["artist"] == "wwe" and item["sound"]["is_original_sound"] is True
    assert item["context_cards"][0]["type"] == "sound"
    assert item["ai"]["description"].startswith("Witness the electrifying climax of a WWE wrestling match")
    assert "wrestling" in item["ai"]["keywords"] and not any(k.startswith("#") for k in item["ai"]["keywords"])
    assert found["transcript"].startswith("Looking to bring Penta right into that corner.")
    assert len(item["comments"]) == 14
    first = item["comments"][0]
    assert first["text"] == "I'm glad penta won .🙌" and first["author"]["display_name"] == "Lucia"
    assert first["posted_at"] == "2026-09-22T15:12:46Z" and first["reply_count"] == 1 and first["snap_id"] == SPOT


def test_spotlight_details_keeps_every_field_of_the_old_response():
    page = old("spotlight_page.json")
    own = page["spotlightFeed"]["spotlightStories"][0]
    before = P.spotlight(own["story"], own["metadata"], comments=P.comments_from_json(page.get("encodedComments")))
    found = spotlight_page()
    now = P.spotlight(*found["own"], comments=[P.comment(c) for c in found["comments"]])
    assert set(now) == set(before)
    for part in ("creator", "stats", "sound", "ai"):
        assert set(now[part]) == set(before[part])
    assert set(now["comments"][0]) == set(before["comments"][0]) and set(now["comments"][0]["author"]) == set(before["comments"][0]["author"])
    assert set(now["context_cards"][0]) == set(before["context_cards"][0])


def test_spotlight_related_is_the_up_next_queue():
    found = spotlight_page()
    related = [P.spotlight(story, meta) for story, meta in found["others"]]
    assert len(related) == 24 and len({item["id"] for item in related}) == 24 and SPOT not in {item["id"] for item in related}
    assert all(item["id"] and item["video"] and item["creator"]["username"] and item["posted_at"] for item in related)
    assert all(item["stats"]["view_count"] is not None for item in related)


def test_spotlight_props_is_none_for_a_page_without_a_video():
    assert approuter.spotlight_props(flight.Page(document(("1", {"videoId": "x", "video": "$undefined"})))) is None
    assert approuter.spotlight_props(flight.Page(document(("1", {"other": 1})))) is None


# ---- search --------------------------------------------------------------------------------

def search():
    found = approuter.search_props(flight.Page(read("app_explore_therock.html")))
    return found, P.search_sections(found)


def test_search_sections():
    found, sections = search()
    assert found["query"] == "therock"
    assert {name: len(items) for name, items in sections.items()} == {"users": 4, "spotlights": 17, "lenses": 11, "places": 10, "topics": 1}
    user = sections["users"][0]
    assert user["username"] == "therock" and user["link"] == "https://www.snapchat.com/@therock"
    assert user["subscriber_count"] == 2877687 and user["is_official"] is True and user["profile_picture"]
    spot = sections["spotlights"][0]
    assert spot["id"] and spot["link"].startswith("https://www.snapchat.com/@") and spot["video"] and spot["thumbnail"]
    assert spot["creator"]["username"] and spot["posted_at"] and spot["media_type"] == "video"
    assert spot["duration_seconds"] == 9.0 and spot["width"] == 540 and spot["height"] == 960      # from videoListLd
    assert spot["stats"]["view_count"] > 0 and spot["stats"]["boost_count"] is not None
    lens = sections["lenses"][0]
    assert lens["name"] == "TheRock Video Call" and len(lens["uuid"]) == 32 and lens["unlock_link"] and lens["icon"]
    place = sections["places"][0]
    assert place["name"] == "#TheRock" and place["id"] and place["link"].startswith("https://www.snapchat.com/place/")
    assert sections["topics"][0]["name"] and sections["topics"][0]["link"].startswith("https://www.snapchat.com/tag/")


def test_search_keeps_every_field_of_the_old_response():
    before = P.search_results(old("explore_therock.json"))
    before.update({k: v for k, v in P.search_results(old("explore_music.json")).items() if k not in before})
    _, sections = search()
    for name, items in sections.items():
        assert top(items) == top(before[name]), name
        if name in ("spotlights", "lenses"):
            assert set(items[0]["creator"]) == set(before[name][0]["creator"]), name


def test_search_shows_and_episodes_from_their_tiles():
    # The "therock" page has neither; the tiles as the "music" page shipped them on the same day.
    found = {"sections": {
        "shows": [approuter._search_publisher({"id": "e6769ab8-5f01-40ae-8ff0-32c99456bcac", "href": "https://www.snapchat.com/p/e6769ab8-5f01-40ae-8ff0-32c99456bcac",
                                               "title": "GOATs Only!", "description": "The greatest of all times", "imageUrl": "https://cf-st.sc-cdn.net/d/x.355", "followerCount": 139802})],
        "episodes": [approuter._search_episode({"id": "1536513508509696", "title": "She Finally Met Her Music Idol", "thumbnailUrl": "https://cf-st.sc-cdn.net/d/y.310",
                                                "publishedAt": 1788699673256, "publisherName": "Facts", "publisherImageUrl": "https://cf-st.sc-cdn.net/d/z.355",
                                                "publisherHref": "https://www.snapchat.com/p/1cd65187-11e2-49e8-b36f-af8f58b1ab02"})],
    }}
    sections = P.search_sections(found)
    show = sections["shows"][0]
    assert show["business_profile_id"] == "e6769ab8-5f01-40ae-8ff0-32c99456bcac" and show["name"] == "GOATs Only!"
    assert show["link"] == "https://www.snapchat.com/p/e6769ab8-5f01-40ae-8ff0-32c99456bcac" and show["subscriber_count"] == 139802
    episode = sections["episodes"][0]
    assert episode["id"] == "1536513508509696" and episode["published_at"] == "2026-09-06T13:01:13Z"
    assert episode["publisher"]["business_profile_id"] == "1cd65187-11e2-49e8-b36f-af8f58b1ab02" and episode["publisher"]["name"] == "Facts"
    assert episode["link"] == "https://www.snapchat.com/p/1cd65187-11e2-49e8-b36f-af8f58b1ab02/1536513508509696"
    before = P.search_results(old("explore_music.json"))
    assert set(show) == set(before["shows"][0]) and set(episode) == set(before["episodes"][0])


def test_search_props_is_none_for_a_page_without_results():
    assert approuter.search_props(flight.Page(document(("1", {"query": "x"})))) is None


# ---- structured data -------------------------------------------------------------------------

def test_video_objects_are_keyed_by_snap_id_wherever_they_are_nested():
    objects = [{"@type": "BreadcrumbList"},
               {"@type": "ItemList", "itemListElement": [{"@type": "VideoObject", "url": "https://www.snapchat.com/@a/spotlight/ID1?x=1", "width": 540}]},
               {"@type": "VideoObject", "url": "https://www.snapchat.com/@b/spotlight/ID2/", "duration": "PT1M5S"}]
    found = approuter.video_objects(objects)
    assert set(found) == {"ID1", "ID2"} and found["ID1"]["width"] == 540
    assert approuter.video_objects(None) == {}
    assert approuter._duration_seconds("PT1M5S") == 65 and approuter._duration_seconds("PT28S") == 28
    assert approuter._duration_seconds("PT1H") == 3600 and approuter._duration_seconds("") is None and approuter._duration_seconds("soon") is None
