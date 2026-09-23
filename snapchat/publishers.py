"""Publisher (Discover show) endpoints: a publisher's profile with its
seasons and latest episodes, an episode list per season with cursor
paging, and one episode with every snap.

The publisher page (`/p/<businessProfileId>`) is server-rendered with the
profile, the season list (id, number, episode count) and the 14 newest
episodes; the GraphQL `publisher.publishedPremiumStoriesConnection` pages
a season's episodes (the season id is required in practice — without it
the connection is null); `premiumStory` returns an episode's snaps with
their HLS tracks. Publisher pages are keyed by id only (`/p/<slug>` is a
404); ids come from search (shows / episodes), the Discover feed and a
public profile's `business_profile_id`.
"""
from . import parsers as P, queries, refs
from .fetch import SnapchatBadRequest, SnapchatNotFound, get_page, graphql


def _page(business_profile_id, locale="en-US"):
    props, _, _ = get_page(f"/p/{business_profile_id}", label=f"publisher {business_profile_id}", locale=locale)
    if not props.get("publicProfileInfo"):
        raise SnapchatNotFound(f"publisher {business_profile_id} not found")
    return props


def get_details(publisher, locale="en-US"):
    return P.publisher(_page(publisher, locale), publisher)


def _season_id(publisher, season):
    page = _page(publisher)
    seasons = [P.season(s) for s in page.get("premiumShowSeasonList") or [] if isinstance(s, dict)]
    if not seasons:
        raise SnapchatNotFound(f"publisher {publisher} has no seasons")
    if not season:
        return max(seasons, key=lambda s: s.get("number") or 0), seasons
    for item in seasons:
        if item["id"] == season or (season.isdigit() and item.get("number") == int(season)):
            return item, seasons
    raise SnapchatBadRequest(f"unknown season {season!r}: pass a season id or number from /snapchat/publishers/details")


def get_episodes(publisher, season=None, cursor=None, limit=25, country="US"):
    chosen, _ = _season_id(publisher, season)
    data = graphql("PublishedPremiumStories", queries.PUBLISHED_PREMIUM_STORIES, {
        "businessProfileId": publisher, "seasonId": chosen["id"], "cursor": cursor or "",
        "limit": limit or 25, "country": country or "US",
    })
    connection = ((data.get("publisher") or {}).get("publishedPremiumStoriesConnection")) or {}
    if not connection and cursor:
        raise SnapchatBadRequest("invalid cursor: pass the next_cursor value from the previous page unchanged")
    episodes = [P.episode_summary(e, publisher) for e in connection.get("premiumStories") or [] if isinstance(e, dict)]
    info = connection.get("pageInfo") or {}
    next_cursor = P.clean(info.get("nextCursor"))
    has_more = bool(episodes) and (P.to_bool(info.get("hasNextPage")) is not False) and bool(next_cursor)
    return {
        "publisher_id": publisher,
        "season": chosen,
        "episode_count": len(episodes),
        "episodes": episodes,
        "next_cursor": next_cursor if has_more else None,
        "has_more": has_more,
    }


def get_episode(episode, country="US"):
    data = graphql("PremiumStory", queries.PREMIUM_STORY, {"storyId": episode["id"], "country": country or "US"})
    raw = data.get("premiumStory")
    if not isinstance(raw, dict) or not raw.get("story"):
        raise SnapchatNotFound(f"episode {episode['id']} not found")
    return P.episode(raw, episode.get("publisher_id"))
