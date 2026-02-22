"""Playwright e2e test fixtures for BD Intelligence Platform."""
import pytest
from playwright.sync_api import Page


@pytest.fixture(scope="session")
def browser_context_args(browser_context_args):
    return {
        **browser_context_args,
        "viewport": {"width": 1280, "height": 720},
        "ignore_https_errors": True,
        "locale": "en-US",
    }


@pytest.fixture(autouse=True)
def wait_for_healthy(page: Page, base_url: str):
    """Navigate to app and wait for the API health indicator."""
    page.goto(base_url, wait_until="networkidle")
    # Wait for sidebar health status (up to 30s for containers to be ready)
    try:
        page.wait_for_selector("text=Healthy", timeout=30000)
    except Exception:
        # If health check doesn't appear, still proceed - some tests don't need it
        pass
    yield


@pytest.fixture
def fresh_page(page: Page, base_url: str):
    """Provide a page with extended timeout for LLM-dependent tests."""
    page.set_default_timeout(60000)
    return page
