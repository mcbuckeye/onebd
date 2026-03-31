"""
TDD: HTML cleaner service tests.

Tests for clean_contract_html() — converts raw HTML-tagged Cortellis
contract text to clean markdown suitable for PageIndex tree indexing.
"""
import pytest


class TestHtmlEntityDecoding:
    """HTML entities must be decoded to their plain-text equivalents."""

    def test_amp_decoded(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html("A &amp; B") == "A & B"

    def test_apos_decoded(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html("it&apos;s") == "it's"

    def test_quot_decoded(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html('say &quot;hello&quot;') == 'say "hello"'

    def test_gt_lt_decoded(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html("a &gt; b &lt; c") == "a > b < c"

    def test_nbsp_decoded_to_space(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html("hello&nbsp;world") == "hello world"

    def test_numeric_decimal_entity(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html("it&#39;s") == "it's"

    def test_numeric_hex_entity(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html("it&#x27;s") == "it's"

    def test_multiple_entities_in_one_string(self):
        from unified_api.services.html_cleaner import clean_contract_html
        # &amp;amp; → single-pass unescape → &amp; (the literal text "&amp;")
        # &apos;test&apos; → 'test'
        assert clean_contract_html("&amp;amp; &apos;test&apos;") == "&amp; 'test'"


class TestBrTagConversion:
    """<br/> and <br> tags must become newlines."""

    def test_br_self_closing(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("line1<br/>line2")
        assert "line1\nline2" in result

    def test_br_open(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("line1<br>line2")
        assert "line1\nline2" in result

    def test_br_with_spaces(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("line1<br />line2")
        assert "line1\nline2" in result


class TestParaTagConversion:
    """<para> blocks become paragraph breaks; </para> is stripped."""

    def test_para_open_becomes_double_newline(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("<para>Some text</para>")
        # Opening <para> → double newline (paragraph break) before content
        # Closing </para> → stripped (or double newline)
        assert "Some text" in result
        # There should be paragraph separation — at least one blank line somewhere
        assert "\n\n" in result or result.strip() == "Some text"

    def test_para_closing_stripped(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("text</para>more")
        assert "</para>" not in result

    def test_para_tags_removed_from_output(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("<para>Hello world</para>")
        assert "<para>" not in result
        assert "</para>" not in result


class TestHtmlTagRemoval:
    """Remaining HTML tags must be stripped."""

    def test_fulltext_tag_removed(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("<FullText>contract text</FullText>")
        assert "<FullText>" not in result
        assert "</FullText>" not in result
        assert "contract text" in result

    def test_span_tag_removed(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html('<span class="bold">text</span>')
        assert "<span" not in result
        assert "</span>" not in result
        assert "text" in result

    def test_arbitrary_tag_removed(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("<unknown>data</unknown>")
        assert "<unknown>" not in result
        assert "data" in result


class TestMarkdownHeadings:
    """Numbered article headers become ## headings; sub-sections become ###."""

    def test_top_level_article_becomes_h2(self):
        from unified_api.services.html_cleaner import clean_contract_html
        # Integer article number with ALL CAPS title
        result = clean_contract_html("\n7.    FINANCIAL TERMS\n")
        assert "## 7. FINANCIAL TERMS" in result

    def test_top_level_article_single_space(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("\n3. DEFINITIONS\n")
        assert "## 3. DEFINITIONS" in result

    def test_top_level_article_multiple_spaces(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("\n12.   REPRESENTATIONS AND WARRANTIES\n")
        assert "## 12. REPRESENTATIONS AND WARRANTIES" in result

    def test_subsection_becomes_h3(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("\n7.1    Upfront Payment.\n")
        assert "### 7.1 Upfront Payment." in result

    def test_subsection_two_digits(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("\n12.5    Milestone Payments.\n")
        assert "### 12.5 Milestone Payments." in result

    def test_subsection_deeper(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("\n7.1.2    Payment Schedule.\n")
        assert "### 7.1.2 Payment Schedule." in result

    def test_lowercase_subsection_becomes_h3(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("\n2.3    grant of license.\n")
        assert "### 2.3 grant of license." in result

    def test_plain_text_not_modified(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("This is just regular text.")
        assert result.strip() == "This is just regular text."


class TestPageMarkerRemoval:
    """Page markers like `- 41 -` must be removed."""

    def test_single_digit_page_marker(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("text\n- 5 -\nmore text")
        assert "- 5 -" not in result

    def test_double_digit_page_marker(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("text\n- 41 -\nmore text")
        assert "- 41 -" not in result

    def test_triple_digit_page_marker(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("text\n- 100 -\nmore text")
        assert "- 100 -" not in result

    def test_surrounding_text_preserved(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("before\n- 41 -\nafter")
        assert "before" in result
        assert "after" in result


class TestBlankLineCollapse:
    """3+ consecutive newlines should collapse to exactly 2."""

    def test_three_newlines_become_two(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("a\n\n\nb")
        assert "\n\n\n" not in result
        assert "a" in result
        assert "b" in result

    def test_five_newlines_become_two(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("a\n\n\n\n\nb")
        assert "\n\n\n" not in result

    def test_two_newlines_preserved(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("a\n\nb")
        assert "\n\n" in result


class TestRedactionMarkerPreservation:
    """[***] redaction markers must survive the cleaning pipeline."""

    def test_redaction_marker_preserved(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("The price is [***] per unit.")
        assert "[***]" in result

    def test_multiple_redaction_markers(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("[***] pays [***] within [***] days.")
        assert result.count("[***]") == 3

    def test_redaction_marker_with_html(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("<para>The fee is [***].</para>")
        assert "[***]" in result


class TestEdgeCases:
    """Edge cases: None, empty string, whitespace handling."""

    def test_none_returns_empty_string(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html(None) == ""

    def test_empty_string_returns_empty_string(self):
        from unified_api.services.html_cleaner import clean_contract_html
        assert clean_contract_html("") == ""

    def test_whitespace_only_returns_empty(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("   \n\n   ")
        assert result.strip() == ""

    def test_line_leading_trailing_whitespace_stripped(self):
        from unified_api.services.html_cleaner import clean_contract_html
        result = clean_contract_html("  hello world  ")
        assert result == "hello world"

    def test_realistic_contract_snippet(self):
        """Integration-style test with a realistic contract fragment."""
        from unified_api.services.html_cleaner import clean_contract_html
        raw = (
            "<FullText>"
            "<para>7.   FINANCIAL TERMS<br/>"
            "7.1   Upfront Payment.<br/>"
            "Licensee shall pay Licensor [***] within thirty (30) days.<br/>"
            "- 42 -<br/>"
            "7.2   Milestone Payments.<br/>"
            "Upon [***] &amp; regulatory approval.</para>"
            "</FullText>"
        )
        result = clean_contract_html(raw)
        assert "<FullText>" not in result
        assert "<para>" not in result
        assert "## 7. FINANCIAL TERMS" in result
        assert "### 7.1 Upfront Payment." in result
        assert "### 7.2 Milestone Payments." in result
        assert "[***]" in result
        assert "&amp;" not in result
        assert "& regulatory" in result
        assert "- 42 -" not in result
