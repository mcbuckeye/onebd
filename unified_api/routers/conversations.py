"""Chat conversation persistence."""
import structlog
import json
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import List, Optional
from sqlalchemy import text
from unified_api.services.database import get_cortellis_session
from unified_api.services.auth import TokenData
from unified_api.routers.auth import get_current_user

logger = structlog.get_logger(__name__)
router = APIRouter(prefix="/conversations", tags=["Conversations"])

SAVE_MESSAGE_SQL = text("""
    INSERT INTO chat_messages (conversation_id, role, content, intent, metadata)
    VALUES (:cid, :role, :content, :intent, CAST(:metadata AS JSONB))
    RETURNING id
""")


class MessageOut(BaseModel):
    role: str
    content: str
    intent: Optional[str] = None
    timestamp: Optional[str] = None


class ConversationSummary(BaseModel):
    id: int
    title: str
    message_count: int
    created_at: str
    updated_at: str


class ConversationDetail(BaseModel):
    id: int
    title: str
    messages: List[MessageOut]
    created_at: str
    updated_at: str


class SaveMessageRequest(BaseModel):
    conversation_id: Optional[int] = None  # None = create new conversation
    role: str
    content: str
    intent: Optional[str] = None
    metadata: Optional[dict] = None


class SaveMessageResponse(BaseModel):
    conversation_id: int
    message_id: int


@router.get("", response_model=List[ConversationSummary])
async def list_conversations(
    limit: int = 20,
    user: TokenData = Depends(get_current_user)
):
    """List recent conversations for the current user."""
    with get_cortellis_session() as session:
        results = session.execute(text("""
            SELECT c.id, c.title, c.created_at::text, c.updated_at::text,
                   (SELECT COUNT(*) FROM chat_messages m WHERE m.conversation_id = c.id) as message_count
            FROM chat_conversations c
            WHERE c.user_id = :uid
            ORDER BY c.updated_at DESC
            LIMIT :limit
        """), {"uid": user.user_id, "limit": limit})
        
        return [ConversationSummary(
            id=r.id, title=r.title, message_count=r.message_count,
            created_at=r.created_at, updated_at=r.updated_at,
        ) for r in results]


@router.get("/{conversation_id}", response_model=ConversationDetail)
async def get_conversation(conversation_id: int, user: TokenData = Depends(get_current_user)):
    """Get a conversation with all messages."""
    with get_cortellis_session() as session:
        conv = session.execute(text("""
            SELECT id, title, created_at::text, updated_at::text
            FROM chat_conversations WHERE id = :id AND user_id = :uid
        """), {"id": conversation_id, "uid": user.user_id}).fetchone()
        
        if not conv:
            raise HTTPException(status_code=404, detail="Conversation not found")
        
        messages = session.execute(text("""
            SELECT role, content, intent, created_at::text as timestamp
            FROM chat_messages WHERE conversation_id = :cid
            ORDER BY created_at ASC
        """), {"cid": conversation_id})
        
        return ConversationDetail(
            id=conv.id, title=conv.title,
            messages=[MessageOut(role=m.role, content=m.content, intent=m.intent, timestamp=m.timestamp) for m in messages],
            created_at=conv.created_at, updated_at=conv.updated_at,
        )


@router.post("/message", response_model=SaveMessageResponse)
async def save_message(req: SaveMessageRequest, user: TokenData = Depends(get_current_user)):
    """Save a message to a conversation. Creates new conversation if conversation_id is None."""
    with get_cortellis_session() as session:
        if req.conversation_id is None:
            # Create new conversation - title from first message
            title = req.content[:100] if req.role == 'user' else 'New conversation'
            result = session.execute(text("""
                INSERT INTO chat_conversations (user_id, title) VALUES (:uid, :title)
                RETURNING id
            """), {"uid": user.user_id, "title": title})
            conv_id = result.fetchone().id
        else:
            # Verify conversation belongs to user
            exists = session.execute(text("""
                SELECT id FROM chat_conversations WHERE id = :id AND user_id = :uid
            """), {"id": req.conversation_id, "uid": user.user_id}).fetchone()
            if not exists:
                raise HTTPException(status_code=404, detail="Conversation not found")
            conv_id = req.conversation_id
            
            # Update conversation timestamp
            session.execute(text("""
                UPDATE chat_conversations SET updated_at = NOW() WHERE id = :id
            """), {"id": conv_id})
        
        # Save message
        result = session.execute(SAVE_MESSAGE_SQL, {
            "cid": conv_id,
            "role": req.role,
            "content": req.content,
            "intent": req.intent,
            "metadata": json.dumps(req.metadata) if req.metadata else None,
        })
        msg_id = result.fetchone().id
        session.commit()
        
        return SaveMessageResponse(conversation_id=conv_id, message_id=msg_id)


@router.delete("/{conversation_id}")
async def delete_conversation(conversation_id: int, user: TokenData = Depends(get_current_user)):
    """Delete a conversation."""
    with get_cortellis_session() as session:
        session.execute(text("DELETE FROM chat_messages WHERE conversation_id = :id"), {"id": conversation_id})
        result = session.execute(text("DELETE FROM chat_conversations WHERE id = :id AND user_id = :uid"),
                                  {"id": conversation_id, "uid": user.user_id})
        session.commit()
        if result.rowcount == 0:
            raise HTTPException(status_code=404, detail="Conversation not found")
        return {"status": "deleted"}


def ensure_conversation_schema(session) -> None:
    """Create conversation tables during the deployment migration phase."""
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_conversations (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title VARCHAR(255) NOT NULL DEFAULT 'New conversation',
            created_at TIMESTAMP DEFAULT NOW(),
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """))
    session.execute(text("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id SERIAL PRIMARY KEY,
            conversation_id INTEGER NOT NULL REFERENCES chat_conversations(id),
            role VARCHAR(20) NOT NULL,
            content TEXT NOT NULL,
            intent VARCHAR(50),
            metadata JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """))
    session.commit()
