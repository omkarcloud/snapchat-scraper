"""Place endpoints: one place's profile (the Snap Map "place" page), place
search (the site search's Places section) and the US local directory
(`/local/united-states/<state>/<city>[/<neighborhood>][/<category>]`:
a city hub of category sections, or a category page of 20 places with
Tripadvisor ratings, prices, hours and the public snaps posted there).
"""
from . import parsers as P, refs
from .discovery import explore
from .fetch import SnapchatNotFound, get_page


def get_details(place, locale="en-US"):
    props, _, _ = get_page(f"/place/place/{place}", label=f"place {place}", locale=locale)
    if not (props.get("placeProfile") or {}).get("placeInfo"):
        raise SnapchatNotFound(f"place {place} not found")
    return P.place(props, place)


def search(query, country=None, locale="en-US"):
    props = explore(query, country=country, locale=locale)
    places = P.search_results(props).get("places") or []
    return {"query": query, "place_count": len(places), "places": places}


def get_local(location, category=None, locale="en-US"):
    category = refs.slugify(category) if category else location.get("category")
    path = f"/local/united-states/{location['state']}/{location['city']}"
    if location.get("neighborhood"):
        path += f"/{location['neighborhood']}"
    if category:
        path += f"/{category}"
    props, _, _ = get_page(path, label=f"local {path}", locale=locale)
    if not props.get("pageData"):
        raise SnapchatNotFound(f"no local page for {path}")
    return P.local_page(props)
