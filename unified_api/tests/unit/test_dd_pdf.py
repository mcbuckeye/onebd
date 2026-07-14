"""Unit coverage for due-diligence PDF evidence labeling."""

from unified_api.services.export_pptx import _dd_item_summary, _pdf_text


def test_dd_item_summary_labels_new_source_backed_sections():
    assert _dd_item_summary({
        "form": "8-K",
        "filing_date": "2026-07-01",
    }) == "8-K — Filed: 2026-07-01"
    assert _dd_item_summary({
        "deal_title": "Pfizer / Example",
        "territory": "Worldwide",
        "scope_type": "Included",
    }) == (
        "Pfizer / Example — Territory: Worldwide; Scope: Included"
    )
    assert _dd_item_summary({
        "deal_title": "Comparable deal",
        "agreement_type": "License",
        "match_score": 9,
    }) == "Comparable deal — Type: License; Comparable score: 9"


def test_pdf_text_escapes_source_markup():
    assert _pdf_text("A&B <Company>") == "A&amp;B &lt;Company&gt;"
