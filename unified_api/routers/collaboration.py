"""Authenticated team workspaces, shared evidence, and discussion."""

from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import BaseModel, Field
from sqlalchemy import text

from unified_api.routers.auth import get_current_user
from unified_api.services.auth import TokenData
from unified_api.services.collaboration import (
    EDIT_ROLES,
    RESOURCE_TYPES,
    ensure_collaboration_schema,
    membership_role,
    require_team_role,
)
from unified_api.services.database import get_cortellis_session

router = APIRouter(prefix="/collaboration", tags=["Collaboration"])


class TeamCreateRequest(BaseModel):
    name: str = Field(min_length=1, max_length=255)


class MemberRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255)
    role: Literal["editor", "viewer"] = "editor"


class MemberRoleRequest(BaseModel):
    role: Literal["editor", "viewer"]


class SharedItemRequest(BaseModel):
    resource_type: Literal[
        "deal", "company", "drug", "filing", "contract",
        "search", "briefing", "other",
    ]
    resource_id: Optional[str] = Field(None, max_length=255)
    title: str = Field(min_length=1, max_length=500)
    resource_url: Optional[str] = Field(None, max_length=2000)
    note: Optional[str] = Field(None, max_length=10000)


class CommentRequest(BaseModel):
    body: str = Field(min_length=1, max_length=4000)


