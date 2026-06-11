import logging
import os

from pydantic_ai import Agent
from pydantic_ai.mcp import MCPServerStreamableHTTP

from agent.deps import AgentDeps
from agent.tools import add_emoji_reaction
from prompts import SLACK_ASSISTANT_PROMPT

logger = logging.getLogger(__name__)

_cached_model: str | None = None


def get_model() -> str:
    """Select the AI model based on available API keys.

    Prefers Anthropic when both keys are set.
    """
    global _cached_model
    if _cached_model is not None:
        return _cached_model

    if os.environ.get("ANTHROPIC_API_KEY"):
        _cached_model = "anthropic:claude-sonnet-4-6"
    elif os.environ.get("OPENAI_API_KEY"):
        _cached_model = "openai:gpt-4.1"
    else:
        raise RuntimeError(
            "No AI provider configured. "
            "Set ANTHROPIC_API_KEY or OPENAI_API_KEY in your environment."
        )
    return _cached_model


SLACK_MCP_URL = "https://mcp.slack.com/mcp"

agent = Agent(
    deps_type=AgentDeps,
    system_prompt=SLACK_ASSISTANT_PROMPT,
    tools=[add_emoji_reaction],
)


def run_agent(text, deps, message_history=None):
    """Run the agent, optionally connecting to the Slack MCP server."""
    toolsets = []
    if deps.user_token:
        logger.info("Slack MCP Server enabled (user_token present)")
        toolsets.append(
            MCPServerStreamableHTTP(
                SLACK_MCP_URL,
                headers={"Authorization": f"Bearer {deps.user_token}"},
            )
        )
    else:
        logger.info("Slack MCP Server disabled (no user_token)")

    return agent.run_sync(
        text,
        model=get_model(),
        deps=deps,
        message_history=message_history,
        toolsets=toolsets,
    )
