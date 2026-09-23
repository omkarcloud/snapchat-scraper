"""Snapchat reference parsing: ONE param per input that auto-detects its
forms (tripadvisor QueryOrIdField convention — never a sibling `url`/`id`
pair). Every resolver raises ValueError with a user-facing message.

  user       wwe | @wwe | https://www.snapchat.com/@wwe | /add/wwe
             | https://www.snapchat.com/add/wwe?share_id=… | snapchat.com/@wwe
             | https://www.snapchat.com/@wwe/spotlight/<id> (the author)
      -> "wwe"
  spotlight  W7_EDlXWTBiXAEEniNoMPwAAYbnJwb2puY29iAaDHCDLvAaDHCC1ZAAAAAQ (snap id)
             | https://www.snapchat.com/spotlight/<id>[/embed]
             | https://www.snapchat.com/@wwe/spotlight/<id>
             | https://www.snapchat.com/p/<businessProfileId>/spotlight/<id>
      -> {"id": …, "username": "wwe" or None}
  lens       565e7595ec4e4a0da689762b127308ef (scannable uuid) | 3411441095283405
             (numeric lens id) | https://www.snapchat.com/lens/<uuid|id>
             | https://www.snapchat.com/unlock/?type=SNAPCODE&uuid=<uuid>&metadata=01
             | https://lens.snapchat.com/<uuid>
      -> "<uuid or numeric id>" (the lens page accepts either)
  tag        wweraw | #WWERaw | https://www.snapchat.com/tag/wweraw   -> "wweraw"
  topic      taylor-red-lifestyle | "Taylor Red Lifestyle"
             | https://www.snapchat.com/topic/taylor-red-lifestyle      -> "taylor-red-lifestyle"
  publisher  c8170832-9bd5-4087-a6d7-a6560c696bfc (business profile id)
             | https://www.snapchat.com/p/<id>[/<storyId>] | story.snapchat.com/p/<id>
      -> "<uuid>"
  episode    3137398530361344 | https://www.snapchat.com/p/<publisherId>/3137398530361344
      -> {"id": "3137398530361344", "publisher_id": … or None}
  place      5f880fc0-9992-11e8-9a55-f32d7289aee6
             | https://www.snapchat.com/place/crystal-lanes-bowling-alley/<id>
      -> "<uuid>"
  location   georgia/atlanta | georgia/atlanta/midtown | united-states/georgia/atlanta
             | https://www.snapchat.com/local/united-states/georgia/atlanta[/midtown][/restaurants]
      -> {"state": "georgia", "city": "atlanta", "neighborhood": None, "category": None}
  comment    13165312488468533182-11545844533123289111 (a comment id from
             /spotlight/comments)                                     -> same string
  cursor     opaque feed cursors: encode_seen / decode_seen pack the tap ids
             already shown into a short urlsafe token.
"""
import base64
import re
import zlib
from urllib.parse import parse_qs, quote, unquote, urlparse

SITE = "https://www.snapchat.com"

_HOST_RE = re.compile(r"(^|\.)snapchat\.com$")
_BARE_LINK_RE = re.compile(r"^(?:www\.|story\.|lens\.|t\.)?snapchat\.com(?:[/?#]|$)", re.I)
_USERNAME_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,31}$")
_SNAP_ID_RE = re.compile(r"^[A-Za-z0-9_-]{20,120}$")
_UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)
_HEX32_RE = re.compile(r"^[0-9a-f]{32}$", re.I)
_DIGITS_RE = re.compile(r"^\d{1,25}$")
_COMMENT_RE = re.compile(r"^\d{1,20}-\d{1,20}$")
_SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,120}$")


def _as_url(text):
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("//"):
        return "https:" + text
    return "https://" + text


def _looks_like_link(text):
    low = text.lower()
    return low.startswith(("http://", "https://", "//")) or bool(_BARE_LINK_RE.match(text))


def _parse_link(text, kind):
    parsed = urlparse(_as_url(text))
    if not _HOST_RE.search((parsed.hostname or "").lower()):
        raise ValueError(f"{kind} link must be a snapchat.com link")
    if (parsed.hostname or "").lower() == "t.snapchat.com":
        raise ValueError("t.snapchat.com share links are not supported; open the link and pass the "
                         "www.snapchat.com address it lands on")
    return parsed, [unquote(p) for p in parsed.path.split("/") if p]


def _username(text):
    name = text.lstrip("@").lower()
    if not _USERNAME_RE.match(name):
        raise ValueError(f"invalid Snapchat username {text!r}")
    return name


