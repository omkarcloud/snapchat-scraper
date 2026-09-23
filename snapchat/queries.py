"""The web-stories-api GraphQL documents the site's own bundles send
(captured 2026-09-22 from the spotlight / discover / publisher chunks).
The endpoint is open and introspectable, so these are plain query texts,
not persisted ids — a field rename upstream shows up as a validation error
naming the field, not as a silent null."""

SPOTLIGHT_FEED = """
query SpotlightFeed($country: String!, $locale: String!, $storiesToFilter: [Long!]!, $freeformTweaks: String) {
  spotlightFeed(country: $country, locale: $locale, storiesToFilter: $storiesToFilter, freeformTweaks: $freeformTweaks) {
    type
    stories {
      story {
        id
        tapId
        title
        subtitle
        thumbnailUrl
        canonicalUrlSuffix
        emoji
        type
        snaps {
          id
          snapMediaType
          snapUrls { mediaUrl mediaPreviewUrl }
          snapTitle
          snapSubtitles
          audioTranscriptionObjectUrl
        }
      }
      metadata {
        hashtags
        contextCards { contextType title subtitle url thumbnailUrl hasBadge snapcodeUrl thumbnailType }
        videoMetadata {
          name
          description
          thumbnailUrl
          uploadDateMs
          contentUrl
          creator { username url }
        }
        engagementStats { viewCount shareCount commentCount boostCount recommendCount }
      }
    }
  }
}
"""

DISCOVER_FEED = """
query DiscoverFeed($first: Int!, $country: String!, $locale: String, $storyTapIdsToFilter: [Long!]) {
  discoverFeed(first: $first, country: $country, locale: $locale, storyTapIdsToFilter: $storyTapIdsToFilter) {
    stories {
      id
      type
      snaps {
        id
        snapUrls { mediaUrl mediaPreviewUrl }
        snapMediaType
        intervalStartTimeMs
      }
      title
      thumbnailUrl
      tapId
      publishedTimeInSec
      ... on PremiumPublisherStory { videoTrackUrl }
      creator {
        businessProfileId
        username
        title
        snapcodeImageUrl
        badge
        bio
        profilePictureUrl
        squareHeroImageUrl
        __typename
        ... on Publisher { primaryColor }
      }
    }
  }
}
"""

PREMIUM_STORY = """
query PremiumStory($storyId: String!, $country: String!) {
  premiumStory(storyId: $storyId, country: $country) {
    publishedTimeInSec
    seasonNumber
    episodeNumber
    ownerBusinessProfileId
    story {
      id
      type
      title
      subtitle
      thumbnailUrl
      tapId
      videoTrackUrl
      snaps {
        index
        id
        snapMediaType
        timestampInSec
        snapTitle
        intervalStartTimeMs
        snapUrls { mediaUrl mediaPreviewUrl overlayUrl }
      }
    }
  }
}
"""

PUBLISHED_PREMIUM_STORIES = """
query PublishedPremiumStories($businessProfileId: ID!, $seasonId: ID, $cursor: ID!, $limit: Int!, $country: String!) {
  publisher(businessProfileId: $businessProfileId) {
    businessProfileId
    publishedPremiumStoriesConnection(first: $limit, from: $cursor, seasonId: $seasonId, country: $country) {
      pageInfo { nextCursor hasNextPage }
      premiumStories {
        publishedTimeInSec
        seasonNumber
        episodeNumber
        ownerBusinessProfileId
        story {
          id
          title
          subtitle
          thumbnailUrl
          type
          videoTrackUrl
        }
      }
    }
  }
}
"""
