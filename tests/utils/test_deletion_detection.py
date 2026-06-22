"""
Tests for deletion detection utilities.

These tests verify the current best-effort by the auto-archiver
to detect when content has been deleted or is unavailable across
various platforms.
"""

from auto_archiver.utils.deletion_detection import detect_deletion, flag_as_deleted, DeletionIndicators
from auto_archiver.core.metadata import Metadata


class TestDeletionIndicators:
    """Test the deletion indicator lists for various platforms."""

    def test_twitter_indicators(self):
        """Verify Twitter deletion indicators are comprehensive."""
        assert "Hmm...this page doesn't exist" in DeletionIndicators.TWITTER
        assert "Try searching for something else" in DeletionIndicators.TWITTER
        assert "This Tweet is unavailable" in DeletionIndicators.TWITTER

    def test_platform_specific_indicators(self):
        """Test that platform-specific indicators are returned based on URL."""
        twitter_indicators = DeletionIndicators.for_url("https://twitter.com/user/status/123")
        assert any("page doesn't exist" in ind.lower() for ind in twitter_indicators)

        instagram_indicators = DeletionIndicators.for_url("https://instagram.com/p/ABC123")
        assert any("page isn't available" in ind.lower() for ind in instagram_indicators)


class TestDetectDeletion:
    """Test the detect_deletion function with various inputs."""

    def test_detect_deletion_in_html_twitter(self):
        """Test detection of Twitter's deleted post page."""
        html = "<html><body>Hmm...this page doesn't exist. Try searching for something else.</body></html>"
        url = "https://twitter.com/user/status/123"

        result = detect_deletion(html_content=html, url=url)

        assert result is not None
        assert result["is_deleted"] is True
        assert result["platform"] == "twitter"
        assert result["source"] == "html_content"
        assert "page doesn't exist" in result["indicator"].lower()

    def test_detect_deletion_in_page_title(self):
        """Test detection via page title."""
        title = "Page Not Found"
        url = "https://facebook.com/post/123"

        result = detect_deletion(page_title=title, url=url)

        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "page_title"

    def test_detect_deletion_in_error_message(self):
        """Test detection via error messages."""
        error = "yt_dlp.utils.DownloadError: This video is no longer available"
        url = "https://youtube.com/watch?v=abc123"

        result = detect_deletion(error_message=error, url=url)

        assert result is not None
        assert result["is_deleted"] is True
        assert result["platform"] == "youtube"
        assert result["source"] == "error_message"

    def test_detect_deletion_in_video_metadata(self):
        """Test detection via yt-dlp video metadata."""
        video_data = {"availability": "unavailable", "title": "Private video"}
        url = "https://youtube.com/watch?v=test123"

        result = detect_deletion(video_data=video_data, url=url)

        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "video_metadata"
        assert "availability" in result["indicator"]

    def test_no_deletion_detected(self):
        """Test that normal content is not flagged as deleted."""
        html = "<html><body><h1>Welcome to my page</h1><p>This is normal content.</p></body></html>"
        title = "My Normal Page"
        url = "https://example.com/page"

        result = detect_deletion(html_content=html, page_title=title, url=url)

        assert result is None

    def test_http_status_code_404(self):
        """Test that HTTP 404 status code triggers deletion detection."""
        result = detect_deletion(http_status_code=404, url="https://example.com/page")

        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "http_status"
        assert "404" in result["indicator"]

    def test_http_status_code_410(self):
        """Test that HTTP 410 (Gone) status code triggers deletion detection."""
        result = detect_deletion(http_status_code=410, url="https://example.com/page")

        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "http_status"
        assert "410" in result["indicator"]

    def test_http_status_code_451(self):
        """Test that HTTP 451 (Unavailable For Legal Reasons) triggers deletion detection."""
        result = detect_deletion(http_status_code=451, url="https://example.com/page")

        assert result is not None
        assert result["is_deleted"] is True
        assert result["source"] == "http_status"
        assert "451" in result["indicator"]

    def test_normal_http_status_codes_not_detected(self):
        """Test that normal HTTP status codes (200, 301, 302, 403) do NOT trigger deletion."""
        for status_code in [200, 201, 301, 302, 400, 401, 403, 500]:
            result = detect_deletion(http_status_code=status_code, url="https://example.com/page")
            assert result is None, f"HTTP {status_code} should not trigger deletion detection"

    def test_normal_page_with_sidebar_removed_text(self):
        """Test that a normal Reddit page with 'removed' in sidebar is NOT flagged as deleted."""
        html = """
        <html>
        <body>
            <div class='main-content'>
                <h1>My Reddit Post</h1>
                <p>This is a normal, active post with lots of content.</p>
                <div class='comment'>Great post!</div>
                <div class='comment'>I agree!</div>
            </div>
            <div class='sidebar'>
                <a href='/removed'>View removed posts</a>
                <p>page not found</p>
            </div>
            <footer>
                <a href='/help/deleted'>How to delete posts</a>
            </footer>
        </body>
        </html>
        """
        title = "My Reddit Post - r/test"
        url = "https://reddit.com/r/test/comments/abc123/my_reddit_post"

        result = detect_deletion(html_content=html, page_title=title, url=url)

        assert result is None, "Normal page with 'removed' in sidebar/footer should not be flagged"

    def test_http_status_takes_priority_over_html(self):
        """Test that HTTP status code is checked before HTML content."""
        html = "<html><body>Hmm...this page doesn't exist</body></html>"
        result = detect_deletion(html_content=html, http_status_code=404, url="https://twitter.com/user/status/123")

        assert result is not None
        assert result["source"] == "http_status", "HTTP status should take priority over HTML content"

    def test_instagram_media_not_found(self):
        """Test Instagram-specific deletion message."""
        error = "Media not found or unavailable"
        url = "https://instagram.com/p/ABC123"

        result = detect_deletion(error_message=error, url=url)

        assert result is not None
        assert result["platform"] == "instagram"
        assert "not found" in result["indicator"].lower()

    def test_reddit_removed_content(self):
        """Test Reddit removed content detection with specific long phrases."""
        html = "<div class='removed-by'>this post has been removed by the moderators of r/test</div>"
        url = "https://reddit.com/r/test/comments/abc123"

        result = detect_deletion(html_content=html, url=url)

        assert result is not None
        assert result["platform"] == "reddit"
        assert "removed" in result["indicator"].lower()

    def test_reddit_short_markers_not_detected(self):
        """Verify that short [removed] and [deleted] markers are NOT detected (to avoid false positives)."""
        html = """
        <div class='comment'>[removed]</div>
        <div class='comment'>[deleted]</div>
        <div class='sidebar'>View removed posts</div>
        """
        url = "https://reddit.com/r/test/comments/abc123"

        result = detect_deletion(html_content=html, url=url)

        assert result is None, "Short [removed]/[deleted] markers should not trigger deletion detection"


class TestFlagAsDeleted:
    """Test the flag_as_deleted function."""

    def test_flag_metadata_as_deleted(self):
        """Verify that metadata is properly flagged with deletion info."""
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
        """Verify investigators have full context about the deletion."""
        metadata = Metadata()
        deletion_info = {
            "is_deleted": True,
            "indicator": "Video has been removed by the uploader",
            "source": "error_message",
            "platform": "youtube",
        }

        flag_as_deleted(metadata, deletion_info)
        assert "deletion_indicator" in metadata.metadata
        assert "uploader" in metadata.get("deletion_indicator")
