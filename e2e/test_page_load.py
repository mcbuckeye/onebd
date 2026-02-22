"""Page load and initial state tests."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import (
    SIDEBAR, WELCOME_HEADING, EXAMPLE_QUERY_FIRST,
    MODE_AUTO, MODE_SQL, MODE_RAG, SIDEBAR_HEALTHY,
)


def test_page_loads(page: Page):
    """Navigate to / and verify the app title is visible."""
    expect(page.locator("text=Cortellis Search").first).to_be_visible()


def test_welcome_screen_shown(page: Page):
    """Welcome heading appears in the main area."""
    expect(page.locator(WELCOME_HEADING)).to_be_visible()


def test_sidebar_shows_healthy(page: Page):
    """Sidebar health indicator says 'Healthy'."""
    expect(page.locator(SIDEBAR_HEALTHY).first).to_be_visible()


def test_example_queries_shown(page: Page):
    """Four example query buttons are displayed on welcome screen."""
    buttons = page.locator("button:has-text('deals'), button:has-text('contracts'), button:has-text('therapies'), button:has-text('milestone')")
    expect(buttons.first).to_be_visible()
    assert buttons.count() >= 4, f"Expected 4 example queries, found {buttons.count()}"


def test_mode_buttons_visible(page: Page):
    """Auto, SQL, and RAG mode buttons are present."""
    expect(page.locator(MODE_AUTO)).to_be_visible()
    expect(page.locator(MODE_SQL)).to_be_visible()
    expect(page.locator(MODE_RAG)).to_be_visible()
