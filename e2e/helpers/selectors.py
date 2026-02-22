"""Centralized CSS/text selectors for Playwright e2e tests."""

# Chat input
TEXTAREA = '[data-testid="chat-input"]'
SEND_BUTTON = '[data-testid="send-button"]'

# Mode buttons
MODE_AUTO = '[data-testid="mode-auto"]'
MODE_SQL = '[data-testid="mode-sql"]'
MODE_RAG = '[data-testid="mode-rag"]'

# Welcome screen
WELCOME_HEADING = 'text=Welcome to Cortellis Search'
EXAMPLE_QUERY_FIRST = 'button:has-text("What are the largest deals")'

# Sidebar
SIDEBAR = '[data-testid="sidebar"]'
SIDEBAR_HEALTHY = 'text=Healthy'
NEW_CHAT_BUTTON = 'button:has-text("New Chat")'

# Loading
LOADING_DOTS = '.typing-dot'

# Messages
MESSAGE_CONTENT = '.markdown-content'
USER_MESSAGE = '.bg-blue-600\\/20'

# Deal panel
DEAL_PANEL = '[data-testid="deal-panel"]'
DEAL_PANEL_CLOSE = '[data-testid="deal-panel-close"]'

# Mode badges in responses
SQL_BADGE = 'text=SQL Query'
RAG_BADGE = 'text=RAG Search'
