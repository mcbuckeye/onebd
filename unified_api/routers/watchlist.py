"""
Watchlist and Notes endpoints for tracking deals.
"""
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Path
from pydantic import BaseModel
import structlog

logger = structlog.get_logger(__name__)

router = APIRouter()


# ============================================
# Models
# ============================================

class WatchlistItem(BaseModel):
    """A deal in the watchlist."""
    id: int
    deal_id: int
    deal_title: Optional[str] = None
    status: str = "watching"
    tags: List[str] = []
    added_at: Optional[str] = None
    updated_at: Optional[str] = None
    # Deal summary data
    principal_company: Optional[str] = None
    partner_company: Optional[str] = None
    deal_status: Optional[str] = None
    total_value: Optional[float] = None
    date_start: Optional[str] = None
    note_count: int = 0


class WatchlistAddRequest(BaseModel):
    """Request to add deal to watchlist."""
    deal_id: int
    status: str = "watching"
    tags: List[str] = []


class WatchlistUpdateRequest(BaseModel):
    """Request to update watchlist item."""
    status: Optional[str] = None
    tags: Optional[List[str]] = None


class WatchlistResponse(BaseModel):
    """Response containing watchlist items."""
    total: int
    items: List[WatchlistItem]


class NoteItem(BaseModel):
    """A note on a deal."""
    id: int
    deal_id: int
    content: str
    is_private: bool = True
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class NoteCreateRequest(BaseModel):
    """Request to create a note."""
    content: str
    is_private: bool = True


class NoteUpdateRequest(BaseModel):
    """Request to update a note."""
    content: str


class SavedSearch(BaseModel):
    """A saved search configuration."""
    id: int
    name: str
    description: Optional[str] = None
    criteria: dict
    is_alert: bool = False
    alert_frequency: Optional[str] = None
    last_run_at: Optional[str] = None
    created_at: Optional[str] = None


class SavedSearchCreateRequest(BaseModel):
    """Request to create a saved search."""
    name: str
    description: Optional[str] = None
    criteria: dict
    is_alert: bool = False
    alert_frequency: Optional[str] = None


# ============================================
# Watchlist Endpoints
# ============================================

