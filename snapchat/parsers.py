"""Snapchat normalizers: the web app's page props, GraphQL objects, internal
story cards and protobuf replies -> one clean snake_case shape per entity.

Output conventions (shared with the other scrapers here): `link` for
canonical snapchat.com URLs, `image` / `video` / `thumbnail` /
`profile_picture` for media URLs, `*_count` for counters, `is_*` / `has_*`
for booleans, ISO-8601 UTC timestamps (the upstream's epoch seconds or ms),
numbers as numbers, null for missing, [] for empty lists. Snap ids are the
site's own opaque strings; comment / user ids that arrive as 128-bit
{highBits, lowBits} pairs are rendered "high-low".

Entity shapes:
  profile        {username, display_name, link, type, bio, website, address,
                  category, subcategory, subscriber_count, is_verified, badge,
                  profile_picture, hero_image, snapcode_image, snapcode_links,
                  primary_color, publisher_type, mutable_username, user_id,
                  business_profile_id, bitmoji, has_story,
                  has_curated_highlights, has_spotlight_highlights,
                  is_username_hidden, related_accounts, same_as_links,
                  created_at, updated_at, counts}
  story          {id, type, title, subtitle, thumbnail, emoji, share_id,
                  video_track, is_attributed, snap_count, snaps[]}
  snap           {id, index, media_type, media, preview_image, overlay,
                  attachment, title, subtitles, transcript_link, posted_at,
                  location, is_sponsored}
  spotlight      {id, link, caption, hashtags, thumbnail, video,
                  preview_image, transcript_link, posted_at, duration_ms,
                  width, height, embedded_text, keywords, creator, stats,
                  sound, lens, context_cards, ai, transcript, comments}
  story_card     the internal card (tag / entertainment pages, fetchSpotlight,
                  search) -> {id, link, caption, hashtags, posted_at,
                  captured_at, expires_at, media_type, video, image,
                  duration_seconds, width, height, thumbnail, creator,
                  lens_id, topic_id, stats, ai, is_top_creator,
                  are_replies_enabled, is_sharing_disabled,
                  is_creator_monetizable, is_ai_flagged, is_ai_disclosed}
  comment        {id, text, posted_at, updated_at, author, reply_count,
                  report_count, ranking_score, is_approved}
  lens           {id, uuid, name, link, unlock_link, icon, preview_image,
                  preview_video, snapcode_image, creator, tags, is_official,
                  updated_at}
  discover story {id, type, title, thumbnail, tap_id, published_at,
                  video_track, snap_count, snaps, creator}
  episode        {id, title, subtitle, thumbnail, video_track, published_at,
                  season_number, episode_number, publisher_id, link,
                  snap_count, snaps}
  place          see place()

Deliberately dropped as noise:
  tracking      gaid, serverSideConfigs, jaguarClientLogging, oneLinkParams,
                deeplink / oneLinkUrl (app-store attribution redirects),
                storyTapId "0", contentToken, storyIdFp / storyDedupeFp /
                storyCacheFp, eventSignature, adsTracking, adOrganicSignals,
                clientRankingFeatures, *ModelHeadScores, scoringModelId
  viewer state  isSubscribed, isPostedByFriend, isNotificationOptedIn,
                isFavorited, showSnapExpiredToast, viewerInfo (the pod's own
                exit country / locale), messages (UI string table),
                localization, pageMetadata / linkPreview (OpenGraph copies of
                data already in the payload), pageLinks (canonical URL is
                rebuilt as `link`)
  encrypted     mediaKey / mediaIv / thumbnailIv and the encrypted mediaUrl of
                internal cards — the unencrypted watermarked / flat renditions
                are served instead; snapBoltInfo content-object byte blobs
  always empty  storyShareId, canonicalUrlSuffix, storySubtitle, emoji on
                spotlights, lensMetadata, userMetadata, lensResource,
                userProfileUrl, s2iTags on pages, remainingSpotlightIds,
                devInfo, placePivots, promotableContents, allowedActions,
                pendingRoleInvites, contents / contentIdentifiers
  zero-only     the internal engagementStats counters that are always 0 for
                an anonymous viewer (rewatch, remix, screenshot, viewer,
                swipe*, tap*, view-time, paid*, combined*, *pendingReply*)
  presentation  playCount "23K" (the count is in the hydrated card),
                creatorNameMaxNumLines / decorators, ageText, teaserText,
                columnCount / sectionLayout / numToShow, displayStartHour
                (kept inside popularity_hours), Hindi/English UI titles
"""
import re
from datetime import datetime, timezone
from urllib.parse import urlparse

from . import proto, refs

STORY_TYPES = {3: "curated_highlight", 5: "public_story", 15: "spotlight", 16: "publisher_episode"}
SNAP_MEDIA_TYPES = {0: "image", 1: "video", "IMAGE": "image", "VIDEO": "video"}
CONTEXT_CARD_TYPES = {1: "lens", 2: "sound", 3: "creator", 4: "place"}
CATEGORY_PREFIXES = ("public-profile-category-v3-", "public-profile-subcategory-v3-")
WEEKDAYS = {1: "monday", 2: "tuesday", 3: "wednesday", 4: "thursday", 5: "friday", 6: "saturday", 7: "sunday"}
PLACE_PROVIDERS = {3: "yelp", 4: "foursquare", 5: "tripadvisor", 6: "google"}
COUNT_CEILING = 10 ** 11        # a "count" above this is a leaked timestamp
PLACEHOLDER_TEXT = {"spotlight snap", "another spotlight snap brought to you by snapchat"}
NEVER_EXPIRES_AFTER = 4102444800   # 2100-01-01: the site's "100 years" expiry sentinel
_HASHTAG_RE = re.compile(r"#([^\s#]+)")


# ---- scalars ---------------------------------------------------------------------------

def clean(value):
    """Whitespace-trimmed string, or None for empty / non-strings."""
    if value is None or isinstance(value, (dict, list, bool)):
        return None
    text = str(value).strip()
    return text or None


def val(value):
    """Unwrap the page props' `{"value": x}` wrappers (protobuf optionals)."""
    if isinstance(value, dict) and set(value.keys()) <= {"value"}:
        return value.get("value")
    return value


def to_int(value):
    value = val(value)
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    text = str(value).strip().replace(",", "")
    try:
        return int(text)
    except ValueError:
        try:
            return int(float(text))
        except ValueError:
            return None


def to_float(value):
    value = val(value)
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def to_count(value):
    """A counter: ints >= 0, with the upstream's -1 / "0" for unknown as null
    where it means unknown (callers decide) and leaked timestamps dropped."""
    number = to_int(value)
    if number is None or number < 0 or number > COUNT_CEILING:
        return None
    return number


def to_bool(value):
    value = val(value)
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    return None


def link_or_none(value):
    text = clean(val(value))
    if not text:
        return None
    if text.startswith("//"):
        return "https:" + text
    if text.startswith(("http://", "https://")):
        return text
    if text.startswith("snapchat://"):
        return text
    if "." in text and " " not in text:
        return "https://" + text
    return text


