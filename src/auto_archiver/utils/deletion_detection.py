"""
Deletion Detection Utilities

Provides a best-effort detection of deleted, missing, or unavailable content
across various social media platforms based on presence of expected keywords.

This module helps identify removed content, helps to:
- Document content that existed but was deleted
- Track patterns of content removal
- Preserve metadata about missing content

Detection uses multiple signal strengths:
- Strong: HTTP status codes (404/410/451), yt-dlp availability metadata
- Medium: Page title matches, multiple indicator matches in main content
- Weak (insufficient alone): Single substring match in full HTML
"""

import re
from typing import Optional, Dict, List
from auto_archiver.utils.custom_logger import logger
from urllib.parse import urlparse

_DELETION_HTTP_CODES = {404, 410, 451}

_STRIP_TAGS_RE = re.compile(r"<[^>]+>")
_STRIP_NON_CONTENT_SECTIONS_RE = re.compile(
    r"<(?:nav|footer|aside|header|script|style|noscript)[^>]*>.*?</(?:nav|footer|aside|header|script|style|noscript)>",
    re.DOTALL | re.IGNORECASE,
)
_MAIN_CONTENT_RE = re.compile(
    r"<(?:main|article)[^>]*>(.*?)</(?:main|article)>",
    re.DOTALL | re.IGNORECASE,
)
_ROLE_MAIN_RE = re.compile(
    r'<[^>]+role=["\']main["\'][^>]*>(.*?)</(?:div|section|main)>',
    re.DOTALL | re.IGNORECASE,
)
_MIN_INDICATOR_LENGTH_FOR_HTML = 15
_MAIN_CONTENT_SHORT_THRESHOLD = 300


class DeletionIndicators:
    """
    Platform-specific indicators that content has been deleted or is unavailable.

    Short/generic strings that frequently appear in normal pages (sidebars,
    comments, navigation) have been removed or replaced with longer, more
    specific alternatives to reduce false positives.
    """

    TWITTER = [
        "Hmm...this page doesn't exist",
        "This Tweet is unavailable",
        "This account doesn't exist",
        "This Tweet has been deleted",
        "This account has been suspended",
        "Sorry, that page doesn't exist",
        "The Tweet you're looking for isn't available",
    ]

    FACEBOOK = [
        "This content isn't available",
        "Sorry, this content isn't available",
        "This content is no longer available",
        "The link you followed may be broken",
        "This content is no longer on Facebook",
    ]

    INSTAGRAM = [
        "Sorry, this page isn't available",
        "The link you followed may be broken",
        "Media not found or unavailable",
        "This post is no longer available",
    ]

    TIKTOK = [
        "Couldn't find this account",
        "This video is no longer available",
        "This video is currently unavailable",
        "This video may have been deleted",
    ]

    YOUTUBE = [
        "This video isn't available anymore",
        "This video has been removed",
        "This video is no longer available",
        "This video is private",
        "This video has been removed by the uploader",
        "This video has been deleted",
    ]

    REDDIT = [
        "this post has been removed",
        "this comment has been removed",
        "there doesn't seem to be anything here",
        "sorry, we couldn't find the page you were looking for",
        "this community doesn't exist",
        "this subreddit was banned",
    ]

    VK = [
        "Post deleted",
    ]

    TELEGRAM = [
        "Message not found",
        "Channel is private",
        "This chat doesn't exist",
    ]

    GENERIC = []

    @classmethod
    def all_indicators(cls) -> List[str]:
        return (
            cls.TWITTER
            + cls.FACEBOOK
            + cls.INSTAGRAM
            + cls.TIKTOK
            + cls.YOUTUBE
            + cls.REDDIT
            + cls.VK
            + cls.TELEGRAM
            + cls.GENERIC
        )

    @classmethod
    def for_url(cls, url: str) -> List[str]:
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
        return indicators_map.get(platform, cls.all_indicators())

    @classmethod
    def indicators_for_html(cls, url: str = None) -> List[str]:
        indicators = cls.for_url(url) if url else cls.all_indicators()
        return [ind for ind in indicators if len(ind) >= _MIN_INDICATOR_LENGTH_FOR_HTML]


