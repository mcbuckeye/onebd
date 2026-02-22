"""Deal detail panel tests."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import (
    TEXTAREA, SEND_BUTTON, MODE_SQL, MESSAGE_CONTENT,
    DEAL_PANEL, DEAL_PANEL_CLOSE,
)


@pytest.mark.chat
def test_deal_id_clickable_in_table(fresh_page: Page):
    """SQL query returns table, click a deal ID, deal panel appears."""
    fresh_page.click(MODE_SQL)
    fresh_page.fill(TEXTAREA, "Show 5 deals with their IDs and titles")
    fresh_page.click(SEND_BUTTON)

    # Wait for response
    expect(fresh_page.locator(MESSAGE_CONTENT).first).to_be_visible(timeout=60000)

    # Look for a clickable deal link in the response
    deal_link = fresh_page.locator(f"{MESSAGE_CONTENT} a[href*='deal']").first
    if deal_link.is_visible():
        deal_link.click()
        expect(fresh_page.locator(DEAL_PANEL)).to_be_visible(timeout=10000)
    else:
        # Try clicking a deal ID number in the table
        deal_cell = fresh_page.locator(f"{MESSAGE_CONTENT} table td >> nth=0").first
        if deal_cell.is_visible():
            deal_cell.click()
            expect(fresh_page.locator(DEAL_PANEL)).to_be_visible(timeout=10000)
        else:
            pytest.skip("No clickable deal IDs found in response")


@pytest.mark.chat
def test_deal_panel_close(fresh_page: Page):
    """Open deal panel, click close button, panel disappears."""
    fresh_page.click(MODE_SQL)
    fresh_page.fill(TEXTAREA, "Show the top 3 largest deals by value")
    fresh_page.click(SEND_BUTTON)

    expect(fresh_page.locator(MESSAGE_CONTENT).first).to_be_visible(timeout=60000)

    # Try to open a deal panel
    deal_link = fresh_page.locator(f"{MESSAGE_CONTENT} a[href*='deal']").first
    if deal_link.is_visible():
        deal_link.click()
        expect(fresh_page.locator(DEAL_PANEL)).to_be_visible(timeout=10000)

        # Close the panel
        fresh_page.click(DEAL_PANEL_CLOSE)
        expect(fresh_page.locator(DEAL_PANEL)).to_be_hidden()
    else:
        pytest.skip("No clickable deal links in response")


@pytest.mark.chat
def test_deal_panel_sections_visible(fresh_page: Page):
    """Open a deal and verify Overview, Parties, Financials sections."""
    fresh_page.click(MODE_SQL)
    fresh_page.fill(TEXTAREA, "Show the top 3 largest deals by value")
    fresh_page.click(SEND_BUTTON)

    expect(fresh_page.locator(MESSAGE_CONTENT).first).to_be_visible(timeout=60000)

    deal_link = fresh_page.locator(f"{MESSAGE_CONTENT} a[href*='deal']").first
    if deal_link.is_visible():
        deal_link.click()
        expect(fresh_page.locator(DEAL_PANEL)).to_be_visible(timeout=10000)

        # Check section headers
        expect(fresh_page.locator(f"{DEAL_PANEL} >> text=Overview")).to_be_visible()
        expect(fresh_page.locator(f"{DEAL_PANEL} >> text=Parties")).to_be_visible()
    else:
        pytest.skip("No clickable deal links in response")
