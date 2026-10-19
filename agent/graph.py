"""
graph.py
---------
Constructs and compiles the LangGraph agent workflow.

Responsibilities:
  - Import all validated tools (Gmail operations and general tools).
  - Register workflow nodes (assistant, tools).
  - Define conditional tool-routing edges using LangGraph prebuilt tools_condition.
  - Compile the executable agent graph.
"""

from langgraph.graph import StateGraph, START
from langgraph.prebuilt import ToolNode, tools_condition

from agent.state import AgentState
from agent.nodes.assistant_node import call_model, get_base_llm

# Gmail Tools
from agent.tools.gmail_tools import (
    search_gmail,
    read_email,
    get_unread_emails,
    create_draft,
    send_email,
    reply_to_email,
    mark_as_read,
    mark_as_unread,
    archive_messages,
    trash_messages,
    create_label,
    apply_label,
    
)

# Contacts Tools
from agent.tools.contacts_tools import create_contact, find_contact

# Calendar Tools
from agent.tools.calendar_tools import CALENDAR_TOOLS

# Tasks Tools
from agent.tools.tasks_tools import TASKS_TOOLS

# Reminder Tools
from agent.tools.reminder_tools import REMINDER_TOOLS

# General Assistant Tools
from agent.tools.assistant_tools import get_current_datetime


# ── Complete Tool Registry ────────────────────────────────────────────────────
TOOLS = [
    # Search and reading
    search_gmail,
    read_email,
    get_unread_emails,
    # Drafting and sending
    create_draft,
    send_email,
    reply_to_email,
    # Organization
    mark_as_read,
    mark_as_unread,
    archive_messages,
    trash_messages,
    create_label,
    apply_label,
    # General utilities
    get_current_datetime,
    # Contacts tools
    find_contact,
    create_contact,
    # Calendar tools
    *CALENDAR_TOOLS,
    # Tasks tools
    *TASKS_TOOLS,
    # Reminder tools
    *REMINDER_TOOLS,
]

# Bind tools to the LLM
_llm_with_tools = get_base_llm().bind_tools(TOOLS)


def assistant(state: AgentState) -> dict:
    """Assistant node closure: invokes the model bound to all tools."""
    return call_model(state, _llm_with_tools)


# ── Workflow Graph Construction ───────────────────────────────────────────────
builder = StateGraph(AgentState)

# Register nodes
builder.add_node("assistant", assistant)
builder.add_node("tools", ToolNode(TOOLS))

# Connect entry point
builder.add_edge(START, "assistant")

# Conditional edge: if model made a tool call, route to tools; otherwise finish
builder.add_conditional_edges("assistant", tools_condition)

# Loop back to assistant after tool execution so it can synthesize the final response
builder.add_edge("tools", "assistant")

# Compile into an executable agent
agent = builder.compile()
