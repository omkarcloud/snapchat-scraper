"""The 26 Snapchat endpoints. Every path is served with and without the
`/snapchat` prefix, so code generated against the hosted API on RapidAPI
(paths like /users/profile) runs unchanged against this server.

Params are validated by the same marshmallow schemas the hosted API uses
(snapchat/schemas.py): `user`, `spotlight`, `lens`, `tag`, `topic`,
`publisher`, `episode`, `place` and `location` each accept a bare value or a
pasted snapchat.com link."""
import json

from bottle import request, response, route

from schema_fields import load_query
from snapchat import discovery, lenses, places, publishers, schemas, spotlight, users
from snapchat.fetch import SnapchatBadRequest, SnapchatNotFound


def json_response(data, status=200):
    response.status = status
    response.content_type = "application/json"
    return json.dumps(data, ensure_ascii=False)


def query_dict():
    """The query as unicode strings (bottle 0.12's .get() hands back latin-1
    decoded bytes, so a UTF-8 "Amélie" would arrive as "AmÃ©lie")."""
    return {key: request.query.getunicode(key) for key in request.query.keys()}


def call(label, schema, fn):
    """Validate, run, map errors: bad params -> 400, missing entity -> 404,
    transport/blocks -> 500."""
    data, error = load_query(schema, query_dict())
    if error:
        return json_response(error, 400)
    try:
        return json_response(fn(**data))
    except ValueError as e:                # bad value (e.g. a mangled cursor)
        return json_response({"error": str(e)}, 400)
    except SnapchatBadRequest as e:        # upstream rejected the request
        return json_response({"error": f"snapchat rejected the request: {e}"}, 400)
    except SnapchatNotFound as e:
        return json_response({"error": str(e) or "not found"}, 404)
    except Exception as e:                 # retries exhausted / blocked
        return json_response({"error": f"snapchat {label} failed: {e}"}, 500)


def mount(path, schema, fn):
    """Serve fn at /path and /snapchat/path."""
    def handler():
        return call(path.strip("/"), schema, fn)
    handler.__name__ = "snapchat_" + path.strip("/").replace("/", "_").replace("-", "_")
    route(path, method="GET")(handler)
    route("/snapchat" + path, method="GET")(handler)


ENDPOINTS = [
    ("/users/profile", schemas.UserSchema, users.get_profile),
    ("/users/spotlights", schemas.UserSchema, users.get_spotlights),
    ("/spotlight/details", schemas.SpotlightSchema, spotlight.get_details),
    ("/users/story", schemas.UserSchema, users.get_story),
    ("/users/highlights", schemas.UserSchema, users.get_highlights),
    ("/spotlight/comments", schemas.SpotlightCommentsSchema, spotlight.get_comments),
    ("/spotlight/stats", schemas.SpotlightBatchSchema, spotlight.get_stats),
    ("/users/search", schemas.UserSearchSchema, discovery.search_users),
    ("/search", schemas.SearchSchema, discovery.search),
    ("/spotlight/feed", schemas.FeedSchema, spotlight.get_feed),
    ("/spotlight/related", schemas.SpotlightSchema, spotlight.get_related),
    ("/hashtags/spotlights", schemas.TagSchema, discovery.get_tag),
    ("/topics/spotlights", schemas.TopicSchema, discovery.get_topic),
    ("/topics/funny", schemas.FunnySchema, discovery.get_funny),
    ("/discover/feed", schemas.DiscoverFeedSchema, discovery.get_discover_feed),
    ("/users/lenses", schemas.UserSchema, users.get_lenses),
    ("/lenses/browse", schemas.LensBrowseSchema, lenses.browse),
    ("/lenses/search", schemas.UserSearchSchema, lenses.search),
    ("/lenses/details", schemas.LensSchema, lenses.get_details),
    ("/lenses/creators", schemas.LensCreatorsSchema, lenses.creators),
    ("/publishers/details", schemas.PublisherSchema, publishers.get_details),
    ("/publishers/episodes", schemas.PublisherEpisodesSchema, publishers.get_episodes),
    ("/publishers/episode", schemas.EpisodeSchema, publishers.get_episode),
    ("/places/search", schemas.UserSearchSchema, places.search),
    ("/places/details", schemas.PlaceSchema, places.get_details),
    ("/places/local", schemas.LocalSchema, places.get_local),
]

for _path, _schema, _fn in ENDPOINTS:
    mount(_path, _schema, _fn)


@route("/", method="GET")
@route("/health", method="GET")
def health():
    return json_response({"status": "ok", "endpoints": [p for p, _, _ in ENDPOINTS]})
