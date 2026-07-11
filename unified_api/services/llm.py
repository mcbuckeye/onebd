"""
LLM service for natural language query processing.

Supports query classification, SQL generation, and response formatting.
"""
from typing import Optional, List, Literal
from openai import AsyncOpenAI
import json
import structlog

from unified_api.config import settings

logger = structlog.get_logger(__name__)

# Query intent classification
QUERY_INTENTS = Literal[
    "deal_search",      # Find deals with specific criteria
    "company_lookup",   # Get info about a company
    "company_compare",  # Compare companies
    "drug_lookup",      # Get info about a drug/asset
    "contract_search",  # Search contract text
    "valuation",        # Valuation benchmarks/comps
    "market_trends",    # Market activity trends
    "relationship",     # Graph/relationship queries
    "general",          # General question
]

INTENT_PROMPT = """You are a query classifier for a pharmaceutical deals database.

Classify the user's query into one of these categories:
- deal_search: Finding deals with specific criteria (company, indication, date range, etc.)
- company_lookup: Getting information about a specific company
- company_compare: Comparing two or more companies
- drug_lookup: Getting information about a specific drug or asset
- contract_search: Searching for specific terms/clauses in contracts
- valuation: Questions about deal values, benchmarks, comparables
- market_trends: Questions about trends over time, market activity
- relationship: Questions about partnerships, networks, connections between companies
- general: General questions about the platform or data

Respond with ONLY the category name, nothing else.

User query: {query}
"""

SQL_GENERATION_PROMPT = """You are a SQL expert for a pharmaceutical deals database.

Given the user's question, generate a PostgreSQL query to answer it.

Available tables and key columns:
- deals: id, title, deal_type, status, date_start, date_end, summary, therapy_area_id
- therapy_areas: id, name (join to get therapy area name)
- companies: id, name, company_type, hq_location
- deal_companies: deal_id, company_id, role ('Principal' or 'Partner')
- drugs: id, name_display, phase_highest_now
- deal_drugs: deal_id, drug_id
- indications: id, name
- deal_indications: deal_id, indication_id
- technologies: id, name
- deal_technologies: deal_id, technology_id
- deal_finance_summary: deal_id, total_projected_current_amount, total_paid_amount (in millions USD)
- deal_timeline_events: deal_id, event_date, event_type, stage, summary
- contract_chunks: id, deal_id, contract_id, content

Important notes:
- Use ILIKE for case-insensitive text matching
- Always include reasonable LIMIT (default 20)
- Join through deal_* junction tables
- total_projected_current_amount is in millions USD
- Use date_start for filtering by date
- CRITICAL: Only ~27% of deals have disclosed financial amounts
- When searching for "largest" or deals with amounts, add: WHERE f.total_projected_current_amount IS NOT NULL
- Use LEFT JOIN for deal_finance_summary since not all deals have financial data
- Use NULLS LAST when ordering by amounts: ORDER BY amount DESC NULLS LAST
- Resolved entities below are authoritative. For status=resolved, filter on the
  supplied companies.id through deal_companies; do not substitute a name match.
- For status=ambiguous, do not silently merge candidates. Return candidate company
  IDs/names so the user can disambiguate.
- Never treat total_projected_current_amount as an upfront, milestone, royalty, or
  acquisition-premium value. If the requested metric has no governed column, do
  not substitute a different financial field.

Resolved entities (JSON):
{resolved_entities}

User question: {question}

Respond with ONLY the SQL query, no explanation. Do not use markdown code blocks.
"""

RESPONSE_FORMAT_PROMPT = """Format the following database query results as a response for a pharmaceutical deals analyst.

User question: {question}

Query results (JSON):
{results}

IMPORTANT FORMATTING RULES:
1. If results contain deal data with IDs, format as a MARKDOWN TABLE
2. Always include the deal 'id' column FIRST so users can click it
3. Include key columns: id, title/name, date_start, status, total_projected_current_amount
4. Keep column headers short and clean (e.g., "id", "title", "date_start", "amount ($M)")
5. Format amounts as numbers (e.g., 500.0 not "500 million")
6. Add a brief summary sentence above the table
7. If empty results, say "No results found" clearly

Example table format:
| id | title | date_start | amount ($M) |
|----|-------|------------|-------------|
| 12345 | Pfizer-AbbVie License | 2024-01-15 | 500.0 |

For contract/RAG search results, provide a brief summary of the relevant excerpts with deal references.
"""

SYNTHESIS_PROMPT = """You are an expert pharmaceutical business development analyst providing intelligence to a biotech CEO.

Given the user's question and the data retrieved, provide a SYNTHESIZED response that includes:

1. **Direct Answer** - Lead with a clear, concise answer in plain language
2. **Supporting Data** - Key numbers, trends, or comparisons that back the answer
3. **Data Quality Note** - Sample size, disclosure rate, or any caveats
4. **Follow-up Suggestions** - 2-3 related questions the user might want to ask next

FORMAT RULES:
- Use markdown formatting (bold, tables, bullet points)
- Lead with the insight, not the methodology
- If data is limited (< 5 results or < 50% disclosed), say so explicitly
- Be specific with numbers — don't round unnecessarily
- When showing financial data, always note if values are in millions USD

User question: {question}

Query mode used: {mode}

Data retrieved ({count} records):
{results}

Provide your synthesized response:
"""


