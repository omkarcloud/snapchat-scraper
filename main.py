"""Use the scraper straight from Python — no server needed.

    python main.py

Every function returns the same JSON the API does; results are written to
output/*.json. See README.md for the full endpoint list.
"""
import json
import os

from snapchat import refs, spotlight, users

os.makedirs("output", exist_ok=True)


def save(name, data):
    path = os.path.join("output", name)
    with open(path, "w") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"saved {path}")


if __name__ == "__main__":
    # a username, @username or any snapchat.com profile link
    save("profile_kyliejenner.json", users.get_profile(refs.resolve_user("kyliejenner")))

    # every Spotlight video on the profile, with stats and first comments
    save("spotlights_kyliejenner.json", users.get_spotlights(refs.resolve_user("kyliejenner")))

    # the trending Spotlight feed for a country (pass next_cursor for page 2)
    save("spotlight_feed_us.json", spotlight.get_feed(country="US"))
