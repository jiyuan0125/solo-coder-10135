"""
Deletion Detection Utilities

Provides a best-effort detection of deleted, missing, or unavailable content
across various social media platforms based on presence of expected keywords.

This module helps identify removed content, helps to:
- Document content that existed but was deleted
- Track patterns of content removal
- Preserve metadata about missing content
"""

import re
from typing import Optional, Dict, List, Tuple
from auto_archiver.utils.custom_logger import logger
from urllib.parse import urlparse

DELETED_HTTP_STATUSES = {404, 410, 451}

_SHORT_PAGE_THRESHOLD = 300


class DeletionIndicators:
    """
    Platform-specific indicators that content has been deleted or is unavailable.

    Indicators are split into two categories:
    - STRONG: Specific enough to trust as a deletion signal when found in
      page titles, error messages, or short HTML pages.
    - CONTEXT_REQUIRED: Short or generic phrases that could appear in normal
      page content (sidebars, navigation, comments). These are only used for
      page title matching and never for raw HTML content scanning.
    """

    TWITTER_STRONG = [
        "Hmm...this page doesn't exist",
        "This Tweet is unavailable",
        "This account doesn't exist",
        "This Tweet has been deleted",
        "This account has been suspended",
        "Sorry, that page doesn't exist",
        "The Tweet you're looking for isn't available",
    ]
    TWITTER_CONTEXT_REQUIRED = [
        "Try searching for something else",
    ]

    FACEBOOK_STRONG = [
        "This content isn't available",
        "Sorry, this content isn't available",
        "This content is no longer available",
        "The link you followed may be broken",
        "This content is no longer on Facebook",
    ]
    FACEBOOK_CONTEXT_REQUIRED = [
        "Page Not Found",
        "Content Not Found",
    ]

    INSTAGRAM_STRONG = [
        "Sorry, this page isn't available",
        "The link you followed may be broken",
        "Media not found or unavailable",
        "This post is no longer available",
    ]
    INSTAGRAM_CONTEXT_REQUIRED = [
        "This account is private",
    ]

    TIKTOK_STRONG = [
        "Couldn't find this account",
        "This video is no longer available",
        "This video is currently unavailable",
        "This video may have been deleted",
    ]
    TIKTOK_CONTEXT_REQUIRED = [
        "Video not found",
    ]

    YOUTUBE_STRONG = [
        "This video isn't available anymore",
        "This video has been removed",
        "This video is no longer available",
        "This video has been removed by the uploader",
        "This video has been deleted",
    ]
    YOUTUBE_CONTEXT_REQUIRED = [
        "This video is private",
    ]

    REDDIT_STRONG = [
        "this post has been removed by a moderator",
        "this comment has been removed by a moderator",
        "sorry, this post has been removed",
        "sorry, this comment has been removed",
        "there doesn't seem to be anything here",
    ]
    REDDIT_CONTEXT_REQUIRED = [
        "[removed]",
        "[deleted]",
    ]

    VK_STRONG = [
        "Post deleted",
    ]
    VK_CONTEXT_REQUIRED = [
        "Page not found",
        "Content unavailable",
        "Access denied",
    ]

    TELEGRAM_STRONG = [
        "Message not found",
        "Deleted message",
    ]
    TELEGRAM_CONTEXT_REQUIRED = [
        "Channel is private",
    ]

    GENERIC_STRONG = [
        "has been removed",
        "no longer available",
        "content removed",
    ]
    GENERIC_CONTEXT_REQUIRED = [
        "page not found",
        "access denied",
    ]

    @classmethod
    def _platform_data(cls, platform: str) -> Tuple[List[str], List[str]]:
        mapping = {
            "twitter": (cls.TWITTER_STRONG, cls.TWITTER_CONTEXT_REQUIRED),
            "facebook": (cls.FACEBOOK_STRONG, cls.FACEBOOK_CONTEXT_REQUIRED),
            "instagram": (cls.INSTAGRAM_STRONG, cls.INSTAGRAM_CONTEXT_REQUIRED),
            "tiktok": (cls.TIKTOK_STRONG, cls.TIKTOK_CONTEXT_REQUIRED),
            "youtube": (cls.YOUTUBE_STRONG, cls.YOUTUBE_CONTEXT_REQUIRED),
            "reddit": (cls.REDDIT_STRONG, cls.REDDIT_CONTEXT_REQUIRED),
            "vk": (cls.VK_STRONG, cls.VK_CONTEXT_REQUIRED),
            "telegram": (cls.TELEGRAM_STRONG, cls.TELEGRAM_CONTEXT_REQUIRED),
        }
        return mapping.get(platform, (cls.GENERIC_STRONG, cls.GENERIC_CONTEXT_REQUIRED))

    @classmethod
    def for_url(cls, url: str) -> Tuple[List[str], List[str]]:
        platform = _extract_platform(url)
        p_strong, p_context = cls._platform_data(platform)
        g_strong, g_context = cls.GENERIC_STRONG, cls.GENERIC_CONTEXT_REQUIRED
        return (p_strong + g_strong, p_context + g_context)

    @classmethod
    def all_indicators(cls) -> Tuple[List[str], List[str]]:
        all_strong = (
            cls.TWITTER_STRONG
            + cls.FACEBOOK_STRONG
            + cls.INSTAGRAM_STRONG
            + cls.TIKTOK_STRONG
            + cls.YOUTUBE_STRONG
            + cls.REDDIT_STRONG
            + cls.VK_STRONG
            + cls.TELEGRAM_STRONG
            + cls.GENERIC_STRONG
        )
        all_context = (
            cls.TWITTER_CONTEXT_REQUIRED
            + cls.FACEBOOK_CONTEXT_REQUIRED
            + cls.INSTAGRAM_CONTEXT_REQUIRED
            + cls.TIKTOK_CONTEXT_REQUIRED
            + cls.YOUTUBE_CONTEXT_REQUIRED
            + cls.REDDIT_CONTEXT_REQUIRED
            + cls.VK_CONTEXT_REQUIRED
            + cls.TELEGRAM_CONTEXT_REQUIRED
            + cls.GENERIC_CONTEXT_REQUIRED
        )
        return (all_strong, all_context)


