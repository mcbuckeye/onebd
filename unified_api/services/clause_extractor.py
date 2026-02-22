"""
Contract Clause Extraction Service

Uses GPT-4o to extract structured deal terms from contract text:
- Royalty rates and structures
- Milestone payments (clinical, regulatory, commercial)
- Upfront/signing fees
- License scope and exclusivity
- Territory rights
- Term duration and termination provisions
"""
import json
from typing import Optional, List
import structlog

from unified_api.config import settings

logger = structlog.get_logger(__name__)

EXTRACTION_PROMPT = """You are a pharmaceutical deal analyst. Extract structured deal terms from the following contract text.

Return a JSON object with these fields (use null for any not found):

{
  "upfront_payment": {"amount": number_in_millions, "currency": "USD"},
  "royalty_rates": [
    {"tier": "description", "min_rate": number, "max_rate": number, "notes": "string"}
  ],
  "milestones": {
    "clinical": [{"event": "description", "amount": number_in_millions, "currency": "USD"}],
    "regulatory": [{"event": "description", "amount": number_in_millions, "currency": "USD"}],
    "commercial": [{"event": "description", "amount": number_in_millions, "currency": "USD"}]
  },
  "total_potential_value": {"amount": number_in_millions, "currency": "USD"},
  "license_scope": {"type": "exclusive|non-exclusive|co-exclusive", "field": "description"},
  "territories": ["list of territories"],
  "term_duration": {"years": number, "notes": "string"},
  "termination_provisions": ["list of key provisions"],
  "key_obligations": ["list of key obligations for each party"]
}

IMPORTANT: Only extract what is explicitly stated. Do not infer or guess values.

Contract text:
"""


async def extract_clauses(contract_text: str, deal_id: Optional[int] = None) -> dict:
    """
    Extract structured clauses from contract text using GPT-4o.

    Args:
        contract_text: The contract text to analyze
        deal_id: Optional deal ID for logging

    Returns:
        Dict with extracted clause data
    """
    import openai

    if not settings.openai_api_key:
        raise ValueError("OpenAI API key not configured")

    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    # Truncate very long contracts to fit context window
    max_chars = 100000  # ~25K tokens
    if len(contract_text) > max_chars:
        contract_text = contract_text[:max_chars] + "\n\n[... truncated ...]"

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a pharmaceutical deal analyst specializing in contract analysis. Extract deal terms precisely."
                },
                {
                    "role": "user",
                    "content": EXTRACTION_PROMPT + contract_text
                }
            ],
            response_format={"type": "json_object"},
            temperature=0.1,
            max_tokens=4096,
        )

        result = json.loads(response.choices[0].message.content)
        result["_metadata"] = {
            "model": settings.openai_model,
            "tokens_used": response.usage.total_tokens if response.usage else None,
            "deal_id": deal_id,
        }

        logger.info(
            "Clause extraction completed",
            deal_id=deal_id,
            tokens=response.usage.total_tokens if response.usage else None,
        )

        return result

    except json.JSONDecodeError as e:
        logger.error("Failed to parse extraction response", error=str(e))
        return {"error": "Failed to parse response", "raw": response.choices[0].message.content[:500]}
    except Exception as e:
        logger.error("Clause extraction failed", error=str(e), deal_id=deal_id)
        raise
