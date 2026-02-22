#!/usr/bin/env python3
"""
Seed initial users for OneBD
Creates JVO (CEO) and Steve (admin) accounts
"""
import sys
import os

# Add parent directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import bcrypt
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker


def hash_password(password: str) -> str:
    """Hash password using bcrypt."""
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode('utf-8'), salt)
    return hashed.decode('utf-8')


def seed_users():
    """Create initial users."""
    # Get database URL from environment
    db_url = os.getenv(
        'CORTELLIS_DB_URL',
        'postgresql://cortellis:changeme@onebd-db-cortellis:5432/cortellis'
    )
    
    print(f"Connecting to database: {db_url.split('@')[1]}")
    
    engine = create_engine(db_url)
    Session = sessionmaker(bind=engine)
    session = Session()
    
    try:
        # Ensure users table exists
        session.execute(text("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                email VARCHAR(255) UNIQUE NOT NULL,
                name VARCHAR(255) NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                role VARCHAR(50) NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """))
        session.commit()
        
        # Create users
        users = [
            {
                'email': 'joyler@beigene.com',
                'name': 'John O\'ler',
                'password': 'OneBD2026!',
                'role': 'ceo'
            },
            {
                'email': 'steve@ipwatcher.com',
                'name': 'Steve',
                'password': 'OneBD2026!',
                'role': 'admin'
            }
        ]
        
        for user in users:
            # Check if user exists
            result = session.execute(
                text("SELECT id FROM users WHERE email = :email"),
                {'email': user['email']}
            )
            if result.fetchone():
                print(f"User {user['email']} already exists, skipping...")
                continue
            
            # Hash password
            password_hash = hash_password(user['password'])
            
            # Insert user
            session.execute(
                text("""
                    INSERT INTO users (email, name, password_hash, role)
                    VALUES (:email, :name, :password_hash, :role)
                """),
                {
                    'email': user['email'],
                    'name': user['name'],
                    'password_hash': password_hash,
                    'role': user['role']
                }
            )
            print(f"Created user: {user['email']} (role: {user['role']})")
        
        session.commit()
        print("\nUser seeding complete!")
        print("\nCredentials:")
        for user in users:
            print(f"  {user['email']} / {user['password']} ({user['role']})")
        
    except Exception as e:
        print(f"Error seeding users: {e}")
        session.rollback()
        raise
    finally:
        session.close()


if __name__ == '__main__':
    seed_users()
