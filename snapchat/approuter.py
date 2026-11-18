"""The App Router pages (profile, Spotlight, search), mapped onto the shapes
the parsers already read.

Until autumn 2026 these pages were Pages Router documents whose
`__NEXT_DATA__` pageProps looked like the site's protobuf messages
(`publicProfileInfo`, `snapList`, `spotlightStoryMetadata`, typed search
sections). parsers.py was written against those. The App Router pages
(flight.py) carry "view models" instead: small objects shaped for the
components that draw them (`publicProfile`, a `tile` and a `playback` per
item, `sections` by kind).

Rather than a second set of parsers, each function here rebuilds the OLD shape
from a view model, so parsers.profile / story / spotlight / lens /
story_card / business_profile … keep producing the same response fields. What
the new pages no longer carry comes out null through the old parsers, nothing
is invented:

    profile     per-snap times of a story are read from the snap ids (below);
                bitmoji 3D images, primary colour, publisher type are gone
    spotlights  duration, size and the AI language tags are gone; "likes" are
                the old boostCount (same number, new label on the site)
    search      a tile carries far less than the old search card did: no
                contact details for accounts, no coordinates for places
"""
import base64
import re
import time

SOUND, LENS, CREATOR, PLACE = 2, 1, 3, 4
_CARD_KINDS = {"sound": SOUND, "lens": LENS, "creator": CREATOR, "place": PLACE}
_USER_HREF_RE = re.compile(r"/@([^/?#]+)")
_UUID_RE = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
_HASHTAG_RE = re.compile(r"#(\w+)")
_FIRST_SNAP_MS = 1_300_000_000_000        # 2011: nothing on Snapchat is older


def snap_time_ms(snap_id):
    """When a snap was posted, in epoch milliseconds, read from its id; None
    for ids that carry no time (highlight snaps have plain UUIDs).

    A story / Spotlight snap id is 44 bytes in URL-safe base64. Bytes 34-39
    hold the post time in milliseconds, shifted left by two bits. Checked
    against the `timestampInSec` the old pages printed beside every id: equal
    to the second on each one."""
    if not isinstance(snap_id, str) or len(snap_id) < 56:
        return None
    try:
        raw = base64.urlsafe_b64decode(snap_id + "=" * (-len(snap_id) % 4))
    except (ValueError, TypeError):
        return None
    if len(raw) != 44:
        return None
    stamp = int.from_bytes(raw[34:40], "big") >> 2
    return stamp if _FIRST_SNAP_MS < stamp < (time.time() + 86400) * 1000 else None


_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+(?:\.\d+)?)S)?$")


