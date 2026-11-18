"""User endpoints: search, profile, public story, curated highlights,
spotlights and lenses — all read off the profile page (`/@<user>`, one
1-1.4 MB server-rendered document that carries everything at once). The
page is memoised in-process for PAGE_TTL seconds so a client walking the
five routes for one account fetches it once; the response cache in front
(cache_config) keys each route on its own params.

Since November 2026 the page is an App Router document: its data is read
from the flight stream (flight.py) and mapped back onto the shapes below by
approuter.profile_props, so the parsers and the responses are unchanged. What
the page stopped carrying: the first comments under each spotlight, a
story snap's own timestamp (now read from the snap id), Bitmoji 3D renders
for creators. Each tab holds at most 32 items.

Facts about the page as it was until then (2026-09-22): creators / brands come as
`publicProfileInfo` with bio, counts, highlights; plain accounts come as
`userInfo` (username, display name, snapcode, bitmoji) and answer 404-free
but empty for story / highlights / spotlights / lenses. An unknown
username is a 404 page (pageType NOT_FOUND). The profile ships up to ~31
spotlights, ~18 curated highlights and every lens with NO load-more: the
`*Cursor` fields in the payload are never consumed by the site's own
client, so there is nothing to page through — the counts here are the
site's counts.
"""
import threading
import time

from . import approuter, parsers as P
from .fetch import SnapchatNotFound, get_flight, ld_objects, snapcode_link

PAGE_TTL = 120
_lock = threading.Lock()
_pages = {}          # username -> (expires, pageProps)


def _page(username):
    now = time.time()
    with _lock:
        hit = _pages.get(username)
        if hit and hit[0] > now:
            return hit[1]
    page, html, _ = get_flight(f"/@{username}", label=f"profile @{username}")
    # A plain account's page says its display name only in the ld+json ProfilePage.
    person = next((o.get("mainEntity") for o in ld_objects(html)
                   if isinstance(o, dict) and o.get("@type") == "ProfilePage" and isinstance(o.get("mainEntity"), dict)), {})
    props = approuter.profile_props(page, username, display_name=person.get("name"),
                                    snapcode_image=snapcode_link(username))
    if props is None:
        raise SnapchatNotFound(f"@{username} not found on Snapchat")
    with _lock:
        if len(_pages) > 2000:
            _pages.clear()
        _pages[username] = (now + PAGE_TTL, props)
    return props


def _profile(page, username):
    prof = P.profile(page, username=username)
    if prof is None:
        raise SnapchatNotFound(f"@{username} not found on Snapchat")
    return prof


def _brief(prof):
    return {k: prof.get(k) for k in ("username", "display_name", "link", "type", "subscriber_count", "is_verified",
                                     "profile_picture")}


def get_profile(user):
    """The full public profile."""
    return _profile(_page(user), user)


def get_story(user):
    """The account's current public story (24-hour snaps), empty when
    nothing is live."""
    page = _page(user)
    prof = _profile(page, user)
    story = P.story(page.get("story")) if page.get("story") else None
    return {
        "user": _brief(prof),
        "has_story": bool(story and story["snaps"]),
        "story": story,
    }


def get_highlights(user):
    """Curated highlights (saved stories) with every snap."""
    page = _page(user)
    prof = _profile(page, user)
    highlights = [P.story(h) for h in page.get("curatedHighlights") or [] if isinstance(h, dict) and h.get("snapList")]
    return {
        "user": _brief(prof),
        "highlight_count": len(highlights),
        "highlights": highlights,
    }


def get_spotlights(user):
    """The account's Spotlight posts with metadata, stats and the first
    comments the page ships."""
    page = _page(user)
    prof = _profile(page, user)
    stories = page.get("spotlightHighlights") or []
    metas = page.get("spotlightStoryMetadata") or []
    # The profile page no longer ships a snap's first comments (it did until
    # November 2026); `comments` stays in each item, empty. /spotlight/comments has them.
    by_snap = {}
    spotlights = []
    for index, story in enumerate(stories):
        if not isinstance(story, dict):
            continue
        meta = metas[index] if index < len(metas) and isinstance(metas[index], dict) else {}
        item = P.spotlight(story, meta)
        if not item["id"]:
            continue    # the page pads the list with empty placeholder slots
        if not item["creator"].get("username"):
            item["creator"]["username"] = prof["username"]
            item["creator"]["link"] = prof["link"]
            item["link"] = item["link"] or f"{prof['link']}/spotlight/{item['id']}"
        item["comments"] = by_snap.get(item["id"], [])
        spotlights.append(item)
    return {
        "user": _brief(prof),
        "spotlight_count": len(spotlights),
        "spotlights": spotlights,
    }


def get_lenses(user):
    """Lenses published by the account."""
    page = _page(user)
    prof = _profile(page, user)
    lenses = [P.lens(l) for l in page.get("lenses") or [] if isinstance(l, dict)]
    return {
        "user": _brief(prof),
        "lens_count": len(lenses),
        "lenses": lenses,
    }
