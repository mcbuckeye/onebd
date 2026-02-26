"""
LangGraph Agent for multi-hop reasoning with self-correction.
Orchestrates tool selection and execution.
"""
import json
import time
from typing import Dict, Any, Optional, AsyncGenerator
from dataclasses import dataclass, field
import structlog

from langgraph.graph import StateGraph, END
from langgraph.graph.message import add_messages

from .models import (
    ConversationState,
    ReasoningStep,
    ToolResult,
    ToolType,
    ToolSelection,
    AgenticRagResponse,
    StreamingEvent
)
from .tools.base import BaseTool

logger = structlog.get_logger(__name__)


@dataclass
class AgentState:
    """State maintained across LangGraph nodes."""
    messages: list = field(default_factory=list)
    conversation_state: Optional[ConversationState] = None
    current_step: Optional[ReasoningStep] = None
    last_tool_result: Optional[ToolResult] = None
    final_answer: Optional[str] = None
    error: Optional[str] = None
    forced_tool: Optional[ToolType] = None  # Hardcoded tool routing


# Keywords that indicate SQL tool should be used (financial/structured data)
SQL_KEYWORDS = [
    'value', 'amount', 'financial', 'deal size', 'upfront', 'milestone',
    'royalty', 'total value', 'payment', 'revenue', 'price', 'cost',
    'million', 'billion', 'usd', 'dollar', 'euro',
    'phase', 'indication', 'therapy area', 'clinical trial', 'patient',
    'company type', 'ticker', 'cik', 'headquarters', 'location'
]

# Keywords that indicate Neo4j tool should be used (graph relationships)
NEO4J_KEYWORDS = [
    'licenses', 'licensed', 'partner', 'partnership', 'collaboration',
    'relationship', 'connected', 'involves', 'between companies',
    'network', 'graph', 'connections'
]

# Keywords for pgvector (semantic search)
PGVECTOR_KEYWORDS = [
    'similar', 'about', 'like', 'related to', 'concept', 'theme',
    'meaning', 'context', 'semantic'
]


def detect_tool_from_query(query: str) -> Optional[ToolType]:
    """
    Intelligently route queries to appropriate tools based on keywords.
    Returns None if no strong signal detected (let LLM decide).
    """
    query_lower = query.lower()

    # Check SQL keywords (highest priority for financial/structured data)
    sql_score = sum(1 for kw in SQL_KEYWORDS if kw in query_lower)
    if sql_score >= 2:
        return ToolType.SQL
    if sql_score >= 1 and any(x in query_lower for x in ['deal', 'company']):
        return ToolType.SQL

    # Check Neo4j keywords
    neo4j_score = sum(1 for kw in NEO4J_KEYWORDS if kw in query_lower)
    if neo4j_score >= 2:
        return ToolType.NEO4J

    # Check pgvector keywords
    pgvector_score = sum(1 for kw in PGVECTOR_KEYWORDS if kw in query_lower)
    if pgvector_score >= 2:
        return ToolType.PGVECTOR

    return None


