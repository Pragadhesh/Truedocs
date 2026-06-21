import logging
from logging import Logger

from slack_sdk import WebClient

import db.credentials as credentials
import db.processes as processes
from integrations.confluence import ConfluenceClient
from listeners.views.register_modal import build_register_modal
from listeners.views.app_home_builder import build_app_home_view

logger = logging.getLogger(__name__)


def handle_open_register_modal(ack, body: dict, client: WebClient):
    """Open a blank Register a Process modal (from App Home button)."""
    ack()
    client.views_open(trigger_id=body["trigger_id"], view=build_register_modal())


def handle_edit_process(ack, body: dict, client: WebClient):
    """Open the Register modal pre-filled with an existing process's values."""
    ack()
    process_id = body["actions"][0]["value"]
    workspace_id = body["team"]["id"]

    proc = next(
        (p for p in processes.list_by_workspace(workspace_id) if p["id"] == process_id),
        None,
    )
    if not proc:
        return

    prefill = {
        "process_name": proc["name"],
        "confluence_page_url": proc["confluence_page_url"],
        "channel_id": proc["channel_id"],
        "lookback_window": proc.get("lookback_window", "1d"),
    }
    client.views_open(
        trigger_id=body["trigger_id"],
        view=build_register_modal(
            trigger_type=proc.get("trigger_type"),
            prefill=prefill,
            process_id=process_id,
        ),
    )


def handle_trigger_type_change(ack, body: dict, client: WebClient):
    """Rebuild the register modal with the right conditional block when trigger type changes."""
    ack()
    selected = body["actions"][0]["selected_option"]["value"]
    prefill = _extract_prefill(body["view"]["state"]["values"])
    process_id = body["view"].get("private_metadata") or None
    client.views_update(
        view_id=body["view"]["id"],
        view=build_register_modal(
            trigger_type=selected,
            prefill=prefill,
            process_id=process_id,
        ),
    )


