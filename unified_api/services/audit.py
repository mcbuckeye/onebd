"""
Audit logging service
Logs user actions for security and compliance.
"""
from typing import Optional, Dict, Any
from sqlalchemy import text
import structlog

from unified_api.services.database import get_cortellis_session

logger = structlog.get_logger(__name__)


def log_audit(
    action: str,
    user_id: Optional[int] = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
):
    """
    Log an audit event to the database.
    
    Args:
        action: Action performed (e.g., 'login', 'search', 'export')
        user_id: ID of user who performed the action
        entity_type: Type of entity affected (e.g., 'deal', 'company')
        entity_id: ID of entity affected
        ip_address: IP address of the request
        metadata: Additional context as JSON
    """
    try:
        with get_cortellis_session() as session:
            # Ensure table exists
            session.execute(text("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id SERIAL PRIMARY KEY,
                    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
                    action VARCHAR(100) NOT NULL,
                    entity_type VARCHAR(50),
                    entity_id VARCHAR(255),
                    ip_address VARCHAR(45),
                    metadata JSONB,
                    created_at TIMESTAMP DEFAULT NOW()
                )
            """))

            # Insert audit log
            session.execute(
                text("""
                    INSERT INTO audit_log 
                        (user_id, action, entity_type, entity_id, ip_address, metadata)
                    VALUES 
                        (:user_id, :action, :entity_type, :entity_id, :ip_address, :metadata)
                """),
                {
                    "user_id": user_id,
                    "action": action,
                    "entity_type": entity_type,
                    "entity_id": entity_id,
                    "ip_address": ip_address,
                    "metadata": metadata,
                }
            )
            session.commit()

            logger.info(
                "audit_logged",
                action=action,
                user_id=user_id,
                entity_type=entity_type,
                entity_id=entity_id
            )
    except Exception as e:
        logger.error("Failed to log audit event", action=action, error=str(e))
        # Don't raise - audit logging should not break application flow
