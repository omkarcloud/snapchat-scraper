# 👻 Snapchat Scraper

Snapchat Scraper is a **free and open-source** scraper that gets you **unlimited** detailed Snapchat data for free.

## ✨ What Can I Get?

- 👻 **460K+ public creator profiles** — subscribers, bio, verified badge, story, highlights & related accounts
- 🎬 **9M+ Spotlight videos** — views, shares, comments, hashtags, sound, transcripts & video links
- 🎭 **650K+ lenses** — browse by category, search, creators, preview videos & unlock links
- 📍 **1M+ Snap Map places** — ratings, hours, reviews, busy hours & the snaps posted there

## 🎥 Example: A Full Snapchat Profile

```json
{
  "username": "kyliejenner",
  "display_name": "King Kylie 👑",
  "link": "https://www.snapchat.com/@kyliejenner",
  "type": "public_profile",
  "website": "https://kyliecosmetics.com",
  "subscriber_count": 29283900,
  "is_verified": true,
  "profile_picture": "https://cf-st.sc-cdn.net/aps/bolt/aHR0cHM6Ly9jZi1zdC5zYy1jZG4ubmV0L2QvaEJwN3Z0ZFl5NFVOeFpnWk04dXBYP2JvPUVna3lBUVJJQWxBWllBRSUzRCZ1Yz0yNQ._RS0,90_FMjpeg",
  "snapcode_image": "https://app.snapchat.com/web/deeplink/snapcode?username=kyliejenner&type=SVG&bitmoji=enable",
  "user_id": "7f445ef2-e1d3-4ef2-a235-a5aec8159168",
  "business_profile_id": "e9bcdb52-a5cc-4dea-88ac-8baa91a78345",
  "has_story": true,
  "related_accounts": [
    { "display_name": "Kim Kardashian", "username": "kimkardashian", "link": "https://www.snapchat.com/@kimkardashian", "is_verified": true },
    { "display_name": "Kendall Jenner", "username": "kendalljenner", "link": "https://www.snapchat.com/@kendalljenner", "is_verified": true }
  ],
  "created_at": "2019-05-22T18:01:50Z",
  "updated_at": "2026-09-19T13:39:12Z",
  "counts": { "story_snaps": 3, "curated_highlights": 18, "spotlights": 10, "lenses": 1 }
}
```

*Trimmed for readability.*

## 🚀 Unlimited Free Snapchat Data — Get It in 60 Seconds

1️⃣ Clone and install:
```bash
git clone https://github.com/omkarcloud/snapchat-scraper
cd snapchat-scraper
python -m pip install -r requirements.txt
```

2️⃣ Start the API:
```bash
python run.py
```

3️⃣ Get your first data:
```bash
curl "http://localhost:8000/users/profile?user=kyliejenner"
```

```json
{
  "username": "kyliejenner",
  "display_name": "King Kylie 👑",
  "link": "https://www.snapchat.com/@kyliejenner",
  "type": "public_profile",
  "website": "https://kyliecosmetics.com",
  "subscriber_count": 29283900,
  "is_verified": true,
  "has_story": true,
  "related_accounts": [
    { "display_name": "Kim Kardashian", "username": "kimkardashian", "link": "https://www.snapchat.com/@kimkardashian", "is_verified": true }
  ],
  "created_at": "2019-05-22T18:01:50Z",
  "counts": { "story_snaps": 3, "curated_highlights": 18, "spotlights": 10, "lenses": 1 }
}
```

All 26 endpoints are now live at `http://localhost:8000`.

## 📚 Endpoints

26 endpoints cover everything you need.

