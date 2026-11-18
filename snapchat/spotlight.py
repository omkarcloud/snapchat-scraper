"""Spotlight endpoints: the ranked feed, one snap's details, related snaps,
threaded comments and batch stats.

  feed      GraphQL spotlightFeed — 25 per call, re-ranked per request;
            paging works by echoing the tap ids already shown
            (storiesToFilter), packed into the opaque `cursor`.
  details   the snap's own page (`/@user/spotlight/<id>`, or the
            `/spotlight/<id>` redirect when only the id is known): metadata
            + stats + hashtags + context cards + the transcript + the first
            comments; the page also carries 25 "up next" snaps (related).
  comments  POST /getreplies (protobuf): root comments with a pagination
            cursor, or one comment's threaded replies (`comment=`).
  stats     POST /api/fetchSpotlight: up to 31 snap ids -> engagement stats,
            creator follower counts and the unencrypted media renditions.
"""
from . import approuter, parsers as P, proto, queries, refs
from .fetch import SnapchatNotFound, fetch_spotlights, get_flight, get_replies, graphql, ld_objects

FEED_PAGE = 25


def get_feed(country="US", locale="en-US", cursor=None):
    seen = refs.decode_seen(cursor)
    data = graphql("SpotlightFeed", queries.SPOTLIGHT_FEED, {
        "country": country or "US", "locale": locale or "en-US",
        "storiesToFilter": [int(i) for i in seen], "freeformTweaks": None,
    })
    feed = data.get("spotlightFeed") or {}
    items = []
    tap_ids = list(seen)
    for entry in feed.get("stories") or []:
        if not isinstance(entry, dict):
            continue
        item = P.spotlight(entry.get("story"), entry.get("metadata"))
        if item["id"] and item["id"] not in {x["id"] for x in items}:
            items.append(item)
            if item.get("tap_id"):
                tap_ids.append(item["tap_id"])
    return {
        "country": country or "US",
        "spotlight_count": len(items),
        "spotlights": items,
        "next_cursor": refs.encode_seen(tap_ids) if items else None,
        "has_more": bool(items),
    }


def _page(spotlight):
    """The snap's own page, as approuter.spotlight_props reads it. Since
    November 2026 it is an App Router document (flight.py); the JSON data
    route it used to have is gone."""
    snap_id = spotlight["id"]
    paths = [f"/spotlight/{snap_id}"]         # 301s to /@user/spotlight/<id>
    if spotlight.get("username"):
        paths.insert(0, f"/@{spotlight['username']}/spotlight/{snap_id}")
    for index, path in enumerate(paths):
        try:
            page, html, _ = get_flight(path, label="spotlight")
        except SnapchatNotFound:
            if index + 1 < len(paths):
                continue    # a wrong username in the link: try the redirect
            raise
        found = approuter.spotlight_props(page, ld_objects(html))
        if found is not None:
            return found
    raise SnapchatNotFound("spotlight not found")


def get_details(spotlight):
    found = _page(spotlight)
    snap_id = spotlight["id"]
    story, meta = found["own"]
    transcript = None
    if found["transcript"] or found["transcript_link"]:
        # The page prints the transcript as plain text; the timed cues are in the .vtt behind `link`.
        transcript = {"link": P.link_or_none(found["transcript_link"]), "cues": [], "text": P.clean(found["transcript"])}
    item = P.spotlight(story, meta, comments=[P.comment(c) for c in found["comments"]], transcript=transcript)
    item["is_restricted"] = None
    item["embed_link"] = f"{refs.SITE}/spotlight/{snap_id}/embed"
    item["related_count"] = len(found["others"])
    return item


def get_related(spotlight):
    """The "up next" snaps the site queues after this one."""
    found = _page(spotlight)
    items = []
    for story, meta in found["others"]:
        item = P.spotlight(story, meta)
        if item["id"] and item["id"] != spotlight["id"] and item["id"] not in {x["id"] for x in items}:
            items.append(item)
    return {"spotlight_id": spotlight["id"], "spotlight_count": len(items), "spotlights": items}


def get_comments(spotlight, comment=None, cursor=None, country="US"):
    """Root comments (newest / ranked first) with `next_cursor`, or with
    `comment` the threaded replies under that comment."""
    fields = get_replies(spotlight["id"], cursor=refs.decode_bytes(cursor), parent_id=comment,
                         country_code=country or "US")
    comments = [P.comment_from_proto(r) for r in proto.messages(fields, 2)]
    next_raw = proto.first(fields, 4)
    return {
        "spotlight_id": spotlight["id"],
        "parent_comment_id": comment,
        "comment_count": len(comments),
        "comments": comments,
        "next_cursor": refs.encode_bytes(next_raw) if next_raw and comments else None,
        "has_more": bool(next_raw and comments),
    }


def get_stats(spotlights):
    """Batch hydration: stats, creator and media for up to 31 snap ids."""
    entries = fetch_spotlights(spotlights)
    items = [P.hydrated_spotlight(e) for e in entries if isinstance(e, dict)]
    found = {item["id"] for item in items if item.get("id")}
    return {
        "requested_count": len(spotlights),
        "spotlight_count": len(items),
        "spotlights": items,
        "missing": [s for s in spotlights if s not in found],
    }