@router.get("/watchlist", response_model=WatchlistResponse)
async def get_watchlist(
    user_id: str = Query("default", description="User ID"),
    status: Optional[str] = Query(None, description="Filter by status"),
    tag: Optional[str] = Query(None, description="Filter by tag"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Get user's watchlist with deal summaries.

    Includes deal metadata and note counts.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting watchlist", user_id=user_id, status=status)

    conditions = ["w.user_id = :user_id"]
    params = {"user_id": user_id, "limit": limit, "offset": offset}

    if status:
        conditions.append("w.status = :status")
        params["status"] = status

    if tag:
        conditions.append(":tag = ANY(w.tags)")
        params["tag"] = tag

    where_clause = " AND ".join(conditions)

    query = f"""
        SELECT
            w.id,
            w.deal_id,
            w.status,
            w.tags,
            w.added_at::text,
            w.updated_at::text,
            d.title as deal_title,
            d.status as deal_status,
            d.date_start::text,
            f.total_projected_current_amount as total_value,
            (SELECT c.name FROM deal_companies dc
             JOIN companies c ON c.id = dc.company_id
             WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal_company,
            (SELECT c.name FROM deal_companies dc
             JOIN companies c ON c.id = dc.company_id
             WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner_company,
            (SELECT COUNT(*) FROM deal_notes n WHERE n.deal_id = w.deal_id AND n.user_id = w.user_id) as note_count
        FROM user_watchlist w
        JOIN deals d ON d.id = w.deal_id
        LEFT JOIN deal_finance_summary f ON f.deal_id = d.id
        WHERE {where_clause}
        ORDER BY w.added_at DESC
        LIMIT :limit OFFSET :offset
    """

    count_query = f"""
        SELECT COUNT(*) FROM user_watchlist w
        WHERE {where_clause}
    """

    with get_cortellis_session() as session:
        total = session.execute(text(count_query), params).scalar()
        result = session.execute(text(query), params)

        items = [
            WatchlistItem(
                id=row.id,
                deal_id=row.deal_id,
                deal_title=row.deal_title,
                status=row.status,
                tags=row.tags or [],
                added_at=row.added_at,
                updated_at=row.updated_at,
                principal_company=row.principal_company,
                partner_company=row.partner_company,
                deal_status=row.deal_status,
                total_value=float(row.total_value) if row.total_value else None,
                date_start=row.date_start,
                note_count=row.note_count,
            )
            for row in result
        ]

    return WatchlistResponse(total=total or 0, items=items)


@router.post("/watchlist")
async def add_to_watchlist(
    request: WatchlistAddRequest,
    user_id: str = Query("default", description="User ID"),
):
    """
    Add a deal to the watchlist.

    Status options: watching, interested, reviewing, passed, in_discussion
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Adding to watchlist", user_id=user_id, deal_id=request.deal_id)

    with get_cortellis_session() as session:
        # Check if deal exists
        deal = session.execute(text(
            "SELECT id, title FROM deals WHERE id = :deal_id"
        ), {"deal_id": request.deal_id}).fetchone()

        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")

        # Insert or update
        result = session.execute(text("""
            INSERT INTO user_watchlist (user_id, deal_id, status, tags)
            VALUES (:user_id, :deal_id, :status, :tags)
            ON CONFLICT (user_id, deal_id) DO UPDATE SET
                status = EXCLUDED.status,
                tags = EXCLUDED.tags,
                updated_at = NOW()
            RETURNING id, added_at::text
        """), {
            "user_id": user_id,
            "deal_id": request.deal_id,
            "status": request.status,
            "tags": request.tags,
        })
        row = result.fetchone()
        session.commit()

    return {
        "success": True,
        "id": row.id,
        "deal_id": request.deal_id,
        "deal_title": deal.title,
        "added_at": row.added_at,
    }


@router.patch("/watchlist/{deal_id}")
async def update_watchlist_item(
    deal_id: int = Path(..., gt=0),
    request: WatchlistUpdateRequest = None,
    user_id: str = Query("default", description="User ID"),
):
    """
    Update a watchlist item's status or tags.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Updating watchlist item", user_id=user_id, deal_id=deal_id)

    updates = []
    params = {"user_id": user_id, "deal_id": deal_id}

    if request.status is not None:
        updates.append("status = :status")
        params["status"] = request.status

    if request.tags is not None:
        updates.append("tags = :tags")
        params["tags"] = request.tags

    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")

    updates.append("updated_at = NOW()")
    update_clause = ", ".join(updates)

    with get_cortellis_session() as session:
        result = session.execute(text(f"""
            UPDATE user_watchlist SET {update_clause}
            WHERE user_id = :user_id AND deal_id = :deal_id
            RETURNING id, status, tags, updated_at::text
        """), params)
        row = result.fetchone()
        session.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Watchlist item not found")

    return {
        "success": True,
        "id": row.id,
        "deal_id": deal_id,
        "status": row.status,
        "tags": row.tags,
        "updated_at": row.updated_at,
    }


@router.delete("/watchlist/{deal_id}")
async def remove_from_watchlist(
    deal_id: int = Path(..., gt=0),
    user_id: str = Query("default", description="User ID"),
):
    """
    Remove a deal from the watchlist.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Removing from watchlist", user_id=user_id, deal_id=deal_id)

    with get_cortellis_session() as session:
        result = session.execute(text("""
            DELETE FROM user_watchlist
            WHERE user_id = :user_id AND deal_id = :deal_id
            RETURNING id
        """), {"user_id": user_id, "deal_id": deal_id})
        row = result.fetchone()
        session.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Watchlist item not found")

    return {"success": True, "deleted_id": row.id}


@router.get("/watchlist/stats")
async def get_watchlist_stats(
    user_id: str = Query("default", description="User ID"),
):
    """
    Get watchlist statistics by status.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    with get_cortellis_session() as session:
        result = session.execute(text("""
            SELECT
                status,
                COUNT(*) as count
            FROM user_watchlist
            WHERE user_id = :user_id
            GROUP BY status
        """), {"user_id": user_id})

        stats = {row.status: row.count for row in result}
        total = sum(stats.values())

    return {"total": total, "by_status": stats}


# ============================================
# Notes Endpoints
# ============================================

@router.get("/deals/{deal_id}/notes", response_model=List[NoteItem])
async def get_deal_notes(
    deal_id: int = Path(..., gt=0),
    user_id: str = Query("default", description="User ID"),
):
    """
    Get all notes for a deal.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting deal notes", deal_id=deal_id, user_id=user_id)

    with get_cortellis_session() as session:
        result = session.execute(text("""
            SELECT id, deal_id, content, is_private, created_at::text, updated_at::text
            FROM deal_notes
            WHERE deal_id = :deal_id AND user_id = :user_id
            ORDER BY created_at DESC
        """), {"deal_id": deal_id, "user_id": user_id})

        return [
            NoteItem(
                id=row.id,
                deal_id=row.deal_id,
                content=row.content,
                is_private=row.is_private,
                created_at=row.created_at,
                updated_at=row.updated_at,
            )
            for row in result
        ]


@router.post("/deals/{deal_id}/notes")
async def create_note(
    deal_id: int = Path(..., gt=0),
    request: NoteCreateRequest = None,
    user_id: str = Query("default", description="User ID"),
):
    """
    Add a note to a deal.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Creating note", deal_id=deal_id, user_id=user_id)

    with get_cortellis_session() as session:
        # Check if deal exists
        deal = session.execute(text(
            "SELECT id FROM deals WHERE id = :deal_id"
        ), {"deal_id": deal_id}).fetchone()

        if not deal:
            raise HTTPException(status_code=404, detail="Deal not found")

        result = session.execute(text("""
            INSERT INTO deal_notes (deal_id, user_id, content, is_private)
            VALUES (:deal_id, :user_id, :content, :is_private)
            RETURNING id, created_at::text
        """), {
            "deal_id": deal_id,
            "user_id": user_id,
            "content": request.content,
            "is_private": request.is_private,
        })
        row = result.fetchone()
        session.commit()

    return {
        "success": True,
        "id": row.id,
        "deal_id": deal_id,
        "created_at": row.created_at,
    }


@router.patch("/notes/{note_id}")
async def update_note(
    note_id: int = Path(..., gt=0),
    request: NoteUpdateRequest = None,
    user_id: str = Query("default", description="User ID"),
):
    """
    Update a note.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Updating note", note_id=note_id, user_id=user_id)

    with get_cortellis_session() as session:
        result = session.execute(text("""
            UPDATE deal_notes SET
                content = :content,
                updated_at = NOW()
            WHERE id = :note_id AND user_id = :user_id
            RETURNING id, deal_id, updated_at::text
        """), {
            "note_id": note_id,
            "user_id": user_id,
            "content": request.content,
        })
        row = result.fetchone()
        session.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Note not found")

    return {
        "success": True,
        "id": row.id,
        "deal_id": row.deal_id,
        "updated_at": row.updated_at,
    }


@router.delete("/notes/{note_id}")
async def delete_note(
    note_id: int = Path(..., gt=0),
    user_id: str = Query("default", description="User ID"),
):
    """
    Delete a note.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Deleting note", note_id=note_id, user_id=user_id)

    with get_cortellis_session() as session:
        result = session.execute(text("""
            DELETE FROM deal_notes
            WHERE id = :note_id AND user_id = :user_id
            RETURNING id
        """), {"note_id": note_id, "user_id": user_id})
        row = result.fetchone()
        session.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Note not found")

    return {"success": True, "deleted_id": row.id}


# ============================================
# Saved Searches Endpoints
# ============================================

@router.get("/saved-searches", response_model=List[SavedSearch])
async def get_saved_searches(
    user_id: str = Query("default", description="User ID"),
    alerts_only: bool = Query(False, description="Only return alert subscriptions"),
):
    """
    Get user's saved searches.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting saved searches", user_id=user_id)

    conditions = ["user_id = :user_id"]
    params = {"user_id": user_id}

    if alerts_only:
        conditions.append("is_alert = TRUE")

    where_clause = " AND ".join(conditions)

    with get_cortellis_session() as session:
        result = session.execute(text(f"""
            SELECT id, name, description, criteria, is_alert, alert_frequency,
                   last_run_at::text, created_at::text
            FROM saved_searches
            WHERE {where_clause}
            ORDER BY created_at DESC
        """), params)

        return [
            SavedSearch(
                id=row.id,
                name=row.name,
                description=row.description,
                criteria=row.criteria,
                is_alert=row.is_alert,
                alert_frequency=row.alert_frequency,
                last_run_at=row.last_run_at,
                created_at=row.created_at,
            )
            for row in result
        ]


@router.post("/saved-searches")
async def create_saved_search(
    request: SavedSearchCreateRequest,
    user_id: str = Query("default", description="User ID"),
):
    """
    Create a saved search (optionally as an alert).

    Alert frequency options: daily, weekly
    """
    from sqlalchemy import text
    import json
    from unified_api.services.database import get_cortellis_session

    logger.info("Creating saved search", user_id=user_id, name=request.name)

    with get_cortellis_session() as session:
        result = session.execute(text("""
            INSERT INTO saved_searches (user_id, name, description, criteria, is_alert, alert_frequency)
            VALUES (:user_id, :name, :description, :criteria, :is_alert, :alert_frequency)
            RETURNING id, created_at::text
        """), {
            "user_id": user_id,
            "name": request.name,
            "description": request.description,
            "criteria": json.dumps(request.criteria),
            "is_alert": request.is_alert,
            "alert_frequency": request.alert_frequency,
        })
        row = result.fetchone()
        session.commit()

    return {
        "success": True,
        "id": row.id,
        "name": request.name,
        "is_alert": request.is_alert,
        "created_at": row.created_at,
    }


@router.delete("/saved-searches/{search_id}")
async def delete_saved_search(
    search_id: int = Path(..., gt=0),
    user_id: str = Query("default", description="User ID"),
):
    """
    Delete a saved search.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Deleting saved search", search_id=search_id, user_id=user_id)

    with get_cortellis_session() as session:
        result = session.execute(text("""
            DELETE FROM saved_searches
            WHERE id = :search_id AND user_id = :user_id
            RETURNING id
        """), {"search_id": search_id, "user_id": user_id})
        row = result.fetchone()
        session.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Saved search not found")

    return {"success": True, "deleted_id": row.id}


# ============================================
# Notifications Endpoints
# ============================================

class NotificationItem(BaseModel):
    """An alert notification for a deal."""
    id: int
    deal_id: int
    deal_title: Optional[str] = None
    alert_name: str
    content: str
    created_at: Optional[str] = None
    # Deal summary
    principal_company: Optional[str] = None
    partner_company: Optional[str] = None
    date_start: Optional[str] = None


class NotificationsResponse(BaseModel):
    """Response containing notifications."""
    total: int
    unread_count: int
    items: List[NotificationItem]


@router.get("/notifications", response_model=NotificationsResponse)
async def get_notifications(
    user_id: str = Query("default", description="User ID"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Get alert notifications for user.

    Notifications are generated by the daily alert check Celery task
    when saved searches with is_alert=TRUE find new matching deals.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Getting notifications", user_id=user_id)

    with get_cortellis_session() as session:
        # Get alert notifications (notes starting with [Alert:)
        result = session.execute(text("""
            SELECT
                n.id,
                n.deal_id,
                n.content,
                n.created_at::text,
                d.title as deal_title,
                d.date_start::text,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Principal' LIMIT 1) as principal_company,
                (SELECT c.name FROM deal_companies dc
                 JOIN companies c ON c.id = dc.company_id
                 WHERE dc.deal_id = d.id AND dc.role = 'Partner' LIMIT 1) as partner_company
            FROM deal_notes n
            JOIN deals d ON d.id = n.deal_id
            WHERE n.user_id = :user_id
              AND n.content LIKE '[Alert:%'
            ORDER BY n.created_at DESC
            LIMIT :limit OFFSET :offset
        """), {"user_id": user_id, "limit": limit, "offset": offset})

        items = []
        for row in result:
            # Extract alert name from content like "[Alert: My Search] New deal..."
            content = row.content
            alert_name = "Unknown Alert"
            if content.startswith("[Alert:"):
                end_bracket = content.find("]")
                if end_bracket > 7:
                    alert_name = content[7:end_bracket].strip()

            items.append(NotificationItem(
                id=row.id,
                deal_id=row.deal_id,
                deal_title=row.deal_title,
                alert_name=alert_name,
                content=content,
                created_at=row.created_at,
                principal_company=row.principal_company,
                partner_company=row.partner_company,
                date_start=row.date_start,
            ))

        # Get total count
        count_result = session.execute(text("""
            SELECT COUNT(*) FROM deal_notes
            WHERE user_id = :user_id AND content LIKE '[Alert:%'
        """), {"user_id": user_id})
        total = count_result.scalar() or 0

    return NotificationsResponse(
        total=total,
        unread_count=total,  # All are "unread" for now - could add read tracking
        items=items,
    )


@router.delete("/notifications/{notification_id}")
async def dismiss_notification(
    notification_id: int = Path(..., gt=0),
    user_id: str = Query("default", description="User ID"),
):
    """
    Dismiss (delete) a notification.
    """
    from sqlalchemy import text
    from unified_api.services.database import get_cortellis_session

    logger.info("Dismissing notification", notification_id=notification_id, user_id=user_id)

    with get_cortellis_session() as session:
        result = session.execute(text("""
            DELETE FROM deal_notes
            WHERE id = :notification_id
              AND user_id = :user_id
              AND content LIKE '[Alert:%'
            RETURNING id
        """), {"notification_id": notification_id, "user_id": user_id})
        row = result.fetchone()
        session.commit()

        if not row:
            raise HTTPException(status_code=404, detail="Notification not found")

    return {"success": True, "deleted_id": row.id}


@router.post("/alerts/trigger")
async def trigger_alerts_check(
    user_id: str = Query("default", description="User ID (admin only)"),
):
    """
    Manually trigger the alert check task.

    This runs the same logic as the daily scheduled task.
    Useful for testing alerts without waiting for the scheduled run.
    """
    from unified_api.workers.celery_app import check_alerts

    logger.info("Manually triggering alert check", user_id=user_id)

    # Queue the task asynchronously
    task = check_alerts.delay()

    return {
        "success": True,
        "message": "Alert check task queued",
        "task_id": task.id,
    }
