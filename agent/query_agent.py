"""OpenAI GPT-powered query agent for natural language SQL queries with RAG support."""

import logging
import re
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

from openai import OpenAI
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown

from src.config import AppConfig

logger = logging.getLogger(__name__)
console = Console()

# Keywords that indicate a contract content search is needed
CONTRACT_KEYWORDS = [
    "contract", "agreement", "clause", "term", "provision", "obligation",
    "liability", "indemnif", "royalt", "milestone", "payment term", "exclusiv",
    "terminat", "confidential", "intellectual property", "license", "sublicense",
    "warranty", "represent", "covenant", "force majeure", "governing law",
]

DATABASE_SCHEMA = """
## Database Schema for Cortellis Deals

### Core Tables

**deals** - Main deal records
- id (INTEGER, PK) - Deal ID
- title (TEXT) - Deal title
- deal_type (VARCHAR) - Type of deal
- status (VARCHAR) - Deal status (Active, Terminated, Completed, Pending)
- therapy_area_id (INTEGER, FK) - Link to therapy_areas
- date_start (DATETIME) - Start date
- date_end (DATETIME) - End date
- date_event_most_recent (DATETIME) - Most recent event date
- date_change_last (DATETIME) - Last modification date
- date_added (DATETIME) - Date added to database
- summary (TEXT) - Deal summary
- agreement_type (VARCHAR) - Agreement classification
- asset_type (VARCHAR) - Asset type
- transaction_type (VARCHAR) - Transaction type
- phase_highest_start (VARCHAR) - Highest phase at deal start
- phase_highest_now (VARCHAR) - Current highest phase
- is_optional (BOOLEAN) - Has options
- is_merger_acquisition (BOOLEAN) - Is M&A deal
- has_contract (BOOLEAN) - Has contracts

**companies** - Company records
- id (INTEGER, PK) - Company ID
- name (VARCHAR) - Company name
- company_type (VARCHAR) - Type (Pharma, Biotech, etc.)
- hq_location (VARCHAR) - HQ location

**deal_companies** - Links deals to companies
- deal_id (INTEGER, FK)
- company_id (INTEGER, FK)
- role (VARCHAR) - 'Principal' (seller/licensor) or 'Partner' (buyer/licensee)

### Reference Tables

**therapy_areas** - Therapy area classifications
- id (INTEGER, PK)
- name (VARCHAR) - e.g., "Cancer", "Cardiovascular"

**indications** - Medical indications/conditions
- id (INTEGER, PK)
- name (VARCHAR)

**technologies** - Technology types
- id (INTEGER, PK)
- name (VARCHAR)

**actions** - Mechanisms of action
- id (INTEGER, PK)
- name (VARCHAR)

**territories** - Geographic territories
- id (VARCHAR, PK) - e.g., "WO" (World), "US"
- name (VARCHAR)

**drugs** - Drug information
- id (INTEGER, PK)
- name_display (VARCHAR)
- phase_highest_start (VARCHAR)
- phase_highest_now (VARCHAR)

**patents** - Patent records
- id (VARCHAR, PK)
- number (VARCHAR)
- title (TEXT)

### Junction Tables (many-to-many relationships)

**deal_indications** - deal_id, indication_id, is_principal
**deal_technologies** - deal_id, technology_id, is_principal
**deal_actions** - deal_id, action_id, action_type ('Primary' or 'Secondary')
**deal_territories** - deal_id, territory_id, territory_type ('Included' or 'Excluded')
**deal_drugs** - deal_id, drug_id
**deal_patents** - deal_id, patent_id

### Financial Tables

**deal_finance_summary** - High-level financials for each deal
- deal_id (INTEGER, PK, FK)
- total_paid_amount (FLOAT) - Amount already paid in USD millions (NULL if undisclosed)
- total_paid_disclosure_status (VARCHAR)
- total_projected_current_amount (FLOAT) - Current projected total value in USD millions (NULL if undisclosed) - BEST metric for deal size
- total_projected_signing_amount (FLOAT) - Projected at signing in USD millions

NOTE: Only ~27% of deals have disclosed financial values. When finding "largest deals" or deal values:
- Always filter WHERE total_projected_current_amount IS NOT NULL (or total_paid_amount)
- Use total_projected_current_amount as the primary size metric (has more data than total_paid_amount)
- Order by the financial column DESC

**deal_timeline_events** - Timeline of deal events
- id (INTEGER, PK)
- deal_id (INTEGER, FK)
- event_date (DATETIME)
- event_type (VARCHAR) - e.g., "Original Deal", "Deal Amendment", "Option Exercised"
- stage (VARCHAR) - Development stage
- summary (TEXT)

**deal_contracts** - Contract documents
- id (INTEGER, PK) - Contract ID
- deal_id (INTEGER, FK)
- contract_types (TEXT) - Comma-separated types
- has_pdf (BOOLEAN)
- has_text (BOOLEAN)
- date_contract (DATETIME)

**cortellis_deal_sources** - Source citations linked by Cortellis to deals
- deal_id (INTEGER, FK)
- source_id (VARCHAR) - Cortellis source record identifier
- source_type (VARCHAR) - e.g., press release, news, publication
- is_current (BOOLEAN) - current citations from the latest source response

**contract_content** - Full text content of contracts (for full-text search)
- id (INTEGER, PK)
- contract_id (INTEGER, FK)
- deal_id (INTEGER, FK)
- content (TEXT) - Full contract text
- content_tsvector (TSVECTOR) - PostgreSQL full-text search index
- word_count (INTEGER)

**contract_chunks** - Chunked contract text with embeddings (for RAG)
- id (INTEGER, PK)
- contract_id (INTEGER, FK)
- deal_id (INTEGER, FK)
- chunk_index (INTEGER) - Position in document
- content (TEXT) - Chunk text (~512 tokens)
- embedding (VECTOR) - OpenAI embedding
- token_count (INTEGER)

### M&A Tables

**deal_ma_summary** - M&A specific information
- deal_id (INTEGER, PK, FK)
- company_type (VARCHAR)
- ownership (VARCHAR) - Public or Private
- attitude (VARCHAR) - Friendly, Hostile, White Knight
- cash_at_acquisition (FLOAT)
- price_per_share (FLOAT)

## Common Query Patterns

1. To find deals by company: JOIN deal_companies
2. To find deals by indication: JOIN deal_indications
3. To find deals by therapy area: JOIN therapy_areas
4. To get financial info: JOIN deal_finance_summary
5. Companies as Principal = seller/licensor
6. Companies as Partner = buyer/licensee

## Example: Finding largest deals
```sql
SELECT d.id, d.title, d.date_start, dfs.total_projected_current_amount
FROM deals d
JOIN deal_finance_summary dfs ON d.id = dfs.deal_id
WHERE dfs.total_projected_current_amount IS NOT NULL
ORDER BY dfs.total_projected_current_amount DESC
LIMIT 10;
```
"""