def handle_register_process_submission(
    ack, body: dict, view: dict, client: WebClient, logger: Logger
):
    """Validate inputs, then create or update a process, refresh App Home."""
    vals = view["state"]["values"]

    process_name = vals["process_name_block"]["process_name"]["value"].strip()
    confluence_page_url = vals["confluence_page_url_block"]["confluence_page_url"][
        "value"
    ].strip()
    channel_id = vals["channel_block"]["channel_id"]["selected_channel"]
    trigger_option = vals["trigger_type_block"]["trigger_type"].get("selected_option")
    trigger_type = trigger_option["value"] if trigger_option else None
    lookback_option = vals["lookback_window_block"]["lookback_window"].get("selected_option")
    lookback_window = lookback_option["value"] if lookback_option else "1d"

    workspace_id = body["team"]["id"]
    user_id = body["user"]["id"]

    errors: dict[str, str] = {}
    if not trigger_type:
        errors["trigger_type_block"] = "Please select a trigger type."
    if not confluence_page_url.startswith("http"):
        errors["confluence_page_url_block"] = (
            "Enter a valid Confluence page URL starting with https://"
        )

    if not errors:
        # Enforce one process per channel — block duplicate registrations
        existing = processes.get_by_channel(workspace_id, channel_id)
        current_id = view.get("private_metadata", "").strip() or None
        if existing and existing["id"] != current_id:
            errors["channel_block"] = (
                f"#{channel_id} is already registered to '{existing['name']}'. "
                "Each channel can have only one process."
            )

    if not errors:
        creds = credentials.get(workspace_id)
        if not creds:
            errors["confluence_page_url_block"] = (
                "Confluence credentials not configured. Set them up in Step 1 first."
            )
        else:
            try:
                cf = ConfluenceClient.from_credentials_and_page_url(creds, confluence_page_url)
                if not cf.can_access_page(confluence_page_url):
                    errors["confluence_page_url_block"] = (
                        "Cannot access this Confluence page. Check the URL and your API credentials."
                    )
            except Exception:
                errors["confluence_page_url_block"] = (
                    "Failed to reach Confluence. Check the URL and your API credentials."
                )

    if errors:
        ack(response_action="errors", errors=errors)
        return

    ack()

    process_id = view.get("private_metadata", "").strip() or None  # set = edit mode

    MANUAL_TRIGGER_PHRASE = "run-truedocs"

    trigger_phrase = trigger_time = trigger_day = None
    if trigger_type == "manual":
        trigger_phrase = MANUAL_TRIGGER_PHRASE
    elif trigger_type == "daily":
        trigger_time = (
            vals.get("trigger_time_block", {})
            .get("trigger_time", {})
            .get("selected_time")
        )
    elif trigger_type == "weekly":
        trigger_day = (
            vals.get("trigger_day_block", {})
            .get("trigger_day", {})
            .get("selected_option", {})
            .get("value")
        )
        trigger_time = (
            vals.get("trigger_time_block", {})
            .get("trigger_time", {})
            .get("selected_time")
        )

    try:
        if process_id:
            processes.update(
                process_id,
                name=process_name,
                channel_id=channel_id,
                confluence_page_url=confluence_page_url,
                trigger_type=trigger_type,
                trigger_phrase=trigger_phrase if trigger_phrase else "",
                trigger_time=trigger_time or "",
                trigger_day=trigger_day or "",
                lookback_window=lookback_window,
            )
        else:
            processes.create(
                workspace_id=workspace_id,
                name=process_name,
                channel_id=channel_id,
                confluence_page_url=confluence_page_url,
                trigger_type=trigger_type,
                trigger_phrase=trigger_phrase,
                trigger_time=trigger_time,
                trigger_day=trigger_day,
                lookback_window=lookback_window,
                created_by=user_id,
            )
    except Exception as e:
        logger.exception(f"Failed to save process: {e}")
        return

    # Auto-join the channel so the bot receives message events from it
    try:
        client.conversations_join(channel=channel_id)
        logger.info(f"Joined channel {channel_id} for process monitoring")
    except Exception as e:
        logger.warning(f"Could not auto-join channel {channel_id}: {e}")

    _refresh_app_home(client, workspace_id, user_id, logger)


def handle_delete_process(ack, body: dict, client: WebClient, logger: Logger):
    """Delete a process and refresh App Home."""
    ack()
    process_id = body["actions"][0]["value"]
    workspace_id = body["team"]["id"]
    user_id = body["user"]["id"]
    try:
        processes.delete(process_id)
    except Exception as e:
        logger.exception(f"Failed to delete process {process_id}: {e}")
    _refresh_app_home(client, workspace_id, user_id, logger)


def _refresh_app_home(
    client: WebClient, workspace_id: str, user_id: str, logger: Logger
) -> None:
    try:
        creds = credentials.get(workspace_id)
        procs = processes.list_by_workspace(workspace_id)
    except Exception:
        creds = None
        procs = []
    try:
        client.views_publish(
            user_id=user_id,
            view=build_app_home_view(creds=creds, processes=procs),
        )
    except Exception as e:
        logger.exception(f"Failed to refresh App Home: {e}")


def _extract_prefill(state: dict) -> dict:
    prefill: dict = {}
    if "process_name_block" in state:
        prefill["process_name"] = (
            state["process_name_block"].get("process_name", {}).get("value") or ""
        )
    if "confluence_page_url_block" in state:
        prefill["confluence_page_url"] = (
            state["confluence_page_url_block"]
            .get("confluence_page_url", {})
            .get("value") or ""
        )
    if "channel_block" in state:
        prefill["channel_id"] = (
            state["channel_block"].get("channel_id", {}).get("selected_channel")
        )
    if "lookback_window_block" in state:
        opt = (
            state["lookback_window_block"]
            .get("lookback_window", {})
            .get("selected_option") or {}
        )
        prefill["lookback_window"] = opt.get("value", "1d")
    return prefill
