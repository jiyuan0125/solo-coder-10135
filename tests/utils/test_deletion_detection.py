"""
Tests for deletion detection utilities.

These tests verify the current best-effort by the auto-archiver
to detect when content has been deleted or is unavailable across
various platforms.
"""

from auto_archiver.utils.deletion_detection import (
    detect_deletion,
    flag_as_deleted,
    DeletionIndicators,
    _extract_main_content_text,
)
from auto_archiver.core.metadata import Metadata


class TestDeletionIndicators:
    def test_twitter_indicators(self):
        assert "Hmm...this page doesn't exist" in DeletionIndicators.TWITTER
        assert "This Tweet is unavailable" in DeletionIndicators.TWITTER

    def test_no_short_indicators_in_reddit(self):
        assert "[removed]" not in DeletionIndicators.REDDIT
        assert "[deleted]" not in DeletionIndicators.REDDIT

    def test_no_short_generic_indicators(self):
        assert "access denied" not in DeletionIndicators.GENERIC
        assert "page not found" not in DeletionIndicators.GENERIC
        assert "has been removed" not in DeletionIndicators.GENERIC

    def test_no_short_vk_indicators(self):
        assert "Access denied" not in DeletionIndicators.VK
        assert "Page not found" not in DeletionIndicators.VK
        assert "Content unavailable" not in DeletionIndicators.VK

    def test_no_short_telegram_indicators(self):
        assert "Deleted message" not in DeletionIndicators.TELEGRAM

    def test_platform_specific_indicators(self):
        twitter_indicators = DeletionIndicators.for_url("https://twitter.com/user/status/123")
        assert any("page doesn't exist" in ind.lower() for ind in twitter_indicators)

        instagram_indicators = DeletionIndicators.for_url("https://instagram.com/p/ABC123")
        assert any("page isn't available" in ind.lower() for ind in instagram_indicators)

    def test_generic_not_combined_with_platform(self):
        twitter_indicators = DeletionIndicators.for_url("https://twitter.com/user/status/123")
        for ind in twitter_indicators:
            assert ind not in DeletionIndicators.GENERIC

    def test_indicators_for_html_filters_short(self):
        html_indicators = DeletionIndicators.indicators_for_html("https://twitter.com/user/status/123")
        for ind in html_indicators:
            assert len(ind) >= 15


class TestExtractMainContentText:
    def test_extracts_main_tag(self):
        html = "<html><body><nav>nav stuff</nav><main>main content here</main><footer>footer</footer></body></html>"
        text = _extract_main_content_text(html)
        assert "main content here" in text
        assert "nav stuff" not in text
        assert "footer" not in text

    def test_extracts_article_tag(self):
        html = "<html><body><article>article content</article></body></html>"
        text = _extract_main_content_text(html)
        assert "article content" in text

    def test_strips_non_content_sections(self):
        html = "<html><body><nav>navigation</nav><aside>sidebar</aside><footer>footer</footer><p>real content</p></body></html>"
        text = _extract_main_content_text(html)
        assert "navigation" not in text
        assert "sidebar" not in text
        assert "footer" not in text
        assert "real content" in text

    def test_strips_script_and_style(self):
        html = "<html><body><script>var x = 1;</script><style>.cls{}</style><p>content</p></body></html>"
        text = _extract_main_content_text(html)
        assert "var x" not in text
        assert ".cls" not in text
        assert "content" in text


