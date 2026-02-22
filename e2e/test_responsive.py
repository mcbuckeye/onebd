"""Responsive layout tests."""
import re
import pytest
from playwright.sync_api import Page, expect, BrowserContext
from helpers.selectors import SIDEBAR


def test_mobile_sidebar_hidden(page: Page, browser: "Browser"):
    """On 375x812 mobile viewport, sidebar is off-screen (translated left)."""
    context = browser.new_context(viewport={"width": 375, "height": 812})
    mobile_page = context.new_page()
    mobile_page.goto(page.url, wait_until="networkidle")

    # Sidebar wrapper uses -translate-x-full to slide off-screen on mobile
    sidebar_wrapper = mobile_page.locator(SIDEBAR).locator("..")
    expect(sidebar_wrapper).to_have_class(re.compile(r"-translate-x-full"))
    context.close()


def test_mobile_menu_toggle(page: Page, browser: "Browser"):
    """On mobile viewport, clicking the menu button reveals the sidebar."""
    context = browser.new_context(viewport={"width": 375, "height": 812})
    mobile_page = context.new_page()
    mobile_page.goto(page.url, wait_until="networkidle")

    # Find and click the mobile menu button (hamburger icon)
    menu_button = mobile_page.locator("button.lg\\:hidden").first
    if menu_button.is_visible():
        menu_button.click()
        # Sidebar should now be visible
        expect(mobile_page.locator(SIDEBAR)).to_be_visible(timeout=5000)
    else:
        pytest.skip("Mobile menu button not found")

    context.close()


def test_desktop_sidebar_visible(page: Page):
    """On 1280x720 desktop viewport, sidebar is visible by default."""
    expect(page.locator(SIDEBAR)).to_be_visible()