| Endpoint | Path | Returns |
|---|---|---|
| User Profile | `/users/profile` | Name, bio, subscribers, verified badge, website and related accounts |
| User Spotlights | `/users/spotlights` | Every Spotlight video with views, shares, comments and hashtags |
| Spotlight Details | `/spotlight/details` | One video with stats, creator, sound, full transcript and comments |
| User Story / Highlights | `/users/story`, `/users/highlights` | Live story and saved highlights with every snap's media link |
| Spotlight Comments | `/spotlight/comments` | Comments and threaded replies, paginated |
| Spotlight Stats | `/spotlight/stats` | Live stats for up to 31 videos in one call |
| Search Users | `/users/search` | Creators and brands with subscriber counts |
| Search | `/search` | Videos, lenses, topics, creators, places, shows and episodes at once |
| Spotlight Feed | `/spotlight/feed` | Trending videos for any country, 25 per page |
| Related Spotlights | `/spotlight/related` | The videos Snapchat queues up next |
| Hashtag / Topic Spotlights | `/hashtags/spotlights`, `/topics/spotlights` | Top videos for any hashtag or topic |
| Funny Spotlights | `/topics/funny` | 200+ comedy keywords and their funniest videos |
| Discover Feed | `/discover/feed` | Show episodes and public creator stories, paginated |
| User Lenses | `/users/lenses` | Every lens a creator published |
| Browse / Search Lenses | `/lenses/browse`, `/lenses/search` | Lenses by category or keyword, with previews |
| Lens Details | `/lenses/details` | One lens with related lenses and videos made with it |
| Lens Creators | `/lenses/creators` | Top lens creators, 25 per page |
| Publisher Details | `/publishers/details` | Discover show profile, seasons and latest episodes |
| Publisher Episodes | `/publishers/episodes` | Every episode of a season, paginated |
| Episode Details | `/publishers/episode` | One episode with every snap and its video track |
| Search Places | `/places/search` | Snap Map places by name with location |
| Place Details | `/places/details` | Address, hours, ratings, reviews and snaps posted there |
| Local Places | `/places/local` | Top places in any US city with ratings and prices |

## 🔍 Exploring Parameters

The same API is published on RapidAPI, and its playground is the easiest place to try parameters and see raw responses. Once a request looks right, run it locally for **unlimited free** data.

1. [Subscribe to the free plan](https://rapidapi.com/OmkarCloud/api/best-snapchat-scraper-free-1000-calls/pricing) — 1,000 calls/month, no credit card.
2. [Try the endpoints in the playground](https://rapidapi.com/OmkarCloud/api/best-snapchat-scraper-free-1000-calls/playground) — every param is pre-filled, so you see real data in one click.
3. Copy the generated code and replace `https://best-snapchat-scraper-free-1000-calls.p.rapidapi.com` with `http://localhost:8000`. It will now run against your local API.

```python
import requests

# generated by the playground, host swapped for the local API
response = requests.get(
    "http://localhost:8000/users/profile",
    params={"user": "kyliejenner"},
)
print(response.json())
```

## 💬 Have Questions? We Have Answers.

You're a developer — we know how hard completing a project can be. So we offer full support: just message us and we'll reply ✅ with a solution within 1 working day.

[![Message Us on WhatsApp about Snapchat Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/whatsapp-us.png)](https://api.whatsapp.com/send?phone=918178804274&text=I%20need%20help%20using%20the%20Snapchat%20Scraper%20API.)

[![Ask Us by Email about Snapchat Scraper](https://raw.githubusercontent.com/omkarcloud/assets/master/images/ask-on-email.png)](mailto:happy.to.help@omkar.cloud?subject=Help%20with%20Snapchat%20Scraper%20API&body=I%20need%20help%20using%20the%20Snapchat%20Scraper%20API.)

## ⚡ Popular Scrapers by Omkar Cloud

- [**Google Maps Scraper (3,100+ GitHub Stars)**](https://github.com/omkarcloud/google-maps-scraper) — type "dentists in New York", get every business as a ready-to-call lead list: phones, emails, websites & reviews. Up to 100K free leads/month.
- [**Threads Scraper**](https://github.com/omkarcloud/threads-scraper) — Threads posts, profiles, replies & search
- [**IMDb Scraper**](https://github.com/omkarcloud/imdb-scraper) — movies, TV shows, ratings, cast & box office
- [**G2 Scraper**](https://www.omkar.cloud/tools/g2-scraper) — G2 product details, ratings & AI-found contacts
- [**Website Email Contact Scraper**](https://www.omkar.cloud/tools/website-email-contact-scraper) — emails, phones & socials from any website
- [**Booking Scraper**](https://www.omkar.cloud/tools/booking-scraper) — Booking.com hotels: prices, ratings, rooms & amenities

## ⭐ Love It? [Star It ⭐!](https://github.com/omkarcloud/snapchat-scraper)

Star the repo ⭐ and become my star hero!

It's just 1 click, but it means the world to me.

[![Star us on GitHub](https://raw.githubusercontent.com/omkarcloud/google-maps-scraper/master/screenshots/star-us.png)](https://github.com/omkarcloud/snapchat-scraper)
