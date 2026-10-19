"""
state.py
---------
Defines the conversation and workflow state for the personal AI agent.

LangGraph passes this state between the assistant reasoning node and the
tool execution node. Inheriting from MessagesState automatically gives us
a 'messages' list that tracks the entire conversation history.
"""

from langgraph.graph import MessagesState


class AgentState(MessagesState):
    """
    State definition for the personal AI agent.

    Attributes:
        messages: Accumulated list of messages (HumanMessage, AIMessage, ToolMessage).
                  Managed automatically by LangGraph's MessagesState.
    """