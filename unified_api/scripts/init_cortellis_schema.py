"""
Initialize Cortellis Database Schema

This script creates all tables defined in the src.models module.
Run this inside Docker after the database container is healthy.
"""
import sys
sys.path.insert(0, '/app')

from sqlalchemy import create_engine, text
from unified_api.config import settings

# Import Base and all models to register them
from src.models import Base


def init_cortellis_schema():
    """Create all tables in the Cortellis database"""
    print(f"Connecting to: {settings.cortellis_db_url.split('@')[1]}")

    engine = create_engine(settings.cortellis_db_url)

    # Enable required extensions first
    with engine.connect() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS pg_trgm"))
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
        conn.commit()
        print("Extensions enabled: pg_trgm, vector")

    # Create all tables
    Base.metadata.create_all(engine)

    # List created tables
    with engine.connect() as conn:
        result = conn.execute(text("""
            SELECT table_name FROM information_schema.tables
            WHERE table_schema = 'public' AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """))
        tables = [row[0] for row in result]
        print(f"\nCreated {len(tables)} tables:")
        for t in tables:
            print(f"  - {t}")

    print("\nCortellis schema initialized successfully!")


if __name__ == "__main__":
    init_cortellis_schema()
