"""Marshmallow request schemas for every /snapchat/* route.

Generic fields live in the shared top-level schema_fields.py; this module
adds the Snapchat resolvers and the per-route schemas. Every schema's
load() output is the kwargs dict its endpoint function takes.

ONE param per input (tripadvisor QueryOrIdField convention, never a sibling
`url`/`id` pair), auto-detected by refs.py:
  user       username, @username or a snapchat.com profile link
  spotlight  a Spotlight snap id or any snapchat.com spotlight link
  spotlights a comma list of the above (batch stats)
  lens       lens uuid, numeric lens id, or a lens / unlock link
  tag        hashtag (with or without #) or a /tag/ link
  topic      topic name / slug or a /topic/ link
  publisher  business profile id or a /p/ link
  episode    episode (story) id or a /p/<publisher>/<episode> link
  place      place id or a /place/ link
  location   state/city[/neighborhood] or a /local/ link
  comment    a comment id from /spotlight/comments (lists its replies)
"""
from marshmallow import ValidationError, fields, validate

from schema_fields import (BaseSchema, ChoiceField, CountryCodeField, LanguageCodeField, LimitField, QueryField,
                           RefField, StrippedString)
from snapchat import refs


class UserRefField(RefField):
    resolver = staticmethod(refs.resolve_user)


class SpotlightRefField(RefField):
    resolver = staticmethod(refs.resolve_spotlight)


class LensRefField(RefField):
    resolver = staticmethod(refs.resolve_lens)


class TagRefField(RefField):
    resolver = staticmethod(refs.resolve_tag)


class TopicRefField(RefField):
    resolver = staticmethod(refs.resolve_topic)


class PublisherRefField(RefField):
    resolver = staticmethod(refs.resolve_publisher)


class EpisodeRefField(RefField):
    resolver = staticmethod(refs.resolve_episode)


class PlaceRefField(RefField):
    resolver = staticmethod(refs.resolve_place)


class LocationRefField(RefField):
    resolver = staticmethod(refs.resolve_location)


class CommentRefField(RefField):
    resolver = staticmethod(refs.resolve_comment)


class SpotlightListField(fields.Field):
    """Comma-separated spotlight ids / links (1-31, the fetchSpotlight cap)."""

    def _deserialize(self, value, attr, data, **kwargs):
        items = []
        for raw in str(value).split(","):
            raw = raw.strip()
            if not raw:
                continue
            try:
                ref = refs.resolve_spotlight(raw)
            except ValueError as e:
                raise ValidationError(str(e))
            if ref["id"] not in items:
                items.append(ref["id"])
        if not items:
            raise ValidationError("Must not be empty.")
        if len(items) > 31:
            raise ValidationError("At most 31 spotlights per request.")
        return items


class CursorField(StrippedString):
    """Opaque next_cursor from the previous page (absent = first page)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("required", False)
        kwargs.setdefault("load_default", None)
        kwargs.setdefault("validate", validate.Length(max=4000))
        super().__init__(**kwargs)


class LocaleField(LanguageCodeField):
    """Site locale tag (en-US, fr-FR, hi-IN, …) — the language of the
    localized strings (category names, section titles). Default en-US."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", "en-US")
        super().__init__(allow_locale=True, **kwargs)


class ViewerCountryField(CountryCodeField):
    """Viewer country for the feeds (GraphQL variable; default US)."""

    def __init__(self, **kwargs):
        kwargs.setdefault("load_default", "US")
        super().__init__(**kwargs)


class ExitCountryField(CountryCodeField):
    """Viewer country for the server-rendered search / local pages, which
    only follow the exit IP: when given, the request is routed through a
    residential exit in that country (slower; default = the pod's own)."""


# ---- users -----------------------------------------------------------------------------

class UserSchema(BaseSchema):
    user = UserRefField(metadata={"description": "username, @username or snapchat.com profile link"})