SYSTEM_PROMPT = f"""You are an expert SQL analyst for a pharmaceutical deals database. Your job is to translate natural language questions into SQL queries and explain the results.

{DATABASE_SCHEMA}

## Instructions

1. When asked a question, first generate a valid PostgreSQL SQL query
2. The query should be read-only (SELECT only, no INSERT/UPDATE/DELETE)
3. Always use proper JOINs when accessing related tables
4. Limit results to 50 rows maximum unless specifically asked for more
5. Format monetary values as USD millions
6. Return ONLY the SQL query, nothing else, wrapped in ```sql``` code blocks

## Important Notes

- All financial amounts are in USD millions
- ALWAYS use ILIKE with wildcards for name searches: WHERE c.name ILIKE '%Pfizer%' (not ILIKE 'Pfizer')
- Company names include suffixes like "Ltd", "Inc", "GmbH", "Co" - always use %wildcards%
- Date fields use ISO format
- For company searches, remember to check both Principal and Partner roles

## Follow-up Questions
- When the user asks a follow-up question (e.g., "show me the largest ones", "what about acquisitions?"), ALWAYS refer back to the conversation history
- Maintain filters from previous questions (company names, date ranges, etc.) unless explicitly changed
- If the previous question was about "BeiGene deals", a follow-up about "largest ones" means "largest BeiGene deals", not all deals
"""


@dataclass
class QueryResult:
    """Result from a query execution."""
    sql: str
    columns: List[str]
    rows: List[tuple]
    error: Optional[str] = None


