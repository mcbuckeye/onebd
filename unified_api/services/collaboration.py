"""Schema and access helpers for shared team workspaces."""

from fastapi import HTTPException
from sqlalchemy import text

from unified_api.services.database import get_cortellis_session

TEAM_ROLES = {"owner", "editor", "viewer"}
EDIT_ROLES = {"owner", "editor"}
RESOURCE_TYPES = {
    "deal",
    "company",
    "drug",
    "filing",
    "contract",
    "search",
    "briefing",
    "other",
}


def _apply_collaboration_schema(session) -> None:
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS collaboration_teams (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS collaboration_team_members (
            team_id INTEGER NOT NULL REFERENCES collaboration_teams(id) ON DELETE CASCADE,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            role VARCHAR(20) NOT NULL,
            joined_at TIMESTAMP NOT NULL DEFAULT NOW(),
            PRIMARY KEY (team_id, user_id),
            CONSTRAINT collaboration_team_member_role
                CHECK (role IN ('owner', 'editor', 'viewer'))
        )
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS collaboration_shared_items (
            id SERIAL PRIMARY KEY,
            team_id INTEGER NOT NULL REFERENCES collaboration_teams(id) ON DELETE CASCADE,
            resource_type VARCHAR(30) NOT NULL,
            resource_id VARCHAR(255),
            title VARCHAR(500) NOT NULL,
            resource_url TEXT,
            note TEXT,
            created_by INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
            CONSTRAINT collaboration_resource_type CHECK (
                resource_type IN (
                    'deal', 'company', 'drug', 'filing', 'contract',
                    'search', 'briefing', 'other'
                )
            )
        )
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS collaboration_comments (
            id SERIAL PRIMARY KEY,
            item_id INTEGER NOT NULL REFERENCES collaboration_shared_items(id) ON DELETE CASCADE,
            author_id INTEGER NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
            body TEXT NOT NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_collaboration_members_user
        ON collaboration_team_members(user_id, team_id)
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_collaboration_items_team
        ON collaboration_shared_items(team_id, created_at DESC)
    """))
    session.execute(text("""
        CREATE INDEX IF NOT EXISTS idx_collaboration_comments_item
        ON collaboration_comments(item_id, created_at)
    """))


def ensure_collaboration_schema(session=None) -> None:
    if session is not None:
        _apply_collaboration_schema(session)
        session.commit()
        return
    with get_cortellis_session() as managed_session:
        _apply_collaboration_schema(managed_session)
        managed_session.commit()


def membership_role(session, team_id: int, user_id: int) -> str:
    role = session.execute(text("""
        SELECT role FROM collaboration_team_members
        WHERE team_id = :team_id AND user_id = :user_id
    """), {"team_id": team_id, "user_id": user_id}).scalar()
    if not role:
        raise HTTPException(status_code=404, detail="Team not found")
    return role


def require_team_role(
    session,
    team_id: int,
    user_id: int,
    allowed_roles: set[str],
) -> str:
    role = membership_role(session, team_id, user_id)
    if role not in allowed_roles:
        raise HTTPException(status_code=403, detail="Insufficient team permissions")
    return role