def _team_summary(row) -> dict:
    return {
        "id": row.id,
        "name": row.name,
        "role": row.role,
        "member_count": row.member_count,
        "item_count": row.item_count,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


@router.get("/teams")
async def list_teams(user: TokenData = Depends(get_current_user)):
    with get_cortellis_session() as session:
        rows = session.execute(text("""
            SELECT team.id, team.name, member.role,
                   team.created_at, team.updated_at,
                   (SELECT COUNT(*) FROM collaboration_team_members count_member
                    WHERE count_member.team_id = team.id) AS member_count,
                   (SELECT COUNT(*) FROM collaboration_shared_items item
                    WHERE item.team_id = team.id) AS item_count
            FROM collaboration_teams team
            JOIN collaboration_team_members member ON member.team_id = team.id
            WHERE member.user_id = :user_id
            ORDER BY team.updated_at DESC, team.id DESC
        """), {"user_id": user.user_id}).fetchall()
    return [_team_summary(row) for row in rows]


@router.post("/teams", status_code=201)
async def create_team(
    request: TeamCreateRequest,
    user: TokenData = Depends(get_current_user),
):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Team name is required")
    with get_cortellis_session() as session:
        row = session.execute(text("""
            INSERT INTO collaboration_teams (name, created_by)
            VALUES (:name, :user_id)
            RETURNING id, name, created_at, updated_at
        """), {"name": name, "user_id": user.user_id}).fetchone()
        session.execute(text("""
            INSERT INTO collaboration_team_members (team_id, user_id, role)
            VALUES (:team_id, :user_id, 'owner')
        """), {"team_id": row.id, "user_id": user.user_id})
        session.commit()
    return {
        "id": row.id,
        "name": row.name,
        "role": "owner",
        "member_count": 1,
        "item_count": 0,
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    }


@router.get("/teams/{team_id}")
async def get_team(
    team_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        role = membership_role(session, team_id, user.user_id)
        team = session.execute(text("""
            SELECT id, name, created_at, updated_at
            FROM collaboration_teams WHERE id = :team_id
        """), {"team_id": team_id}).fetchone()
        members = session.execute(text("""
            SELECT account.id, account.name, account.email, member.role,
                   member.joined_at
            FROM collaboration_team_members member
            JOIN users account ON account.id = member.user_id
            WHERE member.team_id = :team_id AND account.disabled IS NOT TRUE
            ORDER BY CASE member.role WHEN 'owner' THEN 0 WHEN 'editor' THEN 1 ELSE 2 END,
                     account.name
        """), {"team_id": team_id}).fetchall()
    return {
        "id": team.id,
        "name": team.name,
        "role": role,
        "created_at": str(team.created_at),
        "updated_at": str(team.updated_at),
        "members": [
            {
                "id": member.id,
                "name": member.name,
                "email": member.email,
                "role": member.role,
                "joined_at": str(member.joined_at),
            }
            for member in members
        ],
    }


@router.patch("/teams/{team_id}")
async def rename_team(
    request: TeamCreateRequest,
    team_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    name = request.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Team name is required")
    with get_cortellis_session() as session:
        require_team_role(session, team_id, user.user_id, {"owner"})
        session.execute(text("""
            UPDATE collaboration_teams
            SET name = :name, updated_at = NOW()
            WHERE id = :team_id
        """), {"name": name, "team_id": team_id})
        session.commit()
    return {"id": team_id, "name": name}


@router.delete("/teams/{team_id}")
async def delete_team(
    team_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        require_team_role(session, team_id, user.user_id, {"owner"})
        session.execute(
            text("DELETE FROM collaboration_teams WHERE id = :team_id"),
            {"team_id": team_id},
        )
        session.commit()
    return {"status": "deleted", "id": team_id}


@router.post("/teams/{team_id}/members", status_code=201)
async def add_member(
    request: MemberRequest,
    team_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        require_team_role(session, team_id, user.user_id, {"owner"})
        account = session.execute(text("""
            SELECT id, name, email FROM users
            WHERE LOWER(email) = LOWER(:email) AND disabled IS NOT TRUE
        """), {"email": request.email.strip()}).fetchone()
        if not account:
            raise HTTPException(
                status_code=404,
                detail="No active account has that email; create the user first",
            )
        existing_role = session.execute(text("""
            SELECT role FROM collaboration_team_members
            WHERE team_id = :team_id AND user_id = :user_id
        """), {"team_id": team_id, "user_id": account.id}).scalar()
        if existing_role == "owner":
            raise HTTPException(status_code=400, detail="The team owner role cannot be replaced")
        session.execute(text("""
            INSERT INTO collaboration_team_members (team_id, user_id, role)
            VALUES (:team_id, :user_id, :role)
            ON CONFLICT (team_id, user_id) DO UPDATE SET role = EXCLUDED.role
        """), {
            "team_id": team_id,
            "user_id": account.id,
            "role": request.role,
        })
        session.execute(text("""
            UPDATE collaboration_teams SET updated_at = NOW() WHERE id = :team_id
        """), {"team_id": team_id})
        session.commit()
    return {
        "id": account.id,
        "name": account.name,
        "email": account.email,
        "role": request.role,
    }


@router.patch("/teams/{team_id}/members/{member_id}")
async def update_member(
    request: MemberRoleRequest,
    team_id: int = Path(..., gt=0),
    member_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        require_team_role(session, team_id, user.user_id, {"owner"})
        result = session.execute(text("""
            UPDATE collaboration_team_members SET role = :role
            WHERE team_id = :team_id AND user_id = :member_id AND role <> 'owner'
            RETURNING user_id
        """), {"role": request.role, "team_id": team_id, "member_id": member_id})
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Editable team member not found")
        session.commit()
    return {"id": member_id, "role": request.role}


@router.delete("/teams/{team_id}/members/{member_id}")
async def remove_member(
    team_id: int = Path(..., gt=0),
    member_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        actor_role = membership_role(session, team_id, user.user_id)
        if actor_role != "owner" and member_id != user.user_id:
            raise HTTPException(status_code=403, detail="Insufficient team permissions")
        result = session.execute(text("""
            DELETE FROM collaboration_team_members
            WHERE team_id = :team_id AND user_id = :member_id AND role <> 'owner'
            RETURNING user_id
        """), {"team_id": team_id, "member_id": member_id})
        if not result.fetchone():
            raise HTTPException(status_code=404, detail="Removable team member not found")
        session.commit()
    return {"status": "removed", "id": member_id}


@router.get("/teams/{team_id}/items")
async def list_shared_items(
    team_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        membership_role(session, team_id, user.user_id)
        rows = session.execute(text("""
            SELECT item.id, item.resource_type, item.resource_id, item.title,
                   item.resource_url, item.note, item.created_by,
                   account.name AS creator_name, item.created_at, item.updated_at,
                   (SELECT COUNT(*) FROM collaboration_comments comment
                    WHERE comment.item_id = item.id) AS comment_count
            FROM collaboration_shared_items item
            JOIN users account ON account.id = item.created_by
            WHERE item.team_id = :team_id
            ORDER BY item.updated_at DESC, item.id DESC
            LIMIT 250
        """), {"team_id": team_id}).fetchall()
    return [dict(row._mapping) | {
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    } for row in rows]


@router.post("/teams/{team_id}/items", status_code=201)
async def share_item(
    request: SharedItemRequest,
    team_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    if request.resource_type not in RESOURCE_TYPES:
        raise HTTPException(status_code=422, detail="Unsupported resource type")
    title = request.title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Title is required")
    with get_cortellis_session() as session:
        require_team_role(session, team_id, user.user_id, EDIT_ROLES)
        row = session.execute(text("""
            INSERT INTO collaboration_shared_items (
                team_id, resource_type, resource_id, title, resource_url, note, created_by
            ) VALUES (
                :team_id, :resource_type, :resource_id, :title, :resource_url, :note, :created_by
            ) RETURNING id, created_at
        """), {
            "team_id": team_id,
            "resource_type": request.resource_type,
            "resource_id": request.resource_id,
            "title": title,
            "resource_url": request.resource_url,
            "note": request.note,
            "created_by": user.user_id,
        }).fetchone()
        session.execute(text("""
            UPDATE collaboration_teams SET updated_at = NOW() WHERE id = :team_id
        """), {"team_id": team_id})
        session.commit()
    return {"id": row.id, "created_at": str(row.created_at)}


def _item_access(session, item_id: int, user_id: int):
    item = session.execute(text("""
        SELECT id, team_id, created_by FROM collaboration_shared_items
        WHERE id = :item_id
    """), {"item_id": item_id}).fetchone()
    if not item:
        raise HTTPException(status_code=404, detail="Shared item not found")
    role = membership_role(session, item.team_id, user_id)
    return item, role


@router.delete("/items/{item_id}")
async def delete_shared_item(
    item_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        item, role = _item_access(session, item_id, user.user_id)
        if item.created_by != user.user_id and role != "owner":
            raise HTTPException(status_code=403, detail="Only the creator or owner can delete this item")
        session.execute(
            text("DELETE FROM collaboration_shared_items WHERE id = :item_id"),
            {"item_id": item_id},
        )
        session.commit()
    return {"status": "deleted", "id": item_id}


@router.get("/items/{item_id}/comments")
async def list_comments(
    item_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        _item_access(session, item_id, user.user_id)
        rows = session.execute(text("""
            SELECT comment.id, comment.author_id, account.name AS author_name,
                   comment.body, comment.created_at, comment.updated_at
            FROM collaboration_comments comment
            JOIN users account ON account.id = comment.author_id
            WHERE comment.item_id = :item_id
            ORDER BY comment.created_at, comment.id
        """), {"item_id": item_id}).fetchall()
    return [dict(row._mapping) | {
        "created_at": str(row.created_at),
        "updated_at": str(row.updated_at),
    } for row in rows]


@router.post("/items/{item_id}/comments", status_code=201)
async def add_comment(
    request: CommentRequest,
    item_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    body = request.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="Comment is required")
    with get_cortellis_session() as session:
        item, _role = _item_access(session, item_id, user.user_id)
        row = session.execute(text("""
            INSERT INTO collaboration_comments (item_id, author_id, body)
            VALUES (:item_id, :author_id, :body)
            RETURNING id, created_at
        """), {"item_id": item_id, "author_id": user.user_id, "body": body}).fetchone()
        session.execute(text("""
            UPDATE collaboration_shared_items SET updated_at = NOW() WHERE id = :item_id
        """), {"item_id": item_id})
        session.execute(text("""
            UPDATE collaboration_teams SET updated_at = NOW() WHERE id = :team_id
        """), {"team_id": item.team_id})
        session.commit()
    return {"id": row.id, "created_at": str(row.created_at)}


@router.delete("/comments/{comment_id}")
async def delete_comment(
    comment_id: int = Path(..., gt=0),
    user: TokenData = Depends(get_current_user),
):
    with get_cortellis_session() as session:
        comment = session.execute(text("""
            SELECT comment.id, comment.author_id, item.team_id
            FROM collaboration_comments comment
            JOIN collaboration_shared_items item ON item.id = comment.item_id
            WHERE comment.id = :comment_id
        """), {"comment_id": comment_id}).fetchone()
        if not comment:
            raise HTTPException(status_code=404, detail="Comment not found")
        role = membership_role(session, comment.team_id, user.user_id)
        if comment.author_id != user.user_id and role != "owner":
            raise HTTPException(status_code=403, detail="Only the author or owner can delete this comment")
        session.execute(
            text("DELETE FROM collaboration_comments WHERE id = :comment_id"),
            {"comment_id": comment_id},
        )
        session.commit()
    return {"status": "deleted", "id": comment_id}


__all__ = ["router"]
