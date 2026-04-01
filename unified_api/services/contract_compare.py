"""
Deep contract comparison service using PageIndex.

Upgrades the existing /contracts/compare endpoint to do full-text
comparison across multiple contracts, extracting and comparing
specific deal terms side-by-side.
"""
import asyncio
from typing import Callable, Optional

import structlog

logger = structlog.get_logger(__name__)

DEFAULT_COMPARISON_ASPECTS = [
    "financial terms",
    "royalty rates",
    "milestone payments",
    "termination",
    "ip ownership",
    "license scope",
    "territory rights",
    "confidentiality",
]


async def deep_compare_contracts(
    deal_ids: list[int],
    comparison_aspects: Optional[list[str]] = None,
    session_factory: Callable = None,
    openai_api_key: str = "",
    model: str = "gpt-4o-2024-11-20",
) -> dict:
    """
    Compare contracts across multiple deals using PageIndex deep-read.

    For each deal, reads the contract with PageIndex focusing on the
    specified comparison aspects, then synthesizes a side-by-side comparison.

    Args:
        deal_ids: List of deal IDs to compare (2-5)
        comparison_aspects: What to compare (defaults to DEFAULT_COMPARISON_ASPECTS)
        session_factory: DB session factory
        openai_api_key: OpenAI API key
        model: LLM model

    Returns:
        Dict with per-deal data and synthesized comparison.
    """
    from unified_api.services.agentic_rag.tools.pageindex_tool import PageIndexTool

    if not comparison_aspects:
        comparison_aspects = DEFAULT_COMPARISON_ASPECTS

    aspects_text = ", ".join(comparison_aspects)

    tool = PageIndexTool(
        session_factory=session_factory,
        openai_api_key=openai_api_key,
        model=model,
    )

    # Read each contract
    per_deal = []
    for deal_id in deal_ids[:5]:
        question = f"Extract the following deal terms: {aspects_text}"
        result = await tool._execute_impl(f"deal_id:{deal_id} {question}")

        if result.success and result.data:
            per_deal.append({
                "deal_id": deal_id,
                "success": True,
                "terms": result.data[0].get("answer", ""),
            })
        else:
            per_deal.append({
                "deal_id": deal_id,
                "success": False,
                "error": result.error if result.error else "Unknown error",
            })

    # Synthesize comparison
    import litellm

    deals_context = "\n\n---\n\n".join([
        f"Deal {d['deal_id']}:\n{d.get('terms', d.get('error', 'No data'))[:3000]}"
        for d in per_deal
    ])

    response = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: litellm.completion(
            model=model,
            messages=[{
                "role": "user",
                "content": f"""Compare these {len(per_deal)} pharmaceutical deals side-by-side.

Focus on: {aspects_text}

Deal data:
{deals_context[:15000]}

Create a structured comparison table with one column per deal.
Note any data gaps. Format for a BD analyst audience.""",
            }],
            temperature=0,
            api_key=openai_api_key,
        ),
    )

    return {
        "deals": per_deal,
        "comparison": response.choices[0].message.content.strip(),
        "aspects": comparison_aspects,
        "deal_count": len(per_deal),
    }
