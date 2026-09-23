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
from . import parsers as P, proto, queries, refs
from .fetch import SnapchatNotFound, fetch_spotlights, get_page, get_replies, graphql, next_data

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
    snap_id = spotlight["id"]
    if spotlight.get("username"):
        try:
            return next_data("spotlight", f"/@{spotlight['username']}/spotlight/{snap_id}", label="spotlight")
        except SnapchatNotFound:
            pass  # a wrong username in the link: fall through to the redirect
    props, _, _ = get_page(f"/spotlight/{snap_id}", label="spotlight")
    return props


def _own_story(page, snap_id):
    stories = (page.get("spotlightFeed") or {}).get("spotlightStories") or []
    own, others = None, []
    for entry in stories:
        if not isinstance(entry, dict):
            continue
        story = entry.get("story") or {}
        sid = P.clean(P.val(story.get("storyId")))
        if own is None and sid == snap_id:
            own = entry
        else:
            others.append(entry)
    if own is None and stories and isinstance(stories[0], dict):
        own, others = stories[0], stories[1:]
    return own, others


def get_details(spotlight):
    page = _page(spotlight)
    snap_id = spotlight["id"]
    own, others = _own_story(page, snap_id)
    if own is None:
        raise SnapchatNotFound("spotlight not found")
    transcript_raw = (page.get("transcriptMap") or {}).get(snap_id)
    item = P.spotlight(own.get("story"), own.get("metadata"),
                       comments=P.comments_from_json(page.get("encodedComments")),
                       transcript=P.transcript_entry(transcript_raw) if transcript_raw else None)
    video = page.get("videoMetadata") or {}
    if not item["video"]:
        item["video"] = P.link_or_none(video.get("contentUrl"))
    item["is_restricted"] = P.to_bool(page.get("restricted"))
    item["embed_link"] = f"{refs.SITE}/spotlight/{snap_id}/embed"
    item["related_count"] = len(others) + len(page.get("rerankCandidateStories") or [])
    return item


def get_related(spotlight):
    """The "up next" snaps the site queues after this one."""
    page = _page(spotlight)
    own, others = _own_story(page, spotlight["id"])
    if own is None:
        raise SnapchatNotFound("spotlight not found")
    entries = others + [e for e in page.get("rerankCandidateStories") or [] if isinstance(e, dict)]
    items = []
    for entry in entries:
        item = P.spotlight(entry.get("story"), entry.get("metadata"))
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
