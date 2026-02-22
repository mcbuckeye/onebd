"""
Create watchlist and notes tables in Cortellis database.
"""
from sqlalchemy import text
import structlog

logger = structlog.get_logger(__name__)


def create_watchlist_tables():
    """Create user_watchlist and deal_notes tables."""
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        # Create user_watchlist table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS user_watchlist (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL DEFAULT 'default',
                deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                status VARCHAR(50) DEFAULT 'watching',
                tags TEXT[] DEFAULT '{}',
                added_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW(),
                UNIQUE(user_id, deal_id)
            );

            CREATE INDEX IF NOT EXISTS idx_watchlist_user ON user_watchlist(user_id);
            CREATE INDEX IF NOT EXISTS idx_watchlist_deal ON user_watchlist(deal_id);
            CREATE INDEX IF NOT EXISTS idx_watchlist_status ON user_watchlist(status);
        """))

        # Create deal_notes table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS deal_notes (
                id SERIAL PRIMARY KEY,
                deal_id INTEGER NOT NULL REFERENCES deals(id) ON DELETE CASCADE,
                user_id VARCHAR(255) NOT NULL DEFAULT 'default',
                content TEXT NOT NULL,
                is_private BOOLEAN DEFAULT TRUE,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_notes_deal ON deal_notes(deal_id);
            CREATE INDEX IF NOT EXISTS idx_notes_user ON deal_notes(user_id);
        """))

        # Create saved_searches table
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS saved_searches (
                id SERIAL PRIMARY KEY,
                user_id VARCHAR(255) NOT NULL DEFAULT 'default',
                name VARCHAR(255) NOT NULL,
                description TEXT,
                criteria JSONB NOT NULL,
                is_alert BOOLEAN DEFAULT FALSE,
                alert_frequency VARCHAR(50),
                last_run_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT NOW(),
                updated_at TIMESTAMP DEFAULT NOW()
            );

            CREATE INDEX IF NOT EXISTS idx_saved_searches_user ON saved_searches(user_id);
            CREATE INDEX IF NOT EXISTS idx_saved_searches_alert ON saved_searches(is_alert) WHERE is_alert = TRUE;
        """))

        session.commit()
        logger.info("Watchlist tables created successfully")


if __name__ == "__main__":
    create_watchlist_tables()
