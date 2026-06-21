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
    DELETED_HTTP_STATUSES,
)
from auto_archiver.core.metadata import Metadata


class TestDeletionIndicators:
    """Test the deletion indicator lists for various platforms."""

    def test_twitter_strong_indicators(self):
        assert "Hmm...this page doesn't exist" in DeletionIndicators.TWITTER_STRONG
        assert "This Tweet is unavailable" in DeletionIndicators.TWITTER_STRONG

    def test_twitter_context_required_indicators(self):
        assert "Try searching for something else" in DeletionIndicators.TWITTER_CONTEXT_REQUIRED

    def test_platform_specific_indicators(self):
        strong, context = DeletionIndicators.for_url("https://twitter.com/user/status/123")
        assert any("page doesn't exist" in ind.lower() for ind in strong)

        strong, context = DeletionIndicators.for_url("https://instagram.com/p/ABC123")
        assert any("page isn't available" in ind.lower() for ind in strong)

    def test_for_url_returns_tuple(self):
        result = DeletionIndicators.for_url("https://reddit.com/r/test")
        assert isinstance(result, tuple)
        assert len(result) == 2
        strong, context = result
        assert isinstance(strong, list)
        assert isinstance(context, list)

    def test_reddit_context_required_has_short_indicators(self):
        assert "[removed]" in DeletionIndicators.REDDIT_CONTEXT_REQUIRED
        assert "[deleted]" in DeletionIndicators.REDDIT_CONTEXT_REQUIRED

    def test_vk_context_required_has_short_indicators(self):
        assert "Access denied" in DeletionIndicators.VK_CONTEXT_REQUIRED
        assert "Page not found" in DeletionIndicators.VK_CONTEXT_REQUIRED


class TestDetectDeletion:
    """Test the detect_deletion function with various inputs."""

    def test_detect_deletion_in_short_html_twitter(self):
        html = "<html><body>Hmm...this page doesn't exist. Try searching for something else.</body></html>"
        url = "https://twitter.com/user/status/123"

        result = detect_deletion(html_content=html, url=url)

        assert result is not None
        assert result["is_deleted"] is True
        assert result["platform"] == "twitter"
        assert result["source"] == "html_content"
        assert "page doesn't exist" in result["indicator"].lower()

    def test_detect_deletion_in_page_title(self):
        title = "Page Not Found"
        url = "https://facebook.com/post/123"

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

    def test_http_404_detected(self):
        url = "https://example.com/gone"

        result = detect_deletion(http_status=404, url=url)

        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "http_status"
        assert "404" in result["indicator"]

    def test_http_410_detected(self):
        url = "https://example.com/gone"

        result = detect_deletion(http_status=410, url=url)

        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "http_status"

    def test_http_451_detected(self):
        url = "https://example.com/censored"

        result = detect_deletion(http_status=451, url=url)

        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "http_status"

    def test_http_200_not_flagged(self):
        url = "https://example.com/ok"

        result = detect_deletion(http_status=200, url=url)

        assert result is None

    def test_long_html_with_indicator_not_flagged(self):
        html = (
            "<html><body>"
            "<nav>Home About Contact</nav>"
            "<aside>View removed posts and other options</aside>"
            "<main><p>" + "Normal content. " * 100 + "</p></main>"
            "<footer>Page not found in archive? Contact us.</footer>"
            "</body></html>"
        )
        url = "https://reddit.com/r/test/comments/abc123"

        result = detect_deletion(html_content=html, url=url)

        assert result is None

    def test_reddit_sidebar_no_false_positive(self):
        html = (
            "<html><body>"
            "<div class='sidebar'>View removed posts and moderated content</div>"
            "<div class='post'><h2>A normal post title</h2><p>Some normal content here.</p></div>"
            "<footer>Reddit footer with various links and info</footer>"
            "</body></html>"
        )
        url = "https://reddit.com/r/test/comments/abc123"

        result = detect_deletion(html_content=html, url=url)

        assert result is None

    def test_reddit_removed_in_title_detected(self):
        title = "sorry, this post has been removed by a moderator"
        url = "https://reddit.com/r/test/comments/abc123"

        result = detect_deletion(page_title=title, url=url)

        assert result is not None
        assert result["platform"] == "reddit"
        assert result["source"] == "page_title"

    def test_context_required_indicator_in_title_detected(self):
        title = "Access denied"
        url = "https://vk.com/wall123"

        result = detect_deletion(page_title=title, url=url)

        assert result is not None
        assert result["source"] == "page_title"

    def test_context_required_indicator_in_error_detected(self):
        error = "DownloadError: [removed] content"
        url = "https://reddit.com/r/test/comments/abc123"

        result = detect_deletion(error_message=error, url=url)

        assert result is not None
        assert result["source"] == "error_message"

    def test_context_required_indicator_in_html_not_detected(self):
        html = (
            "<html><body>"
            "<div class='comment'>[removed]</div>"
            "<div class='sidebar'>More info about the subreddit</div>"
            "<div class='other-comments'>Many other normal comments here with lots of text</div>"
            "</body></html>"
        )
        url = "https://reddit.com/r/test/comments/abc123"

        result = detect_deletion(html_content=html, url=url)

        assert result is None

    def test_vk_access_denied_in_sidebar_not_flagged(self):
        html = (
            "<html><body>"
            "<nav>Access denied for unauthorized users</nav>"
            "<main><p>This is a normal VK post with lots of content.</p></main>"
            "</body></html>"
        )
        url = "https://vk.com/wall123"

        result = detect_deletion(html_content=html, url=url)

        assert result is None

    def test_video_metadata_only_uses_strong_indicators(self):
        video_data = {"title": "Access denied", "availability": None}
        url = "https://youtube.com/watch?v=test"

        result = detect_deletion(video_data=video_data, url=url)

        assert result is None

    def test_video_metadata_strong_indicator_detected(self):
        video_data = {"title": "This video has been removed by the uploader"}
        url = "https://youtube.com/watch?v=test"

        result = detect_deletion(video_data=video_data, url=url)

        assert result is not None
        assert result["source"] == "video_metadata_title"

    def test_short_error_page_detected(self):
        html = "<html><body>This video is no longer available</body></html>"
        url = "https://youtube.com/watch?v=test"

        result = detect_deletion(html_content=html, url=url)

        assert result is not None
        assert result["source"] == "html_content"


class TestFlagAsDeleted:
    """Test the flag_as_deleted function."""

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

    def test_flag_with_http_status_source(self):
        metadata = Metadata()
        deletion_info = {
            "is_deleted": True,
            "indicator": "HTTP 404",
            "source": "http_status",
            "platform": "unknown",
        }

        flag_as_deleted(metadata, deletion_info)
        assert metadata.get("deletion_source") == "http_status"
        assert metadata.status == "deleted_or_unavailable"