class TestDetectDeletion:
    def test_detect_via_http_status_code(self):
        result = detect_deletion(url="https://example.com/page", status_code=404)
        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "http_status"
        assert "404" in result["indicator"]

    def test_detect_via_http_410(self):
        result = detect_deletion(url="https://example.com/page", status_code=410)
        assert result is not None
        assert result["source"] == "http_status"

    def test_detect_via_http_451(self):
        result = detect_deletion(url="https://example.com/page", status_code=451)
        assert result is not None
        assert result["source"] == "http_status"

    def test_no_detect_via_http_200(self):
        result = detect_deletion(url="https://example.com/page", status_code=200)
        assert result is None

    def test_detect_deletion_in_html_short_page(self):
        html = "<html><body><main>Hmm...this page doesn't exist. Try searching for something else.</main></body></html>"
        url = "https://twitter.com/user/status/123"
        result = detect_deletion(html_content=html, url=url)
        assert result is not None
        assert result["is_deleted"] is True
        assert result["platform"] == "twitter"
        assert result["source"] == "html_content"
        assert "page doesn't exist" in result["indicator"].lower()

    def test_no_false_positive_from_sidebar(self):
        html = (
            "<html><body>"
            "<nav>Home About</nav>"
            "<aside>View removed posts and page not found tips</aside>"
            "<main>This is a normal Reddit post with lots of interesting content about technology and science. "
            "The user shared their experience with various programming languages and frameworks. "
            "Many people commented on the post with their own stories and opinions about the topic at hand. "
            "This is clearly a normal, active post with lots of engagement from the community.</main>"
            "<footer>Terms of Service Privacy Policy</footer>"
            "</body></html>"
        )
        url = "https://reddit.com/r/test/comments/abc123"
        result = detect_deletion(html_content=html, url=url)
        assert result is None

    def test_no_false_positive_from_reddit_removed(self):
        html = (
            "<html><body>"
            "<aside>View removed posts</aside>"
            "<main>This is a long normal Reddit post with lots of content. "
            "The post discusses various topics and has many comments. "
            "Some comments mention removed but the post itself is fine. "
            "This content is clearly still available and active.</main>"
            "</body></html>"
        )
        url = "https://reddit.com/r/test/comments/abc123"
        result = detect_deletion(html_content=html, url=url)
        assert result is None

    def test_detect_deletion_in_page_title(self):
        title = "Sorry, this page isn't available"
        url = "https://instagram.com/p/ABC123"
        result = detect_deletion(page_title=title, url=url)
        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "page_title"

    def test_detect_deletion_in_error_message(self):
        error = "yt_dlp.utils.DownloadError: This video is no longer available"
        url = "https://youtube.com/watch?v=abc123"
        result = detect_deletion(error_message=error, url=url)
        assert result is not None
        assert result["is_deleted"] is True
        assert result["platform"] == "youtube"
        assert result["source"] == "error_message"

    def test_detect_deletion_in_video_metadata(self):
        video_data = {"availability": "unavailable", "title": "Private video"}
        url = "https://youtube.com/watch?v=test123"
        result = detect_deletion(video_data=video_data, url=url)
        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "video_metadata"
        assert "availability" in result["indicator"]

    def test_no_deletion_detected(self):
        html = "<html><body><h1>Welcome to my page</h1><p>This is normal content.</p></body></html>"
        title = "My Normal Page"
        url = "https://example.com/page"
        result = detect_deletion(html_content=html, page_title=title, url=url)
        assert result is None

    def test_instagram_media_not_found(self):
        error = "Media not found or unavailable"
        url = "https://instagram.com/p/ABC123"
        result = detect_deletion(error_message=error, url=url)
        assert result is not None
        assert result["platform"] == "instagram"
        assert "not found" in result["indicator"].lower()

    def test_long_page_single_indicator_not_flagged(self):
        html = (
            "<html><body><main>"
            "This is a very long normal page with lots of content about various topics. "
            "It includes discussion about social media, technology, and more. "
            "The page has many paragraphs of text that clearly indicate it's a normal page. "
            "Someone might mention that this video has been deleted in a comment, "
            "but that's just part of the discussion, not the page itself being deleted. "
            "The rest of the content is clearly still available and active. "
            "There are many more paragraphs of text here to make it a long page. "
            "This ensures the single indicator match is not enough to flag the whole page."
            "</main></body></html>"
        )
        url = "https://youtube.com/watch?v=abc123"
        result = detect_deletion(html_content=html, url=url)
        assert result is None

    def test_http_status_takes_priority_over_html(self):
        html = "<html><body><main>Some content</main></body></html>"
        url = "https://example.com/page"
        result = detect_deletion(html_content=html, url=url, status_code=404)
        assert result is not None
        assert result["source"] == "http_status"


class TestFlagAsDeleted:
    def test_flag_metadata_as_deleted(self):
        metadata = Metadata()
        deletion_info = {
            "is_deleted": True,
            "indicator": "This Tweet is unavailable",
            "source": "html_content",
            "platform": "twitter",
        }
        flag_as_deleted(metadata, deletion_info)
        assert metadata.get("deletion_detected") is True
        assert metadata.get("deletion_indicator") == "This Tweet is unavailable"
        assert metadata.get("deletion_source") == "html_content"
        assert metadata.get("deletion_platform") == "twitter"
        assert metadata.status == "deleted_or_unavailable"

    def test_metadata_contains_deletion_context(self):
        metadata = Metadata()
        deletion_info = {
            "is_deleted": True,
            "indicator": "This video has been removed by the uploader",
            "source": "error_message",
            "platform": "youtube",
        }
        flag_as_deleted(metadata, deletion_info)
        assert "deletion_indicator" in metadata.metadata
        assert "uploader" in metadata.get("deletion_indicator")

    def test_flag_with_http_status(self):
        metadata = Metadata()
        deletion_info = {
            "is_deleted": True,
            "indicator": "HTTP 404",
            "source": "http_status",
            "platform": "unknown",
        }
        flag_as_deleted(metadata, deletion_info)
        assert metadata.get("deletion_source") == "http_status"
