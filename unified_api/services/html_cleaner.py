"""
HTML cleaner service for Cortellis contract content.

Converts raw HTML-tagged contract text (from contract_content.content) into
clean markdown suitable for PageIndex tree indexing. Handles HTML entity
decoding, tag stripping, and markdown heading generation for numbered sections.
"""
import re
from html import unescape


def clean_contract_html(text: str | None) -> str:
    """Convert raw HTML-tagged Cortellis contract text to clean markdown.

    Processing pipeline (order matters):
    1. Guard against None / empty input
    2. Decode HTML entities (&amp; → &, &#39; → ', etc.)
    3. Convert <br/> / <br> tags to newlines
    4. Convert <para> to double-newline paragraph breaks; strip </para>
    5. Strip remaining HTML tags
    6. Remove page markers (- 41 -)
    7. Promote numbered article headers to ## headings
    8. Promote numbered sub-sections to ### headings
    9. Strip leading/trailing whitespace per line
    10. Collapse 3+ consecutive blank lines to 2
    11. Strip overall leading/trailing whitespace

    Args:
        text: Raw contract text, possibly containing HTML markup and entities.

    Returns:
        Clean markdown string. Returns "" for None or empty input.
    """
    if not text:
        return ""

    # 1. Decode HTML entities (handles &amp;, &apos;, &#39;, &#x27;, &nbsp;, etc.)
    text = unescape(text)
    # unescape doesn't handle &nbsp; as a space by default in all cases,
    # but the html module does handle named entities including &nbsp; → \xa0.
    # Normalise non-breaking spaces to regular spaces.
    text = text.replace("\xa0", " ")

    # 2. Convert <br/> and <br> (with optional space before /) to newlines
    text = re.sub(r"<br\s*/?>", "\n", text, flags=re.IGNORECASE)

    # 3. Convert <para> to paragraph break (double newline); strip </para>
    text = re.sub(r"<para>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"</para>", "\n\n", text, flags=re.IGNORECASE)

    # 4. Strip all remaining HTML tags
    text = re.sub(r"<[^>]+>", "", text)

    # 5. Remove page markers like  - 41 -  (standalone on a line or inline)
    text = re.sub(r"-\s*\d+\s*-", "", text)

    # 6. Per-line processing: strip whitespace, then apply heading rules
    lines = text.split("\n")
    processed = []
    for line in lines:
        line = line.strip()

        # Top-level article heading: integer + dot + spaces + ALL CAPS (2+ words or single)
        # e.g. "7.   FINANCIAL TERMS"  →  "## 7. FINANCIAL TERMS"
        m = re.match(r"^(\d+)\.\s{1,}([A-Z][A-Z\s,;&\'\"()\-/]+)$", line)
        if m:
            line = f"## {m.group(1)}. {m.group(2).strip()}"
        else:
            # Sub-section heading: number.number[.number...] + spaces + title (mixed case OK)
            # e.g. "7.1   Upfront Payment."  →  "### 7.1 Upfront Payment."
            m2 = re.match(r"^(\d+(?:\.\d+)+)\s{1,}(.+)$", line)
            if m2:
                line = f"### {m2.group(1)} {m2.group(2).strip()}"

        processed.append(line)

    text = "\n".join(processed)

    # 7. Collapse 3+ consecutive newlines to 2
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()
