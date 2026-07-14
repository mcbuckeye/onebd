"""
TDD: Email digest tests.
"""
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
