"""Discovery endpoints: search, hashtag / topic / funny-keyword pages and
the Discover feed.

  search   `/explore/<query>` — the site's search, server-rendered as
           sections (spotlights, lenses, public profiles and plain accounts,
           places, shows, episodes) plus related topic words. No paging. The
           viewer country is the exit IP's: `country` pins a residential
           exit there.
  tag      `/tag/<tag>`: ~32 internal story cards, no paging.
  topic    `/topic/<slug>`: an App Router page; 18 VideoObjects in its
           ld+json plus ~78 related topic links.
  funny    `/entertainment/funny[/<keyword>]`: 216 curated comedy keywords
           (ld+json ItemList), each an App Router page whose 18 VideoObjects
           are hydrated into story cards through fetchSpotlight.
  discover GraphQL discoverFeed: publisher shows + public user stories,
           paged by echoing seen tap ids.
"""
from . import approuter, parsers as P, queries, refs
from .fetch import SnapchatUpstreamError, fetch_spotlights, get_flight, get_page, graphql, ld_json, quote_path


def explore(query, country=None, locale="en-US"):
    """The search page -> {"<section>": [...]} with every section it carried.
    Since November 2026 `/explore/<query>` is an App Router document
    (flight.py) with sections by kind; approuter.search_props maps them back
    onto what the parsers read."""
    page, _, _ = get_flight(f"/explore/{quote_path(query)}", label="search", locale=locale, country=country)
    found = approuter.search_props(page)
    if found is None:
        raise SnapchatUpstreamError("search: no results block in the page")
    return P.search_sections(found), found


def search(query, type="all", country=None, locale="en-US"):
    sections, found = explore(query, country=country, locale=locale)
    out = {
        "query": P.clean(found.get("query")) or query,
        # The page no longer says which country it was rendered for; this is the one asked for.
        "country": country.upper() if country else None,
        "link": refs.explore_link(query),
    }
    if type and type != "all":
        items = sections.get(type) or []
        out["count"] = len(items)
        out[type] = items
        return out
    out["counts"] = {name: len(items) for name, items in sections.items()}
    out.update(sections)
    return out


def search_users(query, country=None, locale="en-US"):
    users = explore(query, country=country, locale=locale)[0].get("users") or []
    return {"query": query, "user_count": len(users), "users": users}


def get_tag(tag):
    # The page itself: its JSON data route needed the Spotlight app's build id,
    # which was read from /spotlight, and that page has had none since November 2026.
    props, _, _ = get_page(f"/tag/{quote_path(tag)}", label=f"tag #{tag}")
    cards = [P.story_card(c) for c in props.get("spotlights") or [] if isinstance(c, dict)]
    related = []
    for item in props.get("relatedTopics") or []:
        name = P.clean(item.get("text") if isinstance(item, dict) else item)
        if name:
            related.append({"name": name, "link": refs.tag_link(name.replace(" ", "").lower())})
    return {
        "tag": P.clean(props.get("hashtag")) or tag,
        "link": refs.tag_link(tag),
        "spotlight_count": len(cards),
        "spotlights": cards,
        "related_tags": related,
    }


def get_topic(topic):
    objects, html = ld_json(f"/topic/{topic}", label=f"topic {topic}")
    return P.topic(objects, html, topic)


def get_funny(keyword=None):
    # 2026-10-06: both funny pages moved to the App Router (no __NEXT_DATA__,
    # "no __NEXT_DATA__ in page" 502s). Like /topic/, their data is ld+json;
    # a keyword page lists 18 VideoObjects whose ids fetchSpotlight (<= 31)
    # hydrates into the same story cards the old pageProps carried.
    if not keyword:
        objects, _ = ld_json("/entertainment/funny", label="funny keywords")
        keywords = P.funny_keywords(objects)
        return {"keyword_count": len(keywords), "keywords": keywords}
    slug = refs.slugify(keyword)
    objects, html = ld_json(f"/entertainment/funny/{slug}", label=f"funny {slug}")
    ids = P.ld_spotlight_ids(objects)[:31]
    entries = fetch_spotlights(ids) if ids else []
    return P.funny_page(objects, html, slug, entries)


def get_discover_feed(country="US", locale="en-US", limit=30, cursor=None):
    seen = refs.decode_seen(cursor)
    data = graphql("DiscoverFeed", queries.DISCOVER_FEED, {
        "first": limit or 30, "country": country or "US", "locale": locale or "en-US",
        "storyTapIdsToFilter": [int(i) for i in seen],
    })
    stories = (data.get("discoverFeed") or {}).get("stories") or []
    items = []
    tap_ids = list(seen)
    for raw in stories:
        if not isinstance(raw, dict):
            continue
        item = P.discover_story(raw)
        if item["id"] and item["id"] not in {x["id"] for x in items}:
            items.append(item)
            if item.get("tap_id"):
                tap_ids.append(item["tap_id"])
    return {
        "country": country or "US",
        "story_count": len(items),
        "stories": items,
        "next_cursor": refs.encode_seen(tap_ids) if items else None,
        "has_more": bool(items),
    }