def _strip_html_tags(html: str) -> str:
    text = re.sub(r"<script[^>]*>.*?</script>", "", html, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<style[^>]*>.*?</style>", "", text, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def _check_indicators_in_text(indicators: List[str], text: str) -> Optional[str]:
    text_lower = text.lower()
    for indicator in indicators:
        if indicator.lower() in text_lower:
            return indicator
    return None


def detect_deletion(
    html_content: str = None,
    page_title: str = None,
    error_message: str = None,
    url: str = None,
    video_data: dict = None,
    http_status: int = None,
) -> Optional[Dict[str, any]]:
    """
    Best-effort deletion detection across multiple signals.

    Checks HTTP status, page titles, error messages, video metadata, and HTML
    content for indicators that content has been deleted or is unavailable.

    Indicators are split into two categories:
    - Strong indicators: specific enough to trust in page titles, error messages,
      short HTML pages, or video metadata.
    - Context-required indicators: short or generic phrases that could appear in
      normal content. These are ONLY checked against page titles and error
      messages, never against raw HTML content.

    For HTML content, deletion is only flagged when:
    - A strong indicator is found AND the visible text is short (likely an error
      page rather than a full content page with sidebars/navigation).

    Args:
        html_content: Raw HTML source of the page
        page_title: Browser page title
        error_message: Any error message from the extractor
        url: The URL being archived (for platform-specific detection)
        video_data: Video metadata from yt-dlp or other extractors
        http_status: HTTP response status code

    Returns:
        Dictionary with deletion details if detected, None otherwise.
        Format: {
            "is_deleted": True,
            "indicator": "specific text that was found",
            "source": "http_status|html_content|page_title|error_message|video_metadata",
            "platform": "twitter|facebook|etc"
        }
    """

    if url:
        strong_indicators, context_required_indicators = DeletionIndicators.for_url(url)
        platform = _extract_platform(url)
    else:
        strong_indicators, context_required_indicators = DeletionIndicators.all_indicators()
        platform = "unknown"

    all_indicators = strong_indicators + context_required_indicators

    if http_status and http_status in DELETED_HTTP_STATUSES:
        logger.info(f"Deletion detected via HTTP status {http_status} for {url}")
        return {
            "is_deleted": True,
            "indicator": f"HTTP {http_status}",
            "source": "http_status",
            "platform": platform,
        }

    if page_title:
        matched = _check_indicators_in_text(all_indicators, page_title)
        if matched:
            logger.info(f"Deletion detected in page title: '{matched}' found for {url}")
            return {"is_deleted": True, "indicator": matched, "source": "page_title", "platform": platform}

    if error_message:
        matched = _check_indicators_in_text(all_indicators, str(error_message))
        if matched:
            logger.info(f"Deletion detected in error: '{matched}' found for {url}")
            return {"is_deleted": True, "indicator": matched, "source": "error_message", "platform": platform}

    if video_data:
        if video_data.get("availability") in ["unavailable", "private", "deleted"]:
            logger.info(f"Deletion detected in metadata: availability={video_data.get('availability')}")
            return {
                "is_deleted": True,
                "indicator": f"availability: {video_data.get('availability')}",
                "source": "video_metadata",
                "platform": platform,
            }

        for key in ["title", "description", "fulltitle"]:
            if key in video_data:
                matched = _check_indicators_in_text(strong_indicators, str(video_data[key]))
                if matched:
                    logger.info(f"Deletion detected in {key}: '{matched}'")
                    return {
                        "is_deleted": True,
                        "indicator": matched,
                        "source": f"video_metadata_{key}",
                        "platform": platform,
                    }

    if html_content:
        visible_text = _strip_html_tags(html_content)
        matched = _check_indicators_in_text(strong_indicators, visible_text)
        if matched:
            if len(visible_text) <= _SHORT_PAGE_THRESHOLD:
                logger.info(
                    f"Deletion detected in short HTML page: '{matched}' found for {url}"
                )
                return {
                    "is_deleted": True,
                    "indicator": matched,
                    "source": "html_content",
                    "platform": platform,
                }
            logger.debug(
                f"Strong indicator '{matched}' found in long HTML page for {url}, "
                f"not flagging as deleted (likely in sidebar/navigation). "
                f"Visible text length: {len(visible_text)}"
            )

    return None


def _extract_platform(url: str) -> str:
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
