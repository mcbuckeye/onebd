"""Seed initial users for the BD Intelligence Platform."""
import sys
sys.path.insert(0, '.')

from sqlalchemy import text, create_engine
from unified_api.services.auth import hash_password
import os

DB_URL = os.environ.get('CORTELLIS_DB_URL', 'postgresql://cortellis:changeme@localhost:5433/cortellis')

engine = create_engine(DB_URL)

with engine.connect() as conn:
    conn.execute(text("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            email VARCHAR(255) UNIQUE NOT NULL,
            password_hash VARCHAR(255) NOT NULL,
            name VARCHAR(255) NOT NULL,
            role VARCHAR(50) DEFAULT 'analyst',
            preferences JSONB DEFAULT '{}',
            created_at TIMESTAMP DEFAULT NOW(),
            last_login TIMESTAMP
        )
    """))

    # Seed JVO account
    conn.execute(text("""
        INSERT INTO users (email, password_hash, name, role)
        VALUES (:email, :hash, :name, :role)
        ON CONFLICT (email) DO NOTHING
    """), {
        "email": "joyler@beigene.com",
        "hash": hash_password("BDIntel2026!"),
        "name": "John Oyler",
        "role": "ceo",
    })

    # Seed Steve account
    conn.execute(text("""
        INSERT INTO users (email, password_hash, name, role)
        VALUES (:email, :hash, :name, :role)
        ON CONFLICT (email) DO NOTHING
    """), {
        "email": "steve@ipwatcher.com",
        "hash": hash_password("BDIntel2026!"),
        "name": "Steve",
        "role": "admin",
    })

    conn.commit()
    print("Users seeded successfully")