def _extract_main_content_text(html: str) -> str:
    """
    Extracts visible text from the main content area of an HTML page.

    Strips navigation, footer, aside, header, script, and style sections,
    then tries to find <main> or <article> content. Falls back to the full
    body with non-content sections removed.
    """
    cleaned = _STRIP_NON_CONTENT_SECTIONS_RE.sub("", html)

    main_match = _MAIN_CONTENT_RE.search(cleaned)
    if not main_match:
        main_match = _ROLE_MAIN_RE.search(cleaned)

    content_html = main_match.group(1) if main_match else cleaned
    text = _STRIP_TAGS_RE.sub(" ", content_html)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def detect_deletion(
    html_content: str = None,
    page_title: str = None,
    error_message: str = None,
    url: str = None,
    video_data: dict = None,
    status_code: int = None,
) -> Optional[Dict[str, any]]:
    """
    Best-effort deletion detection across multiple signals.

    Prioritizes structural signals (HTTP status codes, yt-dlp metadata) over
    content-based heuristics. For HTML content, only the main content area is
    checked and short/generic indicators are excluded to reduce false positives.

    Args:
        html_content: Raw HTML source of the page
        page_title: Browser page title
        error_message: Any error message from the extractor
        url: The URL being archived (for platform-specific detection)
        video_data: Video metadata from yt-dlp or other extractors
        status_code: HTTP response status code

    Returns:
        Dictionary with deletion details if detected, None otherwise.
    """
    if url:
        platform = _extract_platform(url)
    else:
        platform = "unknown"

    if status_code and status_code in _DELETION_HTTP_CODES:
        logger.info(f"Deletion detected via HTTP status code {status_code} for {url}")
        return {
            "is_deleted": True,
            "indicator": f"HTTP {status_code}",
            "source": "http_status",
            "platform": platform,
        }

    if video_data:
        if video_data.get("availability") in ["unavailable", "private", "deleted"]:
            logger.info(f"Deletion detected in metadata: availability={video_data.get('availability')}")
            return {
                "is_deleted": True,
                "indicator": f"availability: {video_data.get('availability')}",
                "source": "video_metadata",
                "platform": platform,
            }

    all_indicators = DeletionIndicators.for_url(url) if url else DeletionIndicators.all_indicators()
    html_indicators = DeletionIndicators.indicators_for_html(url)

    if page_title:
        for indicator in all_indicators:
            if indicator.lower() in page_title.lower():
                logger.info(f"Deletion detected in page title: '{indicator}' found for {url}")
                return {"is_deleted": True, "indicator": indicator, "source": "page_title", "platform": platform}

    if error_message:
        for indicator in all_indicators:
            if indicator.lower() in str(error_message).lower():
                logger.info(f"Deletion detected in error: '{indicator}' found for {url}")
                return {"is_deleted": True, "indicator": indicator, "source": "error_message", "platform": platform}

    if html_content:
        main_text = _extract_main_content_text(html_content)
        if not main_text:
            return None

        matched_indicators = []
        for indicator in html_indicators:
            if indicator.lower() in main_text.lower():
                matched_indicators.append(indicator)

        if not matched_indicators:
            return None

        is_short_page = len(main_text) < _MAIN_CONTENT_SHORT_THRESHOLD

        if is_short_page:
            logger.info(
                f"Deletion detected in short main content: '{matched_indicators[0]}' found for {url}"
            )
            return {
                "is_deleted": True,
                "indicator": matched_indicators[0],
                "source": "html_content",
                "platform": platform,
            }

        if len(matched_indicators) >= 2:
            logger.info(
                f"Deletion detected: multiple indicators ({matched_indicators}) in main content for {url}"
            )
            return {
                "is_deleted": True,
                "indicator": matched_indicators[0],
                "source": "html_content",
                "platform": platform,
            }

    if video_data:
        for key in ["title", "description", "fulltitle"]:
            if key in video_data:
                for indicator in all_indicators:
                    if indicator.lower() in str(video_data[key]).lower():
                        logger.info(f"Deletion detected in {key}: '{indicator}'")
                        return {
                            "is_deleted": True,
                            "indicator": indicator,
                            "source": f"video_metadata_{key}",
                            "platform": platform,
                        }

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
