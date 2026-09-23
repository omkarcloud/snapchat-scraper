"""Discovery endpoints: search, hashtag / topic / funny-keyword pages and
the Discover feed.

  search   `/explore/<query>` — the site's search, server-rendered as
           typed sections (spotlights, lenses, topics, public profiles,
           places, shows, episodes). No paging (sectionPageToken is always
           empty). The viewer country is the exit IP's: `country` pins a
           residential exit there.
  tag      `/tag/<tag>` JSON: ~32 internal story cards, no paging.
  topic    `/topic/<slug>`: an App Router page; 18 VideoObjects in its
           ld+json plus ~78 related topic links.
  funny    `/entertainment/funny[/<keyword>]`: 216 curated comedy keywords,
           each with 20 story cards.
  discover GraphQL discoverFeed: publisher shows + public user stories,
           paged by echoing seen tap ids.
"""
from . import parsers as P, queries, refs
from .fetch import get_page, graphql, ld_json, next_data, quote_path


def explore(query, country=None, locale="en-US"):
    props, _, _ = get_page(f"/explore/{quote_path(query)}", label="search", locale=locale, country=country)
    return props


def search(query, type="all", country=None, locale="en-US"):
    props = explore(query, country=country, locale=locale)
    sections = P.search_results(props)
    out = {
        "query": P.clean(props.get("query")) or query,
        "country": P.clean(props.get("country")),
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
    props = explore(query, country=country, locale=locale)
    users = P.search_results(props).get("users") or []
    return {"query": query, "user_count": len(users), "users": users}


def get_tag(tag):
    props = next_data("spotlight", f"/tag/{quote_path(tag)}", label=f"tag #{tag}")
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
    if not keyword:
        props, _, _ = get_page("/entertainment/funny", label="funny keywords")
        keywords = [P.funny_keyword(i) for i in props.get("items") or [] if isinstance(i, dict)]
        return {"keyword_count": len(keywords), "keywords": keywords}
    slug = refs.slugify(keyword)
    props, _, _ = get_page(f"/entertainment/funny/{slug}", label=f"funny {slug}")
    return P.funny_page(props)


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