class AgenticRagAgent:
    """
    Multi-hop reasoning agent using LangGraph.

    Flow:
    1. User query -> router node
    2. LLM decides tool -> tool selection node
    3. Execute tool -> tool execution node
    4. Check if complete -> condition node
    5. Loop or synthesize -> synthesis node
    6. Return answer
    """

    def __init__(
        self,
        llm: Any,  # Any LLM with ainvoke/astream methods
        tools: Dict[ToolType, BaseTool],
        max_hops: int = 5,
        max_retries_per_tool: int = 2,
        timeout_seconds: int = 30
    ):
        self.llm = llm
        self.tools = tools
        self.max_hops = max_hops
        self.max_retries_per_tool = max_retries_per_tool
        self.timeout_seconds = timeout_seconds
        self.logger = logger.bind(agent="agentic_rag")

        # Build the graph
        self.graph = self._build_graph()

    def _build_graph(self) -> StateGraph:
        """Build the LangGraph state machine."""
        # Define state schema
        workflow = StateGraph(AgentState)

        # Add nodes
        workflow.add_node("router", self._router_node)
        workflow.add_node("select_tool", self._tool_selection_node)
        workflow.add_node("execute_tool", self._tool_execution_node)
        workflow.add_node("synthesize", self._synthesis_node)

        # Add edges
        workflow.set_entry_point("router")
        workflow.add_edge("router", "select_tool")

        # Conditional edge after tool selection
        workflow.add_conditional_edges(
            "select_tool",
            self._should_continue,
            {
                "execute": "execute_tool",
                "synthesize": "synthesize"
            }
        )

        # After execution, check if we should continue
        workflow.add_conditional_edges(
            "execute_tool",
            self._should_continue,
            {
                "execute": "select_tool",
                "synthesize": "synthesize"
            }
        )

        workflow.add_edge("synthesize", END)

        return workflow.compile()

    async def _router_node(self, state: AgentState) -> AgentState:
        """Initialize conversation state from messages."""
        if not state.messages:
            return state

        last_message = state.messages[-1]
        query = last_message.get("content", "") if isinstance(last_message, dict) else str(last_message)

        state.conversation_state = ConversationState(
            original_query=query,
            max_hops=self.max_hops
        )

        # Pre-detect which tool to use based on keywords
        detected_tool = detect_tool_from_query(query)
        if detected_tool:
            state.forced_tool = detected_tool
            self.logger.info("Tool pre-selected by keyword routing", tool=detected_tool.value, query=query)
        else:
            state.forced_tool = None

        self.logger.info("Router initialized", query=query, forced_tool=state.forced_tool.value if state.forced_tool else None)
        return state

    async def _tool_selection_node(self, state: AgentState) -> AgentState:
        """Use LLM to select next tool or synthesize answer."""
        if not state.conversation_state:
            return state

        cs = state.conversation_state

        # Check if we should stop
        if cs.current_hop >= cs.max_hops:
            self.logger.info("Max hops reached, forcing synthesis")
            state.current_step = None
            return state

        # Check if tool was pre-selected by keyword routing
        if state.forced_tool and cs.current_hop == 0:
            self.logger.info("Using keyword-forced tool selection", tool=state.forced_tool.value)
            # Create a reasoning step for the forced tool
            cs.current_hop = 0  # Will be incremented by add_step
            state.current_step = ReasoningStep(
                hop_number=1,
                thought=f"Query detected as requiring {state.forced_tool.value.upper()} database based on keywords. This tool is best suited for this type of data.",
                tool_type=state.forced_tool,
                query="",  # Will be generated by LLM in next iteration or we can force it here
                result_summary="Routed by keyword detection"
            )
            # Clear forced tool after first use
            state.forced_tool = None
            return state

        # Build context for LLM
        context = self._build_llm_context(cs)

        # Available tools description
        tools_desc = self._get_tools_description()

        prompt = f"""You are an AI assistant for business development intelligence.
Analyze the user's query and decide the next step.

{context}

Available Tools:
{tools_desc}

CRITICAL RULES:
- For financial data (value, amount, deal size, phase, indication): MUST USE sql tool
- For graph relationships (licenses, partners, collaborations): MUST USE neo4j tool
- For semantic/conceptual search (similar, related themes): MUST USE pgvector tool

Available Tool Names: neo4j, sql, pgvector, synthesize

Decide what to do next. Respond in JSON format:
{{
    "thought": "Your reasoning about what to do (mention which database is best for this data)",
    "tool": "one of: neo4j, sql, pgvector, synthesize",
    "query": "The specific query to execute (omit for synthesize)",
    "synthesize": true/false (if true, provide answer instead of query)
}}

Rules:
- Use 'synthesize' when you have enough information to answer
- Max hops: {cs.max_hops}, Current hop: {cs.current_hop + 1}
- Be specific in your queries
- For SQL: Write valid PostgreSQL with ILIKE for text search
- For Neo4j: Write valid Cypher - NO EXISTS(), NO GROUP BY, use toLower() for case-insensitive
- For pgvector: Provide natural language search query"""

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

            # Extract JSON from markdown code blocks if present
            content = content.strip()
            if content.startswith("```json"):
                content = content[7:]
            if content.startswith("```"):
                content = content[3:]
            if content.endswith("```"):
                content = content[:-3]
            content = content.strip()

            # Parse JSON
            selection = json.loads(content)
            tool_selection = ToolSelection(**selection)

            # Create reasoning step
            if tool_selection.synthesize or tool_selection.tool == ToolType.SYNTHESIZE:
                state.current_step = None
                state.final_answer = tool_selection.query if tool_selection.synthesize else None
            else:
                state.current_step = ReasoningStep(
                    hop_number=cs.current_hop + 1,
                    thought=tool_selection.thought,
                    tool_type=tool_selection.tool,
                    query=tool_selection.query,
                    result_summary="Pending execution..."
                )

        except json.JSONDecodeError as e:
            self.logger.error("Failed to parse LLM response", error=str(e))
            state.error = f"Failed to parse tool selection: {str(e)}"
            state.current_step = None
        except Exception as e:
            self.logger.error("Tool selection failed", error=str(e))
            state.error = str(e)
            state.current_step = None

        return state

    async def _generate_query_for_tool(self, tool_type: ToolType, original_query: str, context: str) -> str:
        """Generate a specific query for a given tool type."""
        tool = self.tools.get(tool_type)
        schema_desc = tool.get_schema_description() if tool else "No schema available"

        prompt = f"""Generate a {tool_type.value.upper()} query to answer this user question.

User Question: {original_query}

{context}

Database Schema:
{schema_desc}

IMPORTANT:
- Return ONLY the query, no explanation
- Make it specific and correct for the schema
- Use proper syntax for {tool_type.value}

Query:"""

        response = await self.llm.ainvoke(prompt)
        query = response.content.strip()

        # Remove markdown code blocks if present
        if query.startswith("```"):
            lines = query.split("\n")
            query = "\n".join(lines[1:-1] if lines[-1].startswith("```") else lines[1:])
            query = query.strip()

        return query

    async def _tool_execution_node(self, state: AgentState) -> AgentState:
        """Execute the selected tool."""
        if not state.current_step or not state.conversation_state:
            return state

        # Handle dict or ReasoningStep
        step_data = state.current_step
        if isinstance(step_data, dict):
            step = ReasoningStep(**step_data)
        else:
            step = step_data

        # Get the tool
        tool = self.tools.get(step.tool_type)
        if not tool:
            step.result_summary = f"Tool {step.tool_type} not available"
            step.error = "Tool not found"
            state.last_tool_result = ToolResult(success=False, error="Tool not found")
            return state

        # If query is empty (e.g., from keyword routing), generate it now
        if not step.query or step.query.strip() == "":
            cs = state.conversation_state
            context = self._build_llm_context(cs)
            self.logger.info("Generating query for forced tool", tool=step.tool_type.value)
            step.query = await self._generate_query_for_tool(
                step.tool_type,
                cs.original_query,
                context
            )
            step.result_summary = f"Query generated: {step.query[:100]}..."

        # Retry loop
        for attempt in range(self.max_retries_per_tool + 1):
            try:
                result = await tool.execute(step.query)
                state.last_tool_result = result

                if result.success:
                    step.result_summary = f"Success: {result.row_count} rows"
                    step.retry_count = attempt
                    break
                else:
                    # Log error, will retry
                    step.error = result.error
                    step.retry_count = attempt + 1

                    if attempt < self.max_retries_per_tool:
                        # TODO: Could ask LLM to fix the query
                        pass

            except Exception as e:
                step.error = str(e)
                step.retry_count = attempt + 1
                state.last_tool_result = ToolResult(success=False, error=str(e))

        # Add step to conversation state
        state.conversation_state.add_step(step)

        # Update state with potentially modified step
        state.current_step = step

        return state

    async def _synthesis_node(self, state: AgentState) -> AgentState:
        """Synthesize final answer from all steps."""
        if not state.conversation_state:
            return state

        cs = state.conversation_state

        # If we already have a final answer from LLM
        if state.final_answer:
            cs.mark_complete(state.final_answer)
            return state

        # Check if there were errors in any steps
        error_steps = [s for s in cs.reasoning_steps if s.error]
        if error_steps and not any(s.result_summary and "Success" in s.result_summary for s in cs.reasoning_steps):
            # All steps failed - return helpful error with details
            error_details = "\n\n".join([
                f"Tool: {s.tool_type.value}\nError: {s.error[:500]}"
                for s in error_steps
            ])

            error_answer = f"""I encountered errors while querying the databases:

{error_details}

This usually means:
1. The query syntax doesn't match the database schema
2. You're asking for data that doesn't exist in the selected database
3. There's a temporary connection issue

Try rephrasing your question or ask about different data fields."""

            cs.mark_complete(error_answer)
            state.final_answer = error_answer
            return state

        # Build synthesis prompt
        context = cs.get_context_for_llm()

        # Include errors in context if any
        if error_steps:
            context += "\n\nNote: Some data sources encountered errors:\n"
            for s in error_steps:
                context += f"- {s.tool_type.value}: {s.error[:200]}...\n"

        prompt = f"""Synthesize a final answer based on the gathered information.

Original Query: {cs.original_query}

{context}

Provide a clear, concise answer that directly addresses the user's question.
Include relevant facts and cite which data sources were used.
If information was incomplete or errors occurred, note what additional data might be needed or what went wrong."""

        try:
            response = await self.llm.ainvoke(prompt)
            answer = response.content if hasattr(response, 'content') else str(response)
            cs.mark_complete(answer)
            state.final_answer = answer
        except Exception as e:
            self.logger.error("Synthesis failed", error=str(e))
            cs.mark_complete(f"Error generating answer: {str(e)}")
            state.final_answer = f"Error: {str(e)}"

        return state

    def _should_continue(self, state: AgentState) -> str:
        """Determine if agent should continue or synthesize."""
        if state.error:
            return "synthesize"

        if not state.conversation_state:
            return "synthesize"

        cs = state.conversation_state

        # Check if max hops reached
        if cs.current_hop >= cs.max_hops:
            return "synthesize"

        # Check if LLM indicated synthesis
        if state.current_step is None:
            return "synthesize"

        # Continue
        return "execute"

    def _build_llm_context(self, cs: ConversationState) -> str:
        """Build context string for LLM."""
        context = f"User Query: {cs.original_query}\n\n"

        if cs.reasoning_steps:
            context += "Steps taken so far:\n"
            for step in cs.reasoning_steps:
                context += f"\n{step.hop_number}. {step.tool_type.value}: {step.thought}\n"
                context += f"   Query: {step.query[:200]}...\n"
                context += f"   Result: {step.result_summary}\n"
                if step.error:
                    context += f"   Error (after {step.retry_count} retries): {step.error}\n"

        return context

    def _get_tools_description(self) -> str:
        """Get descriptions of all available tools."""
        descriptions = []
        for tool_type, tool in self.tools.items():
            if tool.is_available():
                desc = tool.get_schema_description()
                descriptions.append(f"\n{tool_type.value}:\n{desc}\n")
        return "\n".join(descriptions)

    async def run(self, query: str, history: Optional[list] = None) -> AgenticRagResponse:
        """
        Run the agent synchronously and return final response.

        Args:
            query: User's natural language query
            history: Previous conversation messages

        Returns:
            AgenticRagResponse with answer and reasoning trace
        """
        start_time = time.time()

        # Initialize state
        initial_state = AgentState()
        initial_state.messages = history or []
        initial_state.messages.append({"role": "user", "content": query})

        try:
            # Run graph - returns dict, not AgentState
            final_state_dict = await self.graph.ainvoke(initial_state)

            # Convert dict back to AgentState
            if isinstance(final_state_dict, dict):
                cs = final_state_dict.get('conversation_state')
                final_error = final_state_dict.get('error')
            else:
                cs = final_state_dict.conversation_state
                final_error = final_state_dict.error

            if not cs:
                return AgenticRagResponse(
                    success=False,
                    answer="No conversation state returned",
                    partial=True,
                    total_hops=0,
                    latency_ms=int((time.time() - start_time) * 1000)
                )

            return AgenticRagResponse(
                success=not bool(final_error),
                answer=cs.final_answer if cs.final_answer else "No answer generated",
                partial=cs.current_hop >= cs.max_hops,
                reasoning_steps=cs.reasoning_steps,
                total_hops=cs.current_hop,
                latency_ms=int((time.time() - start_time) * 1000)
            )

        except Exception as e:
            self.logger.error("Agent run failed", error=str(e))
            return AgenticRagResponse(
                success=False,
                answer=f"Agent error: {str(e)}",
                partial=True,
                total_hops=0,
                latency_ms=int((time.time() - start_time) * 1000)
            )

    async def run_streaming(
        self,
        query: str,
        history: Optional[list] = None
    ) -> AsyncGenerator[StreamingEvent, None]:
        """
        Run the agent with streaming events.

        Yields events for UI to display reasoning trace in real-time.
        """
        import asyncio

        start_time = time.time()

        initial_state = AgentState()
        initial_state.messages = history or []
        initial_state.messages.append({"role": "user", "content": query})

        # Yield start event
        yield StreamingEvent(
            type="thinking",
            data={"message": "Initializing agent...", "hop": 0},
            timestamp=time.time()
        )

        try:
            # Run graph step by step
            # Note: LangGraph doesn't support granular streaming by default
            # We simulate by running and yielding checkpoints

            final_state = await self.graph.ainvoke(initial_state)
            cs = final_state.conversation_state

            # Yield all reasoning steps
            if cs:
                for step in cs.reasoning_steps:
                    yield StreamingEvent(
                        type="reasoning_step",
                        data={
                            "hop": step.hop_number,
                            "thought": step.thought,
                            "tool": step.tool_type.value,
                            "query": step.query[:500],
                            "result": step.result_summary,
                            "retry_count": step.retry_count,
                            "error": step.error
                        },
                        timestamp=time.time()
                    )

            # Yield final answer
            yield StreamingEvent(
                type="answer",
                data={
                    "answer": cs.final_answer if cs else "No answer",
                    "total_hops": cs.current_hop if cs else 0,
                    "partial": cs.current_hop >= cs.max_hops if cs else False,
                    "latency_ms": int((time.time() - start_time) * 1000)
                },
                timestamp=time.time()
            )

        except Exception as e:
            yield StreamingEvent(
                type="error",
                data={"error": str(e)},
                timestamp=time.time()
            )