class LLMService:
    """Service for LLM-powered query processing."""

    def __init__(self):
        if not settings.openai_api_key:
            raise ValueError("OPENAI_API_KEY is required for LLM service")

        self.client = AsyncOpenAI(api_key=settings.openai_api_key)
        self.model = settings.openai_model
        logger.info("LLM service initialized", model=self.model)

    async def classify_intent(self, query: str) -> str:
        """Classify the user's query intent."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": INTENT_PROMPT.format(query=query)}
                ],
                max_tokens=50,
                temperature=0,
            )
            intent = response.choices[0].message.content.strip().lower()
            logger.info("Query intent classified", query=query[:50], intent=intent)
            return intent
        except Exception as e:
            logger.error("Intent classification failed", error=str(e))
            return "general"

    async def generate_sql(self, question: str, resolved_entities: Optional[List[dict]] = None) -> str:
        """Generate SQL query from natural language question."""
        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": SQL_GENERATION_PROMPT.format(
                        question=question,
                        resolved_entities=json.dumps(resolved_entities or [], default=str),
                    )}
                ],
                max_tokens=500,
                temperature=0,
            )
            sql = response.choices[0].message.content.strip()
            # Remove markdown code blocks if present
            if sql.startswith("```"):
                sql = sql.split("\n", 1)[1] if "\n" in sql else sql[3:]
            if sql.endswith("```"):
                sql = sql[:-3]
            sql = sql.strip()
            logger.info("SQL generated", question=question[:50], sql=sql[:100])
            return sql
        except Exception as e:
            logger.error("SQL generation failed", error=str(e))
            raise

    async def format_response(self, question: str, results: list) -> str:
        """Format query results as natural language response."""
        try:
            # Limit results to avoid token limits
            limited_results = results[:20] if len(results) > 20 else results
            results_json = json.dumps(limited_results, indent=2, default=str)

            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": RESPONSE_FORMAT_PROMPT.format(
                        question=question,
                        results=results_json
                    )}
                ],
                max_tokens=500,
                temperature=0.3,
            )
            formatted = response.choices[0].message.content.strip()
            logger.info("Response formatted", question=question[:50])
            return formatted
        except Exception as e:
            logger.error("Response formatting failed", error=str(e))
            # Fallback to simple formatting
            if not results:
                return "No results found for your query."
            return f"Found {len(results)} results. Here are the details:\n" + json.dumps(results[:5], indent=2, default=str)

    async def synthesize_response(self, question: str, mode: str, data: list) -> dict:
        """Generate a synthesized intelligence response with confidence indicators."""
        meaningful = any(
            not isinstance(row, dict) or any(value is not None for value in row.values())
            for row in data
        )
        if not data or not meaningful:
            return {
                "answer": (
                    "No supporting records with populated values were found for this "
                    "question, so the platform cannot provide a reliable answer."
                ),
                "confidence": {
                    "data_completeness": f"{len(data)} records retrieved",
                    "sample_size": len(data),
                    "disclosure_rate": None,
                    "evidence_status": "insufficient",
                },
                "follow_ups": _suggest_follow_ups(question),
            }

        limited = data[:30]
        results_json = json.dumps(limited, indent=2, default=str)

        try:
            response = await self.client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "user", "content": SYNTHESIS_PROMPT.format(
                        question=question,
                        mode=mode,
                        count=len(data),
                        results=results_json,
                    )}
                ],
                max_tokens=1000,
                temperature=0.3,
            )
            answer = response.choices[0].message.content.strip()
        except Exception as e:
            logger.error("Synthesis failed", error=str(e))
            answer = f"Found {len(data)} results but failed to synthesize: {str(e)[:200]}"

        # Calculate confidence metrics
        disclosed = sum(1 for d in data if isinstance(d, dict) and (
            d.get('total_value') is not None or 
            d.get('total_projected_current_amount') is not None
        ))

        return {
            "answer": answer,
            "confidence": {
                "data_completeness": f"{len(data)} records retrieved",
                "sample_size": len(data),
                "disclosure_rate": round(disclosed / len(data) * 100, 1) if data else None,
            },
            "follow_ups": _suggest_follow_ups(question),
        }


# Global instance
_llm_service: Optional[LLMService] = None


def get_llm_service() -> LLMService:
    """Get the global LLM service instance."""
    global _llm_service
    if _llm_service is None:
        _llm_service = LLMService()
    return _llm_service


def _suggest_follow_ups(question: str) -> list:
    """Generate contextual follow-up question suggestions."""
    q_lower = question.lower()
    suggestions = []

    if any(w in q_lower for w in ['company', 'pfizer', 'merck', 'novartis', 'roche', 'abbvie']):
        suggestions.append("What are their most recent deals?")
        suggestions.append("Who are their top partners?")
        suggestions.append("Show their deal activity trend over 5 years")

    if any(w in q_lower for w in ['oncology', 'cancer', 'tumor']):
        suggestions.append("What are typical deal values in this space?")
        suggestions.append("Who are the most active acquirers in oncology?")

    if any(w in q_lower for w in ['adc', 'car-t', 'bispecific', 'antibody']):
        suggestions.append("Show me valuation benchmarks for this modality")
        suggestions.append("Which companies are most active in this space?")

    if any(w in q_lower for w in ['value', 'price', 'cost', 'upfront', 'milestone']):
        suggestions.append("Show me comparable deals with disclosed financials")
        suggestions.append("What's the trend in deal values over time?")

    if not suggestions:
        suggestions = [
            "Show me the largest deals this year",
            "What therapy areas are most active?",
            "Who are the top acquirers by deal volume?",
        ]

    return suggestions[:3]