def _duration_seconds(text):
    """An ISO 8601 duration ("PT1M28S") in seconds, or None."""
    match = _DURATION_RE.match(text or "")
    if not match or not any(match.groups()):
        return None
    hours, minutes, seconds = (float(part) if part else 0.0 for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def video_objects(objects):
    """{snap id: schema.org VideoObject} from a page's structured data (its
    ld+json blocks, or the search page's `videoListLd`). The pages print a
    video's size and length only there."""
    out = {}
    stack = list(objects or [])
    while stack:
        node = stack.pop()
        if isinstance(node, list):
            stack.extend(node)
        elif isinstance(node, dict):
            if node.get("@type") == "VideoObject" and isinstance(node.get("url"), str):
                out[node["url"].split("?")[0].rstrip("/").rsplit("/", 1)[-1]] = node
            stack.extend(value for value in node.values() if isinstance(value, (dict, list)))
    return out


def _username_of(href):
    match = _USER_HREF_RE.search(href or "")
    return match.group(1) if match else None


def _wrap(value):
    """The old pages wrapped optional scalars as {"value": x}."""
    return {"value": value} if value is not None else None


# ---- profile ---------------------------------------------------------------------------

def _related(account):
    return {
        "publicProfileInfo": {
            "title": account.get("displayName"),
            "username": account.get("username"),
            "profilePictureUrl": account.get("profilePictureUrl"),
            "badge": 1 if account.get("badge") else 0,
        },
    }


def _public_info(public, snapcode_image):
    """`publicProfile` -> the old `publicProfileInfo`."""
    return {
        "username": public.get("username"),
        "title": public.get("title"),
        "bio": public.get("bio"),
        "websiteUrl": public.get("websiteUrl"),
        "address": public.get("address"),
        "categoryStringId": public.get("categoryLabelId"),
        "subcategoryStringId": public.get("subcategoryLabelId"),
        "subscriberCount": public.get("subscriberCount"),
        # The badge was a number (1 = verified star); it is a word now ("star").
        "badge": 1 if public.get("badge") else 0,
        "profilePictureUrl": public.get("profilePictureUrl"),
        "squareHeroImageUrl": public.get("squareHeroImageUrl"),
        "snapcodeImageUrl": snapcode_image,
        "hostUserId": public.get("userId"),
        "businessProfileId": public.get("businessProfileId"),
        "hasCuratedHighlights": public.get("hasCuratedHighlights"),
        "hasSpotlightHighlights": public.get("hasSpotlightHighlights"),
        "shouldHideUsername": public.get("hideUsername"),
        "relatedAccountsInfo": [_related(a) for a in public.get("relatedAccounts") or [] if isinstance(a, dict)],
        "sameAsLinks": public.get("sameAsLinks") or [],
        "creationTimestampMs": public.get("creationTimestampMs"),
        "lastUpdateTimestampMs": public.get("lastUpdateTimestampMs"),
    }


def _images(node, out):
    """Every {src, alt} an element tree draws."""
    if isinstance(node, dict):
        if isinstance(node.get("src"), str):
            out.append((node.get("alt") or "", node["src"]))
        for value in node.values():
            _images(value, out)
    elif isinstance(node, list):
        for value in node:
            _images(value, out)
    return out


def _plain_info(header, username, display_name):
    """An account without a public profile. Its page draws a Bitmoji and a
    Snapcode and nothing else; both are read from the images it renders."""
    images = _images(header.get("simplified"), [])
    bitmoji = next((src for alt, src in images if "bitmoji" in alt.lower()), None)
    snapcode = next((src for alt, src in images if "snapcode" in alt.lower()), None)
    return {
        "username": header.get("username") or username,
        "displayName": display_name,
        "snapcodeImageUrl": snapcode,
        "bitmoji3d": {"avatarImage": {"url": bitmoji}} if bitmoji else None,
    }


def _snaps(sequence, timed):
    out = []
    for index, item in enumerate((sequence or {}).get("items") or []):
        if not isinstance(item, dict):
            continue
        stamp = snap_time_ms(item.get("id")) if timed else None
        out.append({
            "snapId": _wrap(item.get("id")),
            "snapIndex": index,
            "snapMediaType": 1 if item.get("kind") == "video" else 0,
            "snapUrls": {"mediaUrl": item.get("src"), "mediaPreviewUrl": item.get("posterSrc")},
            "timestampInSec": stamp // 1000 if stamp else None,
        })
    return out


def _story(item, story_id, story_type, title):
    """A profile "stories" item -> the old story (storyType 5 = the public
    24-hour story, 3 = a curated highlight)."""
    tile = item.get("tile") or {}
    playback = item.get("playback") or {}
    return {
        "storyType": story_type,
        "storyId": _wrap(story_id),
        "storyTitle": _wrap(title),
        "thumbnailUrl": tile.get("thumbnailUrl"),
        "snapList": _snaps(playback.get("sequence"), timed=story_type == 5),
    }


def spotlight_pair(video, tile=None, cards=None, posted_at_ms=None, described=None):
    """A Spotlight `video` (+ its `tile`, + the context cards of its own
    page, + its schema.org VideoObject when the page has one) -> the old
    (story, metadata) pair parsers.spotlight reads."""
    video = video or {}
    tile = tile or {}
    described = described or {}
    snap_id = video.get("id") or video.get("rawSnapId") or tile.get("snapId") or tile.get("id")
    posted = video.get("uploadTimestampMs") or posted_at_ms or snap_time_ms(snap_id)
    username = video.get("postingUsername") or _username_of(tile.get("href"))
    try:
        posted_seconds = int(posted) // 1000
    except (TypeError, ValueError):
        posted_seconds = None
    story = {
        "storyId": _wrap(snap_id),
        "thumbnailUrl": video.get("posterUrl") or tile.get("thumbnailUrl"),
        "isAttributed": video.get("isAttributed"),
        "storyTapId": tile.get("tapStoryKey"),
        "snapList": [{
            "snapId": _wrap(snap_id),
            "snapUrls": {"mediaUrl": video.get("videoUrl") or tile.get("videoPreviewUrl"),
                         "mediaPreviewUrl": video.get("posterUrl") or tile.get("thumbnailUrl")},
            "audioTranscriptionObjectUrl": video.get("transcriptUrl"),
            "timestampInSec": posted_seconds,
        }],
    }
    pick = lambda name: video.get(name) if video.get(name) is not None else tile.get(name)
    caption = video.get("caption") if video.get("caption") is not None else tile.get("rawCaption")
    meta = {
        "videoMetadata": {
            "creator": {"personCreator": {"username": username, "name": video.get("creatorName") or tile.get("creatorName")}},
            "uploadDateMs": posted,
            "thumbnailUrl": tile.get("thumbnailUrl") or video.get("posterUrl"),
            "width": described.get("width"),
            "height": described.get("height"),
            "durationMs": int(_duration_seconds(described.get("duration")) * 1000)
                          if _duration_seconds(described.get("duration")) else None,
            "embeddedTextCaption": described.get("embeddedTextCaption"),
        },
        "engagementStats": {
            "viewCount": pick("viewCount"),
            "shareCount": pick("shareCount"),
            "commentCount": pick("commentCount"),
            "boostCount": pick("likeCount"),
            "recommendCount": video.get("recommendCount"),
        },
        "description": caption,
        # The caption's own hashtags: the structured data lists them (with the #); else they are
        # read from the caption, as whole words ("#MITB!" is the tag MITB).
        "hashtags": [k for k in described.get("keywords") or [] if isinstance(k, str) and k.startswith("#")]
                    or _HASHTAG_RE.findall(caption or ""),
        "llmTitle": tile.get("title"),
        "llmDescription": tile.get("description"),
        # The structured data mixes the caption's hashtags into the keywords; those are in `hashtags` already.
        "llmKeywords": tile.get("keywords") or [k for k in described.get("keywords") or []
                                                 if isinstance(k, str) and not k.startswith("#")],
        "contextCards": [{
            "contextType": _CARD_KINDS.get(card.get("kind")),
            "id": card.get("id"),
            "title": card.get("title"),
            "subtitle": card.get("subtitle"),
            "url": card.get("href") or card.get("url"),
            "thumbnailUrl": card.get("thumbnailUrl"),
        } for card in cards or [] if isinstance(card, dict) and card.get("kind") in _CARD_KINDS],
    }
    return story, meta


def _lens(tile):
    return {
        "lensId": tile.get("id"),
        "lensName": tile.get("name"),
        "unlockUrl": tile.get("unlockUrl"),
        "iconUrl": tile.get("iconUrl"),
        "lensPreviewImageUrl": tile.get("thumbnailUrl"),
        "lensCreatorDisplayName": tile.get("creatorName"),
    }


def profile_props(page, username, display_name=None, snapcode_image=None):
    """A profile page -> the old profile pageProps (`userProfile`, `story`,
    `curatedHighlights`, `spotlightHighlights` + `spotlightStoryMetadata`,
    `lenses`), or None when the page shows no profile at all.

    The page has a header and tabs. Stories: the pinned "live_story" is the
    current 24-hour story, the rest are curated highlights (a highlight the
    page lists without its snaps is skipped, as the old page's empty slots
    were). Each tab ships at most 32 items and nothing loads more."""
    header = page.find_props("variant", "username")
    if not header:
        return None
    header = page.expand({key: value for key, value in header.items() if key != "children"})
    public = header.get("publicProfile")
    if isinstance(public, dict):
        profile = {"$case": "publicProfileInfo", "publicProfileInfo": _public_info(public, snapcode_image)}
    else:
        profile = {"$case": "userInfo", "userInfo": _plain_info(header, username, display_name)}
    tabs = page.find_props("all", "stories", "spotlight") or {}

    def tab(name, field="items"):
        props = page.element_props((tabs.get(name) or {}).get("panel")) or {}
        return page.items(props.get(field))

    story, highlights = None, []
    for item in tab("stories"):
        tile = item.get("tile") or {}
        if tile.get("contentType") == "live_story":
            story = story or _story(item, header.get("username") or username, 5, None)
        elif (item.get("playback") or {}).get("sequence"):
            entry = _story(item, tile.get("id"), 3, tile.get("title"))
            entry["highlightId"] = _wrap(tile.get("id"))
            highlights.append(entry)
    pairs = [spotlight_pair((item.get("playback") or {}).get("video"), item.get("tile"), posted_at_ms=item.get("postedAtMs"))
             for item in tab("spotlight")]
    return {
        "userProfile": profile,
        "story": story,
        "curatedHighlights": highlights,
        "spotlightHighlights": [story_raw for story_raw, _ in pairs],
        "spotlightStoryMetadata": [meta for _, meta in pairs],
        "lenses": [_lens(tile) for tile in tab("lenses", "tiles")],
    }


# ---- one Spotlight ----------------------------------------------------------------------

def spotlight_props(page, ld_objects=None):
    """A Spotlight page -> {"own": (story, metadata), "others": [(story,
    metadata), …] (the "up next" queue), "comments": [reply, …] in the shape
    parsers.comment reads, "transcript": text, "transcript_link": url}, or
    None when the page shows no video. `ld_objects` are the document's
    ld+json blocks: the snap's size and length are printed only there."""
    props = page.find_props("videoId", "video")
    if not props:
        return None
    props = page.expand({key: value for key, value in props.items() if key != "children"})
    video = props.get("video") or {}
    if not video:
        return None
    context = props.get("context") or {}
    own_tile = {"description": props.get("description"), "title": None, "href": (context.get("creator") or {}).get("url")}
    others = []
    for item in ((props.get("upNext") or {}).get("items")) or []:
        if isinstance(item, dict) and (item.get("video") or item.get("tile")):
            others.append(spotlight_pair(item.get("video"), item.get("tile")))
    comments = (props.get("comments") or {}).get("comments") or []
    described = video_objects(ld_objects)
    return {
        "own": spotlight_pair(video, own_tile, cards=context.get("cards"),
                              described=described.get(video.get("id") or props.get("videoId"))),
        "others": others,
        "comments": [c for c in comments if isinstance(c, dict)],
        "transcript": props.get("transcript"),
        "transcript_link": video.get("transcriptUrl"),
        "related_topics": [t for t in props.get("relatedTopics") or [] if isinstance(t, dict)],
    }


# ---- search -------------------------------------------------------------------------------

def _search_spotlight(tile, described=None):
    """A search Spotlight tile (+ its schema.org VideoObject) -> the old
    single-snap story card."""
    snap_id = tile.get("snapId") or tile.get("id")
    described = described or {}
    return {
        "snaps": [{
            "rawSnapId": snap_id,
            "caption": tile.get("rawCaption"),
            "creatorInfo": {"userName": _username_of(tile.get("href")), "displayName": tile.get("creatorName")},
            "mediaInfo": {"mediaType": 1, "boltWatermarkedVideoUrl": tile.get("videoPreviewUrl"),
                          "duration": _duration_seconds(described.get("duration")),
                          "boltWatermarkedVideoDimensions": {"width": described.get("width"), "height": described.get("height")}},
            "creationTimestampMs": snap_time_ms(snap_id),
        }],
        "storyThumbnail": {"thumbnailUrl": tile.get("thumbnailUrl")},
        "singleSnapStoryMetadata": {"llmTitle": tile.get("title"), "llmDescription": tile.get("description"),
                                    "llmKeywords": tile.get("keywords") or []},
        "engagementStats": {"viewCount": tile.get("viewCount"), "shareCount": tile.get("shareCount"),
                            "liveCommentCount": tile.get("commentCount"), "boostCount": tile.get("likeCount")},
    }


def _search_lens(item):
    return {"lensId": item.get("id"), "deeplinkUrl": item.get("unlockUrl") or item.get("href"), "name": item.get("name"),
            "iconUrl": item.get("iconUrl"), "thumbnailUrl": item.get("thumbnailUrl"), "creatorName": item.get("creatorName"),
            "creatorIsOffical": item.get("creatorIsOfficial")}


def _search_account(item):
    """A "Subscribe" (public profile) or "Add Friends" (plain account) tile
    -> the old businessProfile."""
    return {"hostAccountUsername": item.get("username") or _username_of(item.get("href")), "title": item.get("title"),
            "description": item.get("description"), "subscriberCount": item.get("followerCount"),
            "isOfficialAccount": item.get("isOfficial"), "businessLogo": {"originalLogoUrl": item.get("imageUrl")},
            "heroImageUrl": item.get("heroImageUrl"), "id": item.get("id")}


def _search_place(item):
    icon = bool(item.get("imageIsIcon"))
    return {"id": item.get("id"), "displayName": item.get("title"), "locality": item.get("address"),
            "categoryIconUrl": item.get("imageUrl") if icon else None,
            "profilePhoto": {"imageUrl": None if icon else item.get("imageUrl")}}


def _publisher_id(href):
    match = _UUID_RE.search(href or "")
    return match.group(0) if match else None


def _search_publisher(item):
    return {"businessProfileId": _publisher_id(item.get("href")) or item.get("id"), "displayName": item.get("title"),
            "description": item.get("description"), "iconUrl": item.get("imageUrl"),
            "approxSubscriptionCount": item.get("followerCount")}


def _search_episode(item):
    return {"id": item.get("id"), "title": item.get("title"), "thumbnailUrl": item.get("thumbnailUrl"),
            "publishEpoch": item.get("publishedAt"),
            "publisher": {"businessProfileId": _publisher_id(item.get("publisherHref")), "displayName": item.get("publisherName"),
                          "iconUrl": item.get("publisherImageUrl")}}


# section kind on the page -> (name in the response, how to rebuild the old raw)
SEARCH_SECTIONS = {
    "spotlight": ("spotlights", _search_spotlight),
    "lenses": ("lenses", _search_lens),
    "profiles": ("users", _search_account),
    "users": ("users", _search_account),
    "places": ("places", _search_place),
    "publishers": ("shows", _search_publisher),
    "episodes": ("episodes", _search_episode),
}


def search_props(page):
    """A search page -> {"query", "sections": {name: [old raw, …]}, "topics":
    [text, …]}, or None when the page shows no results block. Accounts with a
    public profile and plain accounts both land in "users", in page order."""
    data = page.find_props("query", "sections")
    if not data:
        return None
    data = page.expand(data)
    described = video_objects([data.get("videoListLd")])
    sections = {}
    for section in data.get("sections") or []:
        if not isinstance(section, dict) or section.get("kind") not in SEARCH_SECTIONS:
            continue
        name, rebuild = SEARCH_SECTIONS[section["kind"]]
        for item in section.get("items") or []:
            if not isinstance(item, dict):
                continue
            if name == "spotlights":
                sections.setdefault(name, []).append(rebuild(item, described.get(item.get("snapId") or item.get("id"))))
            else:
                sections.setdefault(name, []).append(rebuild(item))
    return {
        "query": data.get("query"),
        "sections": sections,
        "topics": [topic for topic in data.get("topics") or [] if isinstance(topic, str) and topic.strip()],
    }