class UserSearchSchema(BaseSchema):
    query = QueryField(max_length=100)
    country = ExitCountryField()
    locale = LocaleField()


# ---- spotlight ---------------------------------------------------------------------------

class SpotlightSchema(BaseSchema):
    spotlight = SpotlightRefField(metadata={"description": "Spotlight snap id or snapchat.com spotlight link"})


class SpotlightCommentsSchema(SpotlightSchema):
    comment = CommentRefField(required=False, load_default=None,
                              metadata={"description": "a comment id: list the replies under that comment"})
    cursor = CursorField()
    country = ViewerCountryField()


class SpotlightBatchSchema(BaseSchema):
    spotlights = SpotlightListField(required=True,
                                    metadata={"description": "comma-separated Spotlight ids or links, max 31"})


class FeedSchema(BaseSchema):
    country = ViewerCountryField()
    locale = LocaleField()
    cursor = CursorField()


class DiscoverFeedSchema(FeedSchema):
    limit = LimitField(default=30, max_size=100)


class TagSchema(BaseSchema):
    tag = TagRefField(metadata={"description": "hashtag (with or without #) or a snapchat.com/tag/ link"})


class TopicSchema(BaseSchema):
    topic = TopicRefField(metadata={"description": "topic name / slug or a snapchat.com/topic/ link"})


class FunnySchema(BaseSchema):
    keyword = StrippedString(required=False, load_default=None, validate=validate.Length(max=100),
                             metadata={"description": "a keyword slug from the list (absent = the keyword list)"})


# ---- search ------------------------------------------------------------------------------

SEARCH_TYPES = ["all", "spotlights", "lenses", "topics", "users", "places", "shows", "episodes"]


class SearchSchema(BaseSchema):
    query = QueryField(max_length=100)
    type = ChoiceField(SEARCH_TYPES, load_default="all")
    country = ExitCountryField()
    locale = LocaleField()


# ---- lenses ------------------------------------------------------------------------------

LENS_CATEGORIES = ["for_you", "trending", "face", "world", "music", "web_live"]


class LensBrowseSchema(BaseSchema):
    category = ChoiceField(LENS_CATEGORIES, load_default="for_you")
    cursor = CursorField()
    locale = LocaleField()


class LensSchema(BaseSchema):
    lens = LensRefField(metadata={"description": "lens uuid, numeric lens id, or a snapchat.com lens / unlock link"})
    locale = LocaleField()


class LensCreatorsSchema(BaseSchema):
    cursor = CursorField()
    locale = LocaleField()


# ---- publishers ----------------------------------------------------------------------------

class PublisherSchema(BaseSchema):
    publisher = PublisherRefField(metadata={"description": "business profile id or a snapchat.com/p/ link"})
    locale = LocaleField()


class PublisherEpisodesSchema(BaseSchema):
    publisher = PublisherRefField()
    season = StrippedString(required=False, load_default=None, validate=validate.Length(max=64),
                            metadata={"description": "season id or season number (default: the latest season)"})
    cursor = CursorField()
    limit = LimitField(default=25, max_size=100)
    country = ViewerCountryField()


class EpisodeSchema(BaseSchema):
    episode = EpisodeRefField(metadata={"description": "episode (story) id or a snapchat.com/p/<publisher>/<episode> link"})
    country = ViewerCountryField()


# ---- places --------------------------------------------------------------------------------

class PlaceSchema(BaseSchema):
    place = PlaceRefField(metadata={"description": "place id or a snapchat.com/place/ link"})
    locale = LocaleField()


class LocalSchema(BaseSchema):
    location = LocationRefField(metadata={"description": "state/city[/neighborhood] (US) or a snapchat.com/local/ link"})
    category = StrippedString(required=False, load_default=None, validate=validate.Length(max=60),
                              metadata={"description": "a category slug (restaurants, bars, …); absent = the city hub"})
    locale = LocaleField()
