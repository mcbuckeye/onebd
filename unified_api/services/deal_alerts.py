"""
Deal alerts with contract intelligence.

When new contracts appear via cortellis-sync, this service:
1. Detects newly indexed contracts
2. Auto-generates PageIndex trees
3. Extracts key deal terms
4. Formats and pushes notification summaries
"""
from typing import Optional

import structlog
from sqlalchemy import text

logger = structlog.get_logger(__name__)


def find_new_contracts(session, since_hours: int = 24) -> list:
    """
    Find contracts indexed in the last N hours that don't have
    cached PageIndex trees yet.
    """
    return session.execute(
        text("""
            SELECT cc.id AS contract_id, cc.deal_id, cc.word_count, d.title
            FROM contract_content cc
            JOIN deals d ON d.id = cc.deal_id
            LEFT JOIN contract_tree_index cti ON cti.contract_id = cc.id
            WHERE cc.indexed_at >= NOW() - INTERVAL ':hours hours'
              AND cti.id IS NULL
              AND cc.word_count >= 5000
            ORDER BY cc.word_count DESC
            LIMIT 50
        """.replace(":hours", str(int(since_hours)))),
    ).fetchall()


def format_alert_summary(
    deal_title: str,
    deal_id: int,
    clauses: dict,
) -> str:
    """
    Format extracted deal terms into a concise alert summary.

    Suitable for Telegram/email notification.
    """
    parts = [f"📋 **New Contract Filed**\n{deal_title}\n(Deal #{deal_id})\n"]

    # Financial terms
    upfront = clauses.get("upfront_payment")
    if upfront and upfront.get("amount"):
        parts.append(f"💰 Upfront: ${upfront['amount']}M {upfront.get('currency', 'USD')}")

    royalties = clauses.get("royalty_rates")
    if royalties:
        rates = []
        for r in royalties:
            if r.get("min_rate") and r.get("max_rate"):
                rates.append(f"{r['min_rate']}-{r['max_rate']}%")
            elif r.get("min_rate"):
                rates.append(f"{r['min_rate']}%")
        if rates:
            parts.append(f"📊 Royalties: {', '.join(rates)}")

    # License scope
    scope = clauses.get("license_scope")
    if scope and scope.get("type"):
        field = scope.get("field", "")
        parts.append(f"🔑 License: {scope['type']}{f' — {field}' if field else ''}")

    # Territories
    territories = clauses.get("territories")
    if territories:
        parts.append(f"🌍 Territory: {', '.join(territories[:3])}")

    # Milestones
    milestones = clauses.get("milestones")
    if milestones:
        total = 0
        for category in ["clinical", "regulatory", "commercial"]:
            for m in milestones.get(category, []):
                if m.get("amount"):
                    total += m["amount"]
        if total > 0:
            parts.append(f"🎯 Milestones: up to ${total}M total")

    # Total value
    total_val = clauses.get("total_potential_value")
    if total_val and total_val.get("amount"):
        parts.append(f"💎 Total potential value: ${total_val['amount']}M")

    if len(parts) == 1:
        parts.append("ℹ️ Financial terms not disclosed or redacted")

    return "\n".join(parts)
