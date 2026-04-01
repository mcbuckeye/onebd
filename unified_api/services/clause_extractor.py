"""
Contract Clause Extraction Service

Uses GPT-4o to extract structured deal terms from contract text.
Two extraction modes:
1. Tree-guided (preferred): Uses cached PageIndex tree to target relevant sections
2. Brute-force (fallback): Sends full contract text (truncated at 100K chars)

Extracts:
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

# Keywords for finding financial/legal sections in tree index
_CLAUSE_SECTION_KEYWORDS = [
    "financial", "payment", "royalt", "milestone", "upfront",
    "license", "territory", "terminat", "confidential",
    "intellectual property", "ip", "indemnif", "obligation",
    "representation", "warrant", "scope", "exclusiv",
]


def _find_relevant_lines_from_tree(tree_json: dict) -> list[int]:
    """Find line numbers of financial/legal sections from a PageIndex tree."""
    results = []

    def _search(nodes: list) -> None:
        for n in nodes:
            title = n.get("title", "").lower()
            for kw in _CLAUSE_SECTION_KEYWORDS:
                if kw in title:
                    line_num = n.get("line_num", 0)
                    if line_num > 0:
                        results.append(line_num)
                    break
            for child in n.get("nodes", []):
                _search([child])

    _search(tree_json.get("structure", []))
    return sorted(set(results))


async def extract_clauses_with_tree(
    contract_text: str,
    tree_json: dict,
    deal_id: Optional[int] = None,
) -> dict:
    """
    Extract clauses using PageIndex tree-guided approach.

    Instead of sending the entire contract to GPT-4o, we use the tree index
    to identify financial and legal sections, then extract clauses only from
    those targeted sections. More accurate and cheaper.
    """
    import openai
    from unified_api.services.html_cleaner import clean_contract_html

    if not settings.openai_api_key:
        raise ValueError("OpenAI API key not configured")

    clean_md = clean_contract_html(contract_text)
    doc_lines = clean_md.split("\n")

    # Find relevant sections from tree
    relevant_lines = _find_relevant_lines_from_tree(tree_json)

    if not relevant_lines:
        logger.warning("No relevant sections found in tree, falling back", deal_id=deal_id)
        return await _extract_brute_force(contract_text, deal_id)

    # Extract content from those sections (40 lines each)
    section_texts = []
    for ln in relevant_lines:
        start = max(0, ln - 1)
        end = min(len(doc_lines), start + 40)
        chunk = "\n".join(doc_lines[start:end]).strip()
        if chunk:
            section_texts.append(chunk)

    targeted_text = "\n\n---\n\n".join(section_texts)

    # Send only targeted sections to GPT-4o
    client = openai.AsyncOpenAI(api_key=settings.openai_api_key)

    try:
        response = await client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a pharmaceutical deal analyst specializing in contract analysis. Extract deal terms precisely.",
                },
                {"role": "user", "content": EXTRACTION_PROMPT + targeted_text},
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
            "extraction_method": "pageindex_tree_guided",
            "sections_targeted": len(relevant_lines),
        }

        logger.info(
            "Tree-guided clause extraction completed",
            deal_id=deal_id,
            sections=len(relevant_lines),
            tokens=response.usage.total_tokens if response.usage else None,
        )
        return result

    except json.JSONDecodeError as e:
        logger.error("Failed to parse tree-guided extraction response", error=str(e))
        return {
            "error": "Failed to parse response",
            "raw": response.choices[0].message.content[:500],
        }
    except Exception as e:
        logger.error("Tree-guided clause extraction failed", error=str(e), deal_id=deal_id)
        raise


async def _extract_brute_force(contract_text: str, deal_id: Optional[int] = None) -> dict:
    """Original brute-force extraction — sends full contract to LLM."""
    import openai

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
                    "content": "You are a pharmaceutical deal analyst specializing in contract analysis. Extract deal terms precisely.",
                },
                {"role": "user", "content": EXTRACTION_PROMPT + contract_text},
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
            "extraction_method": "brute_force",
        }

        logger.info(
            "Brute-force clause extraction completed",
            deal_id=deal_id,
            tokens=response.usage.total_tokens if response.usage else None,
        )
        return result

    except json.JSONDecodeError as e:
        logger.error("Failed to parse extraction response", error=str(e))
        return {
            "error": "Failed to parse response",
            "raw": response.choices[0].message.content[:500],
        }
    except Exception as e:
        logger.error("Clause extraction failed", error=str(e), deal_id=deal_id)
        raise


async def extract_clauses(contract_text: str, deal_id: Optional[int] = None) -> dict:
    """
    Extract structured clauses from contract text using GPT-4o.

    Tries tree-guided extraction first (if deal has a cached PageIndex tree),
    then falls back to brute-force extraction.

    Args:
        contract_text: The contract text to analyze
        deal_id: Optional deal ID for logging and tree cache lookup

    Returns:
        Dict with extracted clause data
    """
    if not settings.openai_api_key:
        raise ValueError("OpenAI API key not configured")

    # Try tree-guided extraction if deal has a cached tree
    if deal_id:
        try:
            from unified_api.services.tree_cache import TreeCache
            from unified_api.services.database import get_cortellis_session_factory

            factory = get_cortellis_session_factory()
            cache = TreeCache(session_factory=factory)
            tree = cache.get_tree_by_deal(deal_id)
            if tree:
                logger.info("Using tree-guided clause extraction", deal_id=deal_id)
                return await extract_clauses_with_tree(contract_text, tree, deal_id)
        except Exception as e:
            logger.warning(
                "Tree-guided extraction failed, falling back to brute-force",
                error=str(e),
                deal_id=deal_id,
            )

    # Fallback to brute-force
    return await _extract_brute_force(contract_text, deal_id)
