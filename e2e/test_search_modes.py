"""Search mode toggle and mode-specific response tests."""
import re
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import (
    TEXTAREA, SEND_BUTTON, MODE_AUTO, MODE_SQL, MODE_RAG,
    MESSAGE_CONTENT, SQL_BADGE, RAG_BADGE,
)


@pytest.mark.chat
def test_sql_mode_shows_badge(fresh_page: Page):
    """Select SQL mode, send a query, response has 'SQL Query' badge."""
    fresh_page.click(MODE_SQL)
    fresh_page.fill(TEXTAREA, "Show 5 deals")
    fresh_page.click(SEND_BUTTON)

    # Wait for response with SQL badge
    expect(fresh_page.locator(SQL_BADGE).first).to_be_visible(timeout=60000)


@pytest.mark.chat
def test_rag_mode_shows_badge(fresh_page: Page):
    """Select RAG mode, send a query, response has 'RAG Search' badge."""
    fresh_page.click(MODE_RAG)
    fresh_page.fill(TEXTAREA, "What royalty rates are typical?")
    fresh_page.click(SEND_BUTTON)

    # Wait for response with RAG badge
    expect(fresh_page.locator(RAG_BADGE).first).to_be_visible(timeout=60000)


def test_mode_toggle_active_state(page: Page):
    """Click each mode button and verify it gets the active style."""
    for selector in [MODE_AUTO, MODE_SQL, MODE_RAG]:
        page.click(selector)
        expect(page.locator(selector)).to_have_class(re.compile(r"bg-blue-600"))
