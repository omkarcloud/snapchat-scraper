"""Cache TTL per /snapchat/* endpoint (cache.py, keyed on the validated
params — `user=wwe`, `user=@WWE` and a pasted profile link all validate to
the same key).

Profiles and highlights change slowly; the public story (24-hour snaps),
spotlight stats and comments move by the minute on busy accounts; the
feeds and search are re-ranked per request upstream, so short TTLs keep a
page of results stable for a paging client without serving stale data for
long. Cursor pages are cached per cursor.
"""
from datetime import timedelta

PROFILE_CACHE = timedelta(minutes=30)
STORY_CACHE = timedelta(minutes=5)           # the current 24-hour public story
HIGHLIGHTS_CACHE = timedelta(minutes=30)
USER_SPOTLIGHTS_CACHE = timedelta(minutes=15)
LENSES_CACHE = timedelta(hours=1)            # a user's lenses, lens browse / detail / creators
SPOTLIGHT_CACHE = timedelta(minutes=15)      # details, related
COMMENTS_CACHE = timedelta(minutes=5)
STATS_CACHE = timedelta(minutes=5)
FEED_CACHE = timedelta(minutes=5)            # spotlight / discover feeds
SEARCH_CACHE = timedelta(minutes=15)
TAG_CACHE = timedelta(minutes=15)            # hashtag / topic / entertainment pages
PUBLISHER_CACHE = timedelta(minutes=30)
EPISODE_CACHE = timedelta(hours=6)           # published episodes never change
PLACE_CACHE = timedelta(hours=6)
LOCAL_CACHE = timedelta(hours=6)
