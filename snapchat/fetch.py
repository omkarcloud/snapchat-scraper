"""Snapchat transport: plain curl_cffi with browser-impersonated TLS. No
browser, no login, no cookies, no proxy needed — validated 2026-09-22 from
direct Indian egress (and through a US residential exit): www.snapchat.com,
static.snapchat.com, app.snapchat.com and the web-stories GraphQL host all
answer 200 with `impersonate="chrome"`, no challenge of any kind (server
header "API Gateway"; no Cloudflare / PerimeterX / Akamai). A thread whose
direct egress is ever refused (403 / 429 / HTML where JSON was expected)
moves to a residential exit (config.SNAPCHAT_FALLBACK_PROXY_COUNTRY) for
SNAPCHAT_DIRECT_COOLDOWN seconds. If residential exits start being
challenged too, the next step is the patchright pattern (g2 pool). Not
built: dead code while plain HTTP works.

Upstream surfaces (all anonymous):

  * PAGES  GET https://www.snapchat.com/<path>?locale=en-US
    Server-rendered Next.js pages whose data sits in
    `<script id="__NEXT_DATA__">` (`props.pageProps`). www.snapchat.com is
    several Next apps, each with its OWN buildId: profiles (`/@user`,
    `/add/user` 301s there), the spotlight app (`/spotlight/<id>`, `/tag/`,
    `/p/`, `/place/`, `/local/`, `/entertainment/`), the lens app
    (`/lens`, basePath /lens), the search app (`/explore/<q>`) and the
    discover app. `locale` is picked by geo-IP (an Indian exit gets Hindi
    strings) and Accept-Language is ignored — `?locale=en-US` is what
    fixes the language. `/topic/<slug>` is an App Router page with no
    __NEXT_DATA__: its data is the ld+json ItemList (ld_json()).

  * JSON   GET https://www.snapchat.com/_next/data/<buildId>/<path>.json
    The same pageProps as JSON for the spotlight app (`/@user/spotlight/
    <id>`, `/tag/<tag>`) and the lens app (`/lens/_next/data/<lensBuild>/
    index|category/<c>|<id>.json`). buildIds change on every deploy:
    they are read from a page of that app and refreshed on the first 404
    (a 404 with an unchanged buildId is a real not-found). Profiles have
    no _next/data route (404 for every spelling) — the HTML is parsed.

  * GRAPHQL POST https://www.snapchat.com/api/web-stories-api/graphql
    Open (introspection on), no auth, JSON body {operationName, query,
    variables}: spotlightFeed / discoverFeed (paginated by echoing seen
    tap ids), premiumStory, publisher.publishedPremiumStoriesConnection.

  * HYDRATE POST https://www.snapchat.com/api/fetchSpotlight
    {"spotlightIds": [...]} (<= 31 ids; 60 -> 400) -> the internal story
    cards with engagement stats, creator follower counts and hashtags.

  * COMMENTS POST https://www.snapchat.com/getreplies (protobuf, proto.py)

Failure taxonomy (scraper_errors, mapped to HTTP by route_glue):
  SnapchatUpstreamError  transport failure / 5xx / bad JSON  — retryable
  SnapchatBlocked        403 / 429 / HTML where JSON was due — retryable on a new exit
  SnapchatBadRequest     upstream 400                        — never retried
  SnapchatNotFound       unknown user / snap / tag / lens…   — never retried
"""
import json
import os
import re
import sys
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from scraper_errors import BadRequest, Blocked, NotFound, UpstreamError

from . import proto

SITE = "https://www.snapchat.com"
GRAPHQL_URL = SITE + "/api/web-stories-api/graphql"
FETCH_SPOTLIGHT_URL = SITE + "/api/fetchSpotlight"
REPLIES_URL = SITE + "/getreplies"
SNAPCODE_URL = "https://app.snapchat.com/web/deeplink/snapcode"
IMPERSONATE = "chrome"
DEFAULT_LOCALE = "en-US"

