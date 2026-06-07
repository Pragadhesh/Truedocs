"""Observe: fetch thread messages and extract process steps using Claude."""
from __future__ import annotations
import logging

from pydantic import BaseModel
from pydantic_ai import Agent
from slack_sdk import WebClient

from agent.agent import get_model

logger = logging.getLogger(__name__)


class ProcessStep(BaseModel):
    description: str
    status: str = "done"  # done | skipped | blocked


class ObservedRun(BaseModel):
    steps: list[ProcessStep]
    undocumented_steps: list[str]
    summary: str


_agent = Agent(
    output_type=ObservedRun,
    system_prompt=(
        "You extract process steps from Slack thread messages.\n\n"
        "Given a sequence of Slack messages from a process execution thread:\n"
        "- Identify distinct steps that were performed in order\n"
        "- Mark each step as: done, skipped, or blocked\n"
        "- List undocumented_steps: actions that seem outside the normal process flow\n"
        "- Write a brief summary of what happened\n\n"
        "Ignore casual conversation and bot messages. Focus on actions taken."
    ),
)


def fetch_thread_messages(client: WebClient, channel_id: str, thread_ts: str) -> list[dict]:
    result = client.conversations_replies(channel=channel_id, ts=thread_ts, limit=200)
    return result.get("messages", [])


def extract_steps(
    client: WebClient, channel_id: str, thread_ts: str, process_name: str
) -> ObservedRun:
    messages = fetch_thread_messages(client, channel_id, thread_ts)

    thread_text = "\n".join(
        f"[{m.get('user', 'unknown')}]: {m.get('text', '')}"
        for m in messages
        if not m.get("bot_id")
    )

    prompt = (
        f"Process name: {process_name}\n\n"
        f"Thread messages:\n{thread_text}\n\n"
        "Extract the steps that were performed during this process execution."
    )

    result = _agent.run_sync(prompt, model=get_model())
    return result.output