class QueryAgent:
    """AI-powered query agent for the Cortellis deals database with RAG support."""

    def __init__(self, config: AppConfig):
        self.config = config
        self.client = OpenAI(api_key=config.openai.api_key)
        self.model = config.openai.model
        self.engine = create_engine(config.database.connection_string)
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._contract_indexer = None

    @property
    def contract_indexer(self):
        """Lazy load contract indexer."""
        if self._contract_indexer is None:
            from src.contract_indexer import ContractIndexer
            self._contract_indexer = ContractIndexer(self.config)
        return self._contract_indexer

    def needs_contract_search(self, question: str) -> bool:
        """Determine if the question needs contract content search."""
        question_lower = question.lower()
        return any(kw in question_lower for kw in CONTRACT_KEYWORDS)

    def get_relevant_contract_context(self, question: str, limit: int = 5) -> str:
        """Retrieve relevant contract passages using vector similarity."""
        try:
            results = self.contract_indexer.search_similar(question, limit=limit)
            if not results:
                return ""

            context_parts = []
            for i, r in enumerate(results, 1):
                context_parts.append(
                    f"[Contract Excerpt {i} - Deal {r['deal_id']}: {r['deal_title'][:50]}]\n"
                    f"{r['content']}\n"
                )
            return "\n".join(context_parts)
        except Exception as e:
            logger.warning(f"Error retrieving contract context: {e}")
            return ""

    def generate_sql(self, question: str, history: list = None) -> str:
        """Generate SQL from a natural language question.

        Args:
            question: The current question
            history: Optional list of previous messages [{"role": "user"|"assistant", "content": "..."}]
        """
        messages = [{"role": "system", "content": SYSTEM_PROMPT}]

        # Add conversation history for context (limit to last 6 exchanges)
        if history:
            for msg in history[-12:]:  # Last 6 Q&A pairs
                messages.append({"role": msg["role"], "content": msg["content"]})

        messages.append({"role": "user", "content": question})

        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0,
            max_tokens=1000,
        )

        content = response.choices[0].message.content
        # Extract SQL from code block
        if "```sql" in content:
            sql = content.split("```sql")[1].split("```")[0].strip()
        elif "```" in content:
            sql = content.split("```")[1].split("```")[0].strip()
        else:
            sql = content.strip()

        return sql

    def execute_sql(self, sql: str) -> QueryResult:
        """Execute a SQL query and return results."""
        # Validate query is read-only
        sql_lower = sql.lower().strip()
        if not sql_lower.startswith("select"):
            return QueryResult(
                sql=sql,
                columns=[],
                rows=[],
                error="Only SELECT queries are allowed for safety reasons.",
            )

        # Check for dangerous keywords
        dangerous = ["insert", "update", "delete", "drop", "truncate", "alter", "create"]
        for keyword in dangerous:
            if keyword in sql_lower:
                return QueryResult(
                    sql=sql,
                    columns=[],
                    rows=[],
                    error=f"Query contains forbidden keyword: {keyword}",
                )

        try:
            with self.engine.connect() as conn:
                result = conn.execute(text(sql))
                columns = list(result.keys())
                rows = result.fetchall()

                return QueryResult(
                    sql=sql,
                    columns=columns,
                    rows=rows,
                )
        except Exception as e:
            return QueryResult(
                sql=sql,
                columns=[],
                rows=[],
                error=str(e),
            )

    def explain_results(self, question: str, result: QueryResult) -> str:
        """Generate a natural language explanation of the results."""
        if result.error:
            return f"Error executing query: {result.error}"

        if not result.rows:
            return "No results found for your query."

        # Format results for the AI
        result_text = f"Query returned {len(result.rows)} rows.\n"
        result_text += f"Columns: {', '.join(result.columns)}\n"
        result_text += "Sample data:\n"

        for row in result.rows[:10]:
            row_dict = dict(zip(result.columns, row))
            result_text += f"  {row_dict}\n"

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {
                    "role": "system",
                    "content": "You are a helpful assistant that explains database query results in plain English. Be concise but informative.",
                },
                {
                    "role": "user",
                    "content": f"Question: {question}\n\nQuery Results:\n{result_text}\n\nPlease summarize these results in 2-3 sentences.",
                },
            ],
            temperature=0.3,
            max_tokens=300,
        )

        return response.choices[0].message.content

    def ask(self, question: str, use_rag: bool = True) -> str:
        """Ask a question and get a response.

        Args:
            question: Natural language question
            use_rag: If True, use RAG for contract-related questions
        """
        try:
            # Check if this is a contract content question
            contract_context = ""
            if use_rag and self.needs_contract_search(question):
                contract_context = self.get_relevant_contract_context(question)

            # If we have contract context, answer using RAG
            if contract_context:
                return self._answer_with_rag(question, contract_context)

            # Otherwise, use SQL query approach
            sql = self.generate_sql(question)
            result = self.execute_sql(sql)

            if result.error:
                return f"Error: {result.error}\n\nGenerated SQL:\n{sql}"

            # Format response
            response = f"**SQL Query:**\n```sql\n{sql}\n```\n\n"

            if result.rows:
                response += f"**Results:** ({len(result.rows)} rows)\n\n"
                # Format as table
                table_lines = [" | ".join(result.columns)]
                table_lines.append(" | ".join("-" * len(col) for col in result.columns))
                for row in result.rows[:20]:
                    table_lines.append(" | ".join(str(v) if v is not None else "NULL" for v in row))
                response += "\n".join(table_lines)

                if len(result.rows) > 20:
                    response += f"\n... and {len(result.rows) - 20} more rows"

                # Add explanation
                explanation = self.explain_results(question, result)
                response += f"\n\n**Summary:** {explanation}"
            else:
                response += "No results found."

            return response

        except Exception as e:
            logger.exception("Error processing question")
            return f"Error: {str(e)}"

    def _answer_with_rag(self, question: str, context: str) -> str:
        """Answer a question using retrieved contract context (RAG)."""
        rag_prompt = f"""You are an expert analyst for pharmaceutical deal contracts.
Answer the question based on the contract excerpts provided below.

## Relevant Contract Excerpts
{context}

## Instructions
1. Answer based primarily on the contract excerpts provided
2. Cite specific deals or passages when relevant
3. If the excerpts don't contain enough information to fully answer, say so
4. Be specific about terms, conditions, and provisions mentioned
5. Keep your answer concise but thorough

## Question
{question}
"""

        response = self.client.chat.completions.create(
            model=self.model,
            messages=[
                {"role": "system", "content": "You are an expert pharmaceutical deal analyst."},
                {"role": "user", "content": rag_prompt},
            ],
            temperature=0.3,
            max_tokens=1500,
        )

        answer = response.choices[0].message.content

        # Format the response
        return f"**Contract Analysis (RAG)**\n\n{answer}\n\n---\n*Based on {context.count('[Contract Excerpt')} relevant contract excerpts*"

    def interactive_session(self):
        """Run an interactive query session."""
        console.print(Panel.fit(
            "[bold blue]Cortellis Deals AI Query Agent[/bold blue]\n"
            "Ask questions about pharmaceutical deals in natural language.\n\n"
            "Features:\n"
            "• SQL queries for structured data (deals, companies, financials)\n"
            "• RAG search for contract content (auto-detected)\n\n"
            "Commands:\n"
            "• Type 'exit' or 'quit' to end the session\n"
            "• Type 'sql' to see the last generated SQL query\n"
            "• Type 'rag <query>' to force RAG search\n"
            "• Type 'nosql <query>' to skip SQL and use RAG only",
            title="Welcome",
        ))

        last_sql = None

        while True:
            try:
                question = console.input("\n[bold green]Your question:[/bold green] ").strip()

                if not question:
                    continue

                if question.lower() in ("exit", "quit", "q"):
                    console.print("[yellow]Goodbye![/yellow]")
                    break

                if question.lower() == "sql" and last_sql:
                    console.print(Panel(last_sql, title="Last SQL Query"))
                    continue

                # Check for RAG-only mode
                force_rag = False
                if question.lower().startswith("rag "):
                    force_rag = True
                    question = question[4:].strip()
                elif question.lower().startswith("nosql "):
                    force_rag = True
                    question = question[6:].strip()

                # Check if this is a contract content question
                use_rag = force_rag or self.needs_contract_search(question)

                if use_rag:
                    console.print("[dim]Using RAG for contract content search...[/dim]")
                    with console.status("[bold blue]Searching contracts...[/bold blue]"):
                        context = self.get_relevant_contract_context(question)

                    if context:
                        with console.status("[bold blue]Analyzing...[/bold blue]"):
                            answer = self._answer_with_rag(question, context)
                        console.print(Panel(Markdown(answer), title="Contract Analysis", border_style="cyan"))
                        continue
                    else:
                        console.print("[yellow]No relevant contract content found. Falling back to SQL...[/yellow]")

                with console.status("[bold blue]Thinking...[/bold blue]"):
                    # Generate SQL
                    sql = self.generate_sql(question)
                    last_sql = sql

                    console.print(Panel(sql, title="Generated SQL", border_style="blue"))

                    # Execute query
                    result = self.execute_sql(sql)

                if result.error:
                    console.print(f"[bold red]Error:[/bold red] {result.error}")
                    continue

                if not result.rows:
                    console.print("[yellow]No results found.[/yellow]")
                    continue

                # Display results as table
                table = Table(title=f"Results ({len(result.rows)} rows)")
                for col in result.columns:
                    table.add_column(col, overflow="fold")

                for row in result.rows[:50]:
                    table.add_row(*[str(v) if v is not None else "NULL" for v in row])

                console.print(table)

                if len(result.rows) > 50:
                    console.print(f"[dim]... and {len(result.rows) - 50} more rows[/dim]")

                # Generate explanation
                with console.status("[bold blue]Generating summary...[/bold blue]"):
                    explanation = self.explain_results(question, result)

                console.print(Panel(Markdown(explanation), title="Summary", border_style="green"))

            except KeyboardInterrupt:
                console.print("\n[yellow]Use 'exit' to quit.[/yellow]")
                continue
            except Exception as e:
                console.print(f"[bold red]Error:[/bold red] {str(e)}")
                logger.exception("Error in interactive session")
