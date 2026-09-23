"""Configuration for the Snapchat Scraper. Everything can be set with an
environment variable; the defaults work out of the box.

    PORT            port the API listens on (default 8000)
    SNAPCHAT_PROXY  proxy URL for every request, e.g. http://user:pass@host:port
                    (default: none — direct). snapchat.com runs no bot
                    challenge on the pages and APIs this scraper uses, so you
                    very likely don't need this. Set it only if you start
                    seeing failures at high volume, or to see search results
                    the way viewers in another country do (Snapchat ranks
                    search and local pages by the visitor's IP).

Everything else below is a plain constant with a working default — edit it
here if you need to.
"""
import os

PORT = int(os.environ.get("PORT", "8000"))

# Retry policy for transport errors and blocks (every request).
MAX_RETRIES = 3
RETRY_BACKOFF = 2          # seconds, multiplied by the attempt number

SNAPCHAT_PROXY = os.environ.get("SNAPCHAT_PROXY") or None

# No automatic fallback exit here: a blocked request is simply retried.
SNAPCHAT_FALLBACK_PROXY_COUNTRY = None
SNAPCHAT_DIRECT_COOLDOWN = 900


def snapchat_proxy():
    return os.environ.get("SNAPCHAT_PROXY") or None


def snapchat_fallback_proxy():
    return None


def snapchat_country_proxy(country):
    """The `country` param on search / local pages: the hosted API routes
    those through an exit in that country; here they go through
    SNAPCHAT_PROXY (point it at an exit in the country you want)."""
    return os.environ.get("SNAPCHAT_PROXY") or None
