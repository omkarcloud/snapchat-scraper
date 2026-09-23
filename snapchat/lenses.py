"""Lens endpoints: browse by category, one lens, lens creators, search.

The lens app (`/lens`, its own Next buildId) serves 25 lenses per page
with a constructible offset cursor (`cursor_id` = base64 of a protobuf
varint offset: CBk= is 25, CDI= 50 …); `hasMore: false` ends the walk and
a cursor past the end is an upstream 500, so `next_cursor` is only given
while hasMore holds. The lens detail page accepts the scannable uuid or
the numeric lens id and adds 12 related lenses plus 16 Spotlight snaps
made with the lens. Lens search is the site search's "Lenses" section.
"""
from . import parsers as P, refs
from .discovery import explore
from .fetch import next_data

CATEGORY_PATHS = {"for_you": "/index", "trending": "/category/trending", "face": "/category/face",
                  "world": "/category/world", "music": "/category/music", "web_live": "/category/web_live"}


def _page(path, cursor, locale, label):
    return next_data("lens", path, label=label, locale=locale, params={"cursor_id": cursor} if cursor else None)


def browse(category="for_you", cursor=None, locale="en-US"):
    props = _page(CATEGORY_PATHS.get(category, "/index"), cursor, locale, f"lenses {category}")
    lenses = [P.lens(l) for l in props.get("topLenses") or [] if isinstance(l, dict)]
    has_more = bool(P.to_bool(props.get("hasMore"))) and bool(lenses)
    return {
        "category": category,
        "categories": [{"id": P.clean(c.get("name")).lower(), "name": P.clean(c.get("displayName"))}
                       for c in props.get("categories") or [] if isinstance(c, dict) and P.clean(c.get("name"))],
        "lens_count": len(lenses),
        "lenses": lenses,
        "next_cursor": P.clean(props.get("nextCursorId")) if has_more else None,
        "has_more": has_more,
    }


def get_details(lens, locale="en-US"):
    props = _page(f"/{lens}", None, locale, f"lens {lens}")
    info = props.get("lensDisplayInfo") or {}
    item = P.lens(info)
    using = props.get("spotlightsUsingThisLens") or []
    metas = props.get("spotlightsUsingThisLensMetadata") or []
    spotlights = [P.lens_spotlight(using[i], metas[i] if i < len(metas) else None)
                  for i in range(len(using)) if isinstance(using[i], dict)]
    item["related_lenses"] = [P.lens(l) for l in props.get("moreLenses") or [] if isinstance(l, dict)]
    item["spotlight_count"] = len(spotlights)
    item["spotlights"] = spotlights
    return item


def creators(cursor=None, locale="en-US"):
    props = _page("/category/creators", cursor, locale, "lens creators")
    items = [P.lens_creator(c) for c in props.get("creatorDisplayInfos") or [] if isinstance(c, dict)]
    has_more = bool(P.to_bool(props.get("hasMore"))) and bool(items)
    return {
        "creator_count": len(items),
        "creators": items,
        "next_cursor": P.clean(props.get("nextCursorId")) if has_more else None,
        "has_more": has_more,
    }


def search(query, country=None, locale="en-US"):
    props = explore(query, country=country, locale=locale)
    lenses = P.search_results(props).get("lenses") or []
    return {"query": query, "lens_count": len(lenses), "lenses": lenses}
