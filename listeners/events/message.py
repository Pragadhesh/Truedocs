import logging
import threading
from logging import Logger

logger = logging.getLogger(__name__)

from slack_bolt import BoltContext, Say, SayStream, SetStatus
from slack_sdk import WebClient

from agent import AgentDeps, run_agent
from thread_context import conversation_store
from listeners.views.feedback_builder import build_feedback_blocks
import db.processes as processes
from modes.pipeline import run_pipeline


def _check_trigger(
    client: WebClient,
    workspace_id: str,
    channel_id: str,
    thread_ts: str,
    text: str,
) -> bool:
    """Return True and kick off the pipeline if the message matches a registered trigger."""
    registered = processes.list_by_workspace(workspace_id)
    text_lower = text.lower()
    for proc in registered:
        if proc.get("channel_id") != channel_id:
            continue
        if proc.get("trigger_type") != "manual":
            continue
        phrase = (proc.get("trigger_phrase") or "").lower().strip()
        if phrase and phrase in text_lower:
            logger.info(f"Trigger '{phrase}' matched process '{proc['name']}' in {channel_id}")
            threading.Thread(
                target=run_pipeline,
                args=(client, workspace_id, channel_id, thread_ts, proc),
                daemon=True,
            ).start()
            return True
    logger.debug(f"No trigger matched in {channel_id} for text: {text[:50]!r}")
    return False


def handle_message(
    client: WebClient,
    context: BoltContext,
    event: dict,
    logger: Logger,
    say: Say,
    say_stream: SayStream,
    set_status: SetStatus,
):
    """Handle messages sent to the agent via DM, threads, or channel trigger phrases."""
    # Skip message subtypes (edits, deletes, etc.) and bot messages.
    if event.get("subtype"):
        return
    if event.get("bot_id"):
        return

    is_dm = event.get("channel_type") == "im"
    is_thread_reply = event.get("thread_ts") is not None

    if is_dm:
        pass
    elif is_thread_reply:
        # Channel thread replies are handled only if the bot is already engaged
        history = conversation_store.get_history(context.channel_id, event["thread_ts"])
        if history is None:
            return
    else:
        # Top-level channel message — check for trigger phrases
        triggered = _check_trigger(
            client=client,
            workspace_id=context.team_id,
            channel_id=context.channel_id,
            thread_ts=event["ts"],
            text=event.get("text", ""),
        )
        if triggered:
            return
        # No trigger matched — ignore (top-level non-DM messages go via @mention)
        return

    try:
        channel_id = context.channel_id
        text = event.get("text", "")
        thread_ts = event.get("thread_ts") or event["ts"]

        user_id = context.user_id

        # Get conversation history
        history = conversation_store.get_history(channel_id, thread_ts)

        # Set assistant thread status with loading messages
        set_status(
            status="Thinking...",
            loading_messages=[
                "Teaching the hamsters to type faster…",
                "Untangling the internet cables…",
                "Consulting the office goldfish…",
                "Polishing up the response just for you…",
                "Convincing the AI to stop overthinking…",
            ],
        )

        # Run the agent
        deps = AgentDeps(
            client=client,
            user_id=user_id,
            channel_id=channel_id,
            thread_ts=thread_ts,
            message_ts=event["ts"],
            user_token=context.user_token,
        )
        result = run_agent(text, deps, message_history=history)

        # Stream response in thread with feedback buttons
        streamer = say_stream()
        streamer.append(markdown_text=result.output)
        feedback_blocks = build_feedback_blocks()
        streamer.stop(blocks=feedback_blocks)

        # Store conversation history
        conversation_store.set_history(channel_id, thread_ts, result.all_messages())

    except Exception as e:
        logger.exception(f"Failed to handle message: {e}")
        say(
            text=f":warning: Something went wrong! ({e})",
            thread_ts=event.get("thread_ts") or event.get("ts"),
        )
