"""Chat flow tests - sending messages and receiving responses."""
import pytest
from playwright.sync_api import Page, expect
from helpers.selectors import (
    TEXTAREA, SEND_BUTTON, WELCOME_HEADING,
    MESSAGE_CONTENT, EXAMPLE_QUERY_FIRST, NEW_CHAT_BUTTON,
)


@pytest.mark.chat
def test_send_message_via_button(fresh_page: Page):
    """Type a message and click send - user message bubble appears."""
    fresh_page.fill(TEXTAREA, "Show me 3 deals")
    fresh_page.click(SEND_BUTTON)

    # User message should appear
    expect(fresh_page.locator("text=Show me 3 deals").last).to_be_visible()


@pytest.mark.chat
def test_send_message_via_enter(fresh_page: Page):
    """Type a message and press Enter to send."""
    fresh_page.fill(TEXTAREA, "Count all deals")
    fresh_page.press(TEXTAREA, "Enter")

    expect(fresh_page.locator("text=Count all deals").last).to_be_visible()


@pytest.mark.chat
def test_assistant_response_appears(fresh_page: Page):
    """Send a message and wait for an assistant response with markdown content."""
    fresh_page.fill(TEXTAREA, "How many deals are in the database?")
    fresh_page.click(SEND_BUTTON)

    # Wait for assistant response (up to 60s for LLM)
    expect(fresh_page.locator(MESSAGE_CONTENT).first).to_be_visible(timeout=60000)


@pytest.mark.chat
def test_example_query_click(fresh_page: Page):
    """Clicking an example query populates the textarea."""
    fresh_page.click(EXAMPLE_QUERY_FIRST)

    textarea = fresh_page.locator(TEXTAREA)
    expect(textarea).to_have_value("What are the largest deals in 2024?")


@pytest.mark.chat
def test_new_chat_clears_messages(fresh_page: Page):
    """Send a message, click New Chat, welcome screen returns."""
    fresh_page.fill(TEXTAREA, "Test message for clearing")
    fresh_page.click(SEND_BUTTON)

    # Wait for user message to appear
    expect(fresh_page.locator("text=Test message for clearing")).to_be_visible()

    # Click New Chat
    fresh_page.click(NEW_CHAT_BUTTON)

    # Welcome screen should return
    expect(fresh_page.locator(WELCOME_HEADING)).to_be_visible()
