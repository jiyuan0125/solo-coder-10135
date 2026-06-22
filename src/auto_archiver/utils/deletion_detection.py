"""
Deletion Detection Utilities

Provides a best-effort detection of deleted, missing, or unavailable content
across various social media platforms.

Detection priority (from strongest to weakest signal):
1. HTTP status codes (404, 410, 451) - definitive structural signals
2. yt-dlp metadata (availability field explicitly marked as unavailable)
3. Error messages from extractors that explicitly indicate deletion
4. Page title matches strong platform-specific indicators
5. HTML content matches strong indicators (only as last resort)

This module helps identify removed content, helps to:
- Document content that existed but was deleted
- Track patterns of content removal
- Preserve metadata about missing content
"""

from typing import Optional, Dict, List
from auto_archiver.utils.custom_logger import logger
from urllib.parse import urlparse


class DeletionIndicators:
    """
    Platform-specific indicators that content has been deleted or is unavailable.

    NOTE: Only use long, specific phrases that unambiguously indicate the main
    content is deleted. Avoid short phrases that could appear in page furniture
    (sidebars, footers, comments, navigation) on normal pages.
    """

    # Twitter/X deletion indicators - long, specific phrases
    TWITTER = [
        "Hmm...this page doesn't exist",
        "Try searching for something else",
        "This Tweet is unavailable",
        "This account doesn't exist",
        "This Tweet has been deleted",
        "This account has been suspended",
        "Sorry, that page doesn't exist",
        "The Tweet you're looking for isn't available",
    ]

    # Facebook deletion indicators
    FACEBOOK = [
        "This content isn't available right now",
        "Sorry, this content isn't available",
        "This content is no longer available",
        "The link you followed may be broken",
        "This content is no longer on Facebook",
        "This page isn't available",
    ]

    # Instagram deletion indicators
    INSTAGRAM = [
        "Sorry, this page isn't available",
        "The link you followed may be broken",
        "Media not found or unavailable",
        "This post is no longer available",
        "This account is private",
    ]

    # TikTok deletion indicators
    TIKTOK = [
        "Couldn't find this account",
        "This video is no longer available",
        "This video is currently unavailable",
        "Video not found",
        "This video may have been deleted",
    ]

    # YouTube deletion indicators
    YOUTUBE = [
        "This video isn't available anymore",
        "This video has been removed",
        "This video is no longer available",
        "This video is private",
        "This video has been removed by the uploader",
        "This video has been deleted",
        "This video is unavailable",
    ]

    # Reddit deletion indicators - ONLY long specific phrases
    # Removed short "[removed]" and "[deleted]" because they appear in comment sections everywhere
    REDDIT = [
        "this post has been removed by the moderators",
        "this post has been removed by a moderator",
        "this comment has been removed",
        "this post was removed",
        "there doesn't seem to be anything here",
        "this community has been banned",
        "this account has been suspended",
    ]

    # VK deletion indicators
    VK = [
        "Post deleted",
        "Page not found",
        "Content unavailable",
        "Access denied",
    ]

    # Telegram deletion indicators
    TELEGRAM = [
        "Message not found",
        "Deleted message",
        "Channel is private",
    ]

    # Generic indicators - use ONLY long, specific phrases
    # Removed short "page not found" and "access denied" as they appear in navigation
    GENERIC_STRONG = [
        "has been permanently removed",
        "content has been removed",
        "no longer exists",
        "has been deleted",
        "is no longer available",
        "content unavailable",
    ]

    # Generic indicators for titles (can be slightly more relaxed since title is small)
    GENERIC_TITLE = [
        "page not found",
        "not found",
        "deleted",
        "removed",
        "unavailable",
    ]

    @classmethod
    def strong_indicators_for_url(cls, url: str) -> List[str]:
        """Returns strong platform-specific indicators for content matching."""
        platform = _extract_platform(url)

        indicators_map = {
            "twitter": cls.TWITTER,
            "facebook": cls.FACEBOOK,
            "instagram": cls.INSTAGRAM,
            "tiktok": cls.TIKTOK,
            "youtube": cls.YOUTUBE,
            "reddit": cls.REDDIT,
            "vk": cls.VK,
            "telegram": cls.TELEGRAM,
        }
        return indicators_map.get(platform, [])

    @classmethod
    def title_indicators_for_url(cls, url: str) -> List[str]:
        """Returns indicators suitable for page title checking."""
        return cls.strong_indicators_for_url(url) + cls.GENERIC_TITLE

    @classmethod
    def for_url(cls, url: str) -> List[str]:
        """
        Backward compatibility method - returns strong indicators for the URL.
        Prefer strong_indicators_for_url() or title_indicators_for_url() for clarity.
        """
        return cls.strong_indicators_for_url(url)

    @classmethod
    def all_indicators(cls) -> List[str]:
        """Backward compatibility method - returns all strong indicators from all platforms."""
        return (
            cls.TWITTER + cls.FACEBOOK + cls.INSTAGRAM + cls.TIKTOK + cls.YOUTUBE + cls.REDDIT + cls.VK + cls.TELEGRAM
        )


