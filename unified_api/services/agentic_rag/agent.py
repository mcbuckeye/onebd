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

        self.logger.info("Router initialized", query=query)
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

        # Build context for LLM
        context = self._build_llm_context(cs)

        # Available tools description
        tools_desc = self._get_tools_description()

        prompt = f"""You are an AI assistant for business development intelligence.
Analyze the user's query and decide the next step.

{context}

Available Tools:
{tools_desc}

Available Tool Names: neo4j, sql, pgvector, synthesize

Decide what to do next. Respond in JSON format:
{{
    "thought": "Your reasoning about what to do",
    "tool": "one of: neo4j, sql, pgvector, synthesize",
    "query": "The specific query to execute (omit for synthesize)",
    "synthesize": true/false (if true, provide answer instead of query)
}}

Rules:
- Use 'synthesize' when you have enough information to answer
- Max hops: {cs.max_hops}, Current hop: {cs.current_hop + 1}
- Be specific in your queries
- For SQL: Write valid PostgreSQL
- For Neo4j: Write valid Cypher
- For pgvector: Provide natural language search query"""

        try:
            response = await self.llm.ainvoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)

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

    async def _tool_execution_node(self, state: AgentState) -> AgentState:
        """Execute the selected tool."""
        if not state.current_step or not state.conversation_state:
            return state

        step = state.current_step

        # Get the tool
        tool = self.tools.get(step.tool_type)
        if not tool:
            step.result_summary = f"Tool {step.tool_type} not available"
            step.error = "Tool not found"
            state.last_tool_result = ToolResult(success=False, error="Tool not found")
            return state

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

        # Build synthesis prompt
        context = cs.get_context_for_llm()

        prompt = f"""Synthesize a final answer based on the gathered information.

Original Query: {cs.original_query}

{context}

Provide a clear, concise answer that directly addresses the user's question.
Include relevant facts and cite which data sources were used.
If information was incomplete, note what additional data might be needed."""

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
            # Run graph
            final_state = await self.graph.ainvoke(initial_state)

            cs = final_state.conversation_state

            return AgenticRagResponse(
                success=not bool(final_state.error),
                answer=cs.final_answer if cs else "No answer generated",
                partial=cs.current_hop >= cs.max_hops if cs else False,
                reasoning_steps=cs.reasoning_steps if cs else [],
                total_hops=cs.current_hop if cs else 0,
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