PAGE_TIMEOUT = 45          # profile pages run to 1.4 MB; /explore is a slow SSR (~3 s)
API_TIMEOUT = 30
FANOUT_WORKERS = 4

# Constant identity the web app sends on getreplies (a fixed "SNAPWEB"
# viewer id; the same for every anonymous visitor).
REPLIES_ORIGIN = 20
REPLIES_VIEWER = {1: ("fixed64", 328159700207617257), 2: ("fixed64", 9558230171809176897)}

PAGE_HEADERS = {
    "accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "accept-language": "en-US,en;q=0.9",
    "sec-fetch-dest": "document",
    "sec-fetch-mode": "navigate",
    "sec-fetch-site": "none",
    "upgrade-insecure-requests": "1",
}
JSON_HEADERS = {
    "accept": "*/*",
    "accept-language": "en-US,en;q=0.9",
    "origin": SITE,
    "referer": SITE + "/",
    "sec-fetch-dest": "empty",
    "sec-fetch-mode": "cors",
    "sec-fetch-site": "same-origin",
}

_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.*?)</script>', re.S)
_LD_JSON_RE = re.compile(r'<script type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


class SnapchatUpstreamError(UpstreamError):
    """Transport failure, 5xx or an unparseable body — retryable."""


class SnapchatBlocked(SnapchatUpstreamError, Blocked):
    """403 / 429, or HTML where JSON was expected — retryable on a new exit."""


class SnapchatBadRequest(BadRequest):
    """Upstream 400 — never retried."""


class SnapchatNotFound(NotFound):
    """The user / snap / lens / tag / publisher / place does not exist."""


# ---- sessions --------------------------------------------------------------------
# One curl session per worker thread per exit country (a curl handle must not
# be shared across threads). `country=None` is the default egress (direct, or
# SNAPCHAT_PROXY_COUNTRY); a named country pins a residential exit there, which
# is the only way to change what the SSR search / discover pages consider the
# viewer's country.
_local = threading.local()


def _sessions():
    store = getattr(_local, "sessions", None)
    if store is None:
        store = _local.sessions = {}
    return store


def _session(country=None):
    store = _sessions()
    via_fallback = getattr(_local, "proxy_until", 0) > time.time()
    key = (country or "").lower()
    sess = store.get(key)
    if sess is not None and getattr(sess, "_sc_fallback", False) != via_fallback:
        _drop_session(country)
        sess = None
    if sess is None:
        from curl_cffi import requests as curl_requests
        sess = curl_requests.Session(impersonate=IMPERSONATE)
        if key:
            proxy = config.snapchat_country_proxy(key)
        else:
            proxy = config.snapchat_proxy() or (config.snapchat_fallback_proxy() if via_fallback else None)
        if proxy:
            sess.proxies = {"http": proxy, "https": proxy}
        sess._sc_fallback = via_fallback
        store[key] = sess
    return sess


def _drop_session(country=None):
    store = _sessions()
    sess = store.pop((country or "").lower(), None)
    if sess is not None:
        try:
            sess.close()
        except Exception:
            pass


def _escalate(country=None):
    """The current exit was refused: move this thread's default egress to a
    fresh residential exit for a while (a pinned-country session just gets
    rebuilt on a new sticky port)."""
    if not country and config.snapchat_fallback_proxy() is not None:
        _local.proxy_until = time.time() + config.SNAPCHAT_DIRECT_COOLDOWN
    _drop_session(country)


def dump_debug(name, text):
    """Write a raw response to $SNAPCHAT_DEBUG_DIR/<name>.txt."""
    dbg = os.environ.get("SNAPCHAT_DEBUG_DIR", "")
    if dbg and text:
        try:
            os.makedirs(dbg, exist_ok=True)
            with open(os.path.join(dbg, name + ".txt"), "w") as f:
                f.write(text if isinstance(text, str) else repr(text))
        except OSError:
            pass


def _retrying(fn, country=None):
    last = None
    for attempt in range(1, config.MAX_RETRIES + 1):
        try:
            return fn()
        except (SnapchatNotFound, SnapchatBadRequest):
            raise
        except SnapchatBlocked as e:
            last = e
            _escalate(country)
        except SnapchatUpstreamError as e:
            last = e
            _drop_session(country)
        if attempt < config.MAX_RETRIES:
            time.sleep(config.RETRY_BACKOFF * attempt)
    raise last


def _request(method, url, *, label, country=None, timeout=API_TIMEOUT, **kwargs):
    sess = _session(country)
    try:
        resp = sess.request(method, url, timeout=timeout, **kwargs)
    except Exception as e:
        raise SnapchatUpstreamError(f"{label}: request failed: {type(e).__name__}: {e}")
    status = resp.status_code
    if status in (401, 403, 429):
        dump_debug(f"blocked_{label}", resp.text)
        raise SnapchatBlocked(f"HTTP {status} on {label}")
    if status >= 500:
        raise SnapchatUpstreamError(f"HTTP {status} on {label}")
    return resp


# ---- pages -------------------------------------------------------------------------

def _with_locale(path, params, locale):
    query = {"locale": locale or DEFAULT_LOCALE}
    query.update({k: v for k, v in (params or {}).items() if v not in (None, "")})
    return f"{path}?{urlencode(query)}"


def get_html(path, *, label, params=None, locale=None, country=None, not_found_ok=False):
    """GET one www.snapchat.com page -> (html, status, final_url). A 404 is
    SnapchatNotFound unless not_found_ok (the caller then reads the
    NOT_FOUND pageProps itself)."""
    url = SITE + _with_locale(path, params, locale)

    def once():
        resp = _request("GET", url, label=label, country=country, timeout=PAGE_TIMEOUT,
                        headers=PAGE_HEADERS, allow_redirects=True)
        status = resp.status_code
        if status == 404 and not not_found_ok:
            raise SnapchatNotFound(f"{label} not found")
        if status not in (200, 404):
            raise SnapchatUpstreamError(f"HTTP {status} on {label}")
        html = resp.text or ""
        if "<html" not in html[:3000].lower():
            dump_debug(f"nonhtml_{label}", html)
            raise SnapchatBlocked(f"{label} returned a non-HTML body")
        return html, status, str(resp.url or url)

    return _retrying(once, country)


def next_data_from_html(html, label):
    """The __NEXT_DATA__ document of a page (whole object: buildId, page,
    query, props)."""
    match = _NEXT_DATA_RE.search(html)
    if not match:
        dump_debug(f"nonext_{label}", html)
        raise SnapchatUpstreamError(f"{label}: no __NEXT_DATA__ in page")
    try:
        return json.loads(match.group(1))
    except ValueError:
        dump_debug(f"badnext_{label}", html)
        raise SnapchatUpstreamError(f"{label}: could not parse __NEXT_DATA__")


def get_page(path, *, label, params=None, locale=None, country=None, not_found_ok=False):
    """GET a page -> (pageProps, next_data document, final_url)."""
    html, status, final = get_html(path, label=label, params=params, locale=locale, country=country,
                                   not_found_ok=not_found_ok)
    doc = next_data_from_html(html, label)
    props = (doc.get("props") or {}).get("pageProps") or {}
    # the NOT_FOUND shell nests one level deeper
    if props.get("pageProps") and not props.get("userProfile"):
        props = props["pageProps"]
    if status == 404 or (props.get("pageMetadata") or {}).get("pageType") == "NOT_FOUND":
        raise SnapchatNotFound(f"{label} not found")
    return props, doc, final


def ld_json(path, *, label, params=None, locale=None, country=None):
    """GET an App Router page -> (list of ld+json objects, html)."""
    html, _, _ = get_html(path, label=label, params=params, locale=locale, country=country)
    out = []
    for raw in _LD_JSON_RE.findall(html):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out, html


# ---- _next/data JSON routes ---------------------------------------------------------
# buildId per Next app, learned from a page of that app and refreshed on 404.
_build_lock = threading.Lock()
_build_ids = {}
APP_HOME = {
    "spotlight": ("/spotlight", ""),        # www root app: /spotlight, /tag, /p, /place
    "lens": ("/lens", "/lens"),             # lens app, basePath /lens
}


def build_id(app, refresh=False):
    with _build_lock:
        if not refresh and _build_ids.get(app):
            return _build_ids[app]
    home, _ = APP_HOME[app]
    _, doc, _ = get_page(home, label=f"{app} home")
    value = doc.get("buildId")
    if not value:
        raise SnapchatUpstreamError(f"{app} home page carries no buildId")
    with _build_lock:
        _build_ids[app] = value
    return value


def next_data(app, path, *, label, params=None, locale=None, country=None):
    """GET /_next/data/<buildId>/<path>.json -> pageProps. A 404 refreshes
    the buildId once; a 404 on a current buildId is SnapchatNotFound."""
    _, base_path = APP_HOME[app]

    def fetch(build):
        query = {"locale": locale or DEFAULT_LOCALE}
        query.update({k: v for k, v in (params or {}).items() if v not in (None, "")})
        url = f"{SITE}{base_path}/_next/data/{build}{path}.json?{urlencode(query)}"

        def once():
            resp = _request("GET", url, label=label, country=country, timeout=PAGE_TIMEOUT,
                            headers={**JSON_HEADERS, "x-nextjs-data": "1"}, allow_redirects=True)
            status = resp.status_code
            text = resp.text or ""
            if status == 404:
                return None
            if status != 200:
                raise SnapchatUpstreamError(f"HTTP {status} on {label}")
            if not text.lstrip().startswith("{"):
                dump_debug(f"nonjson_{label}", text)
                raise SnapchatBlocked(f"{label} returned a non-JSON body")
            try:
                return json.loads(text)
            except ValueError:
                dump_debug(f"badjson_{label}", text)
                raise SnapchatUpstreamError(f"{label}: could not parse JSON")

        return _retrying(once, country)

    build = build_id(app)
    doc = fetch(build)
    if doc is None:
        fresh = build_id(app, refresh=True)
        if fresh != build:
            doc = fetch(fresh)
    if doc is None:
        raise SnapchatNotFound(f"{label} not found")
    props = doc.get("pageProps") if isinstance(doc, dict) else None
    if not isinstance(props, dict):
        raise SnapchatUpstreamError(f"{label}: unexpected JSON shape")
    if doc.get("notFound") or (props.get("pageMetadata") or {}).get("pageType") == "NOT_FOUND":
        raise SnapchatNotFound(f"{label} not found")
    return props


# ---- JSON APIs ------------------------------------------------------------------

def _json_post(url, body, *, label, headers=None, country=None):
    def once():
        resp = _request("POST", url, label=label, country=country,
                        headers={**JSON_HEADERS, "content-type": "application/json", **(headers or {})},
                        data=json.dumps(body, separators=(",", ":")))
        status = resp.status_code
        text = resp.text or ""
        if status == 404:
            raise SnapchatNotFound(f"{label} not found")
        if not text.lstrip().startswith(("{", "[")):
            dump_debug(f"nonjson_{label}", text)
            if status == 400:
                raise SnapchatBadRequest(f"snapchat rejected {label}")
            raise SnapchatBlocked(f"{label} returned a non-JSON body")
        try:
            payload = json.loads(text)
        except ValueError:
            dump_debug(f"badjson_{label}", text)
            raise SnapchatUpstreamError(f"{label}: could not parse JSON")
        if status == 400:
            raise SnapchatBadRequest(f"snapchat rejected {label}: {str(payload)[:200]}")
        if status != 200:
            raise SnapchatUpstreamError(f"HTTP {status} on {label}")
        return payload

    return _retrying(once, country)


def graphql(operation, query, variables, *, country=None):
    """Run one web-stories-api query -> its `data` object. Field-level
    nulls with errors (the publisher root's non-null violations) come back
    as data; a null data with errors is an upstream error."""
    payload = _json_post(GRAPHQL_URL, {"operationName": operation, "query": query, "variables": variables},
                         label=f"graphql {operation}", country=country)
    data = payload.get("data") if isinstance(payload, dict) else None
    errors = payload.get("errors") if isinstance(payload, dict) else None
    if data is None:
        dump_debug(f"gqlerror_{operation}", json.dumps(payload)[:5000])
        message = (errors or [{}])[0].get("message", "") if isinstance(errors, list) else ""
        if "Validation error" in message or "Invalid Syntax" in message:
            raise SnapchatBadRequest(f"{operation}: {message[:200]}")
        raise SnapchatUpstreamError(f"{operation} returned no data: {message[:200]}")
    return data


def fetch_spotlights(snap_ids, *, country=None):
    """POST /api/fetchSpotlight -> the raw `spotlights` list (internal story
    cards) for up to 31 spotlight snap ids; unknown ids are simply absent."""
    payload = _json_post(FETCH_SPOTLIGHT_URL, {"spotlightIds": list(snap_ids)}, label="fetchSpotlight",
                         country=country)
    return (payload or {}).get("spotlights") or []


def get_replies(snap_id, cursor=None, parent_id=None, *, country_code="US", country=None):
    """POST /getreplies (protobuf) -> decoded GetRepliesResponse fields."""
    request = {
        1: {
            1: str(uuid.uuid4()),
            2: int(time.time() * 1000),
            3: REPLIES_ORIGIN,
            4: {1: REPLIES_VIEWER, 6: country_code or "US"},
        },
        2: snap_id,
        5: 3,
        9: 2,
        11: 0,
    }
    if cursor:
        request[7] = cursor
    if parent_id:
        request[8] = proto.uuid_message(parent_id)
    body = proto.encode(request)

    def once():
        resp = _request("POST", REPLIES_URL, label="getreplies", country=country,
                        headers={**JSON_HEADERS, "content-type": "application/x-protobuf",
                                 "accept": "application/x-protobuf"},
                        data=body)
        status = resp.status_code
        if status == 404:
            raise SnapchatNotFound("spotlight not found")
        if status == 400:
            raise SnapchatBadRequest("snapchat rejected the comments request (bad cursor or comment id?)")
        if status != 200:
            raise SnapchatUpstreamError(f"HTTP {status} on getreplies")
        raw = resp.content or b""
        if raw[:1] in (b"<", b"{"):
            dump_debug("nonproto_getreplies", resp.text)
            raise SnapchatBlocked("getreplies returned a non-protobuf body")
        try:
            return proto.decode(raw)
        except ValueError as e:
            raise SnapchatUpstreamError(f"getreplies: undecodable response: {e}")

    return _retrying(once, country)


# ---- fan-out -------------------------------------------------------------------------

def run_parallel(fns):
    """Run zero-arg callables in parallel; results align with `fns`.
    Exceptions propagate from the first failing call."""
    if not fns:
        return []
    if len(fns) == 1:
        return [fns[0]()]
    with ThreadPoolExecutor(max_workers=min(FANOUT_WORKERS, len(fns))) as ex:
        futures = [ex.submit(fn) for fn in fns]
        return [f.result() for f in futures]


def snapcode_link(username, fmt="SVG", bitmoji=True, size=None):
    query = {"username": username, "type": fmt, "bitmoji": "enable" if bitmoji else "disable"}
    if size:
        query["size"] = size
    return f"{SNAPCODE_URL}?{urlencode(query)}"


def quote_path(value):
    return quote(str(value), safe="")


if __name__ == "__main__":
    # Smoke test: python -m snapchat.fetch [username]
    who = sys.argv[1] if len(sys.argv) > 1 else "wwe"
    props, doc, final = get_page(f"/@{who}", label="profile")
    info = (props.get("userProfile") or {}).get("publicProfileInfo") or (props.get("userProfile") or {}).get("userInfo") or {}
    print("profile:", final, info.get("username"), info.get("title") or info.get("displayName"), info.get("subscriberCount"))