def detect_deletion(
    html_content: str = None,
    page_title: str = None,
    error_message: str = None,
    url: str = None,
    video_data: dict = None,
    http_status_code: int = None,
) -> Optional[Dict[str, any]]:
    """
    Best-effort deletion detection across multiple signals, ordered by signal strength.

    Detection priority (strongest to weakest):
    1. HTTP status codes (404, 410, 451) - definitive structural signals
    2. yt-dlp metadata (availability explicitly marked as unavailable/deleted/private)
    3. Error messages that explicitly indicate deletion
    4. Page title matches strong indicators
    5. HTML content matches strong indicators (only as last resort)

    Args:
        html_content: Raw HTML source of the page
        page_title: Browser page title
        error_message: Any error message from the extractor
        url: The URL being archived (for platform-specific detection)
        video_data: Video metadata from yt-dlp or other extractors
        http_status_code: HTTP status code from the request (e.g. 404, 410, 451)

    Returns:
        Dictionary with deletion details if detected, None otherwise.
        Format: {
            "is_deleted": True,
            "indicator": "specific text that was found",
            "source": "http_status|video_metadata|error_message|page_title|html_content",
            "platform": "twitter|facebook|etc"
        }
    """

    platform = _extract_platform(url) if url else "unknown"

    # 1. FIRST: Check HTTP status codes - these are definitive structural signals
    if http_status_code is not None:
        if http_status_code in [404, 410, 451]:
            status_text = {
                404: "Not Found",
                410: "Gone (permanently deleted)",
                451: "Unavailable For Legal Reasons",
            }
            logger.info(
                f"Deletion detected via HTTP status code {http_status_code} ({status_text[http_status_code]}) for {url}"
            )
            return {
                "is_deleted": True,
                "indicator": f"HTTP {http_status_code}: {status_text[http_status_code]}",
                "source": "http_status",
                "platform": platform,
            }

    # 2. SECOND: Check yt-dlp metadata - explicit availability flags are reliable
    if video_data:
        availability = video_data.get("availability")
        if availability in ["unavailable", "private", "deleted"]:
            logger.info(f"Deletion detected in metadata: availability={availability}")
            return {
                "is_deleted": True,
                "indicator": f"availability: {availability}",
                "source": "video_metadata",
                "platform": platform,
            }

        # Check if the video was explicitly marked as deleted in metadata
        if video_data.get("duration") == 0 and not video_data.get("title"):
            logger.info("Deletion detected: video has zero duration and no title")
            return {
                "is_deleted": True,
                "indicator": "video metadata: zero duration, no title",
                "source": "video_metadata",
                "platform": platform,
            }

    # 3. THIRD: Check error messages for explicit deletion indicators
    strong_indicators = DeletionIndicators.strong_indicators_for_url(url)
    if error_message:
        error_str = str(error_message).lower()
        for indicator in strong_indicators:
            if indicator.lower() in error_str:
                logger.info(f"Deletion detected in error message: '{indicator}' for {url}")
                return {
                    "is_deleted": True,
                    "indicator": indicator,
                    "source": "error_message",
                    "platform": platform,
                }

    # 4. FOURTH: Check page title - title is a small, focused area, less prone to false positives
    title_indicators = DeletionIndicators.title_indicators_for_url(url)
    if page_title:
        title_lower = page_title.lower()
        for indicator in title_indicators:
            if indicator.lower() in title_lower:
                logger.info(f"Deletion detected in page title: '{indicator}' for {url}")
                return {
                    "is_deleted": True,
                    "indicator": indicator,
                    "source": "page_title",
                    "platform": platform,
                }

    # 5. LAST: Check HTML content - ONLY use strong, specific indicators
    # This is the most prone to false positives, so only check if we didn't find any other signal
    if html_content:
        html_lower = html_content.lower()
        for indicator in strong_indicators:
            if indicator.lower() in html_lower:
                # For HTML matches, require a longer indicator to reduce false positives
                # (avoid matching things that could be in sidebar/comments/footer)
                if len(indicator) >= 15:
                    logger.info(
                        f"Deletion detected in HTML content: '{indicator}' for {url} "
                        f"(indicator length: {len(indicator)} chars)"
                    )
                    return {
                        "is_deleted": True,
                        "indicator": indicator,
                        "source": "html_content",
                        "platform": platform,
                    }
                else:
                    logger.debug(
                        f"Skipping short indicator '{indicator}' in HTML for {url} "
                        f"(too prone to false positives, length: {len(indicator)} chars)"
                    )

    return None


def _extract_platform(url: str) -> str:
    """Extracts platform name from URL."""
    parsed = urlparse(url)
    domain = parsed.netloc

    if "twitter.com" in domain or "x.com" in domain:
        return "twitter"
    elif "facebook.com" in domain or "fb.com" in domain:
        return "facebook"
    elif "instagram.com" in domain:
        return "instagram"
    elif "tiktok.com" in domain:
        return "tiktok"
    elif "youtube.com" in domain or "youtu.be" in domain:
        return "youtube"
    elif "reddit.com" in domain:
        return "reddit"
    elif "vk.com" in domain:
        return "vk"
    elif "t.me" in domain:
        return "telegram"
    return "unknown"


def flag_as_deleted(metadata, deletion_info: Dict[str, any]) -> None:
    """
    Flags metadata object as deleted/unavailable.
    Adds tentative deletion information to the metadata object.

    Args:
        metadata: Metadata object to update
        deletion_info: Dictionary from detect_deletion()
    """
    metadata.set("deletion_detected", True)
    metadata.set("deletion_indicator", deletion_info.get("indicator"))
    metadata.set("deletion_source", deletion_info.get("source"))
    metadata.set("deletion_platform", deletion_info.get("platform"))
    metadata.status = "deleted_or_unavailable"

    logger.debug(
        f"Content marked as deleted/unavailable: "
        f"platform={deletion_info.get('platform')}, "
        f"indicator='{deletion_info.get('indicator')}', "
        f"source={deletion_info.get('source')}"
    )
