"""
TDD: Email digest tests.
"""
import httpx


class TestEmailDigestBuilder:
    """Test email digest HTML generation."""

    def test_build_digest_returns_html(self):
        from unified_api.services.email_digest import build_digest_html
        html = build_digest_html(
            title="Daily Deal Digest",
            sections=[
                {"title": "Market Summary", "content": "10 new deals today"},
                {"title": "Notable Deals", "items": [{"title": "Deal 1", "value": "$500M"}]},
            ],
        )
        assert isinstance(html, str)
        assert "<html" in html
        assert "Daily Deal Digest" in html

    def test_build_digest_includes_sections(self):
        from unified_api.services.email_digest import build_digest_html
        html = build_digest_html(
            title="Test",
            sections=[
                {"title": "Section A", "content": "Content A"},
                {"title": "Section B", "content": "Content B"},
            ],
        )
        assert "Section A" in html
        assert "Section B" in html
        assert "Content A" in html

    def test_build_digest_handles_empty_sections(self):
        from unified_api.services.email_digest import build_digest_html
        html = build_digest_html(title="Empty Digest", sections=[])
        assert isinstance(html, str)
        assert "Empty Digest" in html

    def test_format_deal_row(self):
        from unified_api.services.email_digest import format_deal_row
        row = format_deal_row({
            "title": "Pfizer-Seagen ADC License",
            "value": 500,
            "principal": "Pfizer",
            "partner": "Seagen",
            "date": "2026-07-15",
        })
        assert isinstance(row, str)
        assert "Pfizer" in row

    def test_build_digest_formats_sourced_catalyst_section(self):
        from unified_api.services.email_digest import build_digest_html

        html = build_digest_html(
            title="Weekly Intelligence Digest",
            sections=[{
                "title": "Upcoming Clinical Catalysts",
                "type": "catalysts",
                "items": [{
                    "title": "Pivotal <Trial>",
                    "nct_id": "NCT12345678",
                    "date": "2026-10-05",
                    "phase": "PHASE3",
                    "sponsor": "Example Bio",
                    "companies": "Example Bio",
                    "source_url": "https://clinicaltrials.gov/study/NCT12345678",
                }],
            }],
        )

        assert "Upcoming Clinical Catalysts" in html
        assert "NCT12345678" in html
        assert "2026-10-05" in html
        assert "clinicaltrials.gov/study/NCT12345678" in html
        assert "Pivotal &lt;Trial&gt;" in html

    def test_deal_rows_escape_untrusted_text(self):
        from unified_api.services.email_digest import format_deal_row

        row = format_deal_row({
            "title": "<script>alert(1)</script>",
            "principal": "A&B",
        })

        assert "<script>" not in row
        assert "&lt;script&gt;" in row
        assert "A&amp;B" in row


class TestEmailDelivery:
    def test_status_is_runtime_configurable_and_never_returns_secrets(self, monkeypatch):
        from unified_api.services.email_digest import get_email_delivery_status

        monkeypatch.setenv("SENDGRID_API_KEY", "very-secret")
        status = get_email_delivery_status()

        assert status["configured"] is True
        assert status["provider"] == "sendgrid"
        assert "very-secret" not in str(status)
        assert "SENDGRID_API_KEY" not in status

    def test_unconfigured_delivery_fails_closed(self, monkeypatch):
        from unified_api.services.email_digest import deliver_email

        monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
        monkeypatch.delenv("SMTP_HOST", raising=False)

        result = deliver_email("user@example.com", "Subject", "<p>Body</p>")

        assert result.success is False
        assert result.provider is None
        assert "configured" in result.error

    def test_sendgrid_uses_direct_api_and_accepts_202(self, monkeypatch):
        from unified_api.services.email_digest import deliver_email

        captured = {}

        def fake_post(url, **kwargs):
            captured["url"] = url
            captured.update(kwargs)
            return httpx.Response(202)

        monkeypatch.setenv("SENDGRID_API_KEY", "secret-key")
        monkeypatch.delenv("SMTP_HOST", raising=False)
        monkeypatch.setattr(httpx, "post", fake_post)

        result = deliver_email("user@example.com", "Subject", "<p>Body</p>")

        assert result.success is True
        assert result.provider == "sendgrid"
        assert captured["url"].endswith("/v3/mail/send")
        assert captured["json"]["personalizations"][0]["to"][0]["email"] == "user@example.com"
        assert captured["headers"]["Authorization"] == "Bearer secret-key"

    def test_password_reset_template_only_exposes_token_in_link(self):
        from unified_api.services.email_digest import build_password_reset_email

        html = build_password_reset_email(
            "https://onebd.pchomelab.com/reset-password?token=a&b"
        )

        assert "token=a&amp;b" in html
        assert "expires in one hour" in html