def resolve_user(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("user must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "user")
        if parts and parts[0].startswith("@") and len(parts[0]) > 1:
            return _username(parts[0])
        if len(parts) >= 2 and parts[0] == "add":
            return _username(parts[1])
        raise ValueError(f"no username in link {text!r} (expected /@username or /add/username)")
    return _username(text)


def resolve_spotlight(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("spotlight must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "spotlight")
        username = None
        for i, part in enumerate(parts):
            if part == "spotlight" and i + 1 < len(parts) and _SNAP_ID_RE.match(parts[i + 1]):
                if i >= 1 and parts[i - 1].startswith("@"):
                    username = parts[i - 1][1:].lower()
                return {"id": parts[i + 1], "username": username}
        raise ValueError(f"no spotlight id in link {text!r}")
    if _SNAP_ID_RE.match(text) and not _DIGITS_RE.match(text):
        return {"id": text, "username": None}
    raise ValueError(f"spotlight must be a Spotlight snap id or a snapchat.com spotlight link, got {text!r}")


def resolve_lens(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("lens must not be empty")
    if _looks_like_link(text):
        parsed, parts = _parse_link(text, "lens")
        query = parse_qs(parsed.query)
        uuid = (query.get("uuid") or [""])[0]
        if uuid and _HEX32_RE.match(uuid):
            return uuid.lower()
        for i, part in enumerate(parts):
            if part == "lens" and i + 1 < len(parts):
                candidate = parts[i + 1]
                if _HEX32_RE.match(candidate) or _DIGITS_RE.match(candidate):
                    return candidate.lower()
        if (parsed.hostname or "").lower() == "lens.snapchat.com" and parts and _HEX32_RE.match(parts[0]):
            return parts[0].lower()
        raise ValueError(f"no lens id in link {text!r}")
    if _HEX32_RE.match(text) or _DIGITS_RE.match(text):
        return text.lower()
    raise ValueError(f"lens must be a lens uuid, a numeric lens id or a snapchat.com lens / unlock link, got {text!r}")


def resolve_tag(value):
    text = str(value or "").strip()
    if _looks_like_link(text):
        _, parts = _parse_link(text, "tag")
        if len(parts) >= 2 and parts[0] == "tag":
            text = parts[1]
        else:
            raise ValueError(f"no tag in link {value!r} (expected /tag/<name>)")
    text = "".join(text.lstrip("#").split()).lower()
    if not text:
        raise ValueError("tag must not be empty")
    if len(text) > 100:
        raise ValueError("tag must be at most 100 characters")
    return text


def slugify(text):
    slug = re.sub(r"[^a-z0-9]+", "-", str(text).lower()).strip("-")
    return slug


def resolve_topic(value):
    text = str(value or "").strip()
    if _looks_like_link(text):
        _, parts = _parse_link(text, "topic")
        if len(parts) >= 2 and parts[0] == "topic":
            text = parts[1]
        else:
            raise ValueError(f"no topic in link {value!r} (expected /topic/<slug>)")
    slug = slugify(text)
    if not slug or not _SLUG_RE.match(slug):
        raise ValueError("topic must be a topic name or slug (letters, digits, hyphens)")
    return slug


def resolve_publisher(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("publisher must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "publisher")
        if len(parts) >= 2 and parts[0] == "p" and _UUID_RE.match(parts[1]):
            return parts[1].lower()
        raise ValueError(f"no publisher id in link {text!r} (expected /p/<business profile id>)")
    if _UUID_RE.match(text):
        return text.lower()
    raise ValueError(f"publisher must be a business profile id (uuid) or a snapchat.com/p/ link, got {text!r}")


def resolve_episode(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("episode must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "episode")
        if len(parts) >= 3 and parts[0] == "p" and _UUID_RE.match(parts[1]) and _DIGITS_RE.match(parts[2]):
            return {"id": parts[2], "publisher_id": parts[1].lower()}
        raise ValueError(f"no episode id in link {text!r} (expected /p/<publisher id>/<episode id>)")
    if _DIGITS_RE.match(text):
        return {"id": text, "publisher_id": None}
    raise ValueError(f"episode must be a numeric episode (story) id or a snapchat.com/p/ episode link, got {text!r}")


def resolve_place(value):
    text = str(value or "").strip()
    if not text:
        raise ValueError("place must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "place")
        if parts and parts[0] == "place":
            for part in parts[1:]:
                if _UUID_RE.match(part):
                    return part.lower()
        raise ValueError(f"no place id in link {text!r} (expected /place/<name>/<place id>)")
    if _UUID_RE.match(text):
        return text.lower()
    raise ValueError(f"place must be a place id (uuid) or a snapchat.com/place/ link, got {text!r}")


def resolve_location(value):
    """-> {"state", "city", "neighborhood", "category"} (US only: the site
    has /local/united-states/… pages and nothing else)."""
    text = str(value or "").strip()
    if not text:
        raise ValueError("location must not be empty")
    if _looks_like_link(text):
        _, parts = _parse_link(text, "location")
        if not parts or parts[0] != "local":
            raise ValueError(f"no /local/ path in link {text!r}")
        parts = parts[1:]
    else:
        parts = [p for p in text.replace("\\", "/").split("/") if p.strip()]
    parts = [slugify(p) for p in parts]
    if parts and parts[0] in ("united-states", "us", "usa"):
        parts = parts[1:]
    if len(parts) < 2 or len(parts) > 4 or not all(parts):
        raise ValueError("location must be state/city, state/city/neighborhood or a snapchat.com/local/ link "
                         "(e.g. georgia/atlanta or georgia/atlanta/midtown)")
    out = {"state": parts[0], "city": parts[1], "neighborhood": None, "category": None}
    if len(parts) == 3:
        out["category"] = parts[2]        # ambiguous: /city/<x> is a category page on the site
    elif len(parts) == 4:
        out["neighborhood"], out["category"] = parts[2], parts[3]
    return out


def resolve_comment(value):
    text = str(value or "").strip()
    if not _COMMENT_RE.match(text):
        raise ValueError("comment must be a comment id from /snapchat/spotlight/comments (two numbers joined by '-')")
    return text


# ---- links ------------------------------------------------------------------------

def user_link(username):
    return f"{SITE}/@{username}" if username else None


def spotlight_link(username, snap_id):
    if not snap_id:
        return None
    return f"{SITE}/@{username}/spotlight/{snap_id}" if username else f"{SITE}/spotlight/{snap_id}"


def lens_link(ref):
    return f"{SITE}/lens/{ref}" if ref else None


def unlock_link(uuid):
    return f"{SITE}/unlock/?type=SNAPCODE&uuid={uuid}&metadata=01" if uuid else None


def tag_link(tag):
    return f"{SITE}/tag/{quote(tag, safe='')}" if tag else None


def topic_link(slug):
    return f"{SITE}/topic/{slug}" if slug else None


def publisher_link(business_profile_id):
    return f"{SITE}/p/{business_profile_id}" if business_profile_id else None


def episode_link(business_profile_id, story_id):
    if not story_id:
        return None
    return f"{SITE}/p/{business_profile_id}/{story_id}" if business_profile_id else None


def place_link(name, place_id):
    if not place_id:
        return None
    return f"{SITE}/place/{slugify(name) or 'place'}/{place_id}"


def local_link(state, city, neighborhood=None, category=None):
    path = f"{SITE}/local/united-states/{state}/{city}"
    if neighborhood:
        path += f"/{neighborhood}"
    if category:
        path += f"/{category}"
    return path


def explore_link(query):
    return f"{SITE}/explore/{quote(query, safe='')}"


# ---- feed cursors ----------------------------------------------------------------
# The spotlight / discover feeds page by echoing the tap ids already shown.
# The cursor packs the last SEEN_LIMIT of them (zlib + urlsafe base64); older
# ids may resurface after that, which the feed's own dedup mostly prevents.
SEEN_LIMIT = 250   # 400 x 19-digit ids packs to ~5.5k chars, past CursorField's 4000 cap


def encode_seen(tap_ids):
    ids = [str(i) for i in tap_ids if i][-SEEN_LIMIT:]
    if not ids:
        return None
    raw = zlib.compress(",".join(ids).encode("ascii"), 9)
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_seen(cursor):
    if not cursor:
        return []
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = zlib.decompress(base64.urlsafe_b64decode(padded)).decode("ascii")
    except Exception:
        raise ValueError("invalid cursor: pass the next_cursor value from the previous page unchanged")
    ids = [i for i in raw.split(",") if i]
    if not all(re.match(r"^-?\d{1,20}$", i) for i in ids):
        raise ValueError("invalid cursor: pass the next_cursor value from the previous page unchanged")
    return ids


def encode_bytes(raw):
    """Opaque token for an upstream bytes cursor (comments)."""
    if not raw:
        return None
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_bytes(cursor):
    if not cursor:
        return None
    try:
        return base64.urlsafe_b64decode(cursor + "=" * (-len(cursor) % 4))
    except Exception:
        raise ValueError("invalid cursor: pass the next_cursor value from the previous page unchanged")