def iso_utc(epoch_seconds):
    seconds = to_int(epoch_seconds)
    if not seconds:
        return None
    try:
        return datetime.fromtimestamp(seconds, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (OverflowError, OSError, ValueError):
        return None


def iso_ms(epoch_ms):
    ms = to_int(epoch_ms)
    if not ms:
        return None
    return iso_utc(ms // 1000)


def humanize_category(string_id):
    text = clean(string_id)
    if not text:
        return None
    for prefix in CATEGORY_PREFIXES:
        if text.startswith(prefix):
            text = text[len(prefix):]
    return text.replace("-", " ").strip().title() or None


def strip_hash(tag):
    text = clean(tag)
    return text.lstrip("#") if text else None


def caption_text(value):
    """A caption / description with the site's placeholder copy nulled."""
    text = clean(value)
    if text and text.lower() in PLACEHOLDER_TEXT:
        return None
    return text


def hashtags_in(text):
    return [m for m in _HASHTAG_RE.findall(text or "") if m]


def iso_expiry(epoch_ms):
    ms = to_int(epoch_ms)
    if not ms or ms // 1000 >= NEVER_EXPIRES_AFTER:
        return None
    return iso_ms(ms)


def hashtags_from(values):
    out = []
    for item in values or []:
        title = item.get("title") if isinstance(item, dict) else item
        tag = strip_hash(title)
        if tag and tag not in out:
            out.append(tag)
    return out


def _dedupe(items, key="id"):
    seen, out = set(), []
    for item in items:
        marker = item.get(key) if isinstance(item, dict) else item
        if marker in seen:
            continue
        seen.add(marker)
        out.append(item)
    return out


# ---- users --------------------------------------------------------------------------

def bitmoji(raw):
    raw = raw or {}
    if not isinstance(raw, dict) or not raw:
        return None
    avatar = raw.get("avatarImage") or {}
    background = raw.get("backgroundImage") or {}
    out = {
        "avatar_image": link_or_none(avatar.get("url")),
        "avatar_fallback_image": link_or_none(avatar.get("fallbackUrl")),
        "background_image": link_or_none(background.get("url")),
    }
    return out if any(out.values()) else None


def snapcode_links(username):
    if not username:
        return None
    from .fetch import snapcode_link
    return {"svg": snapcode_link(username, "SVG"), "png": snapcode_link(username, "PNG"),
            "svg_without_bitmoji": snapcode_link(username, "SVG", bitmoji=False)}


def related_account(raw):
    raw = raw or {}
    info = raw.get("publicProfileInfo") or {}
    return {
        "display_name": clean(info.get("title")),
        "username": clean(info.get("username")),
        "link": refs.user_link(clean(info.get("username"))),
        "subscribe_link": link_or_none(raw.get("subscribeLink")),
        "profile_picture": link_or_none(info.get("profilePictureUrl")),
        "business_profile_id": clean(info.get("businessProfileId")),
        "is_verified": bool(to_int(info.get("badge"))),
    }


def public_profile(info, page=None, username=None, link=None, kind="public_profile"):
    """publicProfileInfo (creator / brand / publisher profile) -> profile."""
    info = info or {}
    page = page or {}
    username = clean(info.get("username")) or username
    lenses = page.get("lenses") or []
    # the page pads these lists with empty placeholder slots (no snaps)
    highlights = [h for h in page.get("curatedHighlights") or [] if isinstance(h, dict) and h.get("snapList")]
    spotlights = [h for h in page.get("spotlightHighlights") or [] if isinstance(h, dict) and h.get("snapList")]
    story = page.get("story") or {}
    badge = to_int(info.get("badge")) or 0
    return {
        "username": username,
        "display_name": clean(info.get("title")),
        "link": link or refs.user_link(username),
        "type": kind,
        "bio": clean(info.get("bio")),
        "website": link_or_none(info.get("websiteUrl")),
        "address": clean(info.get("address")),
        "category": humanize_category(info.get("categoryStringId")),
        "subcategory": humanize_category(info.get("subcategoryStringId")),
        "subscriber_count": to_count(info.get("subscriberCount")),
        "is_verified": badge > 0,
        "badge": badge,
        "profile_picture": link_or_none(info.get("profilePictureUrl")),
        "hero_image": link_or_none(info.get("squareHeroImageUrl")),
        "snapcode_image": link_or_none(info.get("snapcodeImageUrl")),
        "snapcode_links": snapcode_links(username),
        "primary_color": clean(info.get("primaryColor")),
        "publisher_type": clean(info.get("publisherType")),
        "mutable_username": clean(info.get("mutableName")),
        "user_id": clean(info.get("hostUserId")),
        "business_profile_id": clean(info.get("businessProfileId")),
        "bitmoji": bitmoji(info.get("bitmoji3d")),
        "has_story": bool(story.get("snapList")) if page else to_bool(info.get("hasStory")),
        "has_curated_highlights": to_bool(info.get("hasCuratedHighlights")),
        "has_spotlight_highlights": to_bool(info.get("hasSpotlightHighlights")),
        "is_username_hidden": to_bool(info.get("shouldHideUsername")),
        "related_accounts": [related_account(r) for r in info.get("relatedAccountsInfo") or [] if isinstance(r, dict)],
        "same_as_links": [link_or_none(x) for x in info.get("sameAsLinks") or [] if clean(x)],
        "created_at": iso_ms(info.get("creationTimestampMs")),
        "updated_at": iso_ms(info.get("lastUpdateTimestampMs")),
        "counts": {
            "story_snaps": len(story.get("snapList") or []) if page else None,
            "curated_highlights": len(highlights) if page else None,
            "spotlights": len(spotlights) if page else None,
            "lenses": len(lenses) if page else None,
        } if page else None,
    }


def plain_user(info, username=None):
    """userInfo (an account without a public profile) -> profile with the
    creator-only fields null."""
    info = info or {}
    username = clean(info.get("username")) or username
    out = public_profile({}, page=None, username=username, kind="user")
    out["display_name"] = clean(info.get("displayName"))
    out["snapcode_image"] = link_or_none(info.get("snapcodeImageUrl"))
    out["bitmoji"] = bitmoji(info.get("bitmoji3d"))
    out["is_verified"] = False
    out["badge"] = 0
    return out


def profile(page, username=None):
    """The profile page's pageProps -> profile (either shape)."""
    wrapper = page.get("userProfile") or {}
    case = wrapper.get("$case")
    if case == "publicProfileInfo" or wrapper.get("publicProfileInfo"):
        return public_profile(wrapper.get("publicProfileInfo"), page=page, username=username)
    if case == "userInfo" or wrapper.get("userInfo"):
        return plain_user(wrapper.get("userInfo"), username=username)
    return None


def creator_ref(username=None, display_name=None, follower_count=None, website=None, link=None, **extra):
    out = {
        "username": clean(username),
        "display_name": clean(display_name),
        "link": link or refs.user_link(clean(username)),
        "follower_count": to_count(follower_count) or None,
        "website": link_or_none(website),
    }
    out.update(extra)
    return out


# ---- stories & snaps -----------------------------------------------------------------

def snap(raw):
    raw = raw or {}
    urls = raw.get("snapUrls") or {}
    lat, lng = to_float(raw.get("lat")), to_float(raw.get("lng"))
    media_type = raw.get("snapMediaType")
    return {
        "id": clean(val(raw.get("snapId"))) or clean(raw.get("id")),
        "index": to_int(raw.get("snapIndex")) if raw.get("snapIndex") is not None else to_int(raw.get("index")),
        "media_type": SNAP_MEDIA_TYPES.get(media_type, clean(media_type).lower() if clean(media_type) else None),
        "media": link_or_none(urls.get("mediaUrl")),
        "preview_image": link_or_none(urls.get("mediaPreviewUrl")),
        "overlay": link_or_none(urls.get("overlayUrl")),
        "attachment": link_or_none(urls.get("attachmentUrl")),
        "title": clean(val(raw.get("snapTitle"))),
        "subtitles": clean(val(raw.get("snapSubtitles"))),
        "transcript_link": link_or_none(raw.get("audioTranscriptionObjectUrl")),
        "posted_at": iso_utc(raw.get("timestampInSec")),
        "interval_start_ms": to_int(raw.get("intervalStartTimeMs")),
        "location": {"latitude": lat, "longitude": lng} if lat is not None and lng is not None else None,
        "is_sponsored": to_bool(raw.get("isSponsored")),
    }


def story(raw):
    raw = raw or {}
    story_type = to_int(raw.get("storyType"))
    snaps = [snap(s) for s in raw.get("snapList") or [] if isinstance(s, dict)]
    tap_id = clean(raw.get("storyTapId"))
    return {
        "id": clean(val(raw.get("highlightId"))) or clean(val(raw.get("storyId"))),
        "type": STORY_TYPES.get(story_type, story_type),
        "title": clean(val(raw.get("storyTitle"))),
        "subtitle": clean(val(raw.get("storySubtitle"))),
        "thumbnail": link_or_none(raw.get("thumbnailUrl")),
        "emoji": clean(val(raw.get("emoji"))),
        "share_id": clean(val(raw.get("storyShareId"))),
        "tap_id": tap_id if tap_id and tap_id != "0" else None,
        "video_track": link_or_none(raw.get("videoTrackUrl")),
        "is_attributed": to_bool(raw.get("isAttributed")),
        "thumbnail_tiles": [link_or_none(t.get("url")) for t in raw.get("thumbnailTiles") or []
                            if isinstance(t, dict) and link_or_none(t.get("url"))],
        "snap_count": len(snaps),
        "snaps": snaps,
    }


# ---- spotlight metadata -----------------------------------------------------------------

def context_card(raw):
    raw = raw or {}
    kind = to_int(raw.get("contextType"))
    return {
        "type": CONTEXT_CARD_TYPES.get(kind, kind),
        "id": clean(raw.get("id")),
        "title": clean(raw.get("title")),
        "subtitle": clean(raw.get("subtitle")),
        "link": link_or_none(raw.get("url")),
        "thumbnail": link_or_none(raw.get("thumbnailUrl")),
        "snapcode_image": link_or_none(raw.get("snapcodeUrl")),
        "has_badge": to_bool(raw.get("hasBadge")),
    }


def _sound_from_cards(cards):
    for card in cards:
        if card.get("type") == "sound":
            subtitle = card.get("subtitle") or ""
            contains = subtitle.startswith("Contains:")
            return {
                "id": card.get("id"),
                "title": card.get("title"),
                "artist": None if contains else (subtitle or None),
                "contains": subtitle[len("Contains:"):].strip() if contains else None,
                "is_original_sound": (card.get("title") or "").lower() == "original sound",
                "thumbnail": card.get("thumbnail"),
            }
    return None


def _lens_from_cards(cards):
    for card in cards:
        if card.get("type") == "lens":
            return {"id": card.get("id"), "name": card.get("title"), "link": card.get("link"),
                    "icon": card.get("thumbnail")}
    return None


def _place_from_cards(cards):
    for card in cards:
        if card.get("type") == "place":
            return {"id": card.get("id"), "name": card.get("title"), "locality": card.get("subtitle"),
                    "link": card.get("link"), "thumbnail": card.get("thumbnail")}
    return None


def cu_signals(signals):
    """The `cuSignals` list -> {description, keywords, languages, llm_keywords}."""
    out = {"description": None, "keywords": [], "languages": [], "s2i_tags": [], "llm_keywords": []}
    for item in signals or []:
        signal = (item or {}).get("signal") or {}
        case = signal.get("$case")
        body = signal.get(case) or {}
        if case == "textMetadata":
            out["description"] = out["description"] or clean(body.get("description"))
            for kw in body.get("keywords") or []:
                if clean(kw) and clean(kw) not in out["keywords"]:
                    out["keywords"].append(clean(kw))
        elif case == "detectedLanguage":
            for score in body.get("languageScores") or []:
                code = clean(score.get("languageCode"))
                if code and code != "unk":
                    out["languages"].append({"code": code, "score": round(to_float(score.get("score")) or 0, 4)})
        elif case == "s2iTags":
            for tag in body.get("tags") or body.get("s2iTags") or []:
                if clean(tag) and clean(tag) not in out["s2i_tags"]:
                    out["s2i_tags"].append(clean(tag))
        elif case == "llmPrediction":
            result = ((body.get("llmPromptResult") or {}).get("promptResult") or {}).get("keywords") or {}
            text = ((result.get("result") or {}).get("stringValue")) if isinstance(result, dict) else None
            if text:
                import json
                try:
                    for entry in json.loads(text):
                        word, _, score = str(entry).rpartition("|")
                        if word:
                            out["llm_keywords"].append({"keyword": word, "score": to_float(score)})
                except ValueError:
                    pass
    best = {}
    for entry in out["languages"]:
        if entry["code"] not in best or (entry["score"] or 0) > (best[entry["code"]]["score"] or 0):
            best[entry["code"]] = entry
    out["languages"] = sorted(best.values(), key=lambda x: -(x["score"] or 0))
    return out


def ai_metadata(meta):
    meta = meta or {}
    signals = cu_signals(meta.get("cuSignals"))
    return {
        "title": clean(meta.get("llmTitle")),
        "description": clean(meta.get("llmDescription")) or signals["description"],
        "keywords": [clean(k) for k in meta.get("llmKeywords") or [] if clean(k)],
        "text_keywords": [clean(k) for k in meta.get("textMetadataKeywords") or [] if clean(k)] or signals["keywords"],
        "seo_keywords": signals["llm_keywords"],
        "entity_tags": [clean(k) for k in meta.get("s2iTags") or [] if clean(k)] or signals["s2i_tags"],
        "language": signals["languages"][0]["code"] if signals["languages"] else None,
        "languages": signals["languages"],
        "model": clean(meta.get("llmModel")),
    }


def engagement(stats):
    stats = stats or {}
    return {
        "view_count": to_count(stats.get("viewCount")),
        "share_count": to_count(stats.get("shareCount")),
        "comment_count": to_count(stats.get("commentCount")),
        "boost_count": to_count(stats.get("boostCount")),
        "recommend_count": to_count(stats.get("recommendCount")),
    }


def spotlight(story_raw, meta, comments=None, transcript=None):
    """A spotlight = the story (its single snap) + its metadata, from a page
    (spotlightStories[i] / spotlightHighlights[i] + spotlightStoryMetadata[i])
    or the GraphQL feed entry ({story, metadata})."""
    story_raw = story_raw or {}
    meta = meta or {}
    video = meta.get("videoMetadata") or {}
    creator_raw = video.get("creator") or {}
    person = creator_raw.get("personCreator") or creator_raw if isinstance(creator_raw, dict) else {}
    snaps = story_raw.get("snapList") or story_raw.get("snaps") or []
    first = snaps[0] if snaps and isinstance(snaps[0], dict) else {}
    urls = first.get("snapUrls") or {}
    snap_id = clean(val(story_raw.get("storyId"))) or clean(story_raw.get("id")) or clean(val(first.get("snapId"))) or clean(first.get("id"))
    username = clean(person.get("username"))
    if not username:
        person_url = clean(person.get("url")) or ""
        match = re.search(r"/@([^/?#]+)", person_url)
        username = match.group(1).lower() if match else None
    cards = [context_card(c) for c in meta.get("contextCards") or [] if isinstance(c, dict)]
    stats = engagement(meta.get("engagementStats"))
    if stats["view_count"] is None:
        stats["view_count"] = to_count(video.get("viewCount"))
    if stats["share_count"] is None:
        stats["share_count"] = to_count(video.get("shareCount"))
    tap_id = clean(story_raw.get("tapId")) or clean(story_raw.get("storyTapId"))
    caption = caption_text(meta.get("description")) or caption_text(video.get("description"))
    return {
        "id": snap_id,
        "link": refs.spotlight_link(username, snap_id),
        "caption": caption,
        "hashtags": hashtags_from(meta.get("hashtags")) or hashtags_in(caption),
        "thumbnail": link_or_none(video.get("thumbnailUrl")) or link_or_none(story_raw.get("thumbnailUrl")),
        "video": link_or_none(video.get("contentUrl")) or link_or_none(urls.get("mediaUrl")),
        "preview_image": link_or_none(urls.get("mediaPreviewUrl")),
        "transcript_link": link_or_none(first.get("audioTranscriptionObjectUrl")),
        "posted_at": iso_ms(video.get("uploadDateMs")) or iso_utc(first.get("timestampInSec")),
        "duration_ms": to_int(video.get("durationMs")) or None,
        "width": to_int(video.get("width")) or None,
        "height": to_int(video.get("height")) or None,
        "embedded_text": clean(video.get("embeddedTextCaption")),
        "tap_id": tap_id if tap_id and tap_id != "0" else None,
        "is_attributed": to_bool(story_raw.get("isAttributed")),
        "creator": creator_ref(username, person.get("name"), person.get("followerCount"), person.get("websiteUrl")),
        "stats": stats,
        "sound": _sound_from_cards(cards),
        "lens": _lens_from_cards(cards),
        "place": _place_from_cards(cards),
        "context_cards": cards,
        "ai": ai_metadata(meta),
        "transcript": transcript,
        "comments": comments,
    }


def transcript_entry(raw):
    raw = raw or {}
    text = clean(raw.get("text"))
    cues = []
    if text:
        for block in re.split(r"\n\s*\n", text.replace("\r", "")):
            lines = [l for l in block.split("\n") if l.strip()]
            if not lines or lines[0].startswith("WEBVTT"):
                continue
            if "-->" in lines[0]:
                start, _, end = lines[0].partition("-->")
                cues.append({"start": start.strip(), "end": end.strip(), "text": " ".join(l.strip() for l in lines[1:])})
    return {"link": link_or_none(raw.get("url")), "cues": cues,
            "text": " ".join(c["text"] for c in cues) or None}


# ---- comments ----------------------------------------------------------------------------

def _pair(raw):
    if isinstance(raw, dict) and raw.get("highBits") is not None and raw.get("lowBits") is not None:
        return f"{raw['highBits']}-{raw['lowBits']}"
    return None


def comment(raw):
    """A reply as the pages encode it (encodedComments JSON) -> comment."""
    raw = raw or {}
    profile_case = raw.get("replyPosterProfile") or {}
    business_id = _pair(profile_case.get("businessProfileId")) if isinstance(profile_case, dict) else None
    return {
        "id": _pair(raw.get("replyId")),
        "text": clean(raw.get("replyText")),
        "posted_at": iso_ms(raw.get("replyTimestampMs")),
        "updated_at": iso_ms(raw.get("lastStateUpdateTsMs")),
        "author": {
            "display_name": clean(raw.get("replyPosterDisplayName")),
            "username": clean(raw.get("replyPosterMutableUsername")),
            "link": refs.user_link(clean(raw.get("replyPosterMutableUsername"))),
            "profile_picture": link_or_none(raw.get("replyPosterProfileLogoUrl")),
            "user_id": _pair(raw.get("replyPosterId")),
            "profile_id": _pair(raw.get("replyPosterProfileId")),
            "business_profile_id": business_id,
            "bitmoji_avatar_id": clean(raw.get("replyPosterBitmojiAvatarId")),
        },
        "reply_count": to_count(raw.get("threadedReplyCount")) or 0,
        "report_count": to_count(raw.get("reportCount")) or 0,
        "ranking_score": to_int(raw.get("rankingScore")),
        "is_approved": to_int(raw.get("approvalState")) == 3,
        "snap_id": clean(raw.get("snapId")),
    }


def comment_from_proto(fields):
    """A decoded Reply message (proto.decode) -> comment. Field numbers as
    observed on 2026-09-22 against the JSON twin of the same replies."""
    profile = proto.message(fields, 27)
    business = proto.uuid_pair(profile) if profile else None
    return comment({
        "replyId": _pair_dict(proto.uuid_pair(proto.message(fields, 1))),
        "snapPosterId": None,
        "snapId": proto.text(fields, 3),
        "replyText": proto.text(fields, 4),
        "reportCount": proto.first(fields, 5),
        "replyPosterId": _pair_dict(proto.uuid_pair(proto.message(fields, 7))),
        "approvalState": proto.first(fields, 8),
        "replyTimestampMs": proto.first(fields, 11),
        "replyPosterDisplayName": proto.text(fields, 12),
        "replyPosterBitmojiAvatarId": proto.text(fields, 13),
        "lastStateUpdateTsMs": proto.first(fields, 15),
        "replyPosterProfileId": _pair_dict(proto.uuid_pair(proto.message(fields, 20))),
        "threadedReplyCount": proto.first(fields, 22),
        "replyPosterProfileLogoUrl": proto.text(fields, 26),
        "replyPosterProfile": {"businessProfileId": _pair_dict(business)} if business else None,
        "replyPosterMutableUsername": proto.text(fields, 31),
        "rankingScore": proto.first(fields, 33),
    })


def _pair_dict(pair):
    if not pair:
        return None
    high, _, low = pair.partition("-")
    return {"highBits": high, "lowBits": low}


def comments_from_json(encoded):
    """The page's encodedComments / encodedSpotlightComments string -> a
    list (per spotlight, for the profile's list-of-lists) of comments."""
    import json
    if not encoded:
        return []
    try:
        data = json.loads(encoded) if isinstance(encoded, str) else encoded
    except ValueError:
        return []
    if not isinstance(data, list):
        return []
    if data and isinstance(data[0], list):
        return [[comment(c) for c in group if isinstance(c, dict)] for group in data]
    return [comment(c) for c in data if isinstance(c, dict)]


# ---- internal story cards -------------------------------------------------------------

def card_creator(snap_raw, story_meta=None, attribution=None):
    info = (snap_raw or {}).get("creatorInfo") or {}
    story_meta = story_meta or {}
    attribution = attribution or {}
    username = clean(info.get("userName")) or clean(attribution.get("username"))
    logo = link_or_none((story_meta.get("businessLogoUrl"))) or link_or_none(
        ((attribution.get("snapProIdentity") or {}).get("logo") or {}).get("logoUrl"))
    return creator_ref(
        username,
        info.get("displayName") or attribution.get("displayName") or story_meta.get("displayName"),
        info.get("followerCount"),
        None,
        user_id=clean(info.get("userId")) or clean(attribution.get("id")),
        business_profile_id=clean(story_meta.get("businessProfileId")) or clean(attribution.get("businessProfileId")),
        profile_picture=logo,
        snap_pro_tier=to_int(info.get("snapproTier")),
        is_official=to_bool(attribution.get("isOfficial")),
    )


def card_stats(stats):
    stats = stats or {}
    comment_count = to_count(stats.get("liveCommentCount"))
    if comment_count is None:
        comment_count = to_count(stats.get("spotlightLiveReplyCount"))
    return {
        "view_count": to_count(stats.get("viewCount")),
        "share_count": to_count(stats.get("shareCount")),
        "comment_count": comment_count,
        "boost_count": to_count(stats.get("boostCount")),
        "recommend_count": to_count(stats.get("recommendCount")),
        "subscription_count": to_count(stats.get("subCount")),
    }


def story_card(card, context=None, cu=None):
    """An internal single-snap story card (tag / entertainment pages'
    `card.singleSnapStoryCard`, fetchSpotlight's `storyCard.card.…`, the
    search page's spotlightCardMap entry — all the same object) -> card."""
    card = card or {}
    inner = card.get("singleSnapStoryCard") or (card.get("card") or {}).get("singleSnapStoryCard") or card
    snaps = inner.get("snaps") or []
    snap_raw = snaps[0] if snaps and isinstance(snaps[0], dict) else {}
    media = snap_raw.get("mediaInfo") or {}
    dims = media.get("boltWatermarkedVideoDimensions") or {}
    thumb = inner.get("storyThumbnail") or {}
    story_meta = inner.get("singleSnapStoryMetadata") or {}
    pivot = ((snap_raw.get("pivotInfo") or {}).get("contextHint") or {}).get("contextClientInfo") or {}
    context = context or {}
    attribution = ((context.get("attributionInfo") or {}).get("info") or {}).get("user") or {}
    ai_info = snap_raw.get("aiGeneratedInfo") or {}
    creator = card_creator(snap_raw, story_meta, attribution)
    snap_id = clean(snap_raw.get("rawSnapId")) or clean(snap_raw.get("externalId"))
    caption = caption_text((snap_raw.get("snapDescription") or {}).get("text")) or caption_text(snap_raw.get("caption"))
    hashtags = hashtags_from(pivot.get("hashtags")) or hashtags_from(context.get("hashtags")) or hashtags_in(caption)
    ai = ai_metadata({**story_meta, **{k: v for k, v in (cu or {}).items() if v}})
    tiles = [link_or_none(t.get("unencryptedUrl")) for t in thumb.get("thumbnailTiles") or []
             if isinstance(t, dict) and link_or_none(t.get("unencryptedUrl"))]
    return {
        "id": snap_id,
        "link": refs.spotlight_link(creator.get("username"), snap_id),
        "caption": caption,
        "hashtags": hashtags,
        "posted_at": iso_ms(snap_raw.get("creationTimestampMs")),
        "captured_at": iso_ms(snap_raw.get("sourceCreationTimestamp")),
        "expires_at": iso_expiry(snap_raw.get("expirationTimestampMs")),
        "media_type": SNAP_MEDIA_TYPES.get(to_int(media.get("mediaType"))),
        "video": link_or_none(media.get("boltWatermarkedVideoUrl")) or link_or_none(media.get("unencryptedFlatVideoUrl")),
        "video_without_watermark": link_or_none(media.get("unencryptedFlatVideoUrl")),
        "image": link_or_none(media.get("unencryptedImageUrl")),
        "duration_seconds": to_float(media.get("duration")),
        "width": to_int(dims.get("width")),
        "height": to_int(dims.get("height")),
        "thumbnail": tiles[0] if tiles else (link_or_none(thumb.get("thumbnailUrl")) if not thumb.get("thumbnailIv") else None),
        "creator": creator,
        "lens_id": clean(snap_raw.get("lensId")),
        "topic_id": clean(story_meta.get("topicId")),
        "title": clean(snap_raw.get("title")),
        "location_text": clean(snap_raw.get("displayGeoInfo")),
        "stats": card_stats(inner.get("engagementStats") or card.get("engagementStats")),
        "ai": ai,
        "is_top_creator": to_bool(inner.get("topCreatorBadge")),
        "are_replies_enabled": to_bool(inner.get("repliesEnabled")),
        "is_sharing_disabled": to_bool(inner.get("isSharingDisabled")),
        "is_creator_monetizable": to_bool(inner.get("isCreatorMonetizable")),
        "is_ai_flagged": to_bool(ai_info.get("isAiFlagged")),
        "is_ai_disclosed": to_bool(ai_info.get("isAiDisclosedByCreator")),
        "is_original_sound": to_bool(story_meta.get("isOriginalSoundSnap")),
    }


def hydrated_spotlight(entry):
    """One fetchSpotlight `spotlights[]` entry ({storyCard, context, cuSignals})."""
    entry = entry or {}
    return story_card(entry.get("storyCard") or {}, context=entry.get("context"), cu=entry.get("cuSignals"))


# ---- lenses --------------------------------------------------------------------------

def lens(raw):
    raw = raw or {}
    uuid = clean(raw.get("scannableUuid"))
    lens_id = clean(raw.get("lensId"))
    unlock = link_or_none(raw.get("unlockUrl"))
    if not uuid and unlock:
        match = re.search(r"uuid=([0-9a-fA-F]{32})", unlock)
        uuid = match.group(1).lower() if match else None
    ref = uuid or lens_id
    creator_username = clean(raw.get("lensCreatorUsername"))
    return {
        "id": lens_id,
        "uuid": uuid,
        "name": clean(raw.get("lensName")),
        "link": refs.lens_link(ref),
        "unlock_link": unlock or refs.unlock_link(uuid),
        "icon": link_or_none(raw.get("iconUrl")),
        "preview_image": link_or_none(raw.get("lensPreviewImageUrl")),
        "preview_video": link_or_none(raw.get("lensPreviewVideoUrl")),
        "snapcode_image": link_or_none(raw.get("scannableImageUrl")),
        "creator": {
            "display_name": clean(raw.get("lensCreatorDisplayName")),
            "username": creator_username,
            "link": refs.user_link(creator_username) or link_or_none(raw.get("userProfileUrl")),
        },
        "tags": [clean(t) for t in raw.get("lensCreatorSearchTags") or [] if clean(t)],
        "is_official": to_bool(raw.get("isOfficialSnapLens")),
        "updated_at": iso_utc(raw.get("lastUpdatedEpoch")),
    }


def search_lens(raw):
    """A lens as the search page lists it."""
    raw = raw or {}
    deeplink = link_or_none(raw.get("deeplinkUrl"))
    match = re.search(r"uuid=([0-9a-fA-F]{32})", deeplink or "")
    uuid = match.group(1).lower() if match else None
    lens_id = clean(raw.get("lensId"))
    seq = raw.get("thumbnailSequence") or {}
    pattern, count = clean(seq.get("urlPattern")), to_int(seq.get("numThumbnails")) or 0
    return {
        "id": lens_id,
        "uuid": uuid,
        "name": clean(raw.get("name")),
        "link": refs.lens_link(uuid or lens_id),
        "unlock_link": deeplink,
        "icon": link_or_none(raw.get("iconUrl")),
        "preview_image": link_or_none(raw.get("thumbnailUrl")),
        "preview_frames": [pattern.replace("%d", str(i)) for i in range(count)] if pattern and "%d" in pattern else [],
        "creator": {
            "display_name": clean(raw.get("creatorName")),
            "user_id": clean(raw.get("creatorUserId")),
            "is_official": to_bool(raw.get("creatorIsOffical")),
        },
        "is_exclusive": to_bool(raw.get("scpExclusive")),
    }


def lens_creator(raw):
    raw = raw or {}
    username = clean(raw.get("username"))
    return {
        "id": clean(raw.get("id")),
        "name": clean(raw.get("name")),
        "username": username,
        "link": refs.user_link(username),
        "profile_picture": link_or_none(raw.get("profilePicUrl")),
        "is_official": to_bool(raw.get("isOfficialCreator")),
        "has_story": to_bool(raw.get("hasStory")),
        "lens_previews": [{"icon": link_or_none(p.get("iconUrl")), "thumbnail": link_or_none(p.get("thumbnailMediaUrl"))}
                          for p in raw.get("lensPreviewInfos") or [] if isinstance(p, dict)],
    }


def lens_spotlight(item, meta):
    """spotlightsUsingThisLens[i] + spotlightsUsingThisLensMetadata[i]."""
    item, meta = item or {}, meta or {}
    link = link_or_none(item.get("storyPageUrl")) or link_or_none(meta.get("contentUrl"))
    match = re.search(r"/@([^/]+)/spotlight/([A-Za-z0-9_-]+)", link or "")
    return {
        "id": match.group(2) if match else None,
        "link": link,
        "creator": creator_ref(match.group(1) if match else None),
        "caption": caption_text(meta.get("embeddedTextCaption")) or caption_text(meta.get("description")),
        "thumbnail": link_or_none(item.get("thumbnailUrl")) or link_or_none(meta.get("thumbnailUrl")),
        "posted_at": iso_ms(meta.get("uploadDateMs")),
        "duration_seconds": to_float(meta.get("durationMs")),
        "width": to_int(meta.get("width")),
        "height": to_int(meta.get("height")),
        "keywords": [clean(k) for k in meta.get("keywords") or [] if clean(k)],
        "view_count": to_count(meta.get("viewCount")),
        "share_count": to_count(meta.get("shareCount")),
    }


# ---- search --------------------------------------------------------------------------

def business_profile(raw):
    """A snapProEntity.profile.businessProfile (search "Subscribe" results)."""
    raw = raw or {}
    logo = raw.get("businessLogo") or {}
    username = clean(raw.get("hostAccountUsername")) or clean(raw.get("hostAccountMutableUsername"))
    return {
        "username": username,
        "display_name": clean(raw.get("title")),
        "link": refs.user_link(username),
        "bio": clean(raw.get("description")),
        "subscriber_count": to_count(raw.get("subscriberCount")),
        "is_official": to_bool(raw.get("isOfficialAccount")),
        "is_brand": to_bool(raw.get("isBrandProfile")),
        "is_partner": to_bool(raw.get("isPartnerProfile")),
        "tier": to_int(raw.get("tier")),
        "profile_picture": link_or_none(logo.get("originalLogoUrl")) or link_or_none(logo.get("manageProfileLogoUrl")),
        "hero_image": link_or_none(raw.get("originalHeroImageUrl")) or link_or_none(raw.get("heroImageUrl")),
        "website": link_or_none(raw.get("websiteUrl")),
        "address": clean(raw.get("displayAddress")) or clean(raw.get("address")),
        "phone": clean(raw.get("phoneNumber")),
        "email": clean(raw.get("emailAddress")),
        "whatsapp": clean(raw.get("whatsappNumber")),
        "category": clean(raw.get("category")),
        "subcategory": clean(raw.get("subcategory")),
        "has_lenses": to_bool(raw.get("hasLenses")),
        "is_lens_creator": to_bool(raw.get("isLensCreator")),
        "has_highlights": to_bool(raw.get("hasHighlights")),
        "is_snapchat_plus_subscriber": to_bool(raw.get("isSnapchatPlusSubscriber")),
        "verified_emoji": clean(raw.get("hostAccountVerifiedEmoji")),
        "bitmoji_avatar_id": clean(raw.get("bitmojiAvatarId")),
        "user_id": clean(raw.get("hostAccountUserId")),
        "business_profile_id": clean(raw.get("id")),
        "created_at": iso_ms(raw.get("createdTimestamp")),
    }


def search_topic(raw):
    raw = raw or {}
    name = clean(raw.get("text"))
    return {
        "name": name,
        "link": refs.tag_link(name.replace(" ", "").lower()) if name else None,
        "snap_count": to_count(raw.get("numSnaps")),
        "thumbnail": link_or_none(raw.get("thumbnail")),
        "icon": link_or_none(raw.get("iconUrl")),
    }


def _geo(point):
    point = point or {}
    lat, lng = to_float(point.get("lat")), to_float(point.get("lng"))
    return {"latitude": lat, "longitude": lng} if lat is not None and lng is not None else None


def _bbox(box):
    box = box or {}
    p1, p2 = _geo(box.get("p1")), _geo(box.get("p2"))
    return {"south_west": p1, "north_east": p2} if p1 and p2 else None


def search_place(raw):
    raw = raw or {}
    name = clean(raw.get("displayName"))
    place_id = clean(raw.get("id"))
    photo = raw.get("profilePhoto") or {}
    stats = raw.get("placeStats") or {}
    return {
        "id": place_id,
        "name": name,
        "link": refs.place_link(name, place_id),
        "locality": clean(raw.get("locality")),
        "category": clean(raw.get("categoryName")),
        "category_icon": link_or_none(raw.get("categoryIconUrl")),
        "image": link_or_none(photo.get("imageUrl")) if to_int(photo.get("imageType")) != 1 else None,
        "location": _geo(raw.get("centroid")),
        "bounding_box": _bbox((raw.get("mapOpenParams") or {}).get("boundingBox")),
        "favorite_count": to_count(stats.get("favoriteCount")),
    }


def search_publisher(raw):
    raw = raw or {}
    bp = clean(raw.get("businessProfileId"))
    return {
        "id": clean(raw.get("id")),
        "business_profile_id": bp,
        "name": clean(raw.get("displayName")),
        "description": clean(raw.get("description")),
        "link": refs.publisher_link(bp),
        "icon": link_or_none(raw.get("iconUrl")),
        "primary_color": clean(raw.get("primaryColor")),
        "is_show": to_bool(raw.get("isShow")),
        "show_id": clean(raw.get("showId")),
        "latest_episode_id": clean(raw.get("latestEditionId")) if clean(raw.get("latestEditionId")) not in (None, "0") else None,
        "subscriber_count": to_count(raw.get("approxSubscriptionCount")) or None,
    }


def search_episode(raw):
    raw = raw or {}
    publisher = search_publisher(raw.get("publisher")) if raw.get("publisher") else None
    bp = publisher.get("business_profile_id") if publisher else None
    return {
        "id": clean(raw.get("id")),
        "title": clean(raw.get("title")),
        "link": refs.episode_link(bp, clean(raw.get("id"))),
        "thumbnail": link_or_none(raw.get("thumbnailUrl")),
        "published_at": iso_ms(raw.get("publishEpoch")),
        "publisher": publisher,
    }


def search_story_card(raw, card_map):
    """A search "Spotlight" tile, hydrated from spotlightCardMap when the
    page shipped the card."""
    raw = raw or {}
    snap_id = clean(raw.get("rawSnapId"))
    hydrated = (card_map or {}).get(snap_id) if snap_id else None
    if isinstance(hydrated, dict):
        out = story_card(hydrated)
        if not out.get("video"):
            out["video"] = link_or_none(raw.get("mediaUrl"))
        return out
    username = clean(raw.get("creatorUsername"))
    return {
        "id": snap_id,
        "link": refs.spotlight_link(username, snap_id),
        "caption": clean(raw.get("teaserText")),
        "video": link_or_none(raw.get("mediaUrl")),
        "creator": creator_ref(username, raw.get("creatorDisplayName") or raw.get("creatorName")),
        "play_count_text": clean(raw.get("playCount")),
    }


SECTION_TYPES = {47: "spotlights", 6: "lenses", 23: "topics", 3: "users", 16: "places", 21: "shows", 22: "episodes"}
SECTION_PARSERS = {
    "spotlights": ("storyCard", None),
    "lenses": ("lens", search_lens),
    "topics": ("topic", search_topic),
    "users": ("snapProEntity", lambda r: business_profile(((r or {}).get("profile") or {}).get("businessProfile"))),
    "places": ("place", search_place),
    "shows": ("publisher", search_publisher),
    "episodes": ("publisherEdition", search_episode),
}


def search_results(page):
    """The /explore/<q> pageProps -> {"<section>": [...]} with every section
    the page carried."""
    page = page or {}
    card_map = page.get("spotlightCardMap") or {}
    out = {}
    for section in page.get("sections") or []:
        name = SECTION_TYPES.get(to_int(section.get("sectionType")))
        if not name:
            continue
        case, parser = SECTION_PARSERS[name]
        items = []
        for result in section.get("results") or []:
            body = (result or {}).get("result") or {}
            raw = body.get(case) if body.get("$case") == case or body.get(case) else None
            if raw is None:
                continue
            items.append(search_story_card(raw, card_map) if name == "spotlights" else parser(raw))
        out[name] = items
    return out


# ---- discover / publishers ---------------------------------------------------------------

def discover_creator(raw):
    raw = raw or {}
    username = clean(raw.get("username"))
    bp = clean(raw.get("businessProfileId"))
    kind = clean(raw.get("__typename"))
    badge = clean(raw.get("badge"))
    return {
        "username": username,
        "display_name": clean(raw.get("title")),
        "link": refs.user_link(username) or refs.publisher_link(bp),
        "type": {"PublicProfileUser": "public_profile", "Publisher": "publisher"}.get(kind, kind.lower() if kind else None),
        "bio": clean(raw.get("bio")),
        "badge": badge.lower() if badge and badge != "NONE" else None,
        "is_verified": bool(badge and badge != "NONE"),
        "profile_picture": link_or_none(raw.get("profilePictureUrl")),
        "hero_image": link_or_none(raw.get("squareHeroImageUrl")),
        "snapcode_image": link_or_none(raw.get("snapcodeImageUrl")),
        "primary_color": clean(raw.get("primaryColor")),
        "subscriber_count": to_count(raw.get("subscriberCount")),
        "business_profile_id": bp,
    }


def discover_story(raw):
    raw = raw or {}
    creator = discover_creator(raw.get("creator"))
    kind = clean(raw.get("type"))
    snaps = [snap(s) for s in raw.get("snaps") or [] if isinstance(s, dict)]
    story_id = clean(raw.get("id"))
    if kind == "SHOW":
        link = refs.episode_link(creator.get("business_profile_id"), story_id)
    else:
        link = creator.get("link")
    thumb = link_or_none(raw.get("thumbnailUrl"))
    if thumb and thumb.startswith("https://app.snapchat.comhttps://"):
        thumb = thumb[len("https://app.snapchat.com"):]
    return {
        "id": story_id,
        "type": {"SHOW": "show", "PUBLIC_USER_STORY": "public_story"}.get(kind, kind.lower() if kind else None),
        "title": clean(raw.get("title")),
        "link": link,
        "thumbnail": thumb,
        "tap_id": clean(raw.get("tapId")),
        "published_at": iso_utc(raw.get("publishedTimeInSec")) if to_int(raw.get("publishedTimeInSec")) and to_int(raw.get("publishedTimeInSec")) < 10 ** 11 else iso_ms(raw.get("publishedTimeInSec")),
        "video_track": link_or_none(raw.get("videoTrackUrl")),
        "snap_count": len(snaps),
        "snaps": snaps,
        "creator": creator,
    }


def season(raw):
    raw = raw or {}
    return {"id": clean(raw.get("seasonId")), "number": to_int(raw.get("seasonNumber")),
            "episode_count": to_int(raw.get("episodeCount"))}


def episode_summary(raw, publisher_id=None):
    """premiumStoryList[i] (page) or premiumStories[i] (GraphQL) -> episode
    without snaps."""
    raw = raw or {}
    player = raw.get("playerStory") or raw.get("story") or {}
    story_id = clean(val(player.get("storyId"))) or clean(player.get("id"))
    owner = clean(raw.get("ownerId")) or clean(raw.get("ownerBusinessProfileId")) or publisher_id
    return {
        "id": story_id,
        "title": clean(val(player.get("storyTitle"))) or clean(player.get("title")),
        "subtitle": clean(player.get("subtitle")),
        "link": refs.episode_link(owner, story_id),
        "thumbnail": link_or_none(player.get("thumbnailUrl")),
        "video_track": link_or_none(player.get("videoTrackUrl")),
        "published_at": iso_utc(raw.get("timestampInSec")) or iso_utc(raw.get("publishedTimeInSec")),
        "season_number": to_int(raw.get("seasonNumber")),
        "episode_number": to_int(raw.get("episodeNumber")),
        "publisher_id": owner,
    }


def episode(raw, publisher_id=None):
    """A premiumStory with its snaps (GraphQL premiumStory or the page's
    preselectedStory.premiumStory)."""
    out = episode_summary(raw, publisher_id)
    player = (raw or {}).get("playerStory") or (raw or {}).get("story") or {}
    snaps = [snap(s) for s in player.get("snapList") or player.get("snaps") or [] if isinstance(s, dict)]
    out["snap_count"] = len(snaps)
    out["snaps"] = snaps
    return out


def publisher(page, business_profile_id):
    page = page or {}
    info = page.get("publicProfileInfo") or {}
    bp = clean(page.get("businessProfileId")) or business_profile_id
    prof = public_profile(info, page=None, link=refs.publisher_link(bp), kind="publisher")
    prof["business_profile_id"] = prof["business_profile_id"] or bp
    prof["snapcode_links"] = None
    prof["has_story"] = to_bool(info.get("hasStory"))
    seasons = [season(s) for s in page.get("premiumShowSeasonList") or [] if isinstance(s, dict)]
    episodes = [episode_summary(e, bp) for e in page.get("premiumStoryList") or [] if isinstance(e, dict)]
    selected = (page.get("preselectedStory") or {}).get("premiumStory")
    return {
        **prof,
        "season_count": len(seasons),
        "seasons": seasons,
        "latest_episodes": episodes,
        "selected_episode": episode(selected, bp) if selected and (selected.get("playerStory") or {}).get("snapList") else None,
        "spotlights": [story_card(c) for c in page.get("publisherSpotlightStoryCards") or [] if isinstance(c, dict)],
    }


# ---- places --------------------------------------------------------------------------

def _hhmm(point):
    point = point or {}
    hour, minute = to_int(point.get("hour")), to_int(point.get("minute"))
    if hour is None:
        return None
    return f"{hour:02d}:{minute or 0:02d}"


def opening_hours(raw):
    raw = raw or {}
    days = []
    for entry in raw.get("dayHours") or []:
        if not isinstance(entry, dict):
            continue
        day = to_int(entry.get("day"))
        days.append({
            "day": WEEKDAYS.get(day, day),
            "hours": [{"open": _hhmm(h.get("start")), "close": _hhmm(h.get("end"))}
                      for h in entry.get("hours") or [] if isinstance(h, dict)],
        })
    if not days and not raw.get("timeZone"):
        return None
    return {
        "timezone": clean(raw.get("timeZone")),
        "days": days,
        "special_hours": raw.get("specialHours") or [],
        "disclaimer": clean(raw.get("disclaimerText")),
    }


def _address(raw):
    raw = raw or {}
    out = {
        "street": clean(raw.get("address1")) or clean(raw.get("street")),
        "street2": clean(raw.get("address2")),
        "locality": clean(raw.get("locality")),
        "region": clean(raw.get("region")),
        "postal_code": clean(raw.get("postalCode")) or clean(raw.get("postal_code")),
        "country": clean(raw.get("country")),
    }
    return out if any(out.values()) else None


def _rating(raw):
    raw = raw or {}
    provider = to_int(raw.get("provider"))
    return {
        "provider": clean(raw.get("providerDisplayName")) or PLACE_PROVIDERS.get(provider, provider),
        "value": to_float(raw.get("value")),
        "max": to_float(raw.get("maximum")),
        "count": to_count(raw.get("count")),
        "icon": link_or_none(raw.get("ratingIconUrl")) or link_or_none(raw.get("iconUrl")),
    }


def place_review(raw):
    raw = raw or {}
    return {
        "id": clean(raw.get("id")),
        "provider": clean(raw.get("providerDisplayName")) or PLACE_PROVIDERS.get(to_int(raw.get("provider"))),
        "rating": _rating(raw.get("aggregatedRating")) if raw.get("aggregatedRating") else None,
        "text": clean(raw.get("text")),
        "original_text": clean(raw.get("originalText")),
        "language": clean(raw.get("locale")),
        "link": link_or_none(raw.get("url")),
        "photos": [link_or_none(p.get("imageUrl") if isinstance(p, dict) else p) for p in raw.get("photos") or []],
        "created_at": iso_ms(raw.get("createdAtMs")),
    }


def place_story(raw):
    raw = raw or {}
    video = raw.get("videoMetadata") or {}
    username = clean(raw.get("posterUsername"))
    snap_id = clean(raw.get("snapId"))
    kind = clean(raw.get("orbisStoryType"))
    return {
        "id": snap_id,
        "type": kind,
        "link": refs.spotlight_link(username, snap_id) if kind == "spotlight" and username else None,
        "thumbnail": link_or_none(raw.get("storyThumbnailUrl")) or link_or_none(video.get("thumbnailUrl")),
        "video": link_or_none(video.get("videoUrl")),
        "media_type": SNAP_MEDIA_TYPES.get(to_int(video.get("mediaType"))),
        "posted_at": iso_ms(raw.get("postedTimestamp")),
        "poster": creator_ref(username, raw.get("posterDisplayName"), None, None, user_id=clean(raw.get("posterUserId")))
        if username or clean(raw.get("posterUserId")) else None,
    }


def nearby_place(raw, stories):
    raw = raw or {}
    place_id = clean(raw.get("placeId"))
    name = clean(raw.get("placeName"))
    return {
        "id": place_id,
        "name": name,
        "link": refs.place_link(name, place_id),
        "category": clean(raw.get("categoryDisplayName")),
        "category_icon": link_or_none(raw.get("iconUrl")),
        "location": _geo(raw.get("location")),
        "photos": [link_or_none(p.get("imageUrl") if isinstance(p, dict) else p) for p in raw.get("photos") or []],
        "opening_hours": opening_hours(raw.get("openingHours")),
        "stories": [place_story(s) for s in (stories or {}).get(place_id) or [] if isinstance(s, dict)],
    }


def place(page, place_id=None):
    page = page or {}
    prof = page.get("placeProfile") or {}
    info = prof.get("placeInfo") or {}
    loc = prof.get("placeLocation") or {}
    contact = info.get("contactInfo") or {}
    phone = contact.get("phoneNumber") or {}
    reviews_raw = prof.get("tippetsReviews") or {}
    popularity = prof.get("popularityHours") or {}
    geometry = info.get("geometry") or loc.get("geometry") or {}
    pid = clean(prof.get("placeId")) or place_id
    name = clean(info.get("name"))
    nearby_stories = page.get("componentThumbnailData") or {}
    external_ids = []
    for c in info.get("concordances") or []:
        if isinstance(c, dict) and clean(c.get("id")):
            provider = to_int(c.get("provider"))
            external_ids.append({"provider": PLACE_PROVIDERS.get(provider, f"provider_{provider}"), "id": clean(c.get("id"))})
    return {
        "id": pid,
        "name": name,
        "link": refs.place_link(name, pid),
        "category": clean(info.get("categoryName")),
        "category_id": clean(info.get("categoryId")),
        "kind": clean(loc.get("kindName")),
        "category_icon": link_or_none(loc.get("categoryIconUrl")),
        "image": link_or_none((info.get("profilePhoto") or {}).get("imageUrl"))
        if to_int((info.get("profilePhoto") or {}).get("imageType")) != 1 else None,
        "photos": [link_or_none(p.get("imageUrl") if isinstance(p, dict) else p) for p in info.get("photos") or []],
        "address": _address(info.get("address") or loc.get("address")),
        "address_text": clean(info.get("addressDisplayText")) or clean(loc.get("addressDisplayText")),
        "location": _geo(geometry.get("centroid")),
        "bounding_box": _bbox(loc.get("bounds")),
        "contact": {
            "phone": clean(phone.get("phoneNumber")),
            "phone_text": clean(info.get("phonenumberDisplayText")),
            "alternate_phones": [clean(p.get("phoneNumber") if isinstance(p, dict) else p) for p in contact.get("alternatePhoneNumbers") or []],
            "email": clean(contact.get("emailAddress")),
            "website": link_or_none(contact.get("website")),
            "website_text": clean(info.get("websiteDisplayText")),
            "menu_link": link_or_none(contact.get("menuUrl")) or link_or_none(info.get("menuUrl")),
            "reservation_link": link_or_none(info.get("reservationUrl")),
            "store_link": link_or_none(info.get("storeUrl")),
        },
        "opening_hours": opening_hours(info.get("openingHours")),
        "popularity_hours": {
            "hours": [to_int(h) or 0 for h in popularity.get("hours") or []],
            "display_start_hour": to_int(popularity.get("displayStartHour")),
            "display_end_hour": to_int(popularity.get("displayEndHour")),
        } if popularity.get("hours") else None,
        "ratings": [_rating(r) for r in info.get("aggregatedRatings") or [] if isinstance(r, dict)],
        "favorite_count": to_count((prof.get("placeStats") or {}).get("favoriteCount")),
        "reviews": [place_review(r) for r in reviews_raw.get("reviews") or [] if isinstance(r, dict)],
        "review_snippets": [clean(t.get("text") if isinstance(t, dict) else t) for t in reviews_raw.get("tippets") or []],
        "review_links": [{"provider": clean(r.get("providerDisplayName")), "link": link_or_none(r.get("url"))}
                         for r in reviews_raw.get("reviewLandingPages") or [] if isinstance(r, dict)],
        "attributes": [clean(a.get("name") if isinstance(a, dict) else a) for a in info.get("placeAttributes") or []],
        "delivery_options": info.get("orderDeliveryDetails") or [],
        "reservation_options": info.get("reservationDetails") or [],
        "external_ids": external_ids,
        "hierarchy": [{"id": clean(h.get("placeId")), "name": clean(h.get("placeName")), "type": to_int(h.get("placeType"))}
                      for h in prof.get("placeHierarchies") or [] if isinstance(h, dict)],
        "breadcrumbs": [{"id": clean(b.get("placeId")), "name": clean(b.get("name"))}
                        for b in page.get("breadcrumbs") or [] if isinstance(b, dict) and not b.get("isCurrentPlace")],
        "nearby": [{
            "title": clean(comp.get("componentTitle")),
            "places": [nearby_place(p, nearby_stories) for p in comp.get("placesInfo") or [] if isinstance(p, dict)],
        } for comp in page.get("placeComponents") or [] if isinstance(comp, dict)],
        "stories": [place_story(s) for s in page.get("storythumbnailData") or [] if isinstance(s, dict)],
        "shows_place_stories": to_bool(prof.get("showPlaceStories")),
    }


def local_place(raw, stories=None):
    raw = raw or {}
    place_id = clean(raw.get("place_id"))
    price = raw.get("priceyness") or {}
    rating = raw.get("rating") or {}
    tags = raw.get("tags") or []
    return {
        "id": place_id,
        "name": clean(raw.get("place_name")),
        "link": link_or_none(raw.get("place_url")) or refs.place_link(raw.get("place_name"), place_id),
        "category": clean(raw.get("category_display")),
        "category_icon": link_or_none(raw.get("category_icon_url")),
        "photo": link_or_none(raw.get("photo_url")),
        "location": _geo(raw.get("location")),
        "address_text": clean(raw.get("address")),
        "address": _address(raw.get("postal_address")),
        "phone": clean(raw.get("phone")),
        "neighborhood": clean(raw.get("neighborhood")),
        "price": {
            "label": clean(raw.get("priceyness_label")),
            "level": to_int(price.get("value")),
            "max": to_int(price.get("maximum")),
            "currency_symbol": clean(price.get("currencySymbol")),
            "provider": clean(price.get("providerDisplayName")),
        } if price or clean(raw.get("priceyness_label")) else None,
        "rating": _rating(rating) if rating else None,
        "is_popular": any((t or {}).get("kind") == "popular" for t in tags),
        "attributes": [clean(t.get("label")) for t in tags if isinstance(t, dict) and t.get("kind") == "attribute" and clean(t.get("label"))],
        "opening_hours": opening_hours({**(raw.get("opening_hours") or {}), "timeZone": raw.get("time_zone")}),
        "is_open": to_bool(raw.get("is_open")),
        "popularity_hours": [to_int(h) or 0 for h in raw.get("popularity_hours") or []] or None,
        "stories": [place_story(s) for s in (stories or {}).get(place_id) or [] if isinstance(s, dict)],
    }


def _local_area(raw):
    raw = raw or {}
    return {
        "slug": clean(raw.get("slug")),
        "name": clean(raw.get("name")),
        "state": clean(raw.get("state")),
        "state_name": clean(raw.get("state_name")),
        "state_slug": clean(raw.get("state_slug")),
        "city_slug": clean(raw.get("city_slug")),
        "place_id": clean(raw.get("locality_place_id")) or clean(raw.get("neighborhood_place_id")),
        "location": _geo(raw.get("centroid")),
        "bounding_box": _bbox(raw.get("bbox")),
    } if raw else None


def _local_crosslinks(items):
    return [{"slug": clean(i.get("slug")), "name": clean(i.get("display_name")),
             "link": refs.SITE + i["url"] if clean(i.get("url")) else None}
            for i in items or [] if isinstance(i, dict)]


def local_page(page):
    page = page or {}
    data = page.get("pageData") or {}
    stories = page.get("placeStories") or {}
    kind = clean(data.get("page_type"))
    out = {
        "type": {"geo_hub": "hub", "leaf": "places"}.get(kind, kind),
        "link": refs.SITE + (clean(data.get("page_url")) or clean(data.get("leaf_url")) or ""),
        "city": _local_area((data.get("scope") or {}).get("city") or data.get("city")),
        "neighborhood": _local_area(data.get("neighborhood")),
        "category": {
            "slug": clean((data.get("category") or {}).get("slug")),
            "name": clean((data.get("category") or {}).get("display_name")),
        } if data.get("category") else None,
    }
    if kind == "geo_hub":
        out["sections"] = [{
            "category": {"slug": clean((s.get("category") or {}).get("slug")),
                         "name": clean((s.get("category") or {}).get("display_name"))},
            "link": refs.SITE + s["leaf_url"] if clean(s.get("leaf_url")) else None,
            "places": [local_place(p, stories) for p in s.get("places") or [] if isinstance(p, dict)],
        } for s in data.get("sections") or [] if isinstance(s, dict)]
        out["neighborhoods"] = _local_crosslinks(data.get("neighborhoods"))
        out["other_cities"] = _local_crosslinks(data.get("same_state_cities")) or _local_crosslinks(data.get("top_cities"))
        out["place_count"] = sum(len(s["places"]) for s in out["sections"])
    else:
        places = [local_place(p, stories) for p in data.get("places") or [] if isinstance(p, dict)]
        out["place_count"] = len(places)
        out["total_count"] = to_int(data.get("total_returned"))
        out["places"] = places
        out["related_categories"] = _local_crosslinks(data.get("same_city_categories"))
        out["other_cities"] = _local_crosslinks(data.get("same_category_other_cities"))
        out["neighborhoods"] = _local_crosslinks(data.get("neighborhood_crosslinks"))
    return out


# ---- topics ----------------------------------------------------------------------------

def _iso_duration_seconds(text):
    match = re.match(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:([\d.]+)S)?$", str(text or ""))
    if not match:
        return None
    hours, minutes, seconds = match.groups()
    return int(hours or 0) * 3600 + int(minutes or 0) * 60 + float(seconds or 0)


def topic_video(raw):
    raw = raw or {}
    link = link_or_none(raw.get("url"))
    match = re.search(r"/@([^/]+)/spotlight/([A-Za-z0-9_-]+)", link or "")
    creator = raw.get("creator") or {}
    stats = {}
    for stat in raw.get("interactionStatistic") or []:
        if not isinstance(stat, dict):
            continue
        kind = str(stat.get("interactionType") or "").rsplit("/", 1)[-1].replace("Action", "").lower()
        if kind:
            stats[f"{kind}_count"] = to_count(stat.get("userInteractionCount"))
    return {
        "id": match.group(2) if match else None,
        "link": link,
        "title": clean(raw.get("name")),
        "description": clean(raw.get("description")),
        "thumbnail": link_or_none(raw.get("thumbnailUrl")),
        "video": link_or_none(raw.get("contentUrl")),
        "embed_link": link_or_none(raw.get("embedUrl")),
        "posted_at": clean(raw.get("uploadDate")),
        "duration_seconds": _iso_duration_seconds(raw.get("duration")),
        "keywords": [k.strip() for k in str(raw.get("keywords") or "").split(",") if k.strip()]
        if isinstance(raw.get("keywords"), str) else [clean(k) for k in raw.get("keywords") or [] if clean(k)],
        "stats": stats or None,
        "creator": creator_ref(match.group(1) if match else None, creator.get("name"), None, None,
                               link=link_or_none(creator.get("url")) or (refs.user_link(match.group(1)) if match else None)),
    }


def topic(ld_objects, html, slug):
    videos, name, description, breadcrumbs = [], None, None, []
    for obj in ld_objects or []:
        kind = obj.get("@type")
        if kind == "ItemList":
            videos = [topic_video(v) for v in obj.get("itemListElement") or [] if isinstance(v, dict)]
        elif kind == "CollectionPage":
            name, description = clean(obj.get("name")), clean(obj.get("description"))
        elif kind == "BreadcrumbList":
            breadcrumbs = [clean(b.get("name")) for b in obj.get("itemListElement") or [] if isinstance(b, dict)]
    if not name:
        match = re.search(r"<h1[^>]*>(.*?)</h1>", html or "", re.S)
        name = clean(re.sub(r"<[^>]+>", "", match.group(1))) if match else None
    related = []
    for href in re.findall(r'href="/topic/([^"/?#]+)', html or ""):
        if href != slug and href not in related:
            related.append(href)
    return {
        "slug": slug,
        "name": name,
        "link": refs.topic_link(slug),
        "description": description,
        "breadcrumbs": breadcrumbs,
        "spotlight_count": len(videos),
        "spotlights": videos,
        "related_topics": [{"slug": r, "name": r.replace("-", " ").title(), "link": refs.topic_link(r)} for r in related],
    }


def funny_keyword(raw):
    raw = raw or {}
    href = clean(raw.get("href")) or ""
    slug = href.rstrip("/").rsplit("/", 1)[-1] if href else None
    return {"name": clean(raw.get("title")), "slug": slug, "link": refs.SITE + href if href else None}


def funny_page(page):
    page = page or {}
    descriptions = page.get("topicDescriptions") or {}
    spotlights = [story_card(c) for c in page.get("spotlights") or [] if isinstance(c, dict)]
    return {
        "topic": {
            "slug": clean(page.get("topicId")),
            "name": clean(page.get("displayName")),
            "link": f"{refs.SITE}/entertainment/funny/{clean(page.get('topicId'))}" if clean(page.get("topicId")) else None,
            "description": clean(descriptions.get("short")),
            "long_description": clean(descriptions.get("long")),
        },
        "spotlight_count": len(spotlights),
        "spotlights": spotlights,
        "related_tags": [clean(t) for t in page.get("relatedS2ITags") or [] if clean(t)],
        "tag_hierarchy": [clean(t) for t in page.get("s2iTagHierarchy") or [] if clean(t)],
    